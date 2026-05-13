"""tests/test_v1_review_followups.py — regression guards for the 6 important
issues raised by Opus adversarial review of PR #65.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from bin import spec_ast
from bin import substrate_wizard
from bin import walker


# ── Issue #6: walker recommended_stop includes the 5 v1.0 view-family flags ──

def test_recommended_stop_blocked_when_views_unanswered(tmp_path):
    """All v0.9 family flags set, but v1.0 view flags False → no stop."""
    draft = tmp_path / "x.spec.md.draft"
    draft.write_text("# x\n", encoding="utf-8")
    state = walker.WalkState(
        spec_intent="test",
        spec_draft_path=draft,
        lifecycle_asked=True,
        prompt_design_asked=True,
        semantic_criteria_asked=True,
    )
    coverage = walker._compute_coverage(state, "")
    # views all False → views_satisfied is False → recommended_stop must be False
    assert coverage["recommended_stop"] is False


def test_recommended_stop_allowed_when_all_views_answered(tmp_path):
    """All v0.9 + v1.0 view flags set, pending empty → stop allowed."""
    draft = tmp_path / "x.spec.md.draft"
    draft.write_text("# x\n", encoding="utf-8")
    state = walker.WalkState(
        spec_intent="test",
        spec_draft_path=draft,
        lifecycle_asked=True,
        prompt_design_asked=True,
        semantic_criteria_asked=True,
        product_input_asked=True,
        product_output_asked=True,
        human_user_asked=True,
        integrator_asked=True,
        operator_asked=True,
    )
    coverage = walker._compute_coverage(state, "")
    assert coverage["recommended_stop"] is True


# ── Issue #7: fenced-block stripping ─────────────────────────────────────────

def test_strip_fenced_blocks_removes_examples():
    body = "intro\n```markdown\n## fake heading\n- fake: example\n```\ntail\n"
    cleaned = spec_ast._strip_fenced_blocks(body)
    assert "fake heading" not in cleaned
    assert "intro" in cleaned and "tail" in cleaned


# ── Issue #8: budget instrumentation emits valid JSON ────────────────────────

def test_budget_emission_is_valid_json(tmp_path, capsys, monkeypatch):
    """Verify the INFO tier3.budget line parses as JSON via json.loads."""
    from bin import llm_judge
    # Stub _run_contradiction_prompt to return empty findings + bypass network
    monkeypatch.setattr(llm_judge, "_run_contradiction_prompt", lambda *a, **kw: [])

    class _Cfg:
        enabled = True
        budget_tokens_per_spec = 1_000_000

    spec_text = "**Spec-version:** 1.0\n\n## 1. Hard Problem\nx\n"
    llm_judge.evaluate(spec_text, config=_Cfg())
    captured = capsys.readouterr()
    budget_lines = [
        line for line in captured.err.splitlines() if line.startswith("INFO tier3.budget")
    ]
    assert len(budget_lines) == 1
    payload = json.loads(budget_lines[0].split(" ", 2)[2])
    assert payload["calls"] == 1
    assert "exemplars_injected" in payload
    assert "dismissals_by_fp" in payload


# ── Issue #9: corrupt state file UX ──────────────────────────────────────────

def test_corrupt_state_file_emits_recovery_hint(tmp_path):
    """Empty / partial JSON state must raise ValueError with recovery hint."""
    state_path = tmp_path / ".walk.json"
    state_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="state file corrupt"):
        walker.load(state_path)


def test_empty_state_file_emits_recovery_hint(tmp_path):
    state_path = tmp_path / ".walk.json"
    state_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="rm.*to restart"):
        walker.load(state_path)


# ── Issue #10: trust-token cross-view disambiguation ─────────────────────────

def test_trust_token_wrong_view_includes_disambiguation_hint():
    """`untrusted-input` is valid for implementing-agent, not human-user.
    The error message must say so explicitly."""
    with pytest.raises(substrate_wizard.WizardValidationError) as exc_info:
        substrate_wizard._validate_view_trust_profile("human-user", "untrusted-input")
    msg = str(exc_info.value)
    assert "implementing-agent" in msg
    assert "human-user" in msg


def test_trust_token_genuine_typo_omits_hint():
    """Unknown token that doesn't exist in any view → no misleading hint."""
    with pytest.raises(substrate_wizard.WizardValidationError) as exc_info:
        substrate_wizard._validate_view_trust_profile("human-user", "bogus-token")
    msg = str(exc_info.value)
    assert "Note:" not in msg
