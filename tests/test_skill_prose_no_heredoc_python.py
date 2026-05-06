"""
test_skill_prose_no_heredoc_python.py — issue #13 Phase 2B + 2C + 2D drift guard.

Phase 2B replaced 3 high-leverage `python3 - <<'PY' ... PY` blocks in
`skills/vision/SKILL.md` (§6.4 evaluator, §6.6 resource node inference, §6.7
sidecar write) with Phase 2A CLI invocations + native harness tools.

Phase 2C replaced the remaining 2 high-leverage heredocs in
`skills/implement/SKILL.md` (§3.5 Persistence-Tier classifier, §5.5 State
Auditor) with new `bin.tier evaluate-action` and `bin.auditor audit-and-clear`
CLI invocations landed in the same PR.

Phase 2D replaced the remaining 18 medium-/low-leverage heredocs (7 in
`skills/vision/SKILL.md` and 11 in `skills/implement/SKILL.md`) with new CLI
entry points across `bin/_scratchpad.py`, `bin/adr.py`, `bin/cdlc_ledger.py`,
`bin/observations.py`, `bin/personal_rules.py`, `bin/setup_wizard.py`,
`bin/templates.py`, `bin/track.py`, plus a `yield-check` subcommand on the
existing `bin/walker.py` __main__.

Issue #13 is now fully closed; Phase 2D tightens both per-file ceilings to
zero AND adds a global cross-file `test_no_python3_heredoc_anywhere_in_skills`
guard so any future heredoc-Python in `skills/**/SKILL.md` breaks CI.
"""
import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent
_VISION_SKILL = _REPO / "skills" / "vision" / "SKILL.md"
_IMPLEMENT_SKILL = _REPO / "skills" / "implement" / "SKILL.md"

_HEREDOC_RE = re.compile(r"python3\s*-\s*<<\s*'?PY'?")


def _heredoc_count(text: str) -> int:
    return len(_HEREDOC_RE.findall(text))


def _section_text(skill_text: str, header_re: str, next_header_re: str) -> str:
    """Return the body between a section header and the next header.

    Both args are full-line regexes (without anchors). Raises AssertionError if
    the section header is missing — that means the skill prose was restructured
    and this test needs intentional update.
    """
    start = re.search(header_re, skill_text, re.MULTILINE)
    assert start is not None, f"section not found in skill: {header_re!r}"
    body_start = start.end()
    nxt = re.search(next_header_re, skill_text[body_start:], re.MULTILINE)
    body_end = body_start + (nxt.start() if nxt else len(skill_text) - body_start)
    return skill_text[body_start:body_end]


# ── Phase 2B replacements: vision §6.4, §6.6, §6.7 ────────────────────────────


def test_vision_step_6_4_evaluator_has_no_python_heredoc():
    """§6.4 (Pre-lock spec evaluator) must invoke `bin.spec_evaluator` via CLI."""
    text = _VISION_SKILL.read_text()
    body = _section_text(
        text,
        r"^### Step 6\.4 — Pre-lock spec evaluator.*$",
        r"^### Step 6\.\d.*$",
    )
    assert _heredoc_count(body) == 0, (
        "§6.4 must use the Phase 2A `python3 -m bin.spec_evaluator evaluate` "
        "CLI — heredoc-python was removed in Phase 2B (issue #13)."
    )
    assert "python3 -m bin.spec_evaluator" in body, (
        "§6.4 must invoke `python3 -m bin.spec_evaluator` (Phase 2A surface)."
    )


def test_vision_step_6_6_resource_node_has_no_python_heredoc():
    """§6.6 (Resource node inference) must read the bundle natively, no heredoc."""
    text = _VISION_SKILL.read_text()
    body = _section_text(
        text,
        r"^### Step 6\.6 — Resource node inference.*$",
        r"^### Step 6\.\d.*$",
    )
    assert _heredoc_count(body) == 0, (
        "§6.6 must read state/.eval-bundle.json natively — heredoc-python was "
        "removed in Phase 2B (issue #13)."
    )
    assert "state/.eval-bundle.json" in body, (
        "§6.6 must reference state/.eval-bundle.json — that is where §6.4 "
        "persists preview_resources."
    )


def test_vision_step_6_7_sidecar_write_block_has_no_python_heredoc():
    """§6.7 step 4 (Write the .eval.json sidecar) must use the eval_metadata CLI.

    Scoped to the sidecar-write block specifically (between the `**Write the
    `<slug>.spec.md.eval.json` sidecar**` marker and the `**Clear the persisted
    bundle**` marker). Other heredocs further down §6.7 (e.g. CDLC ledger
    `generate` transition) are out of scope for Phase 2B and tracked as
    deferrals on the audit's medium-leverage list.
    """
    text = _VISION_SKILL.read_text()
    body = _section_text(
        text,
        r"^4\. \*\*Write the `<slug>\.spec\.md\.eval\.json` sidecar\*\*.*$",
        r"^5\. \*\*Clear the persisted bundle\*\*.*$",
    )
    assert _heredoc_count(body) == 0, (
        "§6.7 sidecar-write block must use `python3 -m bin.eval_metadata "
        "write-sidecar` — heredoc-python was removed in Phase 2B (issue #13)."
    )
    assert "python3 -m bin.eval_metadata write-sidecar" in body, (
        "§6.7 sidecar-write block must invoke the Phase 2A write-sidecar CLI."
    )


