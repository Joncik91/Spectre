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

# ── v1.1 Fix 3: behavioral-claim vs structural-only verification ──────────────
# Matches a why-clause that names behavioral semantics (the "does it do X" claim).
_BEHAVIORAL_VERB_RE = re.compile(
    r"\b(trigger|prevent|ensure|validate|enforce|coalesce|refuse|halt|debounce|atomic)\b",
    re.IGNORECASE,
)

# Anchored: line is ONLY a structural probe, no piped behavioral test.
# Matches "test -f X", "test -d Y", "grep -q PATTERN FILE" alone or chained
# with && between structural probes. Disqualified by pipes (|), backgrounding (&),
# or semicolons (;) which would introduce a behavioral check.
_STRUCTURAL_ONLY_VERIFICATION_RE = re.compile(
    r"^\s*(test\s+-[fd]\s+\S+|grep\s+-q\s+\S+(\s+\S+)?)"
    r"(\s+&&\s+(test\s+-[fd]\s+\S+|grep\s+-q\s+\S+(\s+\S+)?))*\s*$"
)


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
    return m.group(1).strip().strip("`").strip("'\"").lower()


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
            if entry in cumulative_produces:
                continue
            # v0.6.2 (#36): parent-package match — `package:foo` covers
            # `module:foo` and `module:foo.<sub>`; `module:foo.bar` covers
            # `module:foo.bar.<sub>`.
            kind, _, value = entry.partition(":")
            satisfied = False
            if kind == "module":
                top = value.split(".")[0] if value else ""
                if top and f"package:{top}" in cumulative_produces:
                    satisfied = True
                if not satisfied:
                    for prod in cumulative_produces:
                        if prod.startswith("module:"):
                            pv = prod.split(":", 1)[1]
                            if value == pv or value.startswith(pv + "."):
                                satisfied = True
                                break
            if not satisfied:
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


# v1.0 — six-view spec model structural checks
_V1_SUBSTRATE_BLOCKS = {
    "8.3": "Product-input substrate",
    "8.4": "Product-output substrate",
    "8.5": "Human-user substrate",
    "8.6": "Integrator substrate",
    "8.7": "Operator substrate",
}
_V1_VIEW_SECTIONS = {
    "9": "Product-Input View",
    "10": "Product-Output View",
    "11": "Human-User View",
    "12": "Integrator View",
    "13": "Operator View",
}
_V1_CONTRACT_TYPES = ("Mechanical contracts", "Coverage contracts", "Exemplar bindings")


_FENCED_BLOCK_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def _strip_fenced_blocks(text: str) -> str:
    """Remove ```fenced code/markdown blocks``` so heading-matching regexes
    don't see headings embedded in example fragments inside the spec body.
    """
    return _FENCED_BLOCK_RE.sub("", text)


def _extract_section_body(body: str, heading_pattern: str) -> str | None:
    """Find a section by its heading regex and return its body up to the next
    top-level h2 heading. Returns None if heading not present.

    Fenced code blocks are stripped before scanning so contract examples
    inside ```markdown``` fences (template.spec.md) don't trigger false
    positives.
    """
    cleaned = _strip_fenced_blocks(body)
    m = re.search(heading_pattern, cleaned, re.MULTILINE)
    if not m:
        return None
    start = m.end()
    next_h2 = re.search(r"^##\s", cleaned[start:], re.MULTILINE)
    return cleaned[start : start + next_h2.start()] if next_h2 else cleaned[start:]


def _extract_subsection_body(parent_body: str, subheading_pattern: str) -> str | None:
    """Find a sub-section within an already-extracted parent body."""
    m = re.search(subheading_pattern, parent_body, re.MULTILINE)
    if not m:
        return None
    start = m.end()
    next_h = re.search(r"^#{2,4}\s", parent_body[start:], re.MULTILINE)
    return parent_body[start : start + next_h.start()] if next_h else parent_body[start:]


_SPEC_VERSION_RE = re.compile(r"^\*\*Spec-version:\*\*\s*(\S+)", re.MULTILINE)


def is_v1_spec(body: str) -> bool:
    """Return True iff `body` declares `**Spec-version:** 1.0` exactly.

    Shared by spec_ast Tier-1, cross_view_gate Tier-2, and llm_judge Tier-3
    so all three checkers agree on what "is a v1.0 spec" means. Token
    `1.0.1` / `1.0-rc` / `latest` all return False — the value must be
    exactly `1.0` after stripping.
    """
    m = _SPEC_VERSION_RE.search(body)
    if m is None:
        return False
    return m.group(1).strip() == "1.0"
_NOT_APPLICABLE_RE = re.compile(r"^\s*-?\s*not-applicable\s*:", re.MULTILINE)
_CROSS_VIEW_REF_RE = re.compile(r"<([a-z][a-z0-9_-]*)\s+from\s+§(8\.\d)(?:\s+([a-z][a-z0-9_-]*))?>")
_EXEMPLAR_REF_RE = re.compile(r"exemplar:([a-z0-9][a-z0-9:_-]*)")


