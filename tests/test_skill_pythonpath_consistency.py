"""
test_skill_pythonpath_consistency.py — issue #30 regression guard.

Every `python3 -m bin.X` invocation inside a bash/shell code block in skill
prose must be preceded by `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"` on the same
line (or on the prior line if the prior line ends with a backslash
continuation).

Only lines inside fenced code blocks (``` or ```bash) are checked — prose
descriptions that mention `python3 -m bin.X` as documentation text are
intentionally excluded.

This catches future edits that strip the PYTHONPATH prefix from skill
commands, which would silently break execution when the runner's cwd is the
user's project directory (not the plugin install root).
"""

import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent
_VISION_SKILL = _REPO / "skills" / "vision" / "SKILL.md"
_IMPLEMENT_SKILL = _REPO / "skills" / "implement" / "SKILL.md"

# Matches any line that invokes `python3 -m bin.`
_BIN_INVOKE_RE = re.compile(r"python3 -m bin\.")

# Matches a line that has the required PYTHONPATH prefix AND the bin module invocation
_PREFIXED_INLINE_RE = re.compile(r'PYTHONPATH="\$\{CLAUDE_PLUGIN_ROOT\}".*python3 -m bin\.')

# Matches a fenced code block opening (``` or ```bash, ```sh, etc.)
_CODE_FENCE_OPEN_RE = re.compile(r"^```")

# Matches a continuation line (prior line ends with backslash)
_CONTINUATION_SUFFIX_RE = re.compile(r"\\\s*$")


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


def _check_pythonpath_consistency(skill_path: pathlib.Path) -> list[str]:
    """Return a list of violation descriptions (empty = all good).

    Only inspects lines inside fenced code blocks — prose mentions of
    `python3 -m bin.X` are not executable invocations and are skipped.
    """
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    code_line_indices = _extract_code_block_line_numbers(lines)
    violations: list[str] = []

    for i, line in enumerate(lines):
        # Only check lines that are inside a code block.
        if i not in code_line_indices:
            continue

        if not _BIN_INVOKE_RE.search(line):
            continue

        # Case 1: PYTHONPATH prefix is on the same line — OK.
        if _PREFIXED_INLINE_RE.search(line):
            continue

        # Case 2: The invocation is a pipe target (line starts with `|`) and
        # PYTHONPATH appears on the same line — OK.
        stripped = line.lstrip()
        if stripped.startswith("|") and _PREFIXED_INLINE_RE.search(line):
            continue

        # Case 3: Inside a multi-line command (prior line ends with `\`).
        # Walk backwards up the continuation chain to find the head line.
        head_idx = i
        while head_idx > 0 and _CONTINUATION_SUFFIX_RE.search(lines[head_idx - 1]):
            head_idx -= 1

        if head_idx != i:
            # We are inside a multi-line command. Check the head line for the prefix.
            head_line = lines[head_idx]
            if _PREFIXED_INLINE_RE.search(head_line):
                continue

        violations.append(
            f"{skill_path.relative_to(_REPO)}:{i + 1}: "
            f"`python3 -m bin.` invocation missing "
            f'`PYTHONPATH="${{CLAUDE_PLUGIN_ROOT}}"` prefix — {line.strip()!r}'
        )

    return violations


def test_vision_skill_pythonpath_consistency():
    """All `python3 -m bin.X` lines in vision/SKILL.md must carry the PYTHONPATH prefix."""
    violations = _check_pythonpath_consistency(_VISION_SKILL)
    assert violations == [], (
        "vision/SKILL.md has bin-module invocations without PYTHONPATH prefix (issue #30):\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_implement_skill_pythonpath_consistency():
    """All `python3 -m bin.X` lines in implement/SKILL.md must carry the PYTHONPATH prefix."""
    violations = _check_pythonpath_consistency(_IMPLEMENT_SKILL)
    assert violations == [], (
        "implement/SKILL.md has bin-module invocations without PYTHONPATH prefix (issue #30):\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_all_skills_pythonpath_consistency():
    """Global guard — any SKILL.md under skills/ with an unguarded bin-module call fails CI."""
    skills_dir = _REPO / "skills"
    all_violations: list[str] = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        all_violations.extend(_check_pythonpath_consistency(skill_md))
    assert all_violations == [], (
        "bin-module invocations without PYTHONPATH prefix found in skills "
        "(issue #30 regression):\n" + "\n".join(f"  {v}" for v in all_violations)
    )
