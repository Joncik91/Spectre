"""tests/test_cross_view_fingerprint_exemplar.py — v1.1 Fix 1: exemplar
calibrated-for vs view receiver-fingerprint cross-check.

Four test cases:
  1. mismatch → view-fingerprint-contradicts-exemplar-binding at warn
  2. match    → no such finding
  3. empty calibrated-for → any-match, no finding
  4. unknown fingerprint in calibrated-for → CatalogError at load time
"""
from __future__ import annotations

import pathlib

import pytest

from bin import _catalog
from bin import cross_view_gate
from bin._catalog import CatalogError


# ---------------------------------------------------------------------------
# Shared spec builder
# ---------------------------------------------------------------------------

_V1_FRONTMATTER = (
    "# X\n\n"
    "**Generated:** 2026-05-14\n"
    "**Slug:** x\n"
    "**Spec-version:** 1.0\n\n"
)

# Minimal §8 block.  §8.5 fingerprint is parameterised by caller.
_SUBSTRATE_TMPL = (
    "## 8. Receiver Calibration\n\n"
    "### 8.1 Hard contract\n"
    "- mutates: /tmp/output\n"
    "- never-touches: /etc\n"
    "- decision-budget: none\n"
    "- reboot-survival: none\n\n"
    "### 8.5 Human-user substrate\n"
    "- receiver-fingerprint: {fingerprint}\n\n"
)

# §11 Human-User View binding to help-text:gh (calibrated-for: cli-power-user).
_HUMAN_USER_VIEW_WITH_GH = (
    "## 11. Human-User View\n\n"
    "- help-text-style: exemplar:help-text:gh\n"
    "- taxonomy-version: help-text:1\n"
)


def _write_spec(tmp_path: pathlib.Path, fingerprint: str) -> pathlib.Path:
    body = (
        _V1_FRONTMATTER
        + _SUBSTRATE_TMPL.format(fingerprint=fingerprint)
        + _HUMAN_USER_VIEW_WITH_GH
    )
    p = tmp_path / "x.spec.md"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Test 1: fingerprint mismatch → warn finding
# ---------------------------------------------------------------------------

def test_mismatch_emits_warn(tmp_path, monkeypatch):
    """§8.5 gui-only + §11 bound to help-text:gh (cli-only) → exactly one
    view-fingerprint-contradicts-exemplar-binding finding at warn severity."""
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    findings = cross_view_gate.classify(_write_spec(tmp_path, "gui-only"))
    fp_findings = [
        f for f in findings
        if f.kind == "view-fingerprint-contradicts-exemplar-binding"
    ]
    assert len(fp_findings) == 1
    assert fp_findings[0].severity == "warn"


# ---------------------------------------------------------------------------
# Test 2: fingerprint matches → no finding
# ---------------------------------------------------------------------------

def test_match_emits_no_finding(tmp_path, monkeypatch):
    """§8.5 cli-power-user + §11 bound to help-text:gh (cli-power-user) →
    zero view-fingerprint-contradicts-exemplar-binding findings."""
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    findings = cross_view_gate.classify(_write_spec(tmp_path, "cli-power-user"))
    fp_findings = [
        f for f in findings
        if f.kind == "view-fingerprint-contradicts-exemplar-binding"
    ]
    assert len(fp_findings) == 0


# ---------------------------------------------------------------------------
# Test 3: empty calibrated_for → any-match, no finding
# ---------------------------------------------------------------------------

def _write_synthetic_exemplar(root: pathlib.Path, calibrated_for_yaml: str) -> None:
    """Write a minimal help-text exemplar with the given calibrated-for YAML."""
    view_dir = root / "docs" / "exemplars" / "help-text"
    view_dir.mkdir(parents=True)
    # Copy axes.yml from the real plugin root so taxonomy validation passes.
    import os
    real_axes = (
        pathlib.Path(__file__).resolve().parent.parent
        / "docs" / "exemplars" / "help-text" / "axes.yml"
    )
    (view_dir / "axes.yml").write_bytes(real_axes.read_bytes())
    (view_dir / "test-tool.md").write_text(
        "---\n"
        "view-types: [help-text]\n"
        "conventions: [A test convention]\n"
        "axes: {verbosity: terse, structure: flat, example-density: none}\n"
        f"{calibrated_for_yaml}\n"
        "taxonomy-version: 1\n"
        "source-url: https://example.com\n"
        "last-reviewed: 2026-05-14\n"
        "---\n\nSynthetic exemplar body.\n",
        encoding="utf-8",
    )