def _check_v1_spec_version(body: str) -> list[_findings.Finding]:
    """Reject specs whose Spec-version is explicitly non-1.0.

    Pre-v1.0 specs (no Spec-version frontmatter) are treated as v0.9 and
    skip the v1.0 Tier-1 checks. Going forward, /vision always emits
    `**Spec-version:** 1.0` so any new draft enters the v1.0 check path.
    """
    m = _SPEC_VERSION_RE.search(body)
    if m is None:
        return []
    version = m.group(1).strip()
    if version != "1.0":
        return [_findings.Finding(
            tier=1,
            kind="unsupported-spec-version",
            severity="block",
            location=_findings.FindingLocation(scope="spec-wide", ref="frontmatter"),
            message=f"Spec-version {version!r} is not supported. v1.0 only accepts spec-version 1.0.",
            suggested_fix="Re-run /vision to regenerate the spec as v1.0.",
        )]
    return []


def _check_v1_substrate_family(body: str) -> list[_findings.Finding]:
    """Verify §§8.3-8.7 are each present (with either content or not-applicable)."""
    results: list[_findings.Finding] = []
    cleaned = _strip_fenced_blocks(body)
    for section, label in _V1_SUBSTRATE_BLOCKS.items():
        pattern = rf"^#{{2,3}}\s+{re.escape(section)}\b"
        if not re.search(pattern, cleaned, re.MULTILINE):
            results.append(_findings.Finding(
                tier=1,
                kind="missing-substrate-block",
                severity="block",
                location=_findings.FindingLocation(scope="spec-wide", ref=f"section-{section}"),
                message=f"§{section} {label} is absent from spec.",
                suggested_fix=f"Add ### {section} {label} (or mark not-applicable per the v1.0 template).",
            ))
    return results


def _check_v1_view_sections(body: str) -> list[_findings.Finding]:
    """Verify §§9-13 are each present, parse contract subsections, count N/A."""
    results: list[_findings.Finding] = []
    na_views: list[str] = []
    for section, label in _V1_VIEW_SECTIONS.items():
        section_body = _extract_section_body(
            body, rf"^##\s+{re.escape(section)}\.\s+{re.escape(label)}\b"
        )
        if section_body is None:
            results.append(_findings.Finding(
                tier=1,
                kind="missing-view-section",
                severity="block",
                location=_findings.FindingLocation(scope="spec-wide", ref=f"section-{section}"),
                message=f"§{section} {label} is absent from spec.",
                suggested_fix=f"Add ## {section}. {label} (or mark not-applicable per the v1.0 template).",
            ))
            continue
        # Skip contract-shape checks when view is marked not-applicable
        if _NOT_APPLICABLE_RE.search(section_body):
            na_views.append(section)
            continue
        # Verify at least one contract-type subsection exists (Mechanical, Coverage, or Exemplar)
        has_any_contract = any(
            re.search(rf"^#{{3,4}}\s+{re.escape(ct)}\b", section_body, re.MULTILINE)
            for ct in _V1_CONTRACT_TYPES
        )
        if not has_any_contract:
            results.append(_findings.Finding(
                tier=1,
                kind="malformed-view-contract",
                severity="block",
                location=_findings.FindingLocation(scope="spec-wide", ref=f"section-{section}"),
                message=f"§{section} {label} declares no contracts. Add at least one of: {', '.join(_V1_CONTRACT_TYPES)}.",
                suggested_fix=f"Add a `### Mechanical contracts`, `### Coverage contracts`, or `### Exemplar bindings` subsection to §{section}, or mark the view `not-applicable`.",
            ))
    if len(na_views) > 2:
        results.append(_findings.Finding(
            tier=1,
            kind="excessive-not-applicable",
            severity="warn",
            location=_findings.FindingLocation(scope="spec-wide", ref="v1-views"),
            message=f"{len(na_views)} of 5 v1.0 views marked not-applicable (§§{', '.join(na_views)}). Spec may be under-specified.",
            suggested_fix="Review whether each N/A is legitimate scope-narrowing or under-specification. Maximum two N/A views is the recommended ceiling.",
        ))
    return results