# ── Phase 2C replacements: implement §3.5, §5.5 ───────────────────────────────


def test_implement_step_3_5_tier_classifier_block_has_no_python_heredoc():
    """§3.5 classifier block (between the Step 3.5 header and the next prose
    sub-section `**Record observation`) must invoke `bin.tier` via CLI.

    Scoped to the classifier-specific block — other heredocs further down §3.5
    (audit occurrences #12 record-halt, #13 cdlc-halt, #14 persist-pending-
    adoption-prompt) are out of scope for Phase 2C and are tracked as
    deferrals on the audit's medium-leverage list (Phase 2D).
    """
    text = _IMPLEMENT_SKILL.read_text()
    body = _section_text(
        text,
        r"^### Step 3\.5 — Persistence-Tier classifier.*$",
        r"^\*\*Record observation BEFORE accepting input:\*\*.*$",
    )
    assert _heredoc_count(body) == 0, (
        "§3.5 classifier block must use the Phase 2C "
        "`python3 -m bin.tier evaluate-action` CLI — heredoc-python was "
        "removed in Phase 2C (issue #13)."
    )
    assert "python3 -m bin.tier evaluate-action" in body, (
        "§3.5 classifier block must invoke "
        "`python3 -m bin.tier evaluate-action` (Phase 2C surface)."
    )


def test_implement_step_5_5_state_auditor_has_no_python_heredoc():
    """§5.5 (State Auditor) must invoke `bin.auditor` via CLI."""
    text = _IMPLEMENT_SKILL.read_text()
    body = _section_text(
        text,
        r"^### Step 5\.5 — State Auditor.*$",
        r"^### Step 6 — Branch on verification result.*$",
    )
    assert _heredoc_count(body) == 0, (
        "§5.5 must use the Phase 2C `python3 -m bin.auditor audit-and-clear` "
        "CLI — heredoc-python was removed in Phase 2C (issue #13)."
    )
    assert "python3 -m bin.auditor audit-and-clear" in body, (
        "§5.5 must invoke `python3 -m bin.auditor audit-and-clear` (Phase 2C surface)."
    )


# ── Phase 2D count ceilings — zero heredocs anywhere in skills ────────────────


def test_vision_skill_has_zero_python_heredocs():
    """Phase 2D dropped vision/SKILL.md heredocs from 7 to 0. The ceiling is
    now zero — any new heredoc-Python introduces the path-construction /
    escape-layer bug class issue #13 was filed to eliminate."""
    text = _VISION_SKILL.read_text()
    count = _heredoc_count(text)
    assert count == 0, (
        f"vision/SKILL.md has {count} heredoc-python blocks; Phase 2D set the "
        "ceiling at zero. Replace with a `python3 -m bin.<module> <subcommand>` "
        "invocation against the corresponding CLI entry point."
    )


def test_implement_skill_has_zero_python_heredocs():
    """Phase 2D dropped implement/SKILL.md heredocs from 11 to 0. The ceiling
    is now zero — any new heredoc-Python regresses issue #13's closure."""
    text = _IMPLEMENT_SKILL.read_text()
    count = _heredoc_count(text)
    assert count == 0, (
        f"implement/SKILL.md has {count} heredoc-python blocks; Phase 2D set "
        "the ceiling at zero. Replace with a `python3 -m bin.<module> "
        "<subcommand>` invocation against the corresponding CLI entry point."
    )


def test_no_python3_heredoc_anywhere_in_skills():
    """Global guard — fail if ANY file under skills/**/SKILL.md contains a
    `python3 - <<...PY` heredoc, even outside the two known skill files.

    This is the load-bearing CI lock: once Phase 2D merges, no heredoc-Python
    can re-enter Spectre's skill prose surface without breaking the build.
    """
    skills_dir = _REPO / "skills"
    offenders: list[tuple[pathlib.Path, int]] = []
    for skill_md in skills_dir.rglob("SKILL.md"):
        text = skill_md.read_text(encoding="utf-8")
        n = _heredoc_count(text)
        if n > 0:
            offenders.append((skill_md, n))
    assert offenders == [], (
        "heredoc-python found in skills/**/SKILL.md (issue #13 closure violated): "
        + ", ".join(f"{p.relative_to(_REPO)}:{n}" for p, n in offenders)
    )