def _write_spec_with_test_tool(tmp_path: pathlib.Path, fingerprint: str) -> pathlib.Path:
    body = (
        _V1_FRONTMATTER
        + _SUBSTRATE_TMPL.format(fingerprint=fingerprint)
        + (
            "## 11. Human-User View\n\n"
            "- help-text-style: exemplar:help-text:test-tool\n"
            "- taxonomy-version: help-text:1\n"
        )
    )
    p = tmp_path / "x.spec.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_empty_calibrated_for_matches_any(tmp_path, monkeypatch):
    """An exemplar with calibrated-for: [] (omitted) matches any fingerprint —
    no finding should be emitted even with a fingerprint that would otherwise
    mismatch a non-empty calibrated_for list."""
    plugin_root = tmp_path / "plugin"
    _write_synthetic_exemplar(plugin_root, "")  # no calibrated-for field at all

    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    try:
        spec_path = _write_spec_with_test_tool(tmp_path, "gui-only")
        findings = cross_view_gate.classify(spec_path)
        fp_findings = [
            f for f in findings
            if f.kind == "view-fingerprint-contradicts-exemplar-binding"
        ]
        assert len(fp_findings) == 0
    finally:
        monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)


# ---------------------------------------------------------------------------
# Test 4: unknown fingerprint → CatalogError at load
# ---------------------------------------------------------------------------

def test_catalog_load_rejects_unknown_fingerprint(tmp_path):
    """calibrated-for: [not-a-real-fingerprint] must raise CatalogError with
    the bad value in the message when the exemplar file is parsed."""
    bad_exemplar = tmp_path / "bad.md"
    bad_exemplar.write_text(
        "---\n"
        "view-types: [help-text]\n"
        "conventions: [A test convention]\n"
        "axes: {verbosity: terse, structure: flat, example-density: none}\n"
        "calibrated-for: [not-a-real-fingerprint]\n"
        "taxonomy-version: 1\n"
        "source-url: https://example.com\n"
        "last-reviewed: 2026-05-14\n"
        "---\n\nSynthetic exemplar body.\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="not-a-real-fingerprint"):
        _catalog._parse_exemplar_file(bad_exemplar, "plugin")


# ---------------------------------------------------------------------------
# Test 5 & 6: v1.2 regression — help-text:gh now cli-power-user only
# ---------------------------------------------------------------------------

def test_gh_help_text_fires_finding_for_novice_fingerprint(tmp_path, monkeypatch):
    """§8.5 cli-novice + §11 bound to help-text:gh →
    view-fingerprint-contradicts-exemplar-binding fires (gh is power-user only
    after the v1.2 calibrated-for audit)."""
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    findings = cross_view_gate.classify(_write_spec(tmp_path, "cli-novice"))
    fp_findings = [
        f for f in findings
        if f.kind == "view-fingerprint-contradicts-exemplar-binding"
    ]
    assert len(fp_findings) == 1, (
        "expected exactly one view-fingerprint-contradicts-exemplar-binding "
        f"finding; got {len(fp_findings)}"
    )
    assert fp_findings[0].severity == "warn"


def test_gh_help_text_does_not_fire_for_power_user_fingerprint(tmp_path, monkeypatch):
    """§8.5 cli-power-user + §11 bound to help-text:gh →
    no view-fingerprint-contradicts-exemplar-binding (gh IS calibrated for
    power users; this is the happy path that must stay green)."""
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    findings = cross_view_gate.classify(_write_spec(tmp_path, "cli-power-user"))
    fp_findings = [
        f for f in findings
        if f.kind == "view-fingerprint-contradicts-exemplar-binding"
    ]
    assert len(fp_findings) == 0