def _v1_structural_checks(body: str) -> list[_findings.Finding]:
    """Run all v1.0 structural checks. Aggregate entry point called from classify().

    Non-v1.0 specs (no Spec-version frontmatter) short-circuit — the §§8.3-8.7
    and §§9-13 checks only apply to specs explicitly opting into v1.0.
    """
    # Short-circuit when the spec is pre-v1.0 (no frontmatter declaration).
    if _SPEC_VERSION_RE.search(body) is None:
        return []
    results: list[_findings.Finding] = []
    results.extend(_check_v1_spec_version(body))
    # If spec-version check fails (non-1.0 value), the rest are noise
    if any(r.kind == "unsupported-spec-version" for r in results):
        return results
    results.extend(_check_v1_substrate_family(body))
    results.extend(_check_v1_view_sections(body))
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
    - CLI output flags: a token in _SELF_CYCLE_OUTPUT_OPTS means the next
      non-flag token is an authored output destination. Also handles the
      equals-form (--out=path).

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
    # CLI output flags: -o path, --out path, --out=path, etc.
    # Tokenise the action to find flag → next-token pairs.
    tokens: list[str] | None = None
    for attempt in [action, action + "'", action + '"']:
        try:
            tokens = shlex.split(attempt)
            break
        except ValueError:
            continue
    if tokens is not None:
        posix_end = False  # True after a bare '--' token
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "--":
                posix_end = True
                i += 1
                continue
            if not posix_end:
                # Equals-form: --out=path or --output=path
                if "=" in tok:
                    opt, _, val = tok.partition("=")
                    if opt in _SELF_CYCLE_OUTPUT_OPTS and val:
                        created.append(val)
                    i += 1
                    continue
                # Space-separated form: --out path
                if tok in _SELF_CYCLE_OUTPUT_OPTS:
                    if i + 1 < len(tokens):
                        created.append(tokens[i + 1])
                        i += 2
                    else:
                        i += 1
                    continue
            i += 1
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
                    # v0.6.2: parent-package match — `module:foo.bar` covers imports
                    # of `foo.bar` and any deeper child (`foo.bar.baz`).
                    if mod_top in declared_packages or module in declared_modules:
                        continue
                    if any(module == dm or module.startswith(dm + ".") for dm in declared_modules):
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
                # v0.6.2 FIX (#36): exclude spans already matched by
                # `from X import Y` so the symbol after `import` (e.g.
                # `is_blocked`) is not flagged as an unowned module.
                from_import_spans = [im.span() for im in _PYTHON_IMPORT_RE.finditer(body_text)]
                for im in _PYTHON_IMPORT_ALT_RE.finditer(body_text):
                    if any(s <= im.start() < e for s, e in from_import_spans):
                        continue
                    module = im.group(1)
                    mod_top = module.split(".")[0]
                    # Skip stdlib modules — only flag project packages
                    if mod_top in _STDLIB_TOPS:
                        continue
                    # P3 contract shadows: skip if any step declares this package/module
                    if mod_top in declared_packages or module in declared_modules:
                        continue
                    if any(module == dm or module.startswith(dm + ".") for dm in declared_modules):
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
                # Validate each entry; track how many are well-formed (both trigger + handler present)
                well_formed_count = 0
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
                    else:
                        well_formed_count += 1
                # All entries malformed → no valid failure branch; apply same gate as missing
                if well_formed_count == 0 and reboot_survival == "required":
                    msg = (
                        f"Step {step_n} declares produces but has no well-formed negative-paths entries; "
                        f"reboot-survival=required mandates a valid failure-branch declaration."
                    )
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="missing-negative-path",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="negative-paths"
                        ),
                        message=msg,
                        suggested_fix=(
                            "Add at least one negative-paths entry with both trigger: and handler: keys."
                        ),
                    ))

    return results


# ── v0.8 §42: self-cycle produces ────────────────────────────────────────────

# Option-name values that carry input file paths (not output/target paths).
_SELF_CYCLE_INPUT_OPTS: frozenset[str] = frozenset({
    "--manifest", "--config", "--from", "--input", "--source", "--file", "--from-file",
})

# Option-name values that carry output file paths (the destination/target of the action).
# A path following one of these flags is an authored output, not a consumed input,
# so it must NOT trigger a self-cycle-produces finding.
_SELF_CYCLE_OUTPUT_OPTS: frozenset[str] = frozenset({
    "-o", "--out", "--output", "-O", "--outfile",
    "--out-file", "--target", "--dest", "--destination",
})

# File suffixes that make a bare token look like a file path.
_FILE_SUFFIXES: frozenset[str] = frozenset({
    ".toml", ".json", ".sqlite", ".onnx", ".skops", ".yaml", ".yml",
    ".md", ".py", ".txt", ".db", ".sqlite3",
})


def _extract_action_path_tokens(action: str) -> list[str]:
    """Return path tokens from an action string that look like input file paths.

    Tokenises with shlex. Collects:
    - tokens starting with '/' or containing './'
    - tokens with a known file suffix
    - values of long input-option flags (both '--opt value' and '--opt=value')

    Returns the raw token strings (not URI-stripped).
    """
    tokens: list[str] | None = None
    for attempt in [action, action + "'", action + '"']:
        try:
            tokens = shlex.split(attempt)
            break
        except ValueError:
            continue
    if tokens is None:
        return []

    paths: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # '--opt=value' form
        if tok.startswith("--") and "=" in tok:
            opt, _, val = tok.partition("=")
            if opt in _SELF_CYCLE_INPUT_OPTS and val:
                paths.append(val)
            i += 1
            continue
        # '--opt value' form
        if tok in _SELF_CYCLE_INPUT_OPTS:
            if i + 1 < len(tokens):
                paths.append(tokens[i + 1])
                i += 2
            else:
                i += 1
            continue
        # Absolute path or relative-with-./
        if tok.startswith("/") or "./" in tok:
            paths.append(tok)
            i += 1
            continue
        # Known file suffix (relative path token like 'src/foo.toml')
        if any(tok.endswith(sfx) for sfx in _FILE_SUFFIXES):
            paths.append(tok)
            i += 1
            continue
        i += 1
    return paths


