"""Tier 2 default-on coverage gate. Stdlib only.

Checks structural coverage that Tier 1's regex heuristics miss:
  - undeclared-resource (warn)
  - undeclared-host-path (block)
  - calibration-hard-violation (block)
  - decision-without-adr (warn)

Public API:
    classify(spec_path: pathlib.Path, *, preview_adrs: list[str] | None = None)
        -> list[findings.Finding]

Budget: <2s on a 7-step spec.
"""
import pathlib
import re

from bin import findings as _findings
from bin import tier as _tier
from bin import resources as _resources

# ── §8.1 field parsers ────────────────────────────────────────────────────────

_MUTATES_RE = re.compile(r"^\s*[`-]?\s*`?mutates:\s*`?\s*(.*)", re.IGNORECASE)
_NEVER_TOUCHES_RE = re.compile(r"^\s*[`-]?\s*`?never-touches:\s*`?\s*(.*)", re.IGNORECASE)
_ADR_REF_RE = re.compile(r"adr-ref:\s*(\S+)", re.IGNORECASE)
_DECISION_LINE_RE = re.compile(r"^\s*[-*]?\s*decision:\s+\S", re.IGNORECASE | re.MULTILINE)


def parse_81_block(spec_text: str) -> dict[str, list[str]]:
    """Parse §8.1 hard-contract block. Permissive of backticked-key syntax.

    Public API. The skills/implement/SKILL.md heredoc imports this rather
    than re-deriving an inline regex (the inline form was too strict and
    silently produced empty sets on the `mutates:` /path/ backticked-key
    style used in some specs — bug fix v0.4.1 task 10 review).

    Returns a dict with stable keys:
        {
          "mutates": list[str],          # paths after `mutates:`
          "never_touches": list[str],    # paths after `never-touches:`
        }

    Both are empty lists when §8.1 is missing or contains no matching lines.
    Callers that want a flat set of locked paths can `.update()` both lists.
    """
    m81 = re.search(r"^### 8\.1.*$", spec_text, re.MULTILINE)
    if not m81:
        return {"mutates": [], "never_touches": []}

    block_start = m81.end()
    next_h = re.search(r"^#{2,3} ", spec_text[block_start:], re.MULTILINE)
    block = (
        spec_text[block_start : block_start + next_h.start()]
        if next_h
        else spec_text[block_start:]
    )

    mutates: list[str] = []
    never_touches: list[str] = []

    for line in block.splitlines():
        mm = _MUTATES_RE.match(line)
        if mm:
            raw = mm.group(1).strip().strip("`").strip()
            mutates = [v.strip() for v in raw.split(",") if v.strip()]
            continue
        nm = _NEVER_TOUCHES_RE.match(line)
        if nm:
            raw = nm.group(1).strip().strip("`").strip()
            never_touches = [v.strip() for v in raw.split(",") if v.strip()]
            continue

    return {"mutates": mutates, "never_touches": never_touches}


def _parse_81_block(body: str) -> tuple[list[str], list[str]]:
    """Backward-compat tuple shim around parse_81_block.

    Kept so internal call sites (and any test that imported the private
    name) keep working unchanged. Prefer parse_81_block (dict) for new code.
    """
    parsed = parse_81_block(body)
    return parsed["mutates"], parsed["never_touches"]


def _path_covered_by(path: str, prefixes: list[str]) -> bool:
    """Return True if path equals or is under any of the given prefixes.

    Requires a directory boundary: prefix '/etc' does NOT cover '/etcabc'.
    Concretely: path matches if path == prefix or path starts with
    prefix.rstrip('/') + '/'.  This treats every prefix as either an exact
    file path or a directory root — no substring false-positives.
    """
    for prefix in prefixes:
        boundary = prefix.rstrip("/") + "/"
        if path == prefix or path.startswith(boundary):
            return True
    return False


# ── Step parser (private copy — keeps Tier 1 pure; avoids shared module overhead) ──

