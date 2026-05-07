"""Tier 1 deterministic spec-AST classifier. Stdlib only.

PURE parse/structure/tautology checks. Does NOT call bin.tier or bin.resources.
Budget: <100ms per spec.

Public API:
    classify(spec_path: pathlib.Path) -> list[findings.Finding]
"""
import pathlib
import re
import shlex

from bin import findings as _findings

# ── Soft-verification tautology patterns (case-insensitive, stripped) ─────────
_SOFT_VERIFY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^true$", re.IGNORECASE),
    re.compile(r"^:$"),
    re.compile(r"^echo\b[^&|;]*$", re.IGNORECASE),
    re.compile(r"^\[\s*1\s+-eq\s+1\s*\]$"),
    re.compile(r'^\[\s*-z\s+""\s*\]$'),
]

# ── §8.1 required fields ──────────────────────────────────────────────────────
_CALIBRATION_REQUIRED_FIELDS = ("mutates:", "never-touches:", "decision-budget:", "reboot-survival:")

# ── v0.5.2 step contract types ─────────────────────────────────────────────
# Contract entries are "<type>:<value>" strings.  The set below is the
# exhaustive list of recognised type prefixes.
_CONTRACT_TYPES: frozenset[str] = frozenset({
    "file",
    "package",
    "console-script",
    "route",
    "module",
    "binary",
    "db-table",
    "db-column",
})

# ── Path-like token regex (text-match heuristic for action-not-probed) ───────
# Note: the leading `\b` boundary means `/dev/null` after a redirect like `2>/dev/null`
# is captured as `/null` (the `\b` matches at the `>/` transition). The filter below
# accounts for this by checking both the full /dev/<x> form and the bare /<x> form.
_PATH_RE = re.compile(r"\b(/[a-zA-Z0-9_/.-]+)")

# Stream-redirect targets that are not real writable filesystem artifacts. The
# action-not-probed heuristic must skip these — capturing /dev/null in a step's
# action shouldn't demand a corresponding probe in the verification.
_DEV_STREAMS: frozenset[str] = frozenset({
    "/dev/null", "/dev/stdout", "/dev/stderr",
    # After regex word-boundary clipping, these can appear as bare suffixes too:
    "/null", "/stdout", "/stderr",
})

# Pattern that detects when a "/null"/"/stdout"/"/stderr" capture is actually
# a stream redirect (preceded by `/dev` so the original token was /dev/<name>).
_DEV_REDIRECT_RE = re.compile(r"/dev/(null|stdout|stderr)\b")


def _is_soft_verification(value: str) -> bool:
    """Return True if value matches any tautology pattern."""
    stripped = value.strip()
    for pat in _SOFT_VERIFY_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _extract_paths_from_text(text: str) -> list[str]:
    """Return all path-like tokens found in text (text-match heuristic).

    Filters /dev/null, /dev/stdout, /dev/stderr because they are stream redirects,
    not writable artifacts that need probing in the verification.

    Also filters bare `/null`, `/stdout`, `/stderr` captures — these are word-
    boundary artifacts of the regex when the original token was `/dev/null` etc.
    after a redirect like `2>/dev/null` (the `\\b` matches at the `>/` boundary).
    """
    raw = _PATH_RE.findall(text)
    filtered: list[str] = []
    for p in raw:
        if p in _DEV_STREAMS:
            continue
        # If the original text contained `/dev/null` (etc.) and we captured `/null`,
        # verify the source by re-checking the surrounding context.
        if p in ("/null", "/stdout", "/stderr"):
            stream_name = p[1:]
            if f"/dev/{stream_name}" in text:
                continue
        filtered.append(p)
    return filtered


def _parse_contract_list(raw_block: str, key: str) -> list[str]:
    """Parse a YAML list field (produces: or requires:) from a raw step block.

    Handles both inline-list and block-sequence styles:
      produces: ["file:/tmp/x", "package:foo"]
      produces:
        - "file:/tmp/x"
        - package:foo

    Returns a list of unquoted entry strings (possibly empty).
    """
    entries: list[str] = []
    lines = raw_block.splitlines()

    # Find the line that starts the list field
    list_start = -1
    for i, line in enumerate(lines):
        m = re.match(r"^\s+" + re.escape(key) + r":\s*(.*)", line)
        if m:
            inline = m.group(1).strip()
            if inline:
                # Inline style: produces: ["a", "b"]  or  produces: [a, b]
                # Strip surrounding brackets if present
                inner = inline.strip()
                if inner.startswith("[") and inner.endswith("]"):
                    inner = inner[1:-1]
                # Split by comma, respecting quotes (simple approach: split on ,)
                for part in inner.split(","):
                    part = part.strip().strip('"').strip("'")
                    if part:
                        entries.append(part)
            else:
                # Block sequence: entries on following lines indented with '  - '
                list_start = i + 1
            break

    if list_start >= 0:
        for line in lines[list_start:]:
            # Stop at a line that looks like a new scalar field (not a list item)
            stripped = line.strip()
            if not stripped:
                continue
            if re.match(r"^\s+-\s+step:\s*\d+", line):
                break
            # Another scalar field at the same or shallower indentation
            if re.match(r"^\s+\w[\w-]*:\s*\S", line) and not re.match(r"^\s+-\s+", line):
                break
            m_item = re.match(r"^\s+-\s+(.*)", line)
            if m_item:
                val = m_item.group(1).strip().strip('"').strip("'")
                if val:
                    entries.append(val)
            else:
                # Line is not a list item and not empty — stop
                break

    return entries


