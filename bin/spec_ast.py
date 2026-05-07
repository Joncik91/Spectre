"""Tier 1 deterministic spec-AST classifier. Stdlib only.

PURE parse/structure/tautology checks. Does NOT call bin.tier or bin.resources.
Budget: <100ms per spec.

Public API:
    classify(spec_path: pathlib.Path) -> list[findings.Finding]
"""
import pathlib
import re

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


def _parse_steps_section(body: str) -> list[dict[str, str | int | list[str]]]:
    """
    Parse ## 6. Steps section from a spec body.

    Returns a list of dicts, each with keys: 'step' (int), and zero or
    more of 'why', 'action', 'verification' (all str), and 'produces',
    'requires' (both list[str], possibly empty).
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
                steps.append(step)

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

    # ── Check 4: missing-receiver-calibration ────────────────────────────────
    results.extend(_check_receiver_calibration(body))

    # ── Check 5: step contracts (produces/requires) ───────────────────────────
    results.extend(_check_step_contracts(steps))

    return results