def _produces_file_paths(produces: list[str]) -> list[str]:
    """Return the path portion of 'file:<path>' produces entries only.

    Non-file: scheme entries (package:, route:, db-table:, etc.) are ignored.
    """
    result: list[str] = []
    for entry in produces:
        if not isinstance(entry, str):
            continue
        scheme, _, value = entry.partition(":")
        if scheme == "file" and value:
            result.append(value)
    return result


def _action_token_matches_produces_path(token: str, produces_path: str) -> bool:
    """Return True if *token* (from the action string) refers to *produces_path*.

    Exact match first. Then suffix-match: relative token is a suffix of an
    absolute produces_path. This handles the gateway repro shape where the
    action uses 'src/foo.toml' and produces declares
    'file:/abs/path/to/src/foo.toml'.
    """
    if token == produces_path:
        return True
    # Relative token: check suffix against absolute produces path
    if not token.startswith("/"):
        return produces_path.endswith("/" + token)
    # Absolute token: check suffix of produces path against token
    return produces_path == token or produces_path.endswith("/" + token.lstrip("/"))


def _check_self_cycle_produces(steps: list[dict]) -> list[_findings.Finding]:
    """Tier 1 block: a step's action consumes a path it also produces, with no
    earlier step's produces: covering that path.

    Only 'file:' produces entries are considered; other URI schemes are not file
    paths and are skipped.

    Directories in --target (or similar) are excluded: a token must look like a
    full file path (has a known suffix OR came from an explicit input-option flag
    like --manifest/--config/etc.) to trigger a finding.
    """
    results: list[_findings.Finding] = []

    # Accumulate 'file:' produces paths from all prior steps (exact path strings).
    prior_file_produces: list[str] = []

    for step in steps:
        step_n: int = step["step"]  # type: ignore[assignment]
        action: str = step.get("action", "")  # type: ignore[assignment]
        produces: list[str] = step.get("produces", []) or []  # type: ignore[assignment]

        if action:
            action_tokens = _extract_action_path_tokens(action)
            # Exclude paths the action itself *writes* (redirect destinations,
            # cp/install/tee targets) — those are outputs, not consumed inputs.
            authored = set(_action_authored_path(action))
            this_produces_paths = _produces_file_paths(produces)

            for tok in dict.fromkeys(action_tokens):
                if tok in authored:
                    continue
                # Check if this token matches any of THIS step's produces paths
                matching_produce = next(
                    (p for p in this_produces_paths
                     if _action_token_matches_produces_path(tok, p)),
                    None,
                )
                if matching_produce is None:
                    continue
                # Check if an EARLIER step's produces already covers this path
                covered_by_prior = any(
                    _action_token_matches_produces_path(tok, prior_p)
                    for prior_p in prior_file_produces
                )
                if covered_by_prior:
                    continue
                # Self-cycle confirmed
                display = tok if len(tok) <= 60 else "..." + tok[-57:]
                msg = f"Step {step_n} action consumes {display!r} which it also produces (self-cycle)."
                if len(msg) > 140:
                    msg = msg[:137] + "..."
                results.append(_findings.Finding(
                    tier=1,
                    kind="self-cycle-produces",
                    severity="block",
                    location=_findings.FindingLocation(
                        scope="step", step=step_n, ref="produces"
                    ),
                    message=msg,
                    suggested_fix=(
                        "Move the file to a prior step's produces:, or remove it from "
                        "this step's produces: if it is an input, not an output."
                    )[:140],
                ))

        # Accumulate this step's 'file:' produces for subsequent checks
        prior_file_produces.extend(_produces_file_paths(produces))

    return results


# ── v0.9 §46: implicit-precondition-missing ──────────────────────────────────

# Verb phrases in negative-paths trigger text that flag a precondition gap.
_PRECOND_VERB_RE = re.compile(
    r"\b(absent|missing|does\s+not\s+exist|not\s+found|malformed|not\s+writable|cannot\s+find)\b",
    re.IGNORECASE,
)

# File-like suffixes that make a bare token look like a filesystem path.
# Mirrors _FILE_SUFFIXES above but is a separate constant so callers can
# extend independently.
_PRECOND_PATH_SUFFIXES: frozenset[str] = frozenset({
    ".toml", ".json", ".yaml", ".yml", ".lock", ".txt", ".md",
    ".py", ".sh", ".rs", ".go", ".js", ".ts", ".cfg", ".ini",
    ".conf", ".env", ".service",
})

# Canonical bare-name files that have no extension and no '/' but are
# unambiguously filesystem paths (e.g. Makefile, Dockerfile).
_PRECOND_BARE_NAMES: frozenset[str] = frozenset({
    "Makefile", "Dockerfile", "go.mod", "go.sum", "Gemfile", "Rakefile",
    "BUILD", "WORKSPACE", "Cargo.lock", "package-lock.json", "yarn.lock",
})


