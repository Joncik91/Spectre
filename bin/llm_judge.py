"""Tier 3 DeepSeek client — structured contradiction reviewer. Stdlib only.

v0.5.2: replaced three-prompt prose review with a single structured
contradiction-tuple prompt. DeepSeek receives a normalised step table
(JSON) and returns typed contradiction tuples instead of vague findings.
"""
import json
import os
import pathlib
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from bin import findings
from bin.findings import Finding, FindingLocation

# Maximum contradiction tuples surfaced per spec call
_FINDINGS_CAP_PER_PROMPT = 20

# Rough token estimate: 1 token ≈ 4 chars
_CHARS_PER_TOKEN = 4

# Spec-wide sentinel location
_SPEC_WIDE = FindingLocation(scope="spec-wide")

# Maximum chars for action/verification summaries sent in the step table.
# Prevents a single 5KB heredoc from consuming the entire input budget.
# If a field is truncated, a suffix is appended so DeepSeek can flag
# ambiguous-contract when the contract is incomplete.
_STEP_FIELD_TRUNCATE = 1000

# Taxonomy of allowed contradiction kinds (v0.5.2).
# Must stay in sync with findings.TIER3_CONTRADICTION_SEVERITY.
_CONTRADICTION_KINDS = frozenset({
    "missing-producer",
    "shallow-ownership",
    "ambiguous-contract",
    "negative-path-omission",
    "idempotency-risk",
    "migration-on-existing-state",
    "partial-failure-window",
    "concurrency-race",
    "verification-false-positive",
    "adversarial-pathway",
    "unrecognized",
})

# System prompt for the structured contradiction reviewer (~600 tokens).
# Intentionally terse — no adversarial-review boilerplate.
_CONTRADICTION_SYSTEM_PROMPT = """\
You are a spec contradiction detector. You receive a JSON step table and must \
output ONLY a JSON array of contradiction tuples — no prose, no explanation outside \
the tuples.

Allowed "kind" values (pick exactly one per tuple, or use "unrecognized"):
- missing-producer: step N requires an artifact that no earlier step produces
- shallow-ownership: step claims to own/create X but only scaffolds it; \
a later step's verification proves it was never fully built
- ambiguous-contract: a step's action or verification is underspecified enough \
that two engineers would implement it differently
- negative-path-omission: no step handles the obvious failure branch of an \
operation (e.g. service fails to start, file already exists with wrong content)
- idempotency-risk: re-running the step on existing state would corrupt or \
duplicate data
- migration-on-existing-state: step assumes a clean slate but the verification \
of a prior step confirms state already exists
- partial-failure-window: step is a multi-part action with no rollback; \
partial failure leaves the system in an inconsistent state
- concurrency-race: two steps can interleave in a way the spec does not \
serialise
- verification-false-positive: the verification command would pass even if the \
action failed (tautology or wrong probe)
- unrecognized: real gap that does not fit above taxonomy

Output schema — return a JSON array at the top level:
[
  {
    "kind": "<one of the above>",
    "consumer_step": <int|null>,
    "missing": "<artifact name, if kind=missing-producer>",
    "step": <int|null>,
    "claimed": "<string, if kind=shallow-ownership>",
    "actual": "<string, if kind=shallow-ownership>",
    "ambiguous": "<string, if kind=ambiguous-contract>",
    "description": "<free text, required when kind=unrecognized>",
    "rationale": "<≤120 chars explaining the gap>"
  },
  ...
]

Rules:
1. Every tuple MUST have "kind" and "rationale".
2. If kind is "unrecognized", "description" is required.
3. Do NOT emit anything outside the JSON array.
4. Cap output at 20 tuples. Prefer high-signal tuples over exhaustive lists.
5. If you find no contradictions, return an empty array: []
6. CRITICAL — before emitting a "missing-producer" or "unowned-requirement" \
finding, check the step entry's "produces" and "requires" lists in the \
provided step table. If the required artifact already appears in any prior \
step's "produces" list, the requirement IS resolved — do NOT emit a \
missing-producer finding for it. The step table's "produces"/"requires" \
fields are ground truth from deterministic Tier 1 analysis.

---
v0.7 — adversarial-pathway rubric:

For every step that fetches, reads, or processes data from an UNTRUSTED source
(network response, user prose, user-controlled file path), think one move ahead:
if an attacker controlled that source, what subsequent step would amplify the
input into harmful effect? Emit a contradiction tuple with kind
"adversarial-pathway" naming the source step, the sink step, and the exploit
class (e.g. SSRF, command injection, data exfil, path traversal, prompt
injection). Cite both step numbers in the rationale. Do not invent steps.
"""