_FENCE_RE = re.compile(r"```(?:yaml)?\s*\n(.*?)```", re.DOTALL)
_STEP_SPLIT_RE = re.compile(r"(?=^\s*- step:)", re.MULTILINE)


def _parse_steps(body: str) -> list[dict]:
    """Parse ## 6. Steps section; return list of step dicts.

    Each dict has at minimum 'step' (int). May also have 'action', 'why',
    'verification', 'resources' (raw string).
    """
    steps_match = re.search(r"^## 6\. Steps\s*$", body, re.MULTILINE)
    if not steps_match:
        return []

    section_start = steps_match.end()
    next_heading = re.search(r"^## ", body[section_start:], re.MULTILINE)
    section_body = (
        body[section_start : section_start + next_heading.start()]
        if next_heading
        else body[section_start:]
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
            lines = raw.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                m_step = re.match(r"^\s*-\s+step:\s*(\d+)", line)
                if m_step:
                    step["step"] = int(m_step.group(1))
                    i += 1
                    continue
                m_field = re.match(
                    r"^\s+(why|action|verification|resources):\s*(.*)", line
                )
                if m_field:
                    key = m_field.group(1)
                    value = m_field.group(2).strip().strip('"').strip("'")
                    if key == "resources" and value == "":
                        # Block-list format: collect indented `- token` lines
                        tokens: list[str] = []
                        j = i + 1
                        while j < len(lines):
                            m_item = re.match(r"^\s+-\s+(\S+)", lines[j])
                            if m_item:
                                tokens.append(m_item.group(1))
                                j += 1
                            else:
                                break
                        step[key] = ", ".join(tokens)
                        i = j
                    else:
                        step[key] = value
                        i += 1
                    continue
                i += 1
            if "step" in step:
                steps.append(step)

    return steps


def _parse_declared_resources(raw_resources: str) -> set[str]:
    """Parse the 'resources: [res-port-8080, ...]' field into a set of ids."""
    # Strip brackets and split on comma or whitespace
    cleaned = raw_resources.strip().strip("[]").strip()
    if not cleaned:
        return set()
    return {tok.strip().strip(",") for tok in re.split(r"[\s,]+", cleaned) if tok.strip()}


def _extract_host_paths_from_reasons(reasons: list[str]) -> list[str]:
    """Extract host-classified paths from tier.classify reasons strings.

    Reasons look like: "path '/etc/foo.conf' → host"
    """
    host_paths: list[str] = []
    for reason in reasons:
        # Match: path 'X' → host  or  path "X" → host
        m = re.match(r"path\s+['\"]?([^\s'\"]+)['\"]?\s+→\s+host", reason)
        if m:
            host_paths.append(m.group(1))
    return host_paths


def _extract_all_captured_paths_from_reasons(reasons: list[str]) -> list[str]:
    """Extract all path captures from tier.classify reasons (any tier)."""
    paths: list[str] = []
    for reason in reasons:
        m = re.match(r"path\s+['\"]?([^\s'\"]+)['\"]?\s+→\s+\w+", reason)
        if m:
            paths.append(m.group(1))
    return paths


# ── Check implementations ────────────────────────────────────────────────────

def _check_undeclared_resources(
    steps: list[dict],
) -> list[_findings.Finding]:
    """Check: inferred Resources must be declared in step resources: field."""
    results: list[_findings.Finding] = []
    for step in steps:
        step_n: int = step["step"]
        action: str = step.get("action", "")
        if not action:
            continue

        inferred = _resources.extract_resources_from_action(action)
        if not inferred:
            continue

        declared = _parse_declared_resources(step.get("resources", ""))

        for res in inferred:
            if res.id not in declared:
                msg = f"Step {step_n}: inferred resource {res.id!r} not in resources: declaration."
                if len(msg) > _findings.MAX_MESSAGE_LEN:
                    msg = msg[: _findings.MAX_MESSAGE_LEN - 3] + "..."
                fix = f"Add {res.id} to step {step_n} resources:"
                if len(fix) > _findings.MAX_FIX_LEN:
                    fix = fix[: _findings.MAX_FIX_LEN - 3] + "..."
                results.append(
                    _findings.Finding(
                        tier=2,
                        kind="undeclared-resource",
                        severity="warn",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="resources"
                        ),
                        message=msg,
                        suggested_fix=fix,
                    )
                )
    return results


