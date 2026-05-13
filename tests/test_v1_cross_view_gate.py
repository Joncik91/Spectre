"""tests/test_v1_cross_view_gate.py — regression guard for v1.0 Tier-2 cross-view checks.

Covers the critical-severity issues surfaced by Opus adversarial review of PR #65:

  1. gui-only / stdout contradiction finding's message must respect the
     140-char limit enforced by findings.Finding.__post_init__.
  2. Cross-view reference typos like §8.20 (intended §8.2) must emit a
     finding, not silently pass through.
  3. Spec-version detection must agree across spec_ast / cross_view_gate /
     llm_judge — all three short-circuit on non-1.0 specs together.
"""
from __future__ import annotations

import pathlib

import pytest

from bin import cross_view_gate
from bin import spec_ast


_V1_FRONTMATTER = (
    "# X\n\n"
    "**Generated:** 2026-05-13\n"
    "**Slug:** x\n"
    "**Spec-version:** 1.0\n\n"
)


def _write_spec(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    p = tmp_path / "x.spec.md"
    p.write_text(body, encoding="utf-8")
    return p


# ── Critical #1: gui-only contradiction must not crash on message length ─────

def test_gui_only_contradiction_emits_finding_without_crash(tmp_path):
    spec = _V1_FRONTMATTER + (
        "## 8. Receiver Calibration\n\n"
        "### 8.1 Hard contract\n"
        "- mutates: stdout\n"
        "- never-touches: /etc\n"
        "- decision-budget: none\n"
        "- reboot-survival: none\n\n"
        "### 8.5 Human-user substrate\n"
        "- receiver-fingerprint: gui-only\n"
    )
    findings = cross_view_gate.classify(_write_spec(tmp_path, spec))
    kinds = [f.kind for f in findings]
    assert "view-fingerprint-contradicts-hard-contract" in kinds


# ── Critical #2: cross-view ref typo must emit a finding ─────────────────────

def test_typo_section_number_emits_unresolved_finding(tmp_path):
    """Operator types §8.20 instead of §8.2; gate must surface this."""
    spec = _V1_FRONTMATTER + (
        "## 8. Receiver Calibration\n\n"
        "### 8.2 Cognitive-substrate contract\n"
        "- receiver-fingerprint: claude-code+human\n\n"
        "## 11. Human-User View\n\n"
        "### Mechanical contracts\n"
        "- on-failure: <halt-hint from §8.20 ux-contract>\n"
    )
    findings = cross_view_gate.classify(_write_spec(tmp_path, spec))
    kinds = [f.kind for f in findings]
    assert "cross-view-string-unresolved" in kinds


def test_valid_cross_view_ref_emits_no_finding(tmp_path):
    spec = _V1_FRONTMATTER + (
        "## 8. Receiver Calibration\n\n"
        "### 8.2 Cognitive-substrate contract\n"
        "- receiver-fingerprint: claude-code+human\n"
        "- ux-contract:\n"
        "    halt-hint: something\n\n"
        "## 11. Human-User View\n\n"
        "### Mechanical contracts\n"
        "- on-failure: <halt-hint from §8.2 ux-contract>\n"
    )
    findings = cross_view_gate.classify(_write_spec(tmp_path, spec))
    kinds = [f.kind for f in findings]
    assert "cross-view-string-unresolved" not in kinds


# ── Critical #3: spec-version detection agrees across modules ────────────────

@pytest.mark.parametrize("value,expected", [
    ("1.0", True),
    ("1.0.1", False),
    ("1.01", False),
    ("latest", False),
    ("0.9", False),
    ("  1.0  ", True),   # whitespace stripped
])
def test_is_v1_spec_detection(value, expected):
    body = f"**Spec-version:** {value}\n"
    assert spec_ast.is_v1_spec(body) is expected


def test_is_v1_spec_absent_returns_false():
    """Pre-v1.0 specs (no frontmatter) are not v1.0."""
    assert spec_ast.is_v1_spec("# Spec\n\n## 1. Hard Problem\n") is False


def test_cross_view_gate_skips_non_v1_specs(tmp_path):
    """A spec declaring 1.0.1 is not v1.0; cross-view checks must skip."""
    spec = (
        "# X\n\n"
        "**Spec-version:** 1.0.1\n\n"
        "## 11. Human-User View\n\n"
        "### Mechanical contracts\n"
        "- ref: <bogus from §8.2>\n"
    )
    findings = cross_view_gate.classify(_write_spec(tmp_path, spec))
    assert findings == []