# User prompt template — receives the serialised step table.
_CONTRADICTION_USER_TEMPLATE = """\
Review the following spec step table for cross-step contradictions:

{step_table_json}
"""


def _secrets_path_default() -> pathlib.Path:
    """Return the canonical ~/.spectre/secrets.env path (mirrors setup_wizard)."""
    return pathlib.Path.home() / ".spectre" / "secrets.env"


def _resolve_secrets_file_path(explicit: pathlib.Path | None = None) -> pathlib.Path:
    """Resolve secrets file path: explicit > SPECTRE_SECRETS_FILE env > default.

    Mirrors setup_wizard._resolve_secrets_file_path — kept here to decouple
    llm_judge from wizard internals (_resolve_secrets_file_path is private).
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get("SPECTRE_SECRETS_FILE")
    if env_path:
        return pathlib.Path(env_path)
    return _secrets_path_default()


def resolve_api_key(api_key_env: str) -> tuple[str, str] | None:
    """Return (value, source) for *api_key_env*, or None if not found.

    Probe order:
      1. os.environ[api_key_env] — fast path, no disk I/O.
      2. SPECTRE_SECRETS_FILE / ~/.spectre/secrets.env — KEY=value lines,
         with or without surrounding quotes.

    Source strings: "env" | "secrets-file".
    Never logs or returns the key value in an error message.
    """
    # 1. Live environment variable.
    value = os.environ.get(api_key_env)
    if value:
        return (value, "env")

    # 2. Secrets file fallback.
    secrets_path = _resolve_secrets_file_path()
    if secrets_path.is_file():
        try:
            content = secrets_path.read_text(encoding="utf-8")
        except (OSError, PermissionError):
            return None
        prefix = f"{api_key_env}="
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(prefix):
                raw_value = stripped[len(prefix):]
                # Strip surrounding quotes (single or double).
                if len(raw_value) >= 2 and raw_value[0] in ('"', "'") and raw_value[-1] == raw_value[0]:
                    raw_value = raw_value[1:-1]
                if raw_value:
                    return (raw_value, "secrets-file")

    return None


# ── Step table builder ────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)
_STEP_SPLIT_RE = re.compile(r"(?=^\s*- step:)", re.MULTILINE)


def _parse_steps_raw(spec_text: str) -> list[dict]:
    """Extract step dicts from ## 6. Steps section.

    Returns list of dicts with keys: step (int), why, action, verification
    (all str where present). Uses lightweight regex — not a full YAML parser.
    """
    steps_match = re.search(r"^## 6\. Steps\s*$", spec_text, re.MULTILINE)
    if not steps_match:
        return []

    section_start = steps_match.end()
    next_heading = re.search(r"^## ", spec_text[section_start:], re.MULTILINE)
    section_body = (
        spec_text[section_start : section_start + next_heading.start()]
        if next_heading
        else spec_text[section_start:]
    )

    yaml_blocks: list[str] = []
    for m in _FENCE_RE.finditer(section_body):
        yaml_blocks.append(m.group(1))
    if not yaml_blocks:
        yaml_blocks = [section_body]

    steps: list[dict] = []
    for yaml_text in yaml_blocks:
        for raw in _STEP_SPLIT_RE.split(yaml_text):
            raw = raw.strip()
            if not raw:
                continue
            step: dict = {}
            for line in raw.splitlines():
                m_step = re.match(r"^\s*-\s+step:\s*(\d+)", line)
                if m_step:
                    step["step"] = int(m_step.group(1))
                    continue
                m_field = re.match(r"^\s+(why|action|verification):\s*(.*)", line)
                if m_field:
                    key = m_field.group(1)
                    value = m_field.group(2).strip().strip('"').strip("'")
                    step[key] = value
            if "step" in step:
                steps.append(step)
    return steps


def _parse_calibration_section(spec_text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract physics_guardrails, mutates, never_touches from §8.1.

    Returns (physics_guardrails, mutates, never_touches) — each a list of strings.
    Returns empty lists when section is absent.
    """
    m81 = re.search(r"^#{2,3}\s+8\.1\b.*$", spec_text, re.MULTILINE)
    if not m81:
        return [], [], []

    block_start = m81.end()
    next_h = re.search(r"^#{2,3} ", spec_text[block_start:], re.MULTILINE)
    block = spec_text[block_start : block_start + next_h.start()] if next_h else spec_text[block_start:]

    def _extract_list(key: str) -> list[str]:
        """Pull comma/newline/bullet-separated values after 'key:'."""
        m = re.search(rf"^\s*[-*]?\s*`?{re.escape(key)}`?\s*(.*)$", block, re.MULTILINE | re.IGNORECASE)
        if not m:
            return []
        raw = m.group(1).strip()
        # Values may be inline or on subsequent bullet lines; grab inline first.
        items = [v.strip().strip('"').strip("'") for v in re.split(r"[,;]", raw) if v.strip()]
        return [i for i in items if i and i not in ("-", "—", "none", "None")]

    mutates = _extract_list("mutates:")
    never_touches = _extract_list("never-touches:")
    # physics_guardrails = decision-budget + reboot-survival entries (human-readable)
    physics: list[str] = []
    for key in ("decision-budget:", "reboot-survival:"):
        vals = _extract_list(key)
        if vals:
            physics.extend(f"{key} {v}" for v in vals)

    return physics, mutates, never_touches


