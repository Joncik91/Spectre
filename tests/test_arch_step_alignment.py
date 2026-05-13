"""
test_arch_step_alignment.py — phase-name alignment guard.

Every phase name cited in the /vision and /implement tables inside
docs/ARCHITECTURE.md must also appear as a "### Phase: <name>" heading in the
canonical skills/vision/SKILL.md and skills/implement/SKILL.md respectively.

This catches future insertions into SKILL.md that are documented in SKILL.md
but not reflected in ARCHITECTURE.md, or the reverse.

Only the fenced code-block table sections are checked — the prose paragraphs
below the tables reference historical context and are intentionally excluded.
"""
import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent
_ARCH = _REPO / "docs" / "ARCHITECTURE.md"
_VISION_SKILL = _REPO / "skills" / "vision" / "SKILL.md"
_IMPLEMENT_SKILL = _REPO / "skills" / "implement" / "SKILL.md"

# Matches "Phase: Fingerprint (silent, internal)", "Phase: Walker loop", etc.
# at the start of a line (with optional leading whitespace), as found in the
# code-block tables.
_TABLE_PHASE_RE = re.compile(r"^\s*Phase:\s+(.+?)(?:\s{2,}|\s*$)", re.MULTILINE)

# Matches phase headings in SKILL.md: "### Phase: Fingerprint (silent, internal)"
_SKILL_PHASE_RE = re.compile(r"^###\s+Phase:\s+(.+)$", re.MULTILINE)


def _extract_table_phases(arch_text: str, section_header: str) -> set[str]:
    """Extract phase names from the fenced code-block table under a section header.

    Scans from the section header line forward, finds the first fenced code
    block (``` ... ```), and returns the set of phase names inside it.
    """
    # Find the section header
    start_match = re.search(re.escape(section_header), arch_text)
    assert start_match is not None, (
        f"Section header not found in ARCHITECTURE.md: {section_header!r}"
    )
    section_body = arch_text[start_match.start():]

    # Find the first fenced code block in this section
    fence_open = re.search(r"^```", section_body, re.MULTILINE)
    assert fence_open is not None, (
        f"No fenced code block found after section: {section_header!r}"
    )
    after_open = fence_open.end()
    fence_close = re.search(r"^```", section_body[after_open:], re.MULTILINE)
    assert fence_close is not None, (
        f"Unclosed fenced code block in section: {section_header!r}"
    )
    block_body = section_body[after_open: after_open + fence_close.start()]

    return {m.group(1).strip() for m in _TABLE_PHASE_RE.finditer(block_body)}


def _extract_skill_phases(skill_text: str) -> set[str]:
    """Extract phase names from all '### Phase: <name>' headings in a SKILL.md."""
    return {m.group(1).strip() for m in _SKILL_PHASE_RE.finditer(skill_text)}


def test_architecture_vision_table_phases_match_skill():
    """Every phase in ARCHITECTURE.md's /vision table exists in skills/vision/SKILL.md."""
    arch_text = _ARCH.read_text(encoding="utf-8")
    skill_text = _VISION_SKILL.read_text(encoding="utf-8")

    arch_phases = _extract_table_phases(arch_text, "### `/vision <text>`")
    skill_phases = _extract_skill_phases(skill_text)

    missing_from_skill = arch_phases - skill_phases
    assert missing_from_skill == set(), (
        "Phase(s) cited in ARCHITECTURE.md /vision table but missing from "
        f"skills/vision/SKILL.md: {sorted(missing_from_skill)}"
    )

    missing_from_arch = skill_phases - arch_phases
    assert missing_from_arch == set(), (
        "Phase(s) in skills/vision/SKILL.md not reflected in "
        f"ARCHITECTURE.md /vision table: {sorted(missing_from_arch)}"
    )


def test_architecture_implement_table_phases_match_skill():
    """Every phase in ARCHITECTURE.md's /implement table exists in skills/implement/SKILL.md."""
    arch_text = _ARCH.read_text(encoding="utf-8")
    skill_text = _IMPLEMENT_SKILL.read_text(encoding="utf-8")

    arch_phases = _extract_table_phases(arch_text, "### `/implement [check | auto] [<track>]`")
    skill_phases = _extract_skill_phases(skill_text)

    missing_from_skill = arch_phases - skill_phases
    assert missing_from_skill == set(), (
        "Phase(s) cited in ARCHITECTURE.md /implement table but missing from "
        f"skills/implement/SKILL.md: {sorted(missing_from_skill)}"
    )

    missing_from_arch = skill_phases - arch_phases
    assert missing_from_arch == set(), (
        "Phase(s) in skills/implement/SKILL.md not reflected in "
        f"ARCHITECTURE.md /implement table: {sorted(missing_from_arch)}"
    )