def _parse_negative_paths(raw_block: str) -> list[dict[str, str]]:
    """Parse a ``negative-paths:`` YAML list field from a raw step block.

    Each entry is a small dict with ``trigger`` and ``handler`` keys.
    Handles both inline-list (JSON-style) and block-sequence YAML.

    Returns a list of parsed entry dicts (possibly empty).  Missing or
    malformed entries are returned as partial dicts so the caller can
    emit ``malformed-negative-path`` findings.
    """
    entries: list[dict[str, str]] = []
    lines = raw_block.splitlines()

    list_start = -1
    for i, line in enumerate(lines):
        m = re.match(r"^\s+negative-paths:\s*(.*)", line)
        if m:
            inline = m.group(1).strip()
            if inline:
                # Inline style: negative-paths: [{trigger: "x", handler: "y"}, ...]
                # Best-effort: strip outer brackets and split on }, {
                inner = inline.strip()
                if inner.startswith("[") and inner.endswith("]"):
                    inner = inner[1:-1]
                # Split on "},{" boundaries (rough but tolerant)
                item_strs = re.split(r"\}\s*,\s*\{", inner)
                for item_str in item_strs:
                    item_str = item_str.strip().strip("{").strip("}")
                    entry: dict[str, str] = {}
                    for kv in item_str.split(","):
                        kv = kv.strip()
                        kv_m = re.match(r"(['\"]?)(trigger|handler)\1\s*:\s*['\"]?(.*?)['\"]?\s*$", kv)
                        if kv_m:
                            entry[kv_m.group(2)] = kv_m.group(3).strip().strip("'\"")
                    if entry:
                        entries.append(entry)
            else:
                list_start = i + 1
            break

    if list_start >= 0:
        # Block sequence: each entry starts with a list-item line "  - " and
        # sub-keys appear on following lines at deeper indentation, e.g.:
        #   negative-paths:
        #     - trigger: "fetch fails"
        #       handler: "retry"
        #     - trigger: "disk full"
        #       handler: "reject"
        #
        # Strategy: determine the indentation of the negative-paths: field line
        # to know when we've moved back to step-level fields (which stop the scan).
        # The negative-paths: line is at lines[list_start - 1].
        np_line = lines[list_start - 1] if list_start > 0 else ""
        np_indent = len(np_line) - len(np_line.lstrip())

        current_entry: dict[str, str] | None = None
        for line in lines[list_start:]:
            stripped = line.strip()
            if not stripped:
                continue
            # Stop at next step block delimiter
            if re.match(r"^\s*-\s+step:\s*\d+", line):
                break
            # Measure indentation of this line
            line_indent = len(line) - len(line.lstrip())
            # If this line is at or shallower than the negative-paths: field,
            # it must be a sibling step-level field — stop.
            if line_indent <= np_indent and not re.match(r"^\s*-\s+", line):
                break
            # New list item (has "- " marker at deeper-than-np_indent level)
            m_item = re.match(r"^\s+-\s+(.*)", line)
            if m_item:
                if current_entry is not None:
                    entries.append(current_entry)
                current_entry = {}
                rest = m_item.group(1).strip()
                kv_m = re.match(r"(trigger|handler)\s*:\s*(.*)", rest)
                if kv_m:
                    current_entry[kv_m.group(1)] = kv_m.group(2).strip().strip("'\"")
            else:
                # Continuation sub-key for the current entry
                if current_entry is not None:
                    kv_m = re.match(r"^\s+(trigger|handler)\s*:\s*(.*)", line)
                    if kv_m:
                        current_entry[kv_m.group(1)] = kv_m.group(2).strip().strip("'\"")
        if current_entry is not None:
            entries.append(current_entry)

    return entries


def _parse_reboot_survival(body: str) -> str:
    """Extract the ``reboot-survival:`` value from §8.1.

    Returns the value string (e.g. ``"required"``, ``"best-effort"``, ``"none"``)
    or ``""`` if not found.
    """
    m81 = re.search(r"^#{2,3}\s+8\.1\b.*$", body, re.MULTILINE)
    if not m81:
        return ""
    block_start = m81.end()
    next_h = re.search(r"^#{2,3} ", body[block_start:], re.MULTILINE)
    block_81 = body[block_start : block_start + next_h.start()] if next_h else body[block_start:]
    m = re.search(r"^\s*[`-]?\s*`?reboot-survival:`?\s*(.*)", block_81, re.MULTILINE)
    if not m:
        return ""
    return m.group(1).strip().strip("`").strip("'\"")


def _parse_steps_section(body: str) -> list[dict[str, str | int | list[str]]]:
    """
    Parse ## 6. Steps section from a spec body.

    Returns a list of dicts, each with keys: 'step' (int), and zero or
    more of 'why', 'action', 'verification' (all str), and 'produces',
    'requires' (both list[str], possibly empty), and 'negative_paths'
    (list[dict[str, str]], possibly empty).
    """
    # Find ## 6. Steps heading
    steps_match = re.search(r"^## 6\. Steps\s*$", body, re.MULTILINE)
    if not steps_match:
        return []

    # Extract section body until next ## heading (or end)
    section_start = steps_match.end()
    next_heading = re.search(r"^## ", body[section_start:], re.MULTILINE)
    if next_heading:
        section_body = body[section_start : section_start + next_heading.start()]
    else:
        section_body = body[section_start:]

    # Find the yaml block(s) inside code fences
    yaml_blocks: list[str] = []
    fence_re = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)
    for m in fence_re.finditer(section_body):
        yaml_blocks.append(m.group(1))

    if not yaml_blocks:
        # No fenced block — treat section_body itself as yaml
        yaml_blocks = [section_body]

    steps: list[dict[str, str | int | list[str]]] = []
    for yaml_text in yaml_blocks:
        # Split on lines beginning with '- step:' (step block delimiters)
        # We use re.split but keep the delimiter so we can reconstruct step_n
        raw_blocks = re.split(r"(?=^\s*- step:)", yaml_text, flags=re.MULTILINE)
        for raw in raw_blocks:
            raw = raw.strip()
            if not raw:
                continue
            step: dict[str, str | int | list[str]] = {}
            for line in raw.splitlines():
                # step number
                m_step = re.match(r"^\s*-\s+step:\s*(\d+)", line)
                if m_step:
                    step["step"] = int(m_step.group(1))
                    continue
                # key: value fields we care about
                m_field = re.match(r"^\s+(why|action|verification):\s*(.*)", line)
                if m_field:
                    key = m_field.group(1)
                    value = m_field.group(2).strip().strip('"').strip("'")
                    step[key] = value
            if "step" in step:
                # Parse produces/requires contract lists from the raw block
                step["produces"] = _parse_contract_list(raw, "produces")
                step["requires"] = _parse_contract_list(raw, "requires")
                step["negative_paths"] = _parse_negative_paths(raw)
                steps.append(step)

    # W2 NOTE (known limitation, v0.5.2): multi-line YAML literal-block (`|`)
    # and fold (`>`) values in action/verification fields are NOT captured here
    # — only the first line is stored.  The spec template recommends single-line
    # values; spec authors using multi-line blocks should be aware that checks
    # relying on the full text will only see the inline portion.  Fixing this
    # would require a real YAML parser (out-of-scope for stdlib-only policy).
    return steps


