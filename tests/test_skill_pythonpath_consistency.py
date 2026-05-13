"""
test_skill_pythonpath_consistency.py — CLI wrapper discipline guard.

Since v0.8.0 all skill code-block invocations must use the `spectre` shell
wrapper (e.g. `spectre walker init-or-resume ...`). No skill may contain:
  - `python3 -m bin.` — old module-path invocations
  - `PYTHONPATH=` — the wrapper now manages PYTHONPATH internally

Only lines inside fenced code blocks (``` or ```bash) are checked — prose
descriptions that mention these patterns as documentation text are intentionally
excluded.

This catches future edits that reintroduce the old PYTHONPATH-prefix pattern,
which would make skills harder to maintain and inconsistent with the wrapper
contract.
"""

import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent
_VISION_SKILL = _REPO / "skills" / "vision" / "SKILL.md"
_IMPLEMENT_SKILL = _REPO / "skills" / "implement" / "SKILL.md"

# Patterns banned inside code blocks
_BIN_MODULE_RE = re.compile(r"python3 -m bin\.")
_PYTHONPATH_EXPORT_RE = re.compile(r'PYTHONPATH="\$\{CLAUDE_PLUGIN_ROOT\}"')

# Matches a fenced code block opening
_CODE_FENCE_OPEN_RE = re.compile(r"^```")


def _extract_code_block_line_numbers(lines: list[str]) -> set[int]:
    """Return the set of 0-based line indices that are inside fenced code blocks."""
    inside = False
    code_lines: set[int] = set()
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if _CODE_FENCE_OPEN_RE.match(stripped):
            inside = not inside
            continue  # fence markers themselves are not "inside"
        if inside:
            code_lines.add(i)
    return code_lines


def _check_no_direct_bin_invocations(skill_path: pathlib.Path) -> list[str]:
    """Return a list of violation descriptions (empty = all good).

    Only inspects lines inside fenced code blocks — prose mentions are excluded.
    """
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    code_line_indices = _extract_code_block_line_numbers(lines)
    violations: list[str] = []

    for i, line in enumerate(lines):
        if i not in code_line_indices:
            continue

        if _BIN_MODULE_RE.search(line):
            violations.append(
                f"{skill_path.relative_to(_REPO)}:{i + 1}: "
                f"direct `python3 -m bin.` invocation found — use `spectre X` wrapper instead: "
                f"{line.strip()!r}"
            )
        elif _PYTHONPATH_EXPORT_RE.search(line):
            violations.append(
                f"{skill_path.relative_to(_REPO)}:{i + 1}: "
                f"explicit PYTHONPATH= prefix found — use `spectre X` wrapper instead: "
                f"{line.strip()!r}"
            )

    return violations


def test_vision_skill_uses_spectre_wrapper():
    """vision/SKILL.md must not contain python3 -m bin. or PYTHONPATH= in code blocks."""
    violations = _check_no_direct_bin_invocations(_VISION_SKILL)
    assert violations == [], (
        "vision/SKILL.md has direct bin-module invocations — use `spectre X` wrapper:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_implement_skill_uses_spectre_wrapper():
    """implement/SKILL.md must not contain python3 -m bin. or PYTHONPATH= in code blocks."""
    violations = _check_no_direct_bin_invocations(_IMPLEMENT_SKILL)
    assert violations == [], (
        "implement/SKILL.md has direct bin-module invocations — use `spectre X` wrapper:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_all_skills_use_spectre_wrapper():
    """Global guard — any SKILL.md under skills/ with a direct bin-module call fails CI."""
    skills_dir = _REPO / "skills"
    all_violations: list[str] = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        all_violations.extend(_check_no_direct_bin_invocations(skill_md))
    assert all_violations == [], (
        "direct bin-module invocations found in skills (use `spectre X` wrapper):\n"
        + "\n".join(f"  {v}" for v in all_violations)
    )