def _check_undeclared_host_paths(
    steps: list[dict],
    mutates: list[str],
) -> list[_findings.Finding]:
    """Check: host-tier paths inferred by tier.classify must appear in §8.1 mutates:."""
    results: list[_findings.Finding] = []
    for step in steps:
        step_n: int = step["step"]
        action: str = step.get("action", "")
        if not action:
            continue

        _tier_name, reasons, _na = _tier.classify(action)
        host_paths = _extract_host_paths_from_reasons(reasons)

        for path in host_paths:
            if not _path_covered_by(path, mutates):
                msg = f"Step {step_n}: host path {path!r} not declared in §8.1 mutates:."
                if len(msg) > _findings.MAX_MESSAGE_LEN:
                    msg = msg[: _findings.MAX_MESSAGE_LEN - 3] + "..."
                fix = f"Add {path} to §8.1 mutates: or remove from action."
                if len(fix) > _findings.MAX_FIX_LEN:
                    fix = fix[: _findings.MAX_FIX_LEN - 3] + "..."
                results.append(
                    _findings.Finding(
                        tier=2,
                        kind="undeclared-host-path",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="action"
                        ),
                        message=msg,
                        suggested_fix=fix,
                    )
                )
    return results


def _check_calibration_hard_violations(
    steps: list[dict],
    mutates: list[str],
    never_touches: list[str],
) -> list[_findings.Finding]:
    """Check: path captures must subset mutates: AND must not intersect never-touches:.

    For each captured path (from tier.classify):
    - If path is in never-touches → calibration-hard-violation (never-touches collision).
    - Else if path is NOT covered by any mutates prefix → calibration-hard-violation
      (mutates-subset violation: path is not authorized by the §8.1 contract).
    - Else → no finding.

    Skip silently if no path captures exist in a step (non-applicable, not a free pass
    at the spec level — each step is evaluated independently).

    Note: if §8.1 is entirely absent, mutates=[] so every captured host path will fire
    the mutates-subset branch.  Tier 1 also surfaces missing-receiver-calibration
    separately; these two signals are complementary.
    """
    results: list[_findings.Finding] = []
    for step in steps:
        step_n: int = step["step"]
        action: str = step.get("action", "")
        if not action:
            continue

        _tier_name, reasons, _na = _tier.classify(action)
        all_captured = _extract_all_captured_paths_from_reasons(reasons)
        host_captured = _extract_host_paths_from_reasons(reasons)

        # Skip if no path captures at all (non-applicable)
        if not all_captured:
            continue

        # never-touches applies to ALL captured paths (any tier): if a path the
        # action touches is in the never-touches list, that is always a violation.
        for path in all_captured:
            if _path_covered_by(path, never_touches):
                msg = f"Step {step_n}: path {path!r} is in §8.1 never-touches:."
                if len(msg) > _findings.MAX_MESSAGE_LEN:
                    msg = msg[: _findings.MAX_MESSAGE_LEN - 3] + "..."
                fix = f"Remove {path} from action or update never-touches: contract."
                if len(fix) > _findings.MAX_FIX_LEN:
                    fix = fix[: _findings.MAX_FIX_LEN - 3] + "..."
                results.append(
                    _findings.Finding(
                        tier=2,
                        kind="calibration-hard-violation",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="action"
                        ),
                        message=msg,
                        suggested_fix=fix,
                    )
                )

        # mutates-subset applies to host-tier paths only: host paths must be
        # authorized by a mutates: prefix.  Non-host paths are not tracked in
        # mutates: so they are excluded from this check.
        for path in host_captured:
            if _path_covered_by(path, never_touches):
                # Already flagged by the never-touches branch above — skip.
                continue
            if not _path_covered_by(path, mutates):
                msg = (
                    f"Step {step_n}: path {path!r} is not covered by any §8.1 mutates: prefix."
                )
                if len(msg) > _findings.MAX_MESSAGE_LEN:
                    msg = msg[: _findings.MAX_MESSAGE_LEN - 3] + "..."
                fix = f"Add {path} (or its parent directory) to §8.1 mutates:."
                if len(fix) > _findings.MAX_FIX_LEN:
                    fix = fix[: _findings.MAX_FIX_LEN - 3] + "..."
                results.append(
                    _findings.Finding(
                        tier=2,
                        kind="calibration-hard-violation",
                        severity="block",
                        location=_findings.FindingLocation(
                            scope="step", step=step_n, ref="action"
                        ),
                        message=msg,
                        suggested_fix=fix,
                    )
                )
    return results