def _validate_contract_entry(entry: str) -> bool:
    """Return True if entry is a valid contract string ("<type>:<value>").

    Validity requires: at least one ':' separator, the type prefix is in
    _CONTRACT_TYPES, and the value (right of ':') is non-empty.
    """
    if ":" not in entry:
        return False
    prefix, _, value = entry.partition(":")
    return prefix in _CONTRACT_TYPES and bool(value.strip())


def _check_step_contracts(
    steps: list[dict],
) -> list[_findings.Finding]:
    """Run contract checks across all steps.

    Emits:
      - warn/malformed-contract  — entry present but type prefix unknown or value missing
      - warn/missing-contract    — step has no produces: AND no requires: declared
      - block/unowned-requirement — step.requires entry not produced by any earlier step

    Returns list of findings (possibly empty).
    """
    results: list[_findings.Finding] = []

    # Build the running set of produced contracts as we walk steps in order.
    # Each entry is the normalised string exactly as written (after strip/unquote).
    cumulative_produces: set[str] = set()

    for step in steps:
        step_n: int = step["step"]  # type: ignore[assignment]
        raw_produces: list[str] = step.get("produces", [])  # type: ignore[assignment]
        raw_requires: list[str] = step.get("requires", [])  # type: ignore[assignment]

        # ── validate + collect produces ──────────────────────────────────────
        valid_produces: list[str] = []
        for entry in raw_produces:
            if _validate_contract_entry(entry):
                valid_produces.append(entry)
            else:
                msg = f"Step {step_n} produces entry {entry!r} is not a recognised contract type."
                if len(msg) > 140:
                    msg = msg[:137] + "..."
                results.append(_findings.Finding(
                    tier=1,
                    kind="malformed-contract",
                    severity="warn",
                    location=_findings.FindingLocation(scope="step", step=step_n, ref="produces"),
                    message=msg,
                    suggested_fix=(
                        "Use <type>:<value> — valid types: "
                        + ", ".join(sorted(_CONTRACT_TYPES))
                    )[:140],
                ))

        # ── validate + check requires ────────────────────────────────────────
        valid_requires: list[str] = []
        for entry in raw_requires:
            if _validate_contract_entry(entry):
                valid_requires.append(entry)
            else:
                msg = f"Step {step_n} requires entry {entry!r} is not a recognised contract type."
                if len(msg) > 140:
                    msg = msg[:137] + "..."
                results.append(_findings.Finding(
                    tier=1,
                    kind="malformed-contract",
                    severity="warn",
                    location=_findings.FindingLocation(scope="step", step=step_n, ref="requires"),
                    message=msg,
                    suggested_fix=(
                        "Use <type>:<value> — valid types: "
                        + ", ".join(sorted(_CONTRACT_TYPES))
                    )[:140],
                ))

        # ── missing-contract (opt-in, warn only) ────────────────────────────
        # A step without any contract entries is "undeclared" — warn only.
        # Gate on raw lists: a step with only malformed entries attempted a
        # declaration; it already gets malformed-contract and should NOT also
        # get missing-contract (misleading double-fire).
        if not raw_produces and not raw_requires:
            msg = f"Step {step_n} declares no produces: or requires: contract entries."
            results.append(_findings.Finding(
                tier=1,
                kind="missing-contract",
                severity="warn",
                location=_findings.FindingLocation(scope="step", step=step_n, ref="produces"),
                message=msg,
                suggested_fix="Declare produces:/requires: to make step contracts machine-readable.",
            ))

        # ── unowned-requirement (block) ──────────────────────────────────────
        for entry in valid_requires:
            if entry not in cumulative_produces:
                msg = (
                    f"Step {step_n} requires {entry!r} but no prior step's produces: declares it."
                )
                if len(msg) > 140:
                    msg = msg[:137] + "..."
                results.append(_findings.Finding(
                    tier=1,
                    kind="unowned-requirement",
                    severity="block",
                    location=_findings.FindingLocation(scope="step", step=step_n, ref="requires"),
                    message=msg,
                    suggested_fix="Add the entry to a prior step's produces:, or remove the requires: entry.",
                ))

        # Accumulate valid produces for subsequent steps
        cumulative_produces.update(valid_produces)

    return results


