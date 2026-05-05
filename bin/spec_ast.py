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

# ── Path-like token regex (text-match heuristic for action-not-probed) ───────
_PATH_RE = re.compile(r"\b(/[a-zA-Z0-9_/.-]+)")


def _is_soft_verification(value: str) -> bool:
    """Return True if value matches any tautology pattern."""
    stripped = value.strip()
    for pat in _SOFT_VERIFY_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _extract_paths_from_text(text: str) -> list[str]:
    """Return all path-like tokens found in text (text-match heuristic)."""
    return _PATH_RE.findall(text)


def _parse_steps_section(body: str) -> list[dict[str, str | int]]:
    """
    Parse ## 6. Steps section from a spec body.

    Returns a list of dicts, each with keys: 'step' (int), and zero or
    more of 'why', 'action', 'verification' (all str).
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

    steps: list[dict[str, str | int]] = []
    for yaml_text in yaml_blocks:
        # Split on lines beginning with '- step:' (step block delimiters)
        # We use re.split but keep the delimiter so we can reconstruct step_n
        raw_blocks = re.split(r"(?=^\s*- step:)", yaml_text, flags=re.MULTILINE)
        for raw in raw_blocks:
            raw = raw.strip()
            if not raw:
                continue
            step: dict[str, str | int] = {}
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
                steps.append(step)

    return steps


def _check_receiver_calibration(body: str) -> list[_findings.Finding]:
    """Return findings for missing §8.1 section or missing required fields."""
    results: list[_findings.Finding] = []

    # Check for §8 section presence
    has_section = bool(re.search(r"^## 8\. Receiver Calibration", body, re.MULTILINE))
    has_81 = bool(re.search(r"^### 8\.1", body, re.MULTILINE))

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

    # Find §8.1 block (from ### 8.1 until next ### or ## heading or EOF)
    m81 = re.search(r"^### 8\.1.*$", body, re.MULTILINE)
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

    return results