def _truncate_step_field(value: str) -> str:
    """Truncate a step field (action/verification) to _STEP_FIELD_TRUNCATE chars.

    If truncated, appends ``... [truncated, N more chars]`` so DeepSeek knows
    the field is incomplete and can flag ambiguous-contract if needed.
    Short fields pass through verbatim.
    """
    if len(value) <= _STEP_FIELD_TRUNCATE:
        return value
    remainder = len(value) - _STEP_FIELD_TRUNCATE
    return value[:_STEP_FIELD_TRUNCATE] + f"... [truncated, {remainder} more chars]"


def build_step_table(spec_text: str, step_objects: list | None = None) -> dict:
    """Build the structured step table sent to DeepSeek.

    Args:
        spec_text: Full spec text (used for §8.1 extraction and fallback parsing).
        step_objects: Optional list of step dataclass/dict objects from priority-3
            contract parsing. When present, ``produces``/``requires`` fields are
            read via ``getattr(obj, field, [])`` to handle the case where the
            dataclass predates priority-3 (fields simply won't be there). When
            absent, falls back to regex parsing of spec_text.

    Returns dict with keys: steps, physics_guardrails, mutates, never_touches.
    """
    # Parse steps from text (always — we need why/action/verification).
    raw_steps = _parse_steps_raw(spec_text)

    step_entries: list[dict] = []
    for raw in raw_steps:
        step_n = raw["step"]
        action_raw = raw.get("action", "")
        verification_raw = raw.get("verification", "")
        entry: dict = {
            "step": step_n,
            "why": raw.get("why", ""),
            "action_summary": _truncate_step_field(action_raw),
            "verification_summary": _truncate_step_field(verification_raw),
            "produces": [],
            "requires": [],
        }

        # If caller provided step objects (priority-3 contract fields), overlay them.
        if step_objects is not None:
            # Find the matching object by step number.
            for obj in step_objects:
                obj_step = getattr(obj, "step", None) or (obj.get("step") if isinstance(obj, dict) else None)
                if obj_step == step_n:
                    entry["produces"] = list(getattr(obj, "produces", None) or (obj.get("produces") if isinstance(obj, dict) else None) or [])
                    entry["requires"] = list(getattr(obj, "requires", None) or (obj.get("requires") if isinstance(obj, dict) else None) or [])
                    break

        step_entries.append(entry)

    physics, mutates, never_touches = _parse_calibration_section(spec_text)

    return {
        "steps": step_entries,
        "physics_guardrails": physics,
        "mutates": mutates,
        "never_touches": never_touches,
    }


# ── Contradiction tuple parser ────────────────────────────────────────────────

