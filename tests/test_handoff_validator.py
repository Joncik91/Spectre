"""Tests for bin/handoff_validator.py — Tier 0 /implement startup integrity check."""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "bin"))

import handoff_envelope
import handoff_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a project root with specs/ directory created."""
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_active(project: pathlib.Path, rel_spec_path: str) -> None:
    (project / "specs" / ".active").write_text(rel_spec_path, encoding="utf-8")


def _make_sidecar(specs_dir: pathlib.Path, spec_name: str, policy_hash: str = "a" * 64) -> pathlib.Path:
    data = {
        "evaluator_version": "0.6.0",
        "tiers_run": [1],
        "policy_hash": policy_hash,
        "findings_summary": {"block_count": 0, "warn_count": 0, "info_count": 0, "dismissed_t3_count": 0},
        "dismissals": [],
        "deepseek_model_version": None,
        "locked_at": "2026-05-07T00:00:00Z",
    }
    p = specs_dir / (spec_name + ".eval.json")
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_spec(specs_dir: pathlib.Path, spec_name: str = "foo.spec.md") -> pathlib.Path:
    p = specs_dir / spec_name
    p.write_text("# spec content\n", encoding="utf-8")
    return p


def _lock_spec(project: pathlib.Path, spec_name: str = "foo.spec.md") -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Create spec + sidecar + envelope, set .active. Returns (spec, sidecar, envelope) paths."""
    specs_dir = project / "specs"
    spec = _make_spec(specs_dir, spec_name)
    sidecar = _make_sidecar(specs_dir, spec_name)
    envelope = handoff_envelope.build(spec, sidecar, None, None)
    envelope_path = handoff_envelope.envelope_path_for(spec)
    handoff_envelope.write(envelope, envelope_path)
    _write_active(project, f"specs/{spec_name}")
    return spec, sidecar, envelope_path


# ---------------------------------------------------------------------------
# No active spec
# ---------------------------------------------------------------------------

class TestNoActiveSpec:
    def test_missing_active_file_returns_no_active_spec(self, tmp_path):
        project = _make_project(tmp_path)
        # .active file not created
        result = handoff_validator.validate_on_implement_start(project)
        assert result == ["no active spec — run /vision first"]

    def test_empty_active_file_returns_no_active_spec(self, tmp_path):
        project = _make_project(tmp_path)
        (project / "specs" / ".active").write_text("", encoding="utf-8")
        result = handoff_validator.validate_on_implement_start(project)
        assert result == ["no active spec — run /vision first"]


# ---------------------------------------------------------------------------
# Pre-v0.6 spec: envelope missing (warn-level)
# ---------------------------------------------------------------------------

class TestEnvelopeMissing:
    def test_missing_envelope_returns_envelope_missing(self, tmp_path):
        project = _make_project(tmp_path)
        specs_dir = project / "specs"
        _make_spec(specs_dir)
        _make_sidecar(specs_dir, "foo.spec.md")
        # No envelope file written
        _write_active(project, "specs/foo.spec.md")
        result = handoff_validator.validate_on_implement_start(project)
        assert len(result) == 1
        assert result[0].startswith("envelope-missing:")

    def test_missing_envelope_message_mentions_vision(self, tmp_path):
        project = _make_project(tmp_path)
        specs_dir = project / "specs"
        _make_spec(specs_dir)
        _make_sidecar(specs_dir, "foo.spec.md")
        _write_active(project, "specs/foo.spec.md")
        result = handoff_validator.validate_on_implement_start(project)
        assert "/vision" in result[0]


# ---------------------------------------------------------------------------
# Valid envelope: pass
# ---------------------------------------------------------------------------

class TestValidEnvelope:
    def test_locked_spec_with_envelope_returns_empty(self, tmp_path):
        project = _make_project(tmp_path)
        _lock_spec(project)
        result = handoff_validator.validate_on_implement_start(project)
        assert result == []

    def test_locked_spec_pass_is_idempotent(self, tmp_path):
        project = _make_project(tmp_path)
        _lock_spec(project)
        r1 = handoff_validator.validate_on_implement_start(project)
        r2 = handoff_validator.validate_on_implement_start(project)
        assert r1 == []
        assert r2 == []