# Verb-first phrasings: "missing <path>", "cannot find <path>".
# Capture group 1 is the path-shaped noun that follows the verb prefix.
_PRECOND_VERB_FIRST_RE = re.compile(
    r"^(?:missing|cannot\s+find)\s+(\S+)",
    re.IGNORECASE,
)


def _extract_precond_path_token(trigger: str) -> str | None:
    """Extract the filesystem-path-shaped noun from a negative-paths trigger.

    Returns the token (without surrounding whitespace) if:
    1. The trigger contains one of the precondition verb-phrases (absent,
       missing, does not exist, not found, malformed, not writable).
    2. The noun token looks like a filesystem path:
       - contains '/' (e.g. 'state/db.sqlite'), OR
       - has a known file suffix (e.g. 'pyproject.toml'), OR
       - ends with '/' (directory shape, e.g. 'state/'), OR
       - exactly matches a known bare name (e.g. 'Makefile').
    3. The trigger does NOT look like an environmental trigger (port numbers,
       env-var names, WAL-mode, etc.) — these pass through without a finding.

    Supported phrasings:
    - <noun> <verb>  (e.g. "pyproject.toml absent")
    - missing <noun> (verb-first)
    - cannot find <noun> (verb-first)

    Returns None if no match, or if the trigger is environmental.
    """
    trigger_stripped = trigger.strip()

    # Must contain a precondition verb
    if not _PRECOND_VERB_RE.search(trigger_stripped):
        return None

    # Verb-first: "missing <noun>" / "cannot find <noun>"
    m = _PRECOND_VERB_FIRST_RE.match(trigger_stripped)
    if m:
        noun = m.group(1).rstrip(",:;")
    else:
        # Noun-first: extract first token (the noun before the verb)
        parts = trigger_stripped.split()
        if not parts:
            return None
        noun = parts[0].rstrip(",:;")

    # Reject environmental tokens:
    # - pure numeric (port number)
    if re.match(r"^\d+$", noun):
        return None
    # - ALL_CAPS env-var pattern
    if re.match(r"^[A-Z][A-Z0-9_]+$", noun):
        return None
    # - common non-path starters (WAL, port, socket, etc.)
    if re.match(r"^(port|socket|WAL|mode|env|var|flag|pid)\b", noun, re.IGNORECASE):
        return None

    # Accept if path-shaped
    if "/" in noun or noun.endswith("/"):
        return noun
    if any(noun.endswith(sfx) for sfx in _PRECOND_PATH_SUFFIXES):
        return noun
    if noun in _PRECOND_BARE_NAMES:
        return noun

    return None


def _check_implicit_precondition_missing(
    steps: list[dict],
) -> list[_findings.Finding]:
    """Tier 1 block: a step's negative-paths trigger names a filesystem path
    that no step's produces: covers.

    For each step:
    1. Parse negative_paths entries.
    2. For each trigger, attempt to extract a path-shaped noun.
    3. If the noun is not present in any step's produces: (across all steps,
       not just earlier ones — the forgotten-scaffold pattern usually omits
       the file entirely), emit ``implicit-precondition-missing`` block.

    Edge case — directory-shaped tokens (e.g. ``state/``): compare against
    produces entries after stripping a trailing slash from both sides.
    """
    results: list[_findings.Finding] = []

    # Build flat set of all produce values across ALL steps
    all_produces_raw: list[str] = []
    for s in steps:
        for entry in (s.get("produces", []) or []):
            if isinstance(entry, str):
                all_produces_raw.append(entry)

    def _covered(noun: str) -> bool:
        """Return True when *noun* is covered by at least one produces entry."""
        noun_norm = noun.rstrip("/")
        for entry in all_produces_raw:
            if noun_norm in entry:
                return True
            # Directory match: 'state/' covered by 'file:/abs/path/state'
            if entry.rstrip("/").endswith("/" + noun_norm):
                return True
        return False

    for step in steps:
        step_n: int = step.get("step")  # type: ignore[assignment]
        if step_n is None:
            continue
        negative_paths: list[dict] = step.get("negative_paths", []) or []
        for entry in negative_paths:
            if not isinstance(entry, dict):
                continue
            trigger: str = entry.get("trigger", "") or ""
            noun = _extract_precond_path_token(trigger)
            if noun is None:
                continue
            if _covered(noun):
                continue
            noun_display = noun[:60] if len(noun) <= 60 else "..." + noun[-57:]
            msg = (
                f"Step {step_n} negative-path trigger names {noun_display!r} "
                f"but no step's produces: covers it."
            )
            if len(msg) > 140:
                msg = msg[:137] + "..."
            results.append(_findings.Finding(
                tier=1,
                kind="implicit-precondition-missing",
                severity="block",
                location=_findings.FindingLocation(
                    scope="step", step=step_n, ref="negative-paths"
                ),
                message=msg,
                suggested_fix=(
                    "Add a prior step that produces this path, or remove the "
                    "negative-path if the file is always present."
                )[:140],
            ))

    return results


