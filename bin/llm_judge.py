"""Tier 3 DeepSeek client — three-prompt adversarial spec reviewer. Stdlib only."""
import json
import os
import pathlib
import random
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from bin import findings
from bin.findings import Finding, FindingLocation

# Maximum findings surfaced per prompt (cap per spec: 10 × 3 = 30 max)
_FINDINGS_CAP_PER_PROMPT = 10

# Rough token estimate: 1 token ≈ 4 chars
_CHARS_PER_TOKEN = 4

# Spec-wide sentinel location
_SPEC_WIDE = FindingLocation(scope="spec-wide")


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


# Three prompt templates (per Plan Decision 2)
_PROMPTS = [
    {
        "kind": "tier3-context-gap",
        "system": (
            "You are an adversarial reviewer. Find concrete missing context that would block correct "
            "execution. Output JSON only: "
            '{findings: [{kind: \'tier3-context-gap\', message: \'...\', step: <int|null>, '
            "suggested_fix: '<≤140>'}]}. Up to 10 findings."
        ),
        "user": (
            "Review this spec for missing context (assumptions, preconditions, system state, "
            "environment variables, version constraints):\n\n{spec_text}"
        ),
    },
    {
        "kind": "tier3-spec-asserts-wrong",
        "system": (
            "You are an adversarial reviewer. Identify factual claims in the spec that contradict "
            "known systemd, python stdlib, or Linux defaults. Output JSON only: "
            '{findings: [{kind: \'tier3-spec-asserts-wrong\', message: \'...\', step: <int|null>, '
            "suggested_fix: '<≤140>'}]}. Up to 10 findings."
        ),
        "user": "Review this spec for factual errors:\n\n{spec_text}",
    },
    {
        "kind": "tier3-attacker-view",
        "system": (
            "You are an adversarial reviewer. If you were an attacker handed this spec to execute, "
            "what would you exploit? Output JSON only: "
            '{findings: [{kind: \'tier3-attacker-view\', message: \'...\', step: <int|null>, '
            "suggested_fix: '<≤140>'}]}. Up to 10 findings."
        ),
        "user": "Review this spec for attack surfaces:\n\n{spec_text}",
    },
]


class _TotalTimeoutError(Exception):
    """Raised when the total wall-clock budget for a _call_deepseek call is exceeded.

    This is NOT retryable — it is a hard ceiling, not a transient network stall.
    The error fires via a threading.Timer that closes the active HTTP connection
    and then raises here to unblock the reading thread.
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
      - total_timeout_s: hard wall-clock ceiling for the entire call (covering
        chain-of-thought pauses between chunks). Implemented via threading.Timer.
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


def _parse_findings(content: str, expected_kind: str) -> list[Finding]:
    """Parse JSON response content into Finding objects. Raises on malformed content."""
    parsed = json.loads(content)
    raw_items = parsed["findings"]
    result: list[Finding] = []
    for item in raw_items[:_FINDINGS_CAP_PER_PROMPT]:
        kind = item.get("kind", expected_kind)
        # Normalise kind to expected_kind — DeepSeek might vary
        if kind not in findings.KNOWN_KINDS:
            kind = expected_kind
        message = str(item.get("message", ""))[:findings.MAX_MESSAGE_LEN]
        step_raw = item.get("step")
        step = int(step_raw) if step_raw is not None else None
        fix_raw = item.get("suggested_fix")
        fix = str(fix_raw)[:findings.MAX_FIX_LEN] if fix_raw is not None else None
        location = (
            FindingLocation(scope="step", step=step)
            if step is not None
            else _SPEC_WIDE
        )
        result.append(
            Finding(
                tier=3,
                kind=kind,
                severity="info",
                location=location,
                message=message,
                suggested_fix=fix,
                dismissable=True,
            )
        )
    return result


def _run_prompt(prompt_template: dict, spec_text: str, *, config: JudgeConfig) -> list[Finding]:
    """Run one prompt. Returns findings on success; [unavailable] on any failure."""
    prompts = {
        "system": prompt_template["system"],
        "user": prompt_template["user"].format(spec_text=spec_text),
    }
    expected_kind = prompt_template["kind"]
    # Derive a short prong name from the kind (e.g. "tier3-context-gap" → "context-gap").
    prong_name = expected_kind.removeprefix("tier3-")
    total_attempts = _MAX_RETRIES + 1
    try:
        content = _call_deepseek(prompts, config=config)
        return _parse_findings(content, expected_kind)
    except _NoApiKeyError:
        # Distinct skip reason: neither env var nor secrets file has the key.
        return [_unavailable(f"Tier 3 skipped (no-api-key): {config.api_key_env} not found")]
    except _TotalTimeoutError:
        # Hard ceiling exceeded — not retried, distinct message.
        return [_unavailable(
            f"Tier 3 unavailable: total-timeout in {prong_name}"
            f" ({config.total_timeout_s}s wall-clock budget exceeded)"
        )]
    except urllib.error.HTTPError as exc:
        kind_label = f"http-{exc.code}"
        return [_unavailable(
            f"Tier 3 unavailable: timeout in {prong_name} after {total_attempts} attempts"
            f" (last error: {kind_label})"
        )]
    except urllib.error.URLError as exc:
        return [_unavailable(
            f"Tier 3 unavailable: timeout in {prong_name} after {total_attempts} attempts"
            f" (last error: connection-error)"
        )]
    except (TimeoutError, socket.timeout):
        return [_unavailable(
            f"Tier 3 unavailable: timeout in {prong_name} after {total_attempts} attempts"
            f" (last error: socket-timeout)"
        )]
    except json.JSONDecodeError:
        return [_unavailable("Tier 3 unavailable: malformed JSON response")]
    except KeyError as exc:
        return [_unavailable(f"Tier 3 unavailable: missing field {exc}")]
    except RuntimeError as exc:
        return [_unavailable(f"Tier 3 unavailable: {exc}")]
    except Exception as exc:
        return [_unavailable(f"Tier 3 unavailable: {type(exc).__name__}")]


def evaluate(spec_text: str, *, config: JudgeConfig) -> list[Finding]:
    """Run the 3-prompt Tier 3 probing over spec_text.

    Returns Finding list (possibly empty, possibly with tier3-unavailable sentinel).
    Never raises — all failure modes return findings.
    """
    if not config.enabled:
        return []

    # Token budget check (crude: 1 token ≈ 4 chars)
    estimated_tokens = len(spec_text) // _CHARS_PER_TOKEN
    if estimated_tokens >= config.budget_tokens_per_spec:
        return [_unavailable("Tier 3 skipped: spec exceeds budget")]

    all_findings: list[Finding] = []
    for prompt_template in _PROMPTS:
        batch = _run_prompt(prompt_template, spec_text, config=config)
        all_findings.extend(batch)

    return all_findings
