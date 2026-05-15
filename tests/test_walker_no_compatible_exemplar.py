"""tests/test_walker_no_compatible_exemplar.py — v1.1 Fix 2: no-compatible-exemplar
handling in the walker concern generators and cross-view gate.

Tests 1-2: walker._exemplar_options_for filtering behavior.
Tests 3-4: cross_view_gate sentinel recognition and aggregation.
"""
from __future__ import annotations

import pathlib

import pytest

from bin import _catalog
from bin import walker
from bin import cross_view_gate


# ---------------------------------------------------------------------------
# Shared spec builder (mirrors test_cross_view_fingerprint_exemplar.py style)
# ---------------------------------------------------------------------------

_V1_FRONTMATTER = (
    "# X\n\n"
    "**Generated:** 2026-05-14\n"
    "**Slug:** x\n"
    "**Spec-version:** 1.0\n\n"
)

_SUBSTRATE_BASE = (
    "## 8. Receiver Calibration\n\n"
    "### 8.1 Hard contract\n"
    "- mutates: /tmp/output\n"
    "- never-touches: /etc\n"
    "- decision-budget: none\n"
    "- reboot-survival: none\n\n"
)


def _write_spec(tmp_path: pathlib.Path, extra_substrate: str, view_sections: str) -> pathlib.Path:
    body = _V1_FRONTMATTER + _SUBSTRATE_BASE + extra_substrate + view_sections
    p = tmp_path / "x.spec.md"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Helper: write a synthetic exemplar with a specific calibrated-for list
# ---------------------------------------------------------------------------

def _write_synthetic_exemplar(
    root: pathlib.Path,
    view_type: str,
    slug: str,
    calibrated_for_yaml: str,
) -> None:
    """Write a minimal exemplar under <root>/docs/exemplars/<view_type>/<slug>.md."""
    view_dir = root / "docs" / "exemplars" / view_type
    view_dir.mkdir(parents=True, exist_ok=True)
    # Copy real axes.yml so taxonomy validation passes.
    real_axes = (
        pathlib.Path(__file__).resolve().parent.parent
        / "docs" / "exemplars" / view_type / "axes.yml"
    )
    axes_dst = view_dir / "axes.yml"
    if not axes_dst.exists():
        axes_dst.write_bytes(real_axes.read_bytes())
    (view_dir / f"{slug}.md").write_text(
        "---\n"
        f"view-types: [{view_type}]\n"
        "conventions: [A test convention]\n"
        "axes: {verbosity: terse, structure: flat, example-density: none}\n"
        f"{calibrated_for_yaml}\n"
        "taxonomy-version: 1\n"
        "source-url: https://example.com\n"
        "last-reviewed: 2026-05-14\n"
        "---\n\nSynthetic exemplar body.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Test 1: walker filters exemplars by fingerprint — matching ones only
# ---------------------------------------------------------------------------

def test_walker_filters_by_fingerprint(tmp_path, monkeypatch):
    """View with fingerprint cli-power-user + catalog with both cli and gui
    exemplars → only the cli-compatible slugs appear in prefab_options."""
    plugin_root = tmp_path / "plugin"
    _write_synthetic_exemplar(plugin_root, "help-text", "cli-tool",
                              "calibrated-for: [cli-power-user, cli-novice]")
    _write_synthetic_exemplar(plugin_root, "help-text", "gui-app",
                              "calibrated-for: [gui-only]")

    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    try:
        options, has_mismatch = walker._exemplar_options_for("cli-power-user", "help-text")
        assert has_mismatch is False
        assert "cli-tool" in options
        assert "gui-app" not in options
    finally:
        monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)


# ---------------------------------------------------------------------------
# Test 2: zero compatible exemplars → annotated list + post-ship-iteration
# ---------------------------------------------------------------------------

def test_zero_match_offers_post_ship_iteration(tmp_path, monkeypatch):
    """View with fingerprint gui-only + catalog with only cli exemplars →
    prefab_options contains 'post-ship-iteration' and each cli slug annotated
    '[fingerprint-mismatch]', with has_mismatch=True."""
    plugin_root = tmp_path / "plugin"
    _write_synthetic_exemplar(plugin_root, "help-text", "cli-tool",
                              "calibrated-for: [cli-power-user, cli-novice]")

    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    try:
        options, has_mismatch = walker._exemplar_options_for("gui-only", "help-text")
        assert has_mismatch is True
        assert "post-ship-iteration" in options
        assert any("[fingerprint-mismatch]" in opt for opt in options)
        # The cli-tool slug must appear (annotated)
        assert any("cli-tool" in opt for opt in options)
    finally:
        monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)


# ---------------------------------------------------------------------------
# Test 3: single post-ship-iteration sentinel → exactly one info finding
# ---------------------------------------------------------------------------

