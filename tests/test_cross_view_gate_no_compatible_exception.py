"""`excessive-post-ship-iteration` exception for zero-exemplar views (v1.2.1 #5).

When a view's catalog has zero compatible exemplars, the operator is forced
to pick `post-ship-iteration` — penalizing that choice is wrong. The
deferral is tagged `reason="no-compatible-exemplar"` and the aggregate check
counts only `operator-deferral` deferrals.
"""
from bin import cross_view_gate, findings


def _deferral(section: str, reason: str) -> findings.Finding:
    return cross_view_gate._emit_deferral_finding(section, reason=reason)


def test_112_two_no_compatible_deferrals_do_not_trigger_aggregate_warn():
    # Both views forced into post-ship-iteration due to empty catalog —
    # operator had no choice; aggregate warn must NOT fire.
    f1 = _deferral("9", "no-compatible-exemplar")
    f2 = _deferral("10", "no-compatible-exemplar")
    warns = cross_view_gate._check_excessive_post_ship_iteration([f1, f2])
    assert warns == []


def test_113_two_operator_deferrals_trigger_aggregate_warn():
    # Both views had compatible exemplars available; operator chose to
    # defer — aggregate warn fires as designed.
    f1 = _deferral("9", "operator-deferral")
    f2 = _deferral("10", "operator-deferral")
    warns = cross_view_gate._check_excessive_post_ship_iteration([f1, f2])
    assert len(warns) == 1
    assert warns[0].kind == "excessive-post-ship-iteration"


def test_114_mixed_deferrals_count_only_operator_chosen():
    # One forced, two chosen — only the two operator-deferrals count.
    f1 = _deferral("9", "no-compatible-exemplar")
    f2 = _deferral("10", "operator-deferral")
    f3 = _deferral("11", "operator-deferral")
    warns = cross_view_gate._check_excessive_post_ship_iteration([f1, f2, f3])
    assert len(warns) == 1


def test_115_no_compatible_finding_carries_catalog_contribution_hint():
    f = _deferral("9", "no-compatible-exemplar")
    assert f.reason == "no-compatible-exemplar"
    assert "contributing an exemplar" in (f.suggested_fix or "")


def test_116_operator_deferral_finding_carries_catalog_install_hint():
    f = _deferral("9", "operator-deferral")
    assert f.reason == "operator-deferral"
    assert "~/.spectre/exemplars/" in (f.suggested_fix or "")


# ── End-to-end: gui-only fingerprint forces deferral, no excessive warn ─────

def test_117_gui_only_fingerprint_emits_no_compatible_deferral_no_aggregate_warn(
    tmp_path,
):
    """Spec where §8.5 uses gui-only but help-text catalog has only cli-*
    exemplars. The §11 deferral is forced (no-compatible-exemplar) and the
    aggregate warn does not fire even with two deferred views."""
    from bin import _catalog, cross_view_gate
    # Reset catalog cache so the live plugin catalog is loaded.
    _catalog._LOAD_CACHE = None
    body = (
        "# X\n\n**Generated:** 2026-05-15\n**Slug:** x\n**Spec-version:** 1.0\n\n"
        "## 8. Receiver Calibration\n\n"
        "### 8.1 Hard contract\n"
        "- mutates: /tmp/out\n"
        "- never-touches: /etc\n"
        "- decision-budget: none\n"
        "- reboot-survival: none\n\n"
        "### 8.5 Human-user substrate\n"
        "- receiver-fingerprint: gui-only\n\n"
        "### 8.7 Operator substrate\n"
        "- receiver-fingerprint: self-operated\n\n"
        "## 11. Human-User View\n\n"
        "### Exemplar bindings\n"
        "- help-text-style: post-ship-iteration\n\n"
        "## 13. Operator View\n\n"
        "### Exemplar bindings\n"
        "- log-format-style: post-ship-iteration\n"
    )
    spec = tmp_path / "x.spec.md"
    spec.write_text(body, encoding="utf-8")
    findings = cross_view_gate.classify(spec)
    deferrals = [f for f in findings if f.kind == "post-ship-iteration-deferral"]
    excessive = [f for f in findings if f.kind == "excessive-post-ship-iteration"]
    no_compat = [d for d in deferrals if d.reason == "no-compatible-exemplar"]
    assert len(deferrals) == 2
    assert len(no_compat) >= 1, "gui-only fingerprint must produce a no-compatible-exemplar deferral"
    assert excessive == [], "deferrals forced by empty catalog must not trigger excessive warn"