def _check_receiver_calibration(body: str) -> list[_findings.Finding]:
    """Return findings for missing §8.1 section or missing required fields."""
    results: list[_findings.Finding] = []

    # Check for §8 section presence
    has_section = bool(re.search(r"^## 8\. Receiver Calibration", body, re.MULTILINE))
    # Accept h2 (## 8.1) OR h3 (### 8.1) with optional trailing parenthetical
    has_81 = bool(re.search(r"^#{2,3}\s+8\.1\b", body, re.MULTILINE))

    if not has_section or not has_81:
        results.append(_findings.Finding(
            tier=1,
            kind="missing-receiver-calibration",
            severity="block",
            location=_findings.FindingLocation(scope="spec-wide", ref="receiver-calibration"),
            message="§8 Receiver Calibration section (or §8.1) is absent from spec.",
            suggested_fix="Add ## 8. Receiver Calibration with all four §8.1 fields.",
        ))
        return results  # No point checking fields if section absent

    # Find §8.1 block (from ## 8.1 or ### 8.1 until next ### or ## heading or EOF)
    m81 = re.search(r"^#{2,3}\s+8\.1\b.*$", body, re.MULTILINE)
    if not m81:
        results.append(_findings.Finding(
            tier=1,
            kind="missing-receiver-calibration",
            severity="block",
            location=_findings.FindingLocation(scope="spec-wide", ref="receiver-calibration"),
            message="§8.1 Hard contract block is absent from spec.",
            suggested_fix="Add ### 8.1 Hard contract with mutates:, never-touches:, decision-budget:, reboot-survival:.",
        ))
        return results

    block_start = m81.end()
    next_h = re.search(r"^#{2,3} ", body[block_start:], re.MULTILINE)
    block_81 = body[block_start : block_start + next_h.start()] if next_h else body[block_start:]

    # Check presence of each required field
    for field in _CALIBRATION_REQUIRED_FIELDS:
        if not re.search(r"^\s*[`-]?\s*`?" + re.escape(field), block_81, re.MULTILINE):
            msg = f"§8.1 field '{field}' is absent."
            if len(msg) > 140:
                msg = msg[:137] + "..."
            results.append(_findings.Finding(
                tier=1,
                kind="missing-receiver-calibration",
                severity="block",
                location=_findings.FindingLocation(scope="spec-wide", ref="receiver-calibration"),
                message=msg,
                suggested_fix=f"Add '{field}' to §8.1 Hard contract.",
            ))

    return results


def _extract_python_c_bodies(text: str) -> list[str]:
    """Return all bodies from `python3 -c <body>` invocations in *text*.

    Uses shlex to tokenize the command so that quoted bodies with escaped
    characters are handled correctly.  Returns raw body strings (not yet
    unescaped from the outer YAML quoting — that stripping happens in
    _parse_steps_section before we receive the action string).

    Resilience: the YAML field parser strips a trailing quote from the field
    value when the outer YAML wrapper uses a different quote style (e.g. the
    `'` at the end of `"python3 -c 'body'"` is stripped by `.strip("'")`
    leaving an unclosed quote in the shell fragment).  When shlex raises
    ValueError we retry by appending `'` then `"` so the body is still
    extracted.
    """
    bodies: list[str] = []
    tokens: list[str] | None = None
    for attempt in [text, text + "'", text + '"']:
        try:
            tokens = shlex.split(attempt)
            break
        except ValueError:
            continue
    if tokens is None:
        # All attempts failed — can't parse reliably; skip.
        return bodies

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("python3", "python") and i + 1 < len(tokens):
            j = i + 1
            # Scan for -c token
            while j < len(tokens):
                t = tokens[j]
                if t == "-c":
                    # next token is the body
                    if j + 1 < len(tokens):
                        bodies.append(tokens[j + 1])
                    break
                elif t.startswith("-") and "c" in t and not t.startswith("--"):
                    # combined flag like -mc; body is next token
                    if j + 1 < len(tokens):
                        bodies.append(tokens[j + 1])
                    break
                elif not t.startswith("-"):
                    # Hit a non-flag positional — this python invocation ended
                    break
                j += 1
        i += 1
    return bodies


def _check_python_c_syntax(
    field_value: str, step_n: int, ref: str
) -> list[_findings.Finding]:
    """Check all `python3 -c <body>` bodies in *field_value* for SyntaxError.

    Returns block-severity findings for each invalid body.
    """
    results: list[_findings.Finding] = []
    bodies = _extract_python_c_bodies(field_value)
    for body in bodies:
        try:
            compile(body, "<verification>", "exec")
        except SyntaxError as exc:
            loc_info = f"line {exc.lineno}, col {exc.offset}"
            fragment = (exc.text or "").strip()
            if len(fragment) > 40:
                fragment = fragment[:37] + "..."
            msg = (
                f"Step {step_n} {ref} python3 -c body SyntaxError at "
                f"{loc_info}: {fragment!r}"
            )
            if len(msg) > 140:
                msg = msg[:137] + "..."
            results.append(_findings.Finding(
                tier=1,
                kind="verification-syntax-error",
                severity="block",
                location=_findings.FindingLocation(
                    scope="step", step=step_n, ref=ref
                ),
                message=msg,
                suggested_fix="Each statement in python3 -c must be on its own line (use \\n).",
            ))
    return results


# ── §8.1 mutates: field parser ─────────────────────────────────────────────────

