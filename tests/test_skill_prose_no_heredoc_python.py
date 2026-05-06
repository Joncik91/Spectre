"""
test_skill_prose_no_heredoc_python.py — issue #13 Phase 2B + 2C drift guard.

Phase 2B replaced 3 high-leverage `python3 - <<'PY' ... PY` blocks in
`skills/vision/SKILL.md` (§6.4 evaluator, §6.6 resource node inference, §6.7
sidecar write) with Phase 2A CLI invocations + native harness tools.

Phase 2C replaced the remaining 2 high-leverage heredocs in
`skills/implement/SKILL.md` (§3.5 Persistence-Tier classifier, §5.5 State
Auditor) with new `bin.tier evaluate-action` and `bin.auditor audit-and-clear`
CLI invocations landed in the same PR.

These tests guard against the heredocs creeping back in, and against new
heredocs being added in those exact sections.  This file deliberately does NOT
assert global heredoc absence; that is the Phase 2D check once all 18
remaining heredocs are gone.
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


# ── Phase 2C count ceilings — guard against regression in skill files ─────────


def test_vision_skill_total_heredoc_count_at_or_below_phase_2c_ceiling():
    """After Phase 2C, vision/SKILL.md still has 7 remaining heredoc-python
    blocks (Phase 2C did not touch vision; it replaced the two implement-only
    targets deferred from Phase 2B).

    Phase 2D will reduce this further. This test asserts the count never rises
    above 7 — adding a new heredoc to vision/SKILL.md should be a deliberate,
    reviewed action, not an accident.
    """
    text = _VISION_SKILL.read_text()
    count = _heredoc_count(text)
    assert count <= 7, (
        f"vision/SKILL.md has {count} heredoc-python blocks; "
        "Phase 2B/2C set the ceiling at 7 (down from 10). "
        "Adding more should require an intentional update to this test."
    )


def test_implement_skill_total_heredoc_count_at_or_below_phase_2c_ceiling():
    """After Phase 2C, implement/SKILL.md has 11 remaining heredoc-python blocks
    (down from 13 before Phase 2C; §3.5 and §5.5 replaced).

    Phase 2D will reduce this further. This test asserts the count never rises
    above 11 — adding a new heredoc to implement/SKILL.md should be a
    deliberate, reviewed action, not an accident.
    """
    text = _IMPLEMENT_SKILL.read_text()
    count = _heredoc_count(text)
    assert count <= 11, (
        f"implement/SKILL.md has {count} heredoc-python blocks; "
        "Phase 2C set the ceiling at 11 (down from 13: §3.5 + §5.5 replaced). "
        "Adding more should require an intentional update to this test."
    )