def _check_decision_without_adr(
    body: str,
    preview_adrs: list[str],
) -> list[_findings.Finding]:
    """Check: if §2 has a 'decision:' line, spec must have adr-ref: or preview_adrs.

    Deterministic rule — no semantic matching. Pure syntactic.

    Cardinality: exactly ONE finding per spec, regardless of how many 'decision:'
    markers appear in §2.  If §2 has 3 decision: lines and preview_adrs is empty
    with no adr-ref:, one finding is emitted (covering all markers in aggregate).
    Any non-empty preview_adrs satisfies the rule for all markers.  This matches
    the deterministic-rule intent from the v0.3 Copilot review.
    """
    # Find §2 First Principles section
    s2_match = re.search(r"^## 2\. First Principles\s*$", body, re.MULTILINE)
    if not s2_match:
        return []

    s2_start = s2_match.end()
    next_h = re.search(r"^## ", body[s2_start:], re.MULTILINE)
    s2_body = body[s2_start : s2_start + next_h.start()] if next_h else body[s2_start:]

    # Check for literal 'decision:' line in §2
    if not _DECISION_LINE_RE.search(s2_body):
        return []

    # Has decision marker — now check for resolution
    if preview_adrs:
        return []

    # Check for adr-ref: field anywhere in the spec body
    if _ADR_REF_RE.search(body):
        return []

    # No ADR reference found
    msg = "§2 contains 'decision:' marker but no adr-ref: field or preview ADR provided."
    if len(msg) > _findings.MAX_MESSAGE_LEN:
        msg = msg[: _findings.MAX_MESSAGE_LEN - 3] + "..."
    fix = "Add adr-ref: <slug> to spec or provide preview_adrs when calling classify()."
    if len(fix) > _findings.MAX_FIX_LEN:
        fix = fix[: _findings.MAX_FIX_LEN - 3] + "..."

    return [
        _findings.Finding(
            tier=2,
            kind="decision-without-adr",
            severity="warn",
            location=_findings.FindingLocation(scope="spec-wide", ref="first-principles"),
            message=msg,
            suggested_fix=fix,
        )
    ]


# ── Public API ────────────────────────────────────────────────────────────────

def classify(
    spec_path: pathlib.Path,
    *,
    preview_adrs: list[str] | None = None,
) -> list[_findings.Finding]:
    """Tier 2 default-on coverage gate. Returns Finding list (possibly empty).

    Uses bin.tier.classify and bin.resources.extract_resources_from_action.
    Tier 2 budget: <2s on a 7-step spec.
    """
    if preview_adrs is None:
        preview_adrs = []

    text = spec_path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    steps = _parse_steps(text)
    mutates, never_touches = _parse_81_block(text)

    results: list[_findings.Finding] = []
    results.extend(_check_undeclared_resources(steps))
    results.extend(_check_undeclared_host_paths(steps, mutates))
    results.extend(_check_calibration_hard_violations(steps, mutates, never_touches))
    results.extend(_check_decision_without_adr(text, preview_adrs))

    return results
