"""
test_skill_no_version_markers.py — ban version-marker patterns from skill prose.

Since v0.8.0 skill prose must not embed version markers such as "(v0.X)",
"Per v0.X", or "see CHANGELOG" — these create maintenance debt and become
stale immediately after release. Skills should describe behavior timelessly.

Patterns banned:
  - (v0.X), (v0.X.Y), (v0.X.Y.Z) — parenthesized version references
  - Per v0.X, per v0.X.Y        — "per version" citations
  - see CHANGELOG                 — changelog cross-references
"""

import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent

# Patterns that indicate version markers in skill prose
_VERSION_MARKER_PATTERNS = [
    re.compile(r"\(v\d+\.\d+(?:\.\d+)*\)"),   # (v0.X), (v0.X.Y), (v0.X.Y.Z)
    re.compile(r"\bPer v\d+\.\d+", re.IGNORECASE),   # Per v0.X
    re.compile(r"\bper v\d+\.\d+", re.IGNORECASE),   # per v0.X
    re.compile(r"\bsee CHANGELOG\b", re.IGNORECASE),  # see CHANGELOG
]


def _find_version_markers(skill_path: pathlib.Path) -> list[str]:
    """Return list of violation descriptions for version markers in the skill."""
    violations: list[str] = []
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        for pat in _VERSION_MARKER_PATTERNS:
            if pat.search(line):
                violations.append(
                    f"{skill_path.relative_to(_REPO)}:{i + 1}: "
                    f"version marker found — remove or rewrite timelessly: "
                    f"{line.strip()!r}"
                )
                break  # report each line once even if multiple patterns match
    return violations


def test_vision_skill_no_version_markers():
    """vision/SKILL.md must not contain version-marker patterns."""
    skill = _REPO / "skills" / "vision" / "SKILL.md"
    violations = _find_version_markers(skill)
    assert violations == [], (
        "vision/SKILL.md contains version markers:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_implement_skill_no_version_markers():
    """implement/SKILL.md must not contain version-marker patterns."""
    skill = _REPO / "skills" / "implement" / "SKILL.md"
    violations = _find_version_markers(skill)
    assert violations == [], (
        "implement/SKILL.md contains version markers:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_all_skills_no_version_markers():
    """Global guard — any SKILL.md under skills/ with a version marker fails CI."""
    skills_dir = _REPO / "skills"
    all_violations: list[str] = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        all_violations.extend(_find_version_markers(skill_md))
    assert all_violations == [], (
        "version markers found in skills:\n"
        + "\n".join(f"  {v}" for v in all_violations)
    )
