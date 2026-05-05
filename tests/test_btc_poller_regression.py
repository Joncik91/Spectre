"""BTC Poller v0.2.2 regression — success criterion #1.

Proves the v0.3 evaluator catches the v0.2.2 BTC poller spec failures BEFORE lock.

Four of five v0.2.2 failures surface as findings:
  Failure 1  (undeclared resources)         → undeclared-resource
  Failure 3  (no §8 Receiver Calibration)   → missing-receiver-calibration
  Failure 5a (host paths, no mutates:)      → undeclared-host-path
  Failure 5b (paths without §8.1 contract)  → calibration-hard-violation

Not in scope for v0.3:
  Failure 2  (port 8765 already held by rule-router daemon) — live host probe, ideas-doc #4
  Failure 4  (silent tier on systemctl daemon-reload)       — v0.4 / Plan B

Pragma guard: assertion-style names only. One assertion per test.
"""
import pathlib
import time

import pytest

from bin import spec_evaluator

# ── Fixture paths ─────────────────────────────────────────────────────────────

_FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "specs" / "btc_poller_v022.spec.md"
)
_GOOD_MINIMAL = (
    pathlib.Path(__file__).parent / "fixtures" / "specs" / "good_minimal.spec.md"
)


def _run(tmp_path: pathlib.Path) -> spec_evaluator.EvaluatorResult:
    """Run Tier 1 + Tier 2 (no Tier 3) on the BTC poller v0.2.2 fixture."""
    return spec_evaluator.evaluate(_FIXTURE, config_path=None, bundle_persist_dir=tmp_path)


# ── 0. Success-path anchor — good spec produces info max_severity ─────────────
# Required by Pragma python.no_success_assertion: at least one test per file must
# assert a real positive return value from the production symbol.


def test_good_minimal_spec_max_severity_is_info(tmp_path):
    result = spec_evaluator.evaluate(
        _GOOD_MINIMAL, config_path=None, bundle_persist_dir=tmp_path
    )
    assert result.max_severity == "info"


# ── 1. Four distinct failure kinds surface ────────────────────────────────────


def test_btc_poller_v022_evaluator_finds_at_least_4_distinct_failures(tmp_path):
    result = _run(tmp_path)
    assert len({f.kind for f in result.findings}) >= 4


# ── 2. Undeclared resource — port 8765 inferred (curl in steps 3 & 7) ─────────


def test_btc_poller_v022_surfaces_undeclared_resource_finding(tmp_path):
    result = _run(tmp_path)
    assert any(f.kind == "undeclared-resource" for f in result.findings)


# ── 3. Undeclared host path — /opt/btc-poller, /etc/systemd/... ───────────────


def test_btc_poller_v022_surfaces_undeclared_host_path_finding(tmp_path):
    result = _run(tmp_path)
    assert any(f.kind == "undeclared-host-path" for f in result.findings)


# ── 4. Missing §8 Receiver Calibration — not present in v0.2.2 baseline ──────


def test_btc_poller_v022_surfaces_missing_receiver_calibration_finding(tmp_path):
    result = _run(tmp_path)
    assert any(f.kind == "missing-receiver-calibration" for f in result.findings)


# ── 5. Calibration hard violation — host paths written without mutates: ────────


def test_btc_poller_v022_surfaces_calibration_hard_violation_finding(tmp_path):
    result = _run(tmp_path)
    assert any(f.kind == "calibration-hard-violation" for f in result.findings)


# ── 6. Max severity is block ──────────────────────────────────────────────────


def test_btc_poller_v022_max_severity_is_block(tmp_path):
    result = _run(tmp_path)
    assert result.max_severity == "block"


# ── 7. Performance — Tier 1 + Tier 2 complete under 2 seconds ────────────────


def test_btc_poller_v022_evaluator_runs_under_2_seconds(tmp_path):
    start = time.monotonic()
    _run(tmp_path)
    assert time.monotonic() - start < 2.0


# ── 8. All findings are actionable — suggested_fix or location.ref present ────


def test_btc_poller_v022_findings_are_actionable(tmp_path):
    result = _run(tmp_path)
    assert all(f.suggested_fix or f.location.ref for f in result.findings)
