"""Tests for bin/eval_metadata.py — .eval.json sidecar, policy hash, no-downgrade enforcement."""
import json
import pathlib
import sys
import tempfile
import tomllib

import pytest

# Ensure bin/ is on path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "bin"))

import findings as findings_mod
import eval_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(kind="missing-why", severity="block", tier=1):
    loc = findings_mod.FindingLocation(scope="step", step=1, ref="why")
    return findings_mod.Finding(
        tier=tier,
        kind=kind,
        severity=severity,
        location=loc,
        message="Test finding message",
    )


def _write_sidecar_defaults(spec_path, *, extra_findings=None, dismissals=None):
    all_findings = extra_findings or []
    return eval_metadata.write_sidecar(
        spec_path,
        evaluator_version="0.3.0",
        tiers_run=[1, 2],
        findings=all_findings,
        dismissals=dismissals or [],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="abc123",
    )


# ---------------------------------------------------------------------------
# compute_policy_hash
# ---------------------------------------------------------------------------

def test_compute_policy_hash_is_sha256_hex():
    h = eval_metadata.compute_policy_hash({}, {})
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_compute_policy_hash_stable_across_equal_inputs():
    h1 = eval_metadata.compute_policy_hash({"key": "val"}, {"k": "v"})
    h2 = eval_metadata.compute_policy_hash({"key": "val"}, {"k": "v"})
    assert h1 == h2


def test_compute_policy_hash_changes_when_config_changes():
    h1 = eval_metadata.compute_policy_hash({"x": 1}, {})
    h2 = eval_metadata.compute_policy_hash({"x": 2}, {})
    assert h1 != h2


def test_compute_policy_hash_changes_when_overrides_change():
    h1 = eval_metadata.compute_policy_hash({}, {"missing-why": "block"})
    h2 = eval_metadata.compute_policy_hash({}, {"missing-why": "warn"})
    assert h1 != h2


def test_compute_policy_hash_independent_of_dict_order():
    h1 = eval_metadata.compute_policy_hash({"a": 1, "b": 2}, {})
    h2 = eval_metadata.compute_policy_hash({"b": 2, "a": 1}, {})
    assert h1 == h2


# ---------------------------------------------------------------------------
# write_sidecar
# ---------------------------------------------------------------------------

def test_write_sidecar_creates_file_at_spec_path_eval_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "myspec.md"
        spec.write_text("# spec")
        sidecar = _write_sidecar_defaults(spec)
        assert sidecar == pathlib.Path(tmpdir) / "myspec.md.eval.json"
        assert sidecar.exists()


def test_write_sidecar_includes_evaluator_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        sidecar = _write_sidecar_defaults(spec)
        data = json.loads(sidecar.read_text())
        assert data["evaluator_version"] == "0.3.0"


def test_write_sidecar_includes_tiers_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        sidecar = _write_sidecar_defaults(spec)
        data = json.loads(sidecar.read_text())
        assert data["tiers_run"] == [1, 2]


def test_write_sidecar_findings_summary_block_count_correct():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        fs = [_make_finding("missing-why", "block"), _make_finding("missing-why", "block")]
        sidecar = _write_sidecar_defaults(spec, extra_findings=fs)
        data = json.loads(sidecar.read_text())
        assert data["findings_summary"]["block_count"] == 2


def test_write_sidecar_findings_summary_warn_count_correct():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        fs = [_make_finding("undeclared-resource", "warn"), _make_finding("action-not-probed", "warn")]
        sidecar = _write_sidecar_defaults(spec, extra_findings=fs)
        data = json.loads(sidecar.read_text())
        assert data["findings_summary"]["warn_count"] == 2


def test_write_sidecar_findings_summary_info_count_correct():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        fs = [_make_finding("tier3-unavailable", "info", tier=3)]
        sidecar = _write_sidecar_defaults(spec, extra_findings=fs)
        data = json.loads(sidecar.read_text())
        assert data["findings_summary"]["info_count"] == 1


def test_write_sidecar_dismissed_t3_count_matches_dismissals_length():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        dismissals = [
            {"finding_kind": "tier3-context-gap", "step": 3, "fingerprint": "abc", "reason": "ok"},
            {"finding_kind": "tier3-attacker-view", "step": None, "fingerprint": "def", "reason": "ok"},
        ]
        sidecar = _write_sidecar_defaults(spec, dismissals=dismissals)
        data = json.loads(sidecar.read_text())
        assert data["findings_summary"]["dismissed_t3_count"] == 2


def test_write_sidecar_atomic_no_tmp_left_behind():
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        _write_sidecar_defaults(spec)
        tmp_files = [f for f in pathlib.Path(tmpdir).iterdir() if f.suffix == ".tmp"]
        assert tmp_files == []