def _parse_mutates_paths(body: str) -> list[str]:
    """Extract paths listed under §8.1 `mutates:` field.

    Returns list of path strings (may be empty).
    """
    m81 = re.search(r"^#{2,3}\s+8\.1\b.*$", body, re.MULTILINE)
    if not m81:
        return []
    block_start = m81.end()
    next_h = re.search(r"^#{2,3} ", body[block_start:], re.MULTILINE)
    block_81 = body[block_start : block_start + next_h.start()] if next_h else body[block_start:]

    m = re.search(r"^\s*[`-]?\s*`?mutates:`?\s*(.*)", block_81, re.MULTILINE)
    if not m:
        return []
    raw = m.group(1).strip()
    # Handle list syntax like [/tmp/, /opt/] or bare /tmp/ /opt/
    raw = raw.strip("[]")
    # Split on commas or whitespace
    parts = re.split(r"[,\s]+", raw)
    paths = [p.strip().rstrip("/") for p in parts if p.strip() and p.strip() != "none"]
    return paths


def _action_authored_path(action: str) -> list[str]:
    """Heuristic: return file paths that the action plausibly *creates/writes*.

    Looks for:
    - heredoc targets: `cat > /path <<EOF` or `tee /path <<EOF`
    - explicit cp/install destination: last path arg
    - Any > /path or >> /path redirects (file writes)

    Note: mkdir is intentionally excluded — it creates directories, NOT files
    within them. Keeping mkdir paths out prevents false "authored" matches
    when a subsequent step invokes a file inside the created directory.

    Returns a list of created/written file paths.
    """
    created: list[str] = []
    # Redirect writes: > /path or >> /path
    for m in re.finditer(r"(?:>>?)\s*(/[a-zA-Z0-9_/.-]+)", action):
        created.append(m.group(1))
    # cat > /path <<EOF  (heredoc)
    for m in re.finditer(r"\bcat\s+>\s*(/[a-zA-Z0-9_/.-]+)", action):
        created.append(m.group(1))
    # tee /path
    for m in re.finditer(r"\btee\s+(/[a-zA-Z0-9_/.-]+)", action):
        created.append(m.group(1))
    # cp src /dest  — destination is the last abs path
    for m in re.finditer(r"\bcp\s+\S+\s+(/[a-zA-Z0-9_/.-]+)", action):
        created.append(m.group(1))
    # install ... /dest
    for m in re.finditer(r"\binstall\b[^&|;]*\s(/[a-zA-Z0-9_/.-]+)(?:\s|$)", action):
        created.append(m.group(1))
    return created


def _module_path_candidates(module: str) -> list[str]:
    """Convert dotted module `foo.bar.baz` to candidate path suffixes.

    Returns patterns that a prior step's authored path could match.
    """
    parts = module.replace("-", "_").split(".")
    slash_path = "/".join(parts)
    return [
        f"{slash_path}.py",
        f"{slash_path}/__init__.py",
    ]


def _check_action_invokes_uncreated_artifact(
    steps: list[dict],
    mutates_paths: list[str],
) -> list[_findings.Finding]:
    """Gap A: block if an action invokes an absolute path under mutates: that no
    prior step authored.

    Also checks `python3 -m foo.bar.baz` — converts to path candidates and
    checks prior-step authorship.
    """
    results: list[_findings.Finding] = []
    # Track paths authored by each step (cumulative)
    authored: list[str] = []  # all paths authored by steps seen so far

    for step in steps:
        step_n: int = step["step"]  # type: ignore[assignment]
        action: str = step.get("action", "")  # type: ignore[assignment]
        if not action:
            authored.append("")  # placeholder so index stays in sync
            continue

        # --- Check invocations BEFORE updating authored (prior steps only) ---

        # 1. Absolute path invocations: `python3 /abs/path`, `bash /abs/path`
        for m in re.finditer(
            r"\b(?:python3?|bash|sh|node|ruby|perl)\s+(/[a-zA-Z0-9_/.-]+\.(?:py|sh|rb|js|pl))",
            action,
        ):
            invoked_path = m.group(1)
            # Only flag if the path is under a mutates: directory
            if not any(invoked_path.startswith(mp) for mp in mutates_paths):
                continue
            # Check if any prior step authored this exact file path
            if invoked_path in authored:
                continue
            msg = (
                f"Step {step_n} invokes {invoked_path!r} but no prior step authored it."
            )
            if len(msg) > 140:
                msg = msg[:137] + "..."
            results.append(_findings.Finding(
                tier=1,
                kind="action-invokes-uncreated-artifact",
                severity="block",
                location=_findings.FindingLocation(
                    scope="step", step=step_n, ref="action"
                ),
                message=msg,
                suggested_fix="Add a prior step that creates the invoked path via heredoc/cp.",
            ))

        # 2. Module invocations: `python3 -m foo.bar.baz`
        for m in re.finditer(r"\bpython3?\s+-m\s+([\w.]+)", action):
            module = m.group(1)
            candidates = _module_path_candidates(module)
            # Only flag if at least one candidate is under a mutates: dir
            under_mutates = any(
                any(cand.startswith(mp.lstrip("/")) or mp in cand
                    for mp in mutates_paths)
                for cand in candidates
            )
            if not under_mutates:
                continue
            # Check if any prior step mentions a matching path
            prior_text = " ".join(authored)
            if any(cand in prior_text for cand in candidates):
                continue
            msg = (
                f"Step {step_n} invokes module {module!r} but no prior step authored "
                f"its source."
            )
            if len(msg) > 140:
                msg = msg[:137] + "..."
            results.append(_findings.Finding(
                tier=1,
                kind="action-invokes-uncreated-artifact",
                severity="block",
                location=_findings.FindingLocation(
                    scope="step", step=step_n, ref="action"
                ),
                message=msg,
                suggested_fix="Add a prior step that creates the module source file.",
            ))

        # --- Now record what this step authors ---
        authored.extend(_action_authored_path(action))

    return results


# ── Gap C: unowned-requirement (e2e assertion without authoring prior step) ────