def _parse_contradiction_findings(content: str) -> list[Finding]:
    """Parse DeepSeek's JSON array of contradiction tuples into Findings.

    Raises json.JSONDecodeError or ValueError on malformed content — caller
    handles these and emits the tier3-malformed-response fallback finding.
    """
    parsed = json.loads(content)

    # DeepSeek might wrap in {"contradictions": [...]} or return bare list.
    if isinstance(parsed, dict):
        # Try common wrapper keys.
        for key in ("contradictions", "findings", "results", "items"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
        else:
            # Try first list value in the dict.
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
            else:
                raise ValueError("no top-level list found in response dict")

    if not isinstance(parsed, list):
        raise ValueError(f"expected list, got {type(parsed).__name__}")

    result: list[Finding] = []
    for item in parsed[:_FINDINGS_CAP_PER_PROMPT]:
        if not isinstance(item, dict):
            continue

        raw_kind = str(item.get("kind", "unrecognized")).strip().lower()

        # Map "unrecognized" (DeepSeek's taxonomy value) to our internal kind.
        if raw_kind == "unrecognized":
            kind = "tier3-contradiction-unrecognized"
        elif raw_kind in findings.TIER3_CONTRADICTION_SEVERITY:
            kind = raw_kind
        else:
            # Unknown kind from model — treat as unrecognized.
            kind = "tier3-contradiction-unrecognized"

        severity = findings.TIER3_CONTRADICTION_SEVERITY.get(kind, "info")

        # Build message: prefer rationale; fall back to description.
        rationale = str(item.get("rationale", "")).strip()
        description = str(item.get("description", "")).strip()
        message_parts: list[str] = []
        if rationale:
            message_parts.append(rationale)
        elif description:
            message_parts.append(description)
        else:
            message_parts.append(f"contradiction detected (kind={kind})")

        # Enrich with structured fields for specific kinds.
        if kind == "missing-producer":
            missing = str(item.get("missing", "")).strip()
            if missing:
                message_parts.insert(0, f"missing: {missing};")
        elif kind == "shallow-ownership":
            claimed = str(item.get("claimed", "")).strip()
            if claimed:
                message_parts.insert(0, f"claimed: {claimed};")
        elif kind == "ambiguous-contract":
            ambiguous = str(item.get("ambiguous", "")).strip()
            if ambiguous:
                message_parts.insert(0, f"ambiguous: {ambiguous};")
        elif kind == "tier3-contradiction-unrecognized" and description:
            message_parts.insert(0, f"desc: {description};")

        message = " ".join(message_parts)[:findings.MAX_MESSAGE_LEN]

        # Determine step location.
        # For missing-producer: consumer_step is the relevant step.
        step_raw = (
            item.get("consumer_step")
            or item.get("step")
        )
        step = int(step_raw) if step_raw is not None else None

        location = (
            FindingLocation(scope="step", step=step)
            if step is not None
            else _SPEC_WIDE
        )

        result.append(Finding(
            tier=3,
            kind=kind,
            severity=severity,
            location=location,
            message=message,
            dismissable=True,
        ))

    return result


def _malformed_response_finding(detail: str) -> Finding:
    """Return a tier3-malformed-response finding (warn, not dismissable)."""
    msg = f"Tier 3 response not valid JSON: {detail}"[:findings.MAX_MESSAGE_LEN]
    return Finding(
        tier=3,
        kind="tier3-malformed-response",
        severity=findings.TIER3_CONTRADICTION_SEVERITY["tier3-malformed-response"],
        location=_SPEC_WIDE,
        message=msg,
        dismissable=False,
    )


# ── Network / retry infrastructure (unchanged from v0.5.1) ───────────────────

class _TotalTimeoutError(Exception):
    """Raised when the wall-clock total budget is exhausted.

    The Timer thread that fires this tags ``_total_exc`` and calls ``resp.close()``,
    but ``urllib.urlopen().read()`` does not unblock immediately when its socket is
    closed externally on Linux.  The read blocks until the per-recv ``chunk_timeout_s``
    fires, then checks ``_total_exc`` and re-raises this error.  Worst-case abort
    latency is ``total_timeout_s + chunk_timeout_s`` (e.g. ~660s with defaults).

    Not retried — propagates immediately past the retry layer.
    """


@dataclass
class JudgeConfig:
    enabled: bool
    api_key_env: str  # name of env var holding the key (not the key itself)
    model: str
    base_url: str = "https://api.deepseek.com/v1"
    budget_tokens_per_spec: int = 50_000
    # chunk_timeout_s: per-recv socket timeout. Detects real connection hangs.
    # A socket.timeout from this is retryable (per #12 P2 logic).
    chunk_timeout_s: int = 60
    # total_timeout_s: hard wall-clock ceiling for the entire request (including
    # chain-of-thought pauses). Raises _TotalTimeoutError — NOT retryable.
    total_timeout_s: int = 600

    @property
    def timeout_s(self) -> int:
        """Back-compat alias: old code that reads timeout_s gets chunk_timeout_s."""
        return self.chunk_timeout_s

    @timeout_s.setter
    def timeout_s(self, value: int) -> None:
        """Back-compat: setting timeout_s sets chunk_timeout_s."""
        self.chunk_timeout_s = value


class _NoApiKeyError(Exception):
    """Raised when neither env var nor secrets file provides the API key."""

    def __init__(self, api_key_env: str) -> None:
        self.api_key_env = api_key_env
        super().__init__(f"no-api-key: {api_key_env} not found in env or secrets file")


_MAX_RETRIES = 3  # up to 4 total attempts
_MAX_BACKOFF_S = 60.0
_FAIL_FAST_HTTP_CODES = {400, 401, 403}


def _backoff_sleep(attempt: int) -> None:
    """Sleep 2^(attempt+1) seconds, capped at _MAX_BACKOFF_S, plus 0-1s jitter."""
    delay = min(2.0 ** (attempt + 1), _MAX_BACKOFF_S)
    delay += random.uniform(0.0, 1.0)
    time.sleep(delay)


def _call_deepseek(prompts: dict, *, config: JudgeConfig) -> str:
    """API call with retry-with-backoff. Returns response content string.

    Two timeout layers:
      - chunk_timeout_s: per-recv socket timeout passed to urlopen. Fires as
        socket.timeout when no data arrives for that interval. This is a transient
        failure and IS retried per #12 P2 logic.
      - total_timeout_s: hard wall-clock ceiling for the entire call (including
        chain-of-thought pauses). Implemented via threading.Timer.
        When it fires it raises _TotalTimeoutError. This is NOT retried.

    Retries up to _MAX_RETRIES times (4 total attempts) on transient errors:
    socket.timeout, TimeoutError, urllib.error.URLError, HTTP 429, HTTP 5xx.
    Fail-fast on HTTP 400, 401, 403 (not transient) and _TotalTimeoutError.
    Raises on final failure.
    """
    key_result = resolve_api_key(config.api_key_env)
    if not key_result:
        raise _NoApiKeyError(config.api_key_env)
    api_key, _source = key_result
    body = json.dumps(
        {
            "model": config.model,
            "messages": [
                {"role": "system", "content": prompts["system"]},
                {"role": "user", "content": prompts["user"]},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
    ).encode("utf-8")

    # Threading plumbing for total wall-clock timeout.
    # _total_exc is set by the Timer thread; the main thread checks it after
    # urlopen returns or raises.
    _total_exc: list[_TotalTimeoutError] = []
    _active_resp: list[object] = []  # holds the live response object so Timer can close it
    _timer_lock = threading.Lock()

    def _fire_total_timeout() -> None:
        exc = _TotalTimeoutError(
            f"total wall-clock budget exceeded ({config.total_timeout_s}s)"
        )
        with _timer_lock:
            _total_exc.append(exc)
            # Close any active response to unblock resp.read() on the main thread.
            if _active_resp:
                try:
                    _active_resp[0].close()  # type: ignore[attr-defined]
                except Exception:
                    pass

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        # Arm a fresh total-timeout timer for each attempt.
        timer = threading.Timer(config.total_timeout_s, _fire_total_timeout)
        timer.daemon = True
        timer.start()
        try:
            req = urllib.request.Request(
                f"{config.base_url}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=config.chunk_timeout_s) as resp:
                    with _timer_lock:
                        _active_resp.clear()
                        _active_resp.append(resp)
                    try:
                        raw = resp.read()
                    except (OSError, socket.timeout, TimeoutError) as read_exc:
                        # resp.close() from the timer can cause read() to raise OSError.
                        # Check total-timeout first before treating as a chunk failure.
                        with _timer_lock:
                            _active_resp.clear()
                            if _total_exc:
                                raise _total_exc[0]
                        raise
                    with _timer_lock:
                        _active_resp.clear()
                # Check if total timeout fired during read.
                with _timer_lock:
                    if _total_exc:
                        raise _total_exc[0]
                data = json.loads(raw.decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except _TotalTimeoutError:
                raise  # propagate immediately — not retryable
            except urllib.error.HTTPError as exc:
                if exc.code in _FAIL_FAST_HTTP_CODES:
                    raise
                if exc.code == 429 or 500 <= exc.code <= 599:
                    last_exc = exc
                    if attempt < _MAX_RETRIES:
                        _backoff_sleep(attempt)
                    continue
                raise
            except (socket.timeout, TimeoutError, urllib.error.URLError, OSError) as exc:
                # Check if this was actually a total-timeout firing (closed connection
                # may surface as socket.timeout or OSError wrapped in URLError).
                with _timer_lock:
                    if _total_exc:
                        raise _total_exc[0]
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    _backoff_sleep(attempt)
                continue
        finally:
            timer.cancel()

    assert last_exc is not None
    raise last_exc


def _unavailable(message: str) -> Finding:
    """Return a tier3-unavailable sentinel finding (info severity, not dismissable)."""
    # Truncate message to 140 chars (Finding validator enforces this)
    if len(message) > findings.MAX_MESSAGE_LEN:
        message = message[: findings.MAX_MESSAGE_LEN]
    return Finding(
        tier=3,
        kind="tier3-unavailable",
        severity="info",
        location=_SPEC_WIDE,
        message=message,
        dismissable=False,
    )


# ── CoT faithfulness check ────────────────────────────────────────────────────

# Kinds that get the cite-and-verify second pass (block-severity contradiction kinds).
_BLOCK_CONTRADICTION_KINDS = frozenset({"missing-producer", "shallow-ownership", "adversarial-pathway"})

# System prompt for the cite-and-verify pass.
_FAITHFULNESS_SYSTEM_PROMPT = """\
You previously emitted these contradiction tuples on a spec. For each one, cite \
the step number AND a short verbatim excerpt (≤80 chars) from that step's action \
or verification text that backs your claim. If you cannot cite supporting text \
from the spec, say so explicitly with citation: null.

Output JSON only — array of objects matching the order of the input tuples:
[
  {"index": 0, "step": 5, "citation": "import yt_readable.server"},
  {"index": 1, "step": null, "citation": null},
  ...
]"""

# User prompt template for the cite-and-verify pass.
_FAITHFULNESS_USER_TEMPLATE = """\
Contradiction tuples to verify:
{tuples_json}

Spec step table:
{step_table_json}
"""


def _faithfulness_demote_finding(original: Finding) -> Finding:
    """Return a demoted copy of a block-severity contradiction finding (warn, tier3-unfaithful-contradiction)."""
    msg = f"citation not found in spec; demoted from block: {original.message}"[:findings.MAX_MESSAGE_LEN]
    return Finding(
        tier=3,
        kind="tier3-unfaithful-contradiction",
        severity="warn",
        location=original.location,
        message=msg,
        dismissable=True,
    )


def _faithfulness_malformed_finding() -> Finding:
    """Return a tier3-faithfulness-malformed finding when cite response is unparseable."""
    return Finding(
        tier=3,
        kind="tier3-faithfulness-malformed",
        severity="warn",
        location=_SPEC_WIDE,
        message="Tier 3 cite-and-verify response was not valid JSON; block tuples kept as-is",
        dismissable=False,
    )


def _verify_block_tuples_with_citations(
    tuple_findings: list[Finding],
    step_table: dict,
    *,
    config: JudgeConfig,
) -> list[Finding]:
    """Run a second batched API call to verify block-severity contradiction tuples.

    For each finding whose kind is in _BLOCK_CONTRADICTION_KINDS, asks DeepSeek to
    cite the step number and verbatim text that backs its claim.  If the citation
    cannot be found (substring match, case-insensitive) in the step's
    action_summary + verification_summary, the tuple is demoted from block → warn
    with kind ``tier3-unfaithful-contradiction``.

    Non-block findings pass through unchanged.
    Zero block findings → returns input list unchanged without any API call.
    Parse failure on cite response → appends ``tier3-faithfulness-malformed`` warn;
    all block tuples remain block (conservative: couldn't verify, so don't demote).

    Args:
        tuple_findings: Output from _parse_contradiction_findings / _run_contradiction_prompt.
        step_table: The same step table sent to the primary prompt (has ``steps`` list).
        config: JudgeConfig for API calls.

    Returns a new finding list with the same non-block findings plus either
    verified-or-demoted block findings.
    """
    # Separate block (verifiable) from non-block (pass through).
    block_indices: list[int] = []
    for idx, f in enumerate(tuple_findings):
        if f.kind in _BLOCK_CONTRADICTION_KINDS and f.severity == "block":
            block_indices.append(idx)

    # Short-circuit: nothing to verify.
    if not block_indices:
        return list(tuple_findings)

    # Build a minimal representation of block findings to send to DeepSeek.
    block_summaries = []
    for i, orig_idx in enumerate(block_indices):
        f = tuple_findings[orig_idx]
        block_summaries.append({
            "index": i,
            "kind": f.kind,
            "step": f.location.step,
            "message": f.message,
        })

    # Build step lookup: step_number -> {action_summary, verification_summary}.
    step_lookup: dict[int, dict] = {}
    for entry in step_table.get("steps", []):
        sn = entry.get("step")
        if sn is not None:
            step_lookup[int(sn)] = entry

    tuples_json = json.dumps(block_summaries, indent=2)
    step_table_json = json.dumps(step_table, indent=2)
    prompts = {
        "system": _FAITHFULNESS_SYSTEM_PROMPT,
        "user": _FAITHFULNESS_USER_TEMPLATE.format(
            tuples_json=tuples_json,
            step_table_json=step_table_json,
        ),
    }

    try:
        content = _call_deepseek(prompts, config=config)
    except Exception:
        # Any network/auth failure: return originals unchanged + malformed warning.
        result = list(tuple_findings)
        result.append(_faithfulness_malformed_finding())
        return result

    # Parse cite-and-verify JSON response.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            # Unwrap common wrapper keys.
            for key in ("citations", "results", "items"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
                else:
                    raise ValueError("no top-level list found in cite response dict")
        if not isinstance(parsed, list):
            raise ValueError(f"expected list, got {type(parsed).__name__}")
    except (json.JSONDecodeError, ValueError):
        # Parse failure: keep block tuples as-is, add malformed warning.
        result = list(tuple_findings)
        result.append(_faithfulness_malformed_finding())
        return result

    # Build cite lookup by index (as returned by DeepSeek).
    cite_lookup: dict[int, dict] = {}
    for item in parsed:
        if isinstance(item, dict):
            idx = item.get("index")
            if idx is not None:
                try:
                    cite_lookup[int(idx)] = item
                except (TypeError, ValueError):
                    pass

    # Build result: substitute demoted findings where citation fails.
    result = list(tuple_findings)
    for i, orig_idx in enumerate(block_indices):
        original_finding = tuple_findings[orig_idx]
        cite_entry = cite_lookup.get(i)

        should_demote = False
        if cite_entry is None:
            # No citation returned for this tuple → demote.
            should_demote = True
        else:
            cited_step = cite_entry.get("step")
            cited_text = cite_entry.get("citation")
            if cited_step is None or cited_text is None:
                should_demote = True
            else:
                # Verify citation substring exists in the step's action+verification.
                try:
                    step_entry = step_lookup.get(int(cited_step))
                except (TypeError, ValueError):
                    step_entry = None

                if step_entry is None:
                    should_demote = True
                else:
                    haystack = (
                        step_entry.get("action_summary", "") + " "
                        + step_entry.get("verification_summary", "")
                    ).lower()
                    needle = str(cited_text).lower()
                    if needle not in haystack:
                        should_demote = True

        if should_demote:
            result[orig_idx] = _faithfulness_demote_finding(original_finding)

    return result


# ── Deterministic contract-resolution post-filter ────────────────────────────

def _drop_resolved_producer_findings(
    tuple_findings: list[Finding],
    contract_resolution: dict | None,
) -> tuple[list[Finding], list[Finding]]:
    """Drop missing-producer findings for artifacts the Tier 1 resolver shows as resolved.

    Tier 1 (_build_contract_resolution in spec_evaluator) has the ground truth on what
    each step produces and whether each requires is satisfied.  DeepSeek must not be
    allowed to override a resolved produces with a hallucinated missing-producer.

    Args:
        tuple_findings: Raw findings list from the primary contradiction prompt.
        contract_resolution: The dict from spec_evaluator._build_contract_resolution,
            shaped as {"steps": {"<n>": {"produces": [...], "requires": [...],
            "resolution": {"<entry>": {"resolved_by_step": N} | null}}}}.
            When None, no filtering is performed.

    Returns (kept, dropped) where dropped contains the deterministically vetoed findings.
    """
    if contract_resolution is None:
        return list(tuple_findings), []

    steps_map: dict[str, dict] = contract_resolution.get("steps", {})

    # Build a flat set of ALL produces entries across all steps (for fast lookup).
    all_produces: set[str] = set()
    for step_data in steps_map.values():
        all_produces.update(step_data.get("produces", []))

    kept: list[Finding] = []
    dropped: list[Finding] = []

    for f in tuple_findings:
        if f.kind != "missing-producer":
            kept.append(f)
            continue

        # Extract the artifact name from the finding message.
        # Message format: "missing: <artifact>; <rationale>" (built in _parse_contradiction_findings).
        missing_artifact = _extract_missing_artifact(f.message)

        # Check 1: artifact appears in any step's produces list.
        if missing_artifact and missing_artifact in all_produces:
            dropped.append(f)
            continue

        # Check 2: if consumer_step is known, check its resolution map.
        step_n = f.location.step
        if step_n is not None:
            step_data = steps_map.get(str(step_n), {})
            resolution = step_data.get("resolution", {})
            if missing_artifact and missing_artifact in resolution:
                entry = resolution[missing_artifact]
                # entry is {"resolved_by_step": N} when resolved, None when not.
                if entry is not None and entry.get("resolved_by_step") is not None:
                    dropped.append(f)
                    continue

        kept.append(f)

    return kept, dropped


def _extract_missing_artifact(message: str) -> str:
    """Extract the artifact name from a missing-producer finding message.

    Message format from _parse_contradiction_findings:
      "missing: <artifact>; <rationale>"
    Falls back to returning empty string when format doesn't match.
    """
    m = re.match(r"missing:\s*([^;]+)\s*;", message)
    if m:
        return m.group(1).strip()
    return ""


# ── Single contradiction-oriented prompt runner ───────────────────────────────

def _run_contradiction_prompt(
    step_table: dict,
    *,
    config: JudgeConfig,
) -> list[Finding]:
    """Run the single structured contradiction prompt.

    Sends the step table as JSON; parses the contradiction tuple array response.
    On JSON parse failure, returns a warn tier3-malformed-response finding and
    does NOT crash (per spec requirement).

    All network/timeout failures return tier3-unavailable sentinels.
    """
    step_table_json = json.dumps(step_table, indent=2)
    prompts = {
        "system": _CONTRADICTION_SYSTEM_PROMPT,
        "user": _CONTRADICTION_USER_TEMPLATE.format(step_table_json=step_table_json),
    }
    total_attempts = _MAX_RETRIES + 1
    try:
        content = _call_deepseek(prompts, config=config)
        try:
            return _parse_contradiction_findings(content)
        except (json.JSONDecodeError, ValueError) as parse_exc:
            # JSON parse failure: return malformed-response warning, don't crash.
            detail = str(parse_exc)[:80]
            return [_malformed_response_finding(detail)]
    except _NoApiKeyError:
        return [_unavailable(f"Tier 3 skipped (no-api-key): {config.api_key_env} not found")]
    except _TotalTimeoutError:
        return [_unavailable(
            f"Tier 3 unavailable: total-timeout"
            f" ({config.total_timeout_s}s wall-clock budget exceeded)"
        )]
    except urllib.error.HTTPError as exc:
        # v0.6.2 (#37): distinguish auth failures from provider/transient errors so
        # the user knows whether to check ~/.spectre/secrets.env or wait and retry.
        if exc.code in (401, 403):
            return [_unavailable(
                f"Tier 3 unavailable: auth failure (HTTP {exc.code} —"
                f" check ~/.spectre/secrets.env or {config.api_key_env})"
            )]
        if exc.code == 400:
            return [_unavailable(
                f"Tier 3 unavailable: bad request (HTTP 400 — model"
                f" {config.model!r} may be unavailable on your plan)"
            )]
        if 500 <= exc.code <= 599:
            return [_unavailable(
                f"Tier 3 unavailable: provider error after {total_attempts} attempts"
                f" (HTTP {exc.code})"
            )]
        return [_unavailable(
            f"Tier 3 unavailable: contradiction-prompt after {total_attempts} attempts"
            f" (last error: http-{exc.code})"
        )]
    except urllib.error.URLError:
        return [_unavailable(
            f"Tier 3 unavailable: contradiction-prompt after {total_attempts} attempts"
            f" (last error: connection-error)"
        )]
    except (TimeoutError, socket.timeout):
        return [_unavailable(
            f"Tier 3 unavailable: contradiction-prompt after {total_attempts} attempts"
            f" (last error: socket-timeout)"
        )]
    except RuntimeError as exc:
        return [_unavailable(f"Tier 3 unavailable: {exc}")]
    except Exception as exc:
        return [_unavailable(f"Tier 3 unavailable: {type(exc).__name__}")]


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate(
    spec_text: str,
    *,
    config: JudgeConfig,
    step_objects: list | None = None,
    contract_resolution: dict | None = None,
) -> list[Finding]:
    """Run the Tier 3 structured contradiction review over spec_text.

    Sends a single prompt with a normalised step table (JSON) and parses the
    contradiction tuple array response.

    Args:
        spec_text: Full spec text.
        config: JudgeConfig controlling model, key, timeouts, budget.
        step_objects: Optional list of step dataclass objects with priority-3
            contract fields (produces/requires). When absent (or the dataclass
            predates priority-3), those fields are left empty — DeepSeek can
            still reason from action/verification summaries.
        contract_resolution: Optional dict from spec_evaluator._build_contract_resolution.
            When provided, used as ground truth to drop missing-producer findings
            that contradict Tier 1's resolved contract graph.  Shape::

                {"steps": {"<n>": {"produces": [...], "requires": [...],
                                   "resolution": {"<entry>": {"resolved_by_step": N} | null}}}}

    Returns Finding list (possibly empty, possibly with tier3-unavailable
    sentinel or tier3-malformed-response). Never raises.
    """
    if not config.enabled:
        return []

    # Token budget check (crude: 1 token ≈ 4 chars)
    estimated_tokens = len(spec_text) // _CHARS_PER_TOKEN
    if estimated_tokens >= config.budget_tokens_per_spec:
        return [_unavailable("Tier 3 skipped: spec exceeds budget")]

    step_table = build_step_table(spec_text, step_objects=step_objects)
    primary_findings = _run_contradiction_prompt(step_table, config=config)

    # Deterministic post-filter: drop missing-producer findings for artifacts
    # that Tier 1 contract resolution shows as resolved.  This is a hard veto —
    # the model cannot hallucinate a missing-producer when the ground truth says
    # the artifact is produced.  Runs before the faithfulness check so demoted
    # findings don't trigger an unnecessary second API call.
    primary_findings, _dropped = _drop_resolved_producer_findings(
        primary_findings, contract_resolution
    )

    # Second pass: cite-and-verify for block-severity tuples (v0.6 faithfulness check).
    # Zero extra cost when no block tuples; one batched call otherwise.
    return _verify_block_tuples_with_citations(primary_findings, step_table, config=config)
