"""
test_skill_phase_names.py — phase-name discipline guard for skill prose.

Since v0.8.0 skill sections are named by phase (e.g. "Phase: Fingerprint")
rather than numbered steps ("Step 0 —"). This test pins the phase name
inventory for both skills so accidental renames are caught in CI.
"""

import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent
_VISION_SKILL = _REPO / "skills" / "vision" / "SKILL.md"
_IMPLEMENT_SKILL = _REPO / "skills" / "implement" / "SKILL.md"

# Expected phase names (order-insensitive; each must appear exactly once as a
# "### Phase: <name>" heading).
_VISION_PHASES = {
    "First-run welcome",
    "Fingerprint (silent, internal)",
    "Wizard",
    "Intent",
    "Feasibility",
    "Walker loop",
    "Draft",
    "Evaluator gate — setup wizard",
    "Evaluator gate — spec evaluation",
    "Evaluator gate — ADR generation (conditional)",
    "Lock",
    "Transition",
}

_IMPLEMENT_PHASES = {
    "Mode routing",
    "Track",
    "Tier 0 envelope",
    "Context read",
    "Environment",
    "Pre-flight",
    "Check mode",
    "Tier classifier",
    "Resource acquire",
    "Reasoning emit",
    "Execute",
    "Verify",
    "Branch on verification",
    "Drift",
    "Resource release",
    "Failure log",
    "Finding capture",
}

_PHASE_HEADING_RE = re.compile(r"^### Phase:\s+(.+)$")


def _extract_phase_names(skill_path: pathlib.Path) -> set[str]:
    """Return the set of phase names found in ### Phase: <name> headings."""
    names: set[str] = set()
    for line in skill_path.read_text(encoding="utf-8").splitlines():
        m = _PHASE_HEADING_RE.match(line.strip())
        if m:
            names.add(m.group(1).strip())
    return names


def test_vision_skill_has_all_phase_headings():
    """vision/SKILL.md must contain exactly the expected ### Phase: headings."""
    found = _extract_phase_names(_VISION_SKILL)
    missing = _VISION_PHASES - found
    extra = found - _VISION_PHASES
    assert not missing, f"vision/SKILL.md missing phases: {sorted(missing)}"
    assert not extra, f"vision/SKILL.md has unexpected phases: {sorted(extra)}"


def test_implement_skill_has_all_phase_headings():
    """implement/SKILL.md must contain exactly the expected ### Phase: headings."""
    found = _extract_phase_names(_IMPLEMENT_SKILL)
    missing = _IMPLEMENT_PHASES - found
    extra = found - _IMPLEMENT_PHASES
    assert not missing, f"implement/SKILL.md missing phases: {sorted(missing)}"
    assert not extra, f"implement/SKILL.md has unexpected phases: {sorted(extra)}"


def test_vision_skill_has_no_step_number_headings():
    """vision/SKILL.md must not use '### Step N —' numbered headings."""
    text = _VISION_SKILL.read_text(encoding="utf-8")
    step_re = re.compile(r"^### Step \d", re.MULTILINE)
    matches = step_re.findall(text)
    assert matches == [], (
        f"vision/SKILL.md still uses numbered step headings: {matches}"
    )


def test_implement_skill_has_no_step_number_headings():
    """implement/SKILL.md must not use '### Step N —' numbered headings."""
    text = _IMPLEMENT_SKILL.read_text(encoding="utf-8")
    step_re = re.compile(r"^### Step \d", re.MULTILINE)
    matches = step_re.findall(text)
    assert matches == [], (
        f"implement/SKILL.md still uses numbered step headings: {matches}"
    )