# B1 FIX: Capture full URL path (after host[:port]) up to ?/space/pipe/&/;/quote.
# The original pattern only captured the last path segment.
_CURL_ROUTE_RE = re.compile(
    r"\bcurl\b[^|&;'\"]*(?:localhost|127\.0\.0\.1)(?::\d+)?(/[a-zA-Z0-9_/.-]*[a-zA-Z0-9_/-])(?=[?'\"\s|&;]|$)"
)

# B1 FIX: Allowlist of universal health/probe routes that must NOT generate findings.
# Hard-coded for v0.5.2; not configurable.
_CURL_ROUTE_ALLOWLIST: frozenset[str] = frozenset({
    "/",
    "/healthz",
    "/health",
    "/ready",
    "/metrics",
    "/ping",
    "/status",
})

_CURL_GREP_RE = re.compile(r"\bcurl\b[^|]*\|\s*grep\s+['\"]?([^'\"|\s]+)")

# W1 FIX: Require stronger anchor for SQL ownership — `CREATE TABLE <name>` or
# `<name>(` in a SQL context, not flat substring match on table/column names.
_SQL_SELECT_RE = re.compile(
    r"\bSELECT\b[^;]*\bFROM\b\s+(\w+)\b[^;]*\bWHERE\b[^;]*\b(\w+)\b\s*=",
    re.IGNORECASE,
)
_SQL_CREATE_TABLE_RE = re.compile(r"\bCREATE\s+TABLE\s+(\w+)\s*\(", re.IGNORECASE)
_SQL_CREATE_INDEX_RE = re.compile(r"\bCREATE\s+INDEX\b[^(]*\(([^)]+)\)", re.IGNORECASE)

# B2+B3 FIX: These regexes now search INSIDE the extracted -c body (not anchored
# to the start of the body). The outer shell extraction uses shlex.
# _PYTHON_IMPORT_RE and _PYTHON_IMPORT_ALT_RE match anywhere inside the -c body.
_PYTHON_IMPORT_RE = re.compile(r"\bfrom\s+([\w.]+)\s+import\b")
_PYTHON_IMPORT_ALT_RE = re.compile(r"\bimport\s+([\w.]+)")

# B3 FIX: stdlib top-level module names — bare `import X` for these is not flagged.
# Covers Python 3.11 stdlib common tops; not exhaustive but prevents false positives
# on the modules most frequently used in inline -c snippets.
_STDLIB_TOPS: frozenset[str] = frozenset({
    "abc", "ast", "asyncio", "base64", "binascii", "builtins", "calendar",
    "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs", "codeop",
    "collections", "colorsys", "compileall", "concurrent", "configparser",
    "contextlib", "contextvars", "copy", "copyreg", "cProfile", "csv",
    "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal",
    "difflib", "dis", "doctest", "email", "encodings", "enum", "errno",
    "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob",
    "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http", "idlelib",
    "imaplib", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json", "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
    "mailbox", "marshal", "math", "mimetypes", "mmap", "modulefinder",
    "multiprocessing", "netrc", "nis", "nntplib", "numbers", "operator",
    "optparse", "os", "pathlib", "pdb", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty",
    "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random",
    "re", "readline", "reprlib", "resource", "rlcompleter", "runpy",
    "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil",
    "signal", "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
    "spwd", "sqlite3", "sre_compile", "sre_constants", "sre_parse", "ssl",
    "stat", "statistics", "string", "stringprep", "struct", "subprocess",
    "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
    "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "tomllib", "trace",
    "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "unicodedata", "unittest", "urllib", "uu", "uuid",
    "venv", "warnings", "wave", "weakref", "webbrowser", "wsgiref",
    "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "zoneinfo", "_thread",
})