# ── v0.9 §50 Contract 2: stub-producer-invoked ───────────────────────────────

# Stub marker patterns checked inside heredoc / write bodies.
_STUB_MARKER_STRINGS: tuple[str, ...] = (
    "raise NotImplementedError",
    "pass  # stub",
    "pass  # TODO",
    "pass  # placeholder",
    "# TODO: implement",
    "# todo: implement",
    "# TODO: Implement",
    'console.log("stub")',
    "console.log('stub')",
    'console.log("not implemented")',
    "console.log('not implemented')",
)


def _extract_write_bodies(action: str) -> list[tuple[str, str]]:
    """Extract (target_path, body) pairs from write operations in *action*.

    Handles:
    1. Heredoc: ``cat > <path> <<'EOF' ... EOF`` (and variants without quotes).
    2. ``echo "..." > <path>`` / ``printf "..." > <path>``.
    3. ``python3 -c "..." > <path>`` bodies via shlex.
    4. ``tee <path>`` with preceding pipe body.

    Returns list of (path, body_text) tuples.  The path may be empty string if
    the target cannot be determined; callers should still check the body.
    """
    results: list[tuple[str, str]] = []

    # 1. Heredoc: cat > <path> <<'EOF'\n...\nEOF
    # Allow: cat >, cat>  (optional spaces), tee, echo with heredoc
    for m in re.finditer(
        r"(?:cat\s*>|tee)\s*(/[a-zA-Z0-9_./\-]+)\s*<<['\"]?(\w+)['\"]?\n(.*?)\n\s*\2\b",
        action,
        re.DOTALL,
    ):
        path = m.group(1)
        body = m.group(3)
        results.append((path, body))

    # 2. echo "..." > path  (single-line write)
    for m in re.finditer(
        r"""\becho\s+['"]([^'"]{0,300})['"]\s*(?:>>?\s*)(/[a-zA-Z0-9_./\-]+)""",
        action,
    ):
        results.append((m.group(2), m.group(1)))

    # 3. printf "..." > path
    for m in re.finditer(
        r"""\bprintf\s+['"]([^'"]{0,500})['"]\s*(?:>>?\s*)(/[a-zA-Z0-9_./\-]+)""",
        action,
    ):
        results.append((m.group(2), m.group(1)))

    return results