def test_write_sidecar_includes_locked_at_timestamp():
    import re
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = pathlib.Path(tmpdir) / "s.md"
        spec.write_text("")
        sidecar = _write_sidecar_defaults(spec)
        data = json.loads(sidecar.read_text())
        # ISO8601 with UTC Z suffix
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", data["locked_at"])


# ---------------------------------------------------------------------------
# validate_no_severity_downgrade
# ---------------------------------------------------------------------------

def test_validate_no_severity_downgrade_raises_when_block_lowered_to_warn():
    with pytest.raises(ValueError, match="downgrade"):
        eval_metadata.validate_no_severity_downgrade("block", "warn")


def test_validate_no_severity_downgrade_raises_when_warn_lowered_to_info():
    with pytest.raises(ValueError, match="downgrade"):
        eval_metadata.validate_no_severity_downgrade("warn", "info")


def test_validate_no_severity_downgrade_returns_none_when_block_kept_at_block():
    result = eval_metadata.validate_no_severity_downgrade("block", "block")
    assert result is None


def test_validate_no_severity_downgrade_returns_none_when_warn_raised_to_block():
    result = eval_metadata.validate_no_severity_downgrade("warn", "block")
    assert result is None


def test_validate_no_severity_downgrade_raises_on_unknown_default():
    with pytest.raises(ValueError, match="unknown severity"):
        eval_metadata.validate_no_severity_downgrade("critical", "block")


def test_validate_no_severity_downgrade_raises_on_unknown_override():
    with pytest.raises(ValueError, match="unknown severity"):
        eval_metadata.validate_no_severity_downgrade("block", "critical")


# ---------------------------------------------------------------------------
# load_severity_overrides_from_config
# ---------------------------------------------------------------------------

def test_load_severity_overrides_from_missing_config_returns_empty_dict():
    result = eval_metadata.load_severity_overrides_from_config(
        pathlib.Path("/nonexistent/path/reviewer.toml")
    )
    assert result == {}


def test_load_severity_overrides_raises_on_downgrade_attempt():
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        # missing-why default is "block"; trying to lower to "warn" is a downgrade
        f.write('[severity_overrides]\n"missing-why" = "warn"\n')
        f.flush()
        path = pathlib.Path(f.name)
    try:
        with pytest.raises(ValueError, match="downgrade"):
            eval_metadata.load_severity_overrides_from_config(path)
    finally:
        path.unlink(missing_ok=True)


def test_load_severity_overrides_accepts_upgrade():
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        # undeclared-resource default is "warn"; raising to "block" is allowed
        f.write('[severity_overrides]\n"undeclared-resource" = "block"\n')
        f.flush()
        path = pathlib.Path(f.name)
    try:
        result = eval_metadata.load_severity_overrides_from_config(path)
        assert result["undeclared-resource"] == "block"
    finally:
        path.unlink(missing_ok=True)


def test_load_severity_overrides_returns_empty_dict_when_table_absent():
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        f.write('[some_other_section]\nfoo = "bar"\n')
        f.flush()
        path = pathlib.Path(f.name)
    try:
        result = eval_metadata.load_severity_overrides_from_config(path)
        assert result == {}
    finally:
        path.unlink(missing_ok=True)


def test_load_severity_overrides_raises_on_unknown_kind():
    with tempfile.NamedTemporaryFile(suffix=".toml", mode="w", delete=False) as f:
        # Typo in finding kind must raise, not silently pass through
        f.write('[severity_overrides]\nbogus-kind = "block"\n')
        f.flush()
        path = pathlib.Path(f.name)
    try:
        with pytest.raises(ValueError, match="unknown finding kind"):
            eval_metadata.load_severity_overrides_from_config(path)
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# write_sidecar — findings_summary override
# ---------------------------------------------------------------------------

def test_write_sidecar_uses_findings_summary_override_when_provided(tmp_path):
    """When findings_summary is passed, it is written verbatim — not recomputed."""
    spec = tmp_path / "foo.spec.md"
    spec.write_text("# spec\n", encoding="utf-8")
    override = {"block_count": 2, "warn_count": 1, "info_count": 0, "dismissed_t3_count": 0}
    sidecar_path = eval_metadata.write_sidecar(
        spec,
        evaluator_version="0.5.0-rc1",
        tiers_run=[1, 2],
        findings=[],  # empty — would produce all-zero counts if recomputed
        dismissals=[],
        config_path=None,
        config_hash=None,
        deepseek_model_version=None,
        policy_hash="deadbeef" * 8,
        findings_summary=override,
    )
    on_disk = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert on_disk["findings_summary"] == override