def _check_unowned_requirement(steps: list[dict]) -> list[_findings.Finding]:
    """Gap C: block if a verification asserts runtime behavior (route, HTML, DB,
    import) that no prior step's action authored.

    Conservative: emit block only for clear mismatches; warn when uncertain.
    Skips findings that are already covered by an explicit P3 produces: contract
    on any step — the machine-readable channel shadows the heuristic.
    """
    results: list[_findings.Finding] = []
    # Accumulate all prior-step action text as a corpus
    prior_actions: list[str] = []

    # P1↔P3 integration: collect every produces: entry across all steps so
    # explicit contracts shadow the heuristic.  Build sets of declared
    # package/module names, route paths, and file paths.
    declared_packages: set[str] = set()
    declared_modules: set[str] = set()
    declared_routes: set[str] = set()
    declared_files: set[str] = set()
    for s in steps:
        for entry in s.get("produces", []) or []:
            if not isinstance(entry, str) or ":" not in entry:
                continue
            kind, _, value = entry.partition(":")
            value = value.strip()
            if kind == "package":
                declared_packages.add(value)
            elif kind == "module":
                declared_modules.add(value)
            elif kind == "route":
                _, _, route_path = value.partition(" ")
                if route_path:
                    declared_routes.add(route_path.strip())
                declared_routes.add(value.strip())
            elif kind == "file":
                declared_files.add(value)

    for step in steps:
        step_n: int = step["step"]  # type: ignore[assignment]
        verification: str = step.get("verification", "")  # type: ignore[assignment]
        action: str = step.get("action", "")  # type: ignore[assignment]

        prior_corpus = " ".join(prior_actions)

        if verification:
            # ── 1. curl route assertion ──────────────────────────────────────
            # B1 FIX: regex now captures full URL path; group(1) already has
            # the leading slash.  Skip paths in the universal-probe allowlist.
            for m in _CURL_ROUTE_RE.finditer(verification):
                route = m.group(1)
                # Skip universal health/probe routes — no authorship required.
                if route in _CURL_ROUTE_ALLOWLIST:
                    continue
                # P3 contract shadows: skip if any step's produces declares this route
                if route in declared_routes:
                    continue
                # Check if any prior action mentions this route
                if route not in prior_corpus:
                    msg = (
                        f"Step {step_n} verifies route {route!r} but no prior "
                        f"step authored it."
                    )
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="unowned-requirement-heuristic",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="verification"
                        ),
                        message=msg,
                        suggested_fix="Add a prior step that authors the route handler.",
                    ))

            # ── 2. curl | grep HTML token ────────────────────────────────────
            for m in _CURL_GREP_RE.finditer(verification):
                token = m.group(1).strip("'\"")
                # Only flag tokens that look like HTML tags (contain < or end with >)
                # e.g. '<sidebar>', '<div>', 'div>' — not plain words like 'ok', 'true'
                if "<" not in token and not token.endswith(">"):
                    continue
                if token not in prior_corpus:
                    msg = (
                        f"Step {step_n} greps HTML token {token!r} but no prior "
                        f"step authored it."
                    )
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="unowned-requirement-heuristic",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="verification"
                        ),
                        message=msg,
                        suggested_fix="Add a prior step that authors the HTML element.",
                    ))

            # ── 3. SQL SELECT asserting on table+column ──────────────────────
            # W1 FIX: ownership requires `CREATE TABLE <name>(` or a column
            # appearing inside a CREATE TABLE body in prior actions.  Flat
            # substring on common English words (user, name, id) caused too
            # many false passes.
            for m in _SQL_SELECT_RE.finditer(verification):
                table = m.group(1)
                column = m.group(2)
                # A prior step "owns" the table if its action contains
                # CREATE TABLE <table>( (case-insensitive).
                table_owned = any(
                    tm.group(1).lower() == table.lower()
                    for act in prior_actions
                    for tm in _SQL_CREATE_TABLE_RE.finditer(act)
                )
                # A prior step "owns" the column if it appears inside any
                # CREATE TABLE body or CREATE INDEX clause in prior actions.
                col_owned = table_owned and any(
                    column.lower() in act.lower()
                    for act in prior_actions
                    if _SQL_CREATE_TABLE_RE.search(act) or
                       _SQL_CREATE_INDEX_RE.search(act)
                )
                if not table_owned or not col_owned:
                    missing = table if not table_owned else column
                    msg = (
                        f"Step {step_n} queries {missing!r} but no prior step "
                        f"authored it."
                    )
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="unowned-requirement-heuristic",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="verification"
                        ),
                        message=msg,
                        suggested_fix="Add a prior step that creates the table/column.",
                    ))

            # ── 4. python3 -c imports anywhere in body ──────────────────────
            # B2+B3 FIX: use shlex to extract the -c body, then run both
            # _PYTHON_IMPORT_RE (from X import Y) and _PYTHON_IMPORT_ALT_RE
            # (import X) over the full body so leading statements like
            # `import sys; from app import foo` are caught.
            c_bodies = _extract_python_c_bodies(verification)
            for body_text in c_bodies:
                # from X import Y — always checked (no stdlib exemption needed
                # since project packages dominate this form)
                for im in _PYTHON_IMPORT_RE.finditer(body_text):
                    module = im.group(1)
                    mod_top = module.split(".")[0]
                    # P3 contract shadows: skip if any step declares this package/module
                    if mod_top in declared_packages or module in declared_modules:
                        continue
                    candidates = _module_path_candidates(module)
                    if not any(cand in prior_corpus for cand in candidates):
                        if mod_top not in prior_corpus:
                            msg = (
                                f"Step {step_n} imports {module!r} but no prior "
                                f"step authored its source."
                            )
                            if len(msg) > 140:
                                msg = msg[:137] + "..."
                            results.append(_findings.Finding(
                                tier=1,
                                kind="unowned-requirement-heuristic",
                                severity="block",
                                location=_findings.FindingLocation(
                                    scope="step", step=step_n, ref="verification"
                                ),
                                message=msg,
                                suggested_fix="Add a prior step that creates the module.",
                            ))
                # import X — B2 wire-up + B3 stdlib exemption
                for im in _PYTHON_IMPORT_ALT_RE.finditer(body_text):
                    module = im.group(1)
                    mod_top = module.split(".")[0]
                    # Skip stdlib modules — only flag project packages
                    if mod_top in _STDLIB_TOPS:
                        continue
                    # P3 contract shadows: skip if any step declares this package/module
                    if mod_top in declared_packages or module in declared_modules:
                        continue
                    candidates = _module_path_candidates(module)
                    if not any(cand in prior_corpus for cand in candidates):
                        if mod_top not in prior_corpus:
                            msg = (
                                f"Step {step_n} imports {module!r} but no prior "
                                f"step authored its source."
                            )
                            if len(msg) > 140:
                                msg = msg[:137] + "..."
                            results.append(_findings.Finding(
                                tier=1,
                                kind="unowned-requirement-heuristic",
                                severity="block",
                                location=_findings.FindingLocation(
                                    scope="step", step=step_n, ref="verification"
                                ),
                                message=msg,
                                suggested_fix="Add a prior step that creates the module.",
                            ))

        # Record this step's action in the prior corpus for subsequent steps
        if action:
            prior_actions.append(action)

    return results