def _body_is_stub(body: str) -> tuple[bool, str]:
    """Return (is_stub, reason) based on heuristic stub detection.

    Checks for explicit stub markers and empty-function bodies.
    """
    for marker in _STUB_MARKER_STRINGS:
        if marker in body:
            return True, f"contains {marker!r}"

    # Empty function body: only 'pass' (no other non-blank, non-comment lines)
    non_blank_lines = [
        line for line in body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if non_blank_lines and all(line.strip() in ("pass",) for line in non_blank_lines):
        return True, "body is only 'pass'"

    # Body length < 5 non-blank non-comment lines AND contains 'pass' or TODO
    if len(non_blank_lines) < 5:
        body_lower = body.lower()
        if "pass" in body_lower or "todo" in body_lower or "stub" in body_lower:
            return True, f"short body ({len(non_blank_lines)} lines) with stub keyword"

    return False, ""


def _why_is_stub(why: str) -> tuple[bool, str]:
    """Return (is_stub, reason) if a step's why: text contains stub-intent keywords."""
    why_lower = why.lower()
    for kw in ("stub", "placeholder", "scaffold-only", "replaced by step"):
        if kw in why_lower:
            return True, f"why: contains {kw!r}"
    return False, ""


def _action_writes_path(action: str, path_suffix: str) -> bool:
    """Return True if *action* writes to a path ending with *path_suffix*."""
    for pat, _ in _extract_write_bodies(action):
        if pat and (pat == path_suffix or pat.endswith("/" + path_suffix.lstrip("/"))):
            return True
    # Also check simple redirect targets not in heredoc form
    for m in re.finditer(r"(?:>>?)\s*(/[a-zA-Z0-9_./\-]+)", action):
        p = m.group(1)
        if p == path_suffix or p.endswith("/" + path_suffix.lstrip("/")):
            return True
    return False


def _extract_artifact_path_from_contract(entry: str) -> str:
    """Return a filesystem-path-like string from a contract entry.

    For 'file:/some/path' returns '/some/path'.
    For 'module:foo.bar' returns 'foo/bar' (dot-to-slash).
    For 'package:foo' returns 'foo'.
    Otherwise returns the value portion.
    """
    if ":" not in entry:
        return entry
    scheme, _, value = entry.partition(":")
    if scheme == "file":
        return value
    if scheme == "module":
        return value.replace(".", "/")
    return value


def _module_invoked_in_action(action: str, artifact_value: str) -> bool:
    """Return True if *action* invokes the module/package named by *artifact_value*.

    Checks: python3 -m <module>, direct invocation of path patterns.
    """
    # python3 -m <module>
    mod_slash = artifact_value.replace(".", "/")
    mod_dot = artifact_value.replace("/", ".")
    for m in re.finditer(r"\bpython3?\s+-m\s+([\w.]+)", action):
        invoked = m.group(1)
        if invoked == mod_dot or invoked.startswith(mod_dot + "."):
            return True
    # Direct path invocation
    for m in re.finditer(
        r"\b(?:python3?|bash|sh|node|ruby|perl)\s+(/[a-zA-Z0-9_./\-]+)",
        action,
    ):
        p = m.group(1)
        if mod_slash in p:
            return True
    return False


def _check_stub_producer_invoked(steps: list[dict]) -> list[_findings.Finding]:
    """Tier 1 block: a step invokes an artifact produced by an earlier stub step,
    and no intermediate step replaces the stub body.

    Logic per step N:
    1. For each requires: entry in step N, identify the producing step M
       (the latest step < N that produces the entry).
    2. Check if step M's action writes a stub body for the artifact.
       Also check if step M's why: text contains stub keywords.
    3. Scan steps M+1..N-1 for any action that overwrites the artifact without
       a stub body (healing step).
    4. If stub detected and no healer found: emit block finding.
    """
    results: list[_findings.Finding] = []

    # Build: artifact -> (step_index, step_dict) for each produces entry
    # We want the LAST step that produces each artifact before step N.
    for idx_n, step in enumerate(steps):
        step_n: int = step["step"]  # type: ignore[assignment]
        requires: list[str] = step.get("requires", []) or []  # type: ignore[assignment]

        for req_entry in requires:
            if not _validate_contract_entry(req_entry):
                continue

            # Find the LAST producer step before step N
            producer_step: dict | None = None
            producer_idx: int = -1
            for idx_m in range(idx_n):
                m_step = steps[idx_m]
                m_produces: list[str] = m_step.get("produces", []) or []
                if req_entry in m_produces:
                    producer_step = m_step
                    producer_idx = idx_m

            if producer_step is None:
                # unowned-requirement catches this; skip
                continue

            # Check if the producer step looks like a stub
            m_action: str = producer_step.get("action", "") or ""
            m_why: str = producer_step.get("why", "") or ""

            is_stub = False
            stub_reason = ""

            # Check why: text first (explicit intent signal)
            stub_from_why, why_reason = _why_is_stub(m_why)
            if stub_from_why:
                is_stub = True
                stub_reason = why_reason

            # Check action bodies
            if not is_stub and m_action:
                for _path, body in _extract_write_bodies(m_action):
                    body_stub, body_reason = _body_is_stub(body)
                    if body_stub:
                        is_stub = True
                        stub_reason = body_reason
                        break

            if not is_stub:
                continue

            # Determine the artifact path for healing check
            artifact_path = _extract_artifact_path_from_contract(req_entry)

            # Scan steps M+1..N-1 for a healing write (real body, no stub markers)
            healed = False
            for idx_h in range(producer_idx + 1, idx_n):
                h_step = steps[idx_h]
                h_action: str = h_step.get("action", "") or ""
                if not h_action:
                    continue
                # Does this step write to the artifact path?
                if not _action_writes_path(h_action, artifact_path):
                    continue
                # Confirm the write is NOT itself a stub
                all_stub = True
                for _p, body in _extract_write_bodies(h_action):
                    body_stub, _ = _body_is_stub(body)
                    if not body_stub:
                        all_stub = False
                        break
                if not all_stub:
                    healed = True
                    break

            if healed:
                continue

            m_step_n: int = producer_step["step"]  # type: ignore[assignment]
            artifact_display = artifact_path[:40] if len(artifact_path) <= 40 else "..." + artifact_path[-37:]
            msg = (
                f"Step {step_n} requires {req_entry!r} produced by Step {m_step_n} "
                f"which looks like a stub ({stub_reason})."
            )
            if len(msg) > 140:
                msg = msg[:137] + "..."
            results.append(_findings.Finding(
                tier=1,
                kind="stub-producer-invoked",
                severity="block",
                location=_findings.FindingLocation(
                    scope="step", step=step_n, ref="requires"
                ),
                message=msg,
                suggested_fix=(
                    f"Step {m_step_n} should write the real implementation of "
                    f"{artifact_display!r}, or insert an authoring step before Step {step_n}."
                )[:140],
            ))

    return results


# ── v0.9 §50 Contract 3: verification-anchored-to-produces ───────────────────


def _produces_path_tokens(produces: list[str]) -> set[str]:
    """Return path-like tokens from a produces: list (file: entries only).

    Returns both full paths and basenames so substring checks against
    verification text can match either form.
    """
    result: set[str] = set()
    for entry in produces:
        if not isinstance(entry, str):
            continue
        scheme, _, value = entry.partition(":")
        if scheme == "file" and value:
            result.add(value)
            # Also add basename for partial-match verification
            basename = value.split("/")[-1] if "/" in value else value
            if basename:
                result.add(basename)
    return result


def _verification_references_any(verification: str, path_tokens: set[str]) -> bool:
    """Return True if *verification* contains any of *path_tokens* as a substring."""
    for tok in path_tokens:
        if tok and tok in verification:
            return True
    return False


def _check_verification_anchored(steps: list[dict]) -> list[_findings.Finding]:
    """Contract 3a: warn if step's verification has no path token overlapping
    with THIS step's produces: (verification-not-anchored-to-produces).

    Only applies when:
    - The step has at least one 'file:' produces entry
    - The step has a non-trivial verification (not a tautology)

    Contract 3b: warn if verification ONLY references paths from earlier steps'
    produces, not this step's (verification-upstream-only).

    Implementation uses substring matching (not _PATH_RE) because the word-
    boundary anchor in _PATH_RE clips paths that follow non-word chars like
    spaces or flag dashes (e.g. ``test -x /opt/hello/hello``).
    """
    results: list[_findings.Finding] = []

    # Cumulative produces path tokens across prior steps
    cumulative_file_paths: list[set[str]] = []

    for idx, step in enumerate(steps):
        step_n: int = step["step"]  # type: ignore[assignment]
        verification: str = step.get("verification", "") or ""  # type: ignore[assignment]
        produces: list[str] = step.get("produces", []) or []  # type: ignore[assignment]

        this_produces_paths = _produces_path_tokens(produces)
        prior_paths: set[str] = set()
        for prior_set in cumulative_file_paths:
            prior_paths.update(prior_set)

        if verification and not _is_soft_verification(verification) and this_produces_paths:
            # Contract 3a: does verification reference ANY token from THIS step's produces?
            anchored_to_this = _verification_references_any(verification, this_produces_paths)

            if not anchored_to_this:
                # Contract 3b: does it reference prior-step paths only?
                anchored_to_prior = _verification_references_any(verification, prior_paths)
                if anchored_to_prior:
                    msg = (
                        f"Step {step_n} verification references only prior-step paths, "
                        f"not this step's produces: ({', '.join(sorted(this_produces_paths)[:2])})."
                    )
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="verification-upstream-only",
                        severity="warn",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="verification"
                        ),
                        message=msg,
                        suggested_fix="Add a check on this step's own produced artifacts.",
                    ))
                else:
                    msg = (
                        f"Step {step_n} verification has no path token overlapping "
                        f"this step's produces: ({', '.join(sorted(this_produces_paths)[:2])})."
                    )
                    if len(msg) > 140:
                        msg = msg[:137] + "..."
                    results.append(_findings.Finding(
                        tier=1,
                        kind="verification-not-anchored-to-produces",
                        severity="warn",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="verification"
                        ),
                        message=msg,
                        suggested_fix="Add a check on this step's produced paths.",
                    ))

        cumulative_file_paths.append(this_produces_paths)

    return results


