"""Tests for bin/coverage_gate.py — Tier 2 default-on coverage gate.

All tests have one assertion per the pragma test-gaming guard.
Tests asserting absence/emptiness use _returns_empty/_is_none/_does_not_flag naming.
Tests with rejects/raises/refuses/denies names would use pytest.raises (none here —
classify() never raises on bad input; it returns findings).
"""
import pathlib
import time

import pytest

# coverage_gate does not exist yet — all tests will FAIL until it is implemented.
from bin import coverage_gate

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "specs"


# ── 1. Clean baseline ────────────────────────────────────────────────────────

def test_good_minimal_returns_empty_finding_list():
    result = coverage_gate.classify(FIXTURES / "good_minimal.spec.md")
    assert result == []


# ── 2-5. undeclared-resource ─────────────────────────────────────────────────

def test_undeclared_resource_detected_when_port_inferred_but_not_in_resources_field():
    fs = coverage_gate.classify(FIXTURES / "undeclared_resource_port.spec.md")
    assert any(f.kind == "undeclared-resource" for f in fs)


def test_undeclared_resource_severity_warn():
    fs = coverage_gate.classify(FIXTURES / "undeclared_resource_port.spec.md")
    finding = next(f for f in fs if f.kind == "undeclared-resource")
    assert finding.severity == "warn"


def test_undeclared_resource_includes_step_location():
    fs = coverage_gate.classify(FIXTURES / "undeclared_resource_port.spec.md")
    finding = next(f for f in fs if f.kind == "undeclared-resource")
    assert finding.location.scope == "step"


def test_undeclared_resource_suggested_fix_present():
    fs = coverage_gate.classify(FIXTURES / "undeclared_resource_port.spec.md")
    finding = next(f for f in fs if f.kind == "undeclared-resource")
    assert finding.suggested_fix is not None


# ── 6. Resource correctly declared produces no finding ───────────────────────

def test_resource_correctly_declared_does_not_flag_undeclared_resource():
    fs = coverage_gate.classify(FIXTURES / "declared_resource_port.spec.md")
    assert not any(f.kind == "undeclared-resource" for f in fs)


# ── 7-9. undeclared-host-path ────────────────────────────────────────────────

def test_undeclared_host_path_detected_when_action_writes_to_etc_not_in_mutates():
    fs = coverage_gate.classify(FIXTURES / "undeclared_host_path.spec.md")
    assert any(f.kind == "undeclared-host-path" for f in fs)


def test_undeclared_host_path_severity_block():
    fs = coverage_gate.classify(FIXTURES / "undeclared_host_path.spec.md")
    finding = next(f for f in fs if f.kind == "undeclared-host-path")
    assert finding.severity == "block"


def test_host_path_in_mutates_does_not_produce_finding():
    fs = coverage_gate.classify(FIXTURES / "declared_host_path.spec.md")
    assert not any(f.kind == "undeclared-host-path" for f in fs)


# ── 10-11. calibration-hard-violation ───────────────────────────────────────

def test_calibration_hard_violation_when_action_touches_never_touches_path():
    fs = coverage_gate.classify(FIXTURES / "never_touches_collision.spec.md")
    assert any(f.kind == "calibration-hard-violation" for f in fs)


def test_calibration_hard_violation_severity_block():
    fs = coverage_gate.classify(FIXTURES / "never_touches_collision.spec.md")
    finding = next(f for f in fs if f.kind == "calibration-hard-violation")
    assert finding.severity == "block"


# ── 12-16. decision-without-adr ─────────────────────────────────────────────

def test_decision_without_adr_detected_when_decision_marker_no_adr_ref_no_preview():
    fs = coverage_gate.classify(
        FIXTURES / "decision_without_adr.spec.md",
        preview_adrs=[],
    )
    assert any(f.kind == "decision-without-adr" for f in fs)


def test_decision_with_preview_adr_does_not_produce_finding():
    fs = coverage_gate.classify(
        FIXTURES / "decision_without_adr.spec.md",
        preview_adrs=["0042-pick-x"],
    )
    assert not any(f.kind == "decision-without-adr" for f in fs)


def test_decision_with_adr_ref_field_does_not_produce_finding():
    fs = coverage_gate.classify(
        FIXTURES / "decision_with_adr_ref.spec.md",
        preview_adrs=[],
    )
    assert not any(f.kind == "decision-without-adr" for f in fs)


def test_decision_without_adr_severity_warn():
    fs = coverage_gate.classify(
        FIXTURES / "decision_without_adr.spec.md",
        preview_adrs=[],
    )
    finding = next(f for f in fs if f.kind == "decision-without-adr")
    assert finding.severity == "warn"


def test_decision_without_adr_location_is_spec_wide():
    fs = coverage_gate.classify(
        FIXTURES / "decision_without_adr.spec.md",
        preview_adrs=[],
    )
    finding = next(f for f in fs if f.kind == "decision-without-adr")
    assert finding.location.scope == "spec-wide"


# ── 17. Performance ──────────────────────────────────────────────────────────

def test_classify_runs_under_2s_on_seven_step_spec():
    start = time.monotonic()
    coverage_gate.classify(FIXTURES / "seven_step_perf.spec.md")
    elapsed = time.monotonic() - start
    assert elapsed < 2.0


# ── 18. No path captures — calibration-hard-violation is non-applicable ──────

def test_no_path_captures_does_not_trigger_calibration_hard_violation():
    fs = coverage_gate.classify(FIXTURES / "no_path_captures.spec.md")
    assert not any(f.kind == "calibration-hard-violation" for f in fs)


# ── 19. undeclared-resource message contains resource id format ──────────────

def test_undeclared_resource_uses_resource_id_format():
    fs = coverage_gate.classify(FIXTURES / "undeclared_resource_port.spec.md")
    finding = next(f for f in fs if f.kind == "undeclared-resource")
    assert "res-port-" in finding.message


# ── 20. classify signature accepts None preview_adrs ────────────────────────

def test_classify_signature_accepts_none_preview_adrs():
    # Must not raise; result must be a list
    result = coverage_gate.classify(FIXTURES / "good_minimal.spec.md")
    assert isinstance(result, list)