# ---------------------------------------------------------------------------
# Tampered envelope: block-level
# ---------------------------------------------------------------------------

class TestEnvelopeTampered:
    def test_modified_spec_after_lock_returns_envelope_tampered(self, tmp_path):
        project = _make_project(tmp_path)
        spec, _sidecar, _env_path = _lock_spec(project)
        # Modify spec content after envelope was locked
        spec.write_text("# MODIFIED spec content\n", encoding="utf-8")
        # Now corrupt the envelope's integrity by rewriting it with wrong spec_path
        stored = handoff_envelope.read(_env_path)
        stored["spec_path"] = "/tampered/path.spec.md"
        # Keep the old integrity_hash so mismatch is detected
        handoff_envelope.write(stored, _env_path)
        result = handoff_validator.validate_on_implement_start(project)
        assert len(result) == 1
        assert result[0].startswith("envelope-tampered:")

    def test_envelope_tampered_message_mentions_vision(self, tmp_path):
        project = _make_project(tmp_path)
        _spec, _sidecar, env_path = _lock_spec(project)
        stored = handoff_envelope.read(env_path)
        stored["policy_hash"] = "b" * 64
        # Keep the old (now invalid) integrity_hash
        handoff_envelope.write(stored, env_path)
        result = handoff_validator.validate_on_implement_start(project)
        assert "/vision" in result[0]

    def test_mutated_integrity_hash_detected(self, tmp_path):
        project = _make_project(tmp_path)
        _spec, _sidecar, env_path = _lock_spec(project)
        stored = handoff_envelope.read(env_path)
        # Corrupt just the integrity_hash field — recompute will disagree
        stored["walker_yield_history"] = [99, 99, 99]
        # Leave integrity_hash as original (now stale)
        handoff_envelope.write(stored, env_path)
        result = handoff_validator.validate_on_implement_start(project)
        assert result[0].startswith("envelope-tampered:")

    def test_sidecar_policy_hash_drift_detected(self, tmp_path):
        project = _make_project(tmp_path)
        _spec, sidecar_path, env_path = _lock_spec(project)
        # Overwrite sidecar with a different policy_hash after lock
        new_sidecar_data = {
            "evaluator_version": "0.6.0",
            "tiers_run": [1],
            "policy_hash": "c" * 64,  # drifted
            "findings_summary": {"block_count": 0, "warn_count": 0, "info_count": 0, "dismissed_t3_count": 0},
            "dismissals": [],
            "deepseek_model_version": None,
            "locked_at": "2026-05-07T01:00:00Z",
        }
        sidecar_path.write_text(json.dumps(new_sidecar_data), encoding="utf-8")
        result = handoff_validator.validate_on_implement_start(project)
        assert result[0].startswith("envelope-tampered:")


# ---------------------------------------------------------------------------
# Malformed schema
# ---------------------------------------------------------------------------

class TestMalformedSchema:
    def test_envelope_with_missing_field_returns_schema_violations(self, tmp_path):
        project = _make_project(tmp_path)
        _spec, _sidecar, env_path = _lock_spec(project)
        stored = handoff_envelope.read(env_path)
        # Remove a field and recompute integrity_hash so it passes tamper check
        del stored["receiver"]
        stored["integrity_hash"] = handoff_envelope.compute_integrity_hash(stored)
        handoff_envelope.write(stored, env_path)
        result = handoff_validator.validate_on_implement_start(project)
        assert "missing field: receiver" in result

    def test_envelope_wrong_protocol_version_returns_violation(self, tmp_path):
        project = _make_project(tmp_path)
        _spec, _sidecar, env_path = _lock_spec(project)
        stored = handoff_envelope.read(env_path)
        stored["protocol_version"] = "0.5"
        stored["integrity_hash"] = handoff_envelope.compute_integrity_hash(stored)
        handoff_envelope.write(stored, env_path)
        result = handoff_validator.validate_on_implement_start(project)
        assert any("protocol_version" in v for v in result)