def test_single_deferral_emits_info(tmp_path, monkeypatch):
    """Spec with one view bound to post-ship-iteration → exactly one
    post-ship-iteration-deferral finding at info severity, tier 2."""
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)

    spec = _write_spec(
        tmp_path,
        extra_substrate=(
            "### 8.5 Human-user substrate\n"
            "- receiver-fingerprint: gui-only\n\n"
        ),
        view_sections=(
            "## 11. Human-User View\n\n"
            "### Exemplar bindings\n"
            "- help-text-style: post-ship-iteration\n"
            "- taxonomy-version: help-text:1\n"
        ),
    )
    findings = cross_view_gate.classify(spec)
    deferral = [f for f in findings if f.kind == "post-ship-iteration-deferral"]
    assert len(deferral) == 1
    assert deferral[0].severity == "info"
    assert deferral[0].tier == 2


# ---------------------------------------------------------------------------
# Test 4: two post-ship-iteration deferrals → both info + one excessive warn
# ---------------------------------------------------------------------------

def test_two_deferrals_emits_excessive_warn(tmp_path, monkeypatch):
    """Spec with two views bound to post-ship-iteration → two info findings
    PLUS one excessive-post-ship-iteration warn finding.

    v1.2.1 #5: fingerprints chosen so the catalog has compatible exemplars,
    making both deferrals operator-chosen (not catalog-forced). The aggregate
    warn only fires for operator-chosen deferrals.
    """
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)

    spec = _write_spec(
        tmp_path,
        extra_substrate=(
            "### 8.5 Human-user substrate\n"
            "- receiver-fingerprint: cli-power-user\n\n"
            "### 8.7 Operator substrate\n"
            "- receiver-fingerprint: on-call-engineer\n\n"
        ),
        view_sections=(
            "## 11. Human-User View\n\n"
            "### Exemplar bindings\n"
            "- help-text-style: post-ship-iteration\n"
            "- taxonomy-version: help-text:1\n\n"
            "## 13. Operator View\n\n"
            "### Exemplar bindings\n"
            "- log-format-style: post-ship-iteration\n"
            "- taxonomy-version: log-format:1\n"
        ),
    )
    findings = cross_view_gate.classify(spec)
    deferral = [f for f in findings if f.kind == "post-ship-iteration-deferral"]
    excessive = [f for f in findings if f.kind == "excessive-post-ship-iteration"]
    assert len(deferral) == 2
    assert all(f.severity == "info" for f in deferral), "deferral findings must be info severity"
    assert all(f.tier == 2 for f in deferral), "deferral findings must be Tier 2"
    assert len(excessive) == 1
    assert excessive[0].severity == "warn"
    assert excessive[0].tier == 2


# ---------------------------------------------------------------------------
# Test 5: prefixed sentinel form (exemplar:post-ship-iteration) — the bug fix
# ---------------------------------------------------------------------------

def test_prefixed_sentinel_emits_deferral_not_exemplar_not_found(tmp_path, monkeypatch):
    """Spec where the operator writes `exemplar:post-ship-iteration` (with the
    `exemplar:` prefix) instead of the bare sentinel form must emit
    post-ship-iteration-deferral (info), NOT exemplar-not-found (block).

    This is the v1.2 Fix O root cause: the prefixed form was mis-firing as a
    missing-catalog error because _check_exemplar_bindings didn't guard against
    the `post-ship-iteration` raw_ref before the catalog lookup.
    """
    monkeypatch.setattr(_catalog, "_LOAD_CACHE", None)

    # v1.2.1 #5: fingerprints chosen so compatible exemplars EXIST in the
    # catalog (cli-power-user for help-text; on-call-engineer for log-format).
    # The deferral is therefore an operator choice, not catalog-forced —
    # `excessive-post-ship-iteration` aggregate warn fires as designed.
    spec = _write_spec(
        tmp_path,
        extra_substrate=(
            "### 8.5 Human-user substrate\n"
            "- receiver-fingerprint: cli-power-user\n\n"
            "### 8.7 Operator substrate\n"
            "- receiver-fingerprint: on-call-engineer\n\n"
        ),
        view_sections=(
            "## 11. Human-User View\n\n"
            "### Exemplar bindings\n"
            "- help-text-style: exemplar:post-ship-iteration\n"
            "- taxonomy-version: help-text:1\n\n"
            "## 13. Operator View\n\n"
            "### Exemplar bindings\n"
            "- log-format-style: exemplar:post-ship-iteration\n"
            "- taxonomy-version: log-format:1\n"
        ),
    )
    findings = cross_view_gate.classify(spec)
    deferral = [f for f in findings if f.kind == "post-ship-iteration-deferral"]
    not_found = [f for f in findings if f.kind == "exemplar-not-found"]
    excessive = [f for f in findings if f.kind == "excessive-post-ship-iteration"]
    assert len(not_found) == 0, f"prefixed sentinel must NOT emit exemplar-not-found, got: {not_found}"
    assert len(deferral) == 2, f"expected 2 deferral findings, got {len(deferral)}"
    assert all(f.severity == "info" for f in deferral)
    assert all(f.tier == 2 for f in deferral)
    assert all(f.reason == "operator-deferral" for f in deferral), \
        "compatible-exemplar deferrals must be tagged operator-deferral"
    assert len(excessive) == 1, "two operator-chosen deferrals must trigger excessive warn"
    assert excessive[0].severity == "warn"