def _check_negative_paths(
    steps: list[dict],
    body: str,
) -> list[_findings.Finding]:
    """Tier 1 check for missing or malformed ``negative-paths:`` declarations.

    Rules:
    - Step with ``produces`` non-empty AND ``negative_paths`` empty:
        - ``reboot-survival: required``  → block severity ``missing-negative-path``
        - otherwise                      → warn severity ``missing-negative-path``
    - Step with a malformed entry (missing ``trigger`` or ``handler``, or wrong
      type) → warn ``malformed-negative-path``; evaluator continues.
    """
    results: list[_findings.Finding] = []
    reboot_survival = _parse_reboot_survival(body)

    for step in steps:
        step_n: int = step.get("step")  # type: ignore[assignment]
        if step_n is None:
            continue
        produces: list[str] = step.get("produces", []) or []  # type: ignore[assignment]
        negative_paths: list[dict] = step.get("negative_paths", []) or []  # type: ignore[assignment]

        if produces:
            if not negative_paths:
                # missing-negative-path
                severity = "block" if reboot_survival == "required" else "warn"
                if severity == "block":
                    msg = (
                        f"Step {step_n} declares produces but no negative-paths; "
                        f"reboot-survival=required mandates failure-branch declaration."
                    )
                else:
                    msg = (
                        f"Step {step_n} declares produces but no negative-paths; "
                        f"consider documenting the obvious failure branch."
                    )
                if len(msg) > 140:
                    msg = msg[:137] + "..."
                results.append(_findings.Finding(
                    tier=1,
                    kind="missing-negative-path",
                    severity=severity,
                    location=_findings.FindingLocation(
                        scope="step", step=step_n, ref="negative-paths"
                    ),
                    message=msg,
                    suggested_fix=(
                        "Add negative-paths: with trigger: and handler: entries."
                    ),
                ))
            else:
                # Validate each entry
                for entry in negative_paths:
                    if not isinstance(entry, dict):
                        msg = f"Step {step_n} negative-paths entry is not a dict: {entry!r}."
                        if len(msg) > 140:
                            msg = msg[:137] + "..."
                        results.append(_findings.Finding(
                            tier=1,
                            kind="malformed-negative-path",
                            severity="warn",
                            location=_findings.FindingLocation(
                                scope="step", step=step_n, ref="negative-paths"
                            ),
                            message=msg,
                            suggested_fix="Each negative-paths entry must be a dict with trigger: and handler: keys.",
                        ))
                        continue
                    missing = [k for k in ("trigger", "handler") if not entry.get(k)]
                    if missing:
                        missing_str = ", ".join(missing)
                        msg = (
                            f"Step {step_n} negative-paths entry missing required key(s): {missing_str}."
                        )
                        if len(msg) > 140:
                            msg = msg[:137] + "..."
                        results.append(_findings.Finding(
                            tier=1,
                            kind="malformed-negative-path",
                            severity="warn",
                            location=_findings.FindingLocation(
                                scope="step", step=step_n, ref="negative-paths"
                            ),
                            message=msg,
                            suggested_fix=(
                                "Each negative-paths entry must have both trigger: and handler: keys."
                            )[:140],
                        ))

    return results


def classify(spec_path: pathlib.Path) -> list[_findings.Finding]:
    """Tier 1 deterministic classifier. Returns Finding list (possibly empty).

    PURE parse/structure/tautology. Does NOT call bin.tier or bin.resources.
    Budget: <100ms.
    """
    text = spec_path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # CRLF/CR normalization
    body = text
    results: list[_findings.Finding] = []

    # ── Parse steps ──────────────────────────────────────────────────────────
    steps = _parse_steps_section(body)

    for step in steps:
        step_n: int = step["step"]  # type: ignore[assignment]

        # Check 1: missing-why
        if "why" not in step:
            results.append(_findings.Finding(
                tier=1,
                kind="missing-why",
                severity="block",
                location=_findings.FindingLocation(scope="step", step=step_n, ref="why"),
                message=f"Step {step_n} is missing the required 'why:' field.",
                suggested_fix="Add a one-line first-principles justification as why: field.",
            ))

        # Check 2: soft-verification
        verification: str = step.get("verification", "")  # type: ignore[assignment]
        if verification and _is_soft_verification(verification):
            results.append(_findings.Finding(
                tier=1,
                kind="soft-verification",
                severity="block",
                location=_findings.FindingLocation(
                    scope="step", step=step_n, ref="verification"
                ),
                message=f"Step {step_n} verification is a tautology: {verification!r}.",
                suggested_fix="Replace with a structural post-condition check on actual output.",
            ))

        # Check 3: action-not-probed (text-match heuristic, warn only)
        action: str = step.get("action", "")  # type: ignore[assignment]
        if action and verification:
            action_paths = _extract_paths_from_text(action)
            if action_paths:
                # At least one path in action must appear somewhere in verification
                verif_text = verification
                any_probed = any(p in verif_text for p in action_paths)
                if not any_probed:
                    path_list = ", ".join(action_paths[:3])
                    msg = f"Step {step_n} action path(s) ({path_list}) not found in verification."
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="action-not-probed",
                        severity="warn",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="verification"
                        ),
                        message=msg,
                        suggested_fix="Add a check on the path written by the action.",
                    ))

        # Check 5 (Gap D): python3 -c syntax check in action and verification
        if action:
            results.extend(_check_python_c_syntax(action, step_n, "action"))
        if verification:
            results.extend(_check_python_c_syntax(verification, step_n, "verification"))

    # ── Check 4: missing-receiver-calibration ────────────────────────────────
    results.extend(_check_receiver_calibration(body))

    # ── Check 5: step contracts (produces/requires) ───────────────────────────
    results.extend(_check_step_contracts(steps))

    # ── Check 6 (Gap A): action invokes uncreated artifact ───────────────────
    mutates_paths = _parse_mutates_paths(body)
    if mutates_paths:
        results.extend(_check_action_invokes_uncreated_artifact(steps, mutates_paths))

    # ── Check 7 (Gap C): unowned-requirement (e2e assertions) ────────────────
    results.extend(_check_unowned_requirement(steps))

    # ── Check 8 (v0.6): negative-path declarations ───────────────────────────
    results.extend(_check_negative_paths(steps, body))

    return results