def _check_verification_depth(step: dict, step_n: int) -> list[_findings.Finding]:
    """Tier-1: warn if a behavioral why-clause is paired with structural-only verification.

    An implementing agent could satisfy a structural check (test -f, grep -q) with
    a no-op symbol matching the claimed name; the load-bearing behavior never gets
    tested. When the why-clause names behavioral semantics, the verification must
    exercise that behavior.
    """
    why = step.get("why", "") or ""
    verification = step.get("verification", "") or ""
    if not why or not verification:
        return []
    if not _BEHAVIORAL_VERB_RE.search(why):
        return []
    if not _STRUCTURAL_ONLY_VERIFICATION_RE.match(verification):
        return []
    verb = _BEHAVIORAL_VERB_RE.search(why).group(1)  # type: ignore[union-attr]
    return [_findings.Finding(
        tier=1,
        kind="verification-too-shallow-for-claim",
        severity="warn",
        location=_findings.FindingLocation(scope="step", step=step_n, ref="verification"),
        message=(
            f"Step {step_n} why-clause names behavioral semantics "
            f"({verb!r}) but verification is "
            f"structural-only — agent could satisfy with a no-op."
        ),
        suggested_fix=(
            "Add a runtime test (e.g. `pnpm exec vitest run <module>.test.ts`) "
            "that exercises the claimed behavior, not just the symbol's existence."
        ),
    )]


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

        # Check 6 (v1.1 Fix 3): behavioral claim with structural-only verification
        results.extend(_check_verification_depth(step, step_n))

    # ── Check 4: missing-receiver-calibration ────────────────────────────────
    results.extend(_check_receiver_calibration(body))

    # ── v1.0 — six-view spec model structural checks ─────────────────────────
    results.extend(_v1_structural_checks(body))

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

    # ── Check 9 (v0.8 §42): self-cycle produces ──────────────────────────────
    results.extend(_check_self_cycle_produces(steps))

    # ── Check 10 (v0.9 §46): implicit-precondition-missing ───────────────────
    results.extend(_check_implicit_precondition_missing(steps))

    # ── Check 11 (v0.9 §50): stub-producer-invoked ───────────────────────────
    results.extend(_check_stub_producer_invoked(steps))

    # ── Check 12 (v0.9 §50): verification anchored to produces ───────────────
    results.extend(_check_verification_anchored(steps))

    return results
