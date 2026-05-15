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


# ── Issue #8: budget instrumentation emits via _status channel ───────────────

def test_budget_emission_via_status_channel(tmp_path, capsys, monkeypatch):
    """Verify the INFO tier3.budget line uses key=value format via _status.emit."""
    from bin import llm_judge
    # Stub _run_contradiction_prompt to return empty findings + bypass network
    monkeypatch.setattr(llm_judge, "_run_contradiction_prompt", lambda *a, **kw: [])

    class _Cfg:
        enabled = True
        budget_tokens_per_spec = 1_000_000

    spec_text = "**Spec-version:** 1.0\n\n## 1. Hard Problem\nx\n"
    llm_judge.evaluate(spec_text, config=_Cfg())
    captured = capsys.readouterr()
    all_output = captured.out + captured.err
    budget_lines = [
        line for line in all_output.splitlines() if line.startswith("INFO tier3.budget")
    ]
    assert len(budget_lines) == 1
    line = budget_lines[0]
    assert "calls=1" in line
    assert "exemplars_injected=" in line
    assert "dismissals_by_fp=" in line


def test_budget_emission_suppressed_by_spectre_quiet(tmp_path, capsys, monkeypatch):
    """SPECTRE_QUIET=1 must suppress the INFO tier3.budget line."""
    from bin import llm_judge
    monkeypatch.setattr(llm_judge, "_run_contradiction_prompt", lambda *a, **kw: [])
    monkeypatch.setenv("SPECTRE_QUIET", "1")

    class _Cfg:
        enabled = True
        budget_tokens_per_spec = 1_000_000

    spec_text = "**Spec-version:** 1.0\n\n## 1. Hard Problem\nx\n"
    llm_judge.evaluate(spec_text, config=_Cfg())
    captured = capsys.readouterr()
    all_output = captured.out + captured.err
    budget_lines = [
        line for line in all_output.splitlines() if line.startswith("INFO tier3.budget")
    ]
    assert len(budget_lines) == 0


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
    The finding's suggested_fix must reference the correct view."""
    result = substrate_wizard._validate_view_trust_profile("human-user", "untrusted-input")
    profile, findings = result
    assert "untrusted-input" not in profile
    assert len(findings) == 1
    fix = findings[0].suggested_fix or ""
    assert "implementing-agent" in fix


def test_trust_token_genuine_typo_omits_hint():
    """Unknown token that doesn't exist in any view → block finding with valid-tokens fix."""
    result = substrate_wizard._validate_view_trust_profile("human-user", "bogus-token")
    profile, findings = result
    assert "bogus-token" not in profile
    assert len(findings) == 1
    # No other-view hint; fix should list valid tokens for this view
    fix = findings[0].suggested_fix or ""
    assert "implementing-agent" not in fix


# ── Issue #11: user-overlay shadowing surfaced via validate_catalog ──────────

def test_user_overlay_shadowing_surfaced(monkeypatch, tmp_path):
    """A user-overlay exemplar at the same key as a plugin entry must be
    listed in validate_catalog() output."""
    from bin import _catalog
    # Create a fake user-overlay matching an existing plugin entry
    user_root = tmp_path / "user_exemplars"
    user_dir = user_root / "help-text"
    user_dir.mkdir(parents=True)
    user_entry = user_dir / "curl.md"
    user_entry.write_text(
        "---\n"
        "view-types: [help-text]\n"
        "conventions: [overrides plugin curl]\n"
        "axes: {verbosity: terse, structure: flat, example-density: none}\n"
        "taxonomy-version: 1\n"
        "source-url: https://example.com\n"
        "last-reviewed: 2026-05-13\n"
        "---\n\nlocal overlay body\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_catalog, "_user_overlay_root", lambda: user_root)
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)

    errors = _catalog.validate_catalog()
    shadow_msgs = [e for e in errors if "shadowed:" in e]
    assert len(shadow_msgs) == 1
    assert "help-text:curl" in shadow_msgs[0]
    # Reset cache so other tests aren't affected
    _catalog._LOAD_CACHE = None


# ── Issue #12: lookup_status distinguishes not-found vs ambiguous ────────────

def test_lookup_status_found_qualified():
    from bin import _catalog
    status, matches = _catalog.lookup_status("help-text:gh")
    assert status == "found"
    assert len(matches) == 1


def test_lookup_status_found_unambiguous_bare():
    from bin import _catalog
    status, matches = _catalog.lookup_status("curl")   # only help-text:curl exists
    assert status == "found"


def test_lookup_status_ambiguous_bare_slug():
    """`gh` exists under both help-text and error-text → ambiguous."""
    from bin import _catalog
    status, matches = _catalog.lookup_status("gh")
    assert status == "ambiguous"
    assert len(matches) == 2


def test_lookup_status_not_found():
    from bin import _catalog
    status, matches = _catalog.lookup_status("nonexistent-slug-xyz")
    assert status == "not-found"
    assert matches == []
