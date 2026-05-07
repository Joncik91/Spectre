"""Tests for bin/handoff_envelope.py — Context Sled v0.6 envelope builder/validator."""
import json
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "bin"))

import handoff_envelope


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_sidecar(tmp_path: pathlib.Path, policy_hash: str = "a" * 64, contract_resolution=None) -> pathlib.Path:
    """Write a minimal .eval.json sidecar and return its path."""
    data: dict = {
        "evaluator_version": "0.6.0",
        "tiers_run": [1],
        "policy_hash": policy_hash,
        "findings_summary": {"block_count": 0, "warn_count": 0, "info_count": 0, "dismissed_t3_count": 0},
        "dismissals": [],
        "deepseek_model_version": None,
        "locked_at": "2026-05-07T00:00:00Z",
    }
    if contract_resolution is not None:
        data["contract_resolution"] = contract_resolution
    p = tmp_path / "foo.spec.md.eval.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_spec(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "foo.spec.md"
    p.write_text("# spec\n", encoding="utf-8")
    return p


def _make_walk(tmp_path: pathlib.Path, yield_history=None, stop_reason=None) -> pathlib.Path:
    data = {
        "yield_history": yield_history or [1, 2, 3],
        "stop_reason": stop_reason,
    }
    p = tmp_path / ".walk.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _build_envelope(tmp_path: pathlib.Path, **kwargs) -> dict:
    spec_path = _make_spec(tmp_path)
    sidecar_path = _make_sidecar(tmp_path)
    defaults = dict(
        spec_path=spec_path,
        sidecar_path=sidecar_path,
        walk_path=None,
        decisions_dir=None,
    )
    defaults.update(kwargs)
    return handoff_envelope.build(**defaults)


# ---------------------------------------------------------------------------
# build() — all required fields populated
# ---------------------------------------------------------------------------

class TestBuild:
    def test_build_has_protocol_version(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "protocol_version" in env

    def test_build_has_receiver(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "receiver" in env

    def test_build_has_spec_path(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "spec_path" in env

    def test_build_has_sidecar_path(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "sidecar_path" in env

    def test_build_has_policy_hash(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "policy_hash" in env

    def test_build_has_contract_resolution(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "contract_resolution" in env

    def test_build_has_walker_yield_history(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "walker_yield_history" in env

    def test_build_has_walker_stop_reason(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "walker_stop_reason" in env

    def test_build_has_decisions_indexed(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "decisions_indexed" in env

    def test_build_has_integrity_hash(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "integrity_hash" in env

    def test_build_has_created_at(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "created_at" in env

    def test_build_protocol_version_is_0_6(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert env["protocol_version"] == "0.6"

    def test_build_receiver_is_claude_code_implementer(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert env["receiver"] == "claude-code-implementer"

    def test_build_extracts_policy_hash_from_sidecar(self, tmp_path):
        ph = "b" * 64
        sidecar = _make_sidecar(tmp_path, policy_hash=ph)
        spec = _make_spec(tmp_path)
        env = handoff_envelope.build(spec, sidecar, None, None)
        assert env["policy_hash"] == ph

    def test_build_extracts_contract_resolution_from_sidecar(self, tmp_path):
        cr = {"steps": {"1": {"produces": ["foo"], "requires": []}}}
        sidecar = _make_sidecar(tmp_path, contract_resolution=cr)
        spec = _make_spec(tmp_path)
        env = handoff_envelope.build(spec, sidecar, None, None)
        assert env["contract_resolution"] == cr

    def test_build_contract_resolution_none_when_absent(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert env["contract_resolution"] is None

    def test_build_walker_yield_history_from_walk_path(self, tmp_path):
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        walk = _make_walk(tmp_path, yield_history=[10, 20])
        env = handoff_envelope.build(spec, sidecar, walk, None)
        assert env["walker_yield_history"] == [10, 20]

    def test_build_walker_stop_reason_from_walk_path(self, tmp_path):
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        walk = _make_walk(tmp_path, stop_reason="max_rounds")
        env = handoff_envelope.build(spec, sidecar, walk, None)
        assert env["walker_stop_reason"] == "max_rounds"

    def test_build_defaults_walker_fields_when_walk_path_absent(self, tmp_path):
        env = _build_envelope(tmp_path, walk_path=None)
        assert env["walker_yield_history"] == []
        assert env["walker_stop_reason"] is None

    def test_build_defaults_walker_fields_when_walk_path_missing_file(self, tmp_path):
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        env = handoff_envelope.build(spec, sidecar, tmp_path / "nonexistent.json", None)
        assert env["walker_yield_history"] == []
        assert env["walker_stop_reason"] is None

    def test_build_decisions_indexed_sorted(self, tmp_path):
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        dec_dir = tmp_path / "decisions"
        dec_dir.mkdir()
        (dec_dir / "zzz.md").write_text("z")
        (dec_dir / "aaa.md").write_text("a")
        (dec_dir / "mmm.md").write_text("m")
        env = handoff_envelope.build(spec, sidecar, None, dec_dir)
        assert env["decisions_indexed"] == ["aaa.md", "mmm.md", "zzz.md"]

    def test_build_decisions_indexed_empty_when_dir_absent(self, tmp_path):
        env = _build_envelope(tmp_path, decisions_dir=tmp_path / "nonexistent")
        assert env["decisions_indexed"] == []

    def test_build_decisions_indexed_only_md_files(self, tmp_path):
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        dec_dir = tmp_path / "decisions"
        dec_dir.mkdir()
        (dec_dir / "a.md").write_text("a")
        (dec_dir / "b.txt").write_text("b")
        (dec_dir / "c.json").write_text("{}")
        env = handoff_envelope.build(spec, sidecar, None, dec_dir)
        assert env["decisions_indexed"] == ["a.md"]

    def test_build_integrity_hash_is_64_char_hex(self, tmp_path):
        env = _build_envelope(tmp_path)
        h = env["integrity_hash"]
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_build_created_at_is_iso_utc(self, tmp_path):
        env = _build_envelope(tmp_path)
        # Should be "YYYY-MM-DDTHH:MM:SSZ" format
        ca = env["created_at"]
        assert ca.endswith("Z")
        assert "T" in ca

    def test_build_has_spec_sha256(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "spec_sha256" in env

    def test_build_spec_sha256_is_64_char_hex(self, tmp_path):
        env = _build_envelope(tmp_path)
        h = env["spec_sha256"]
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_build_spec_sha256_matches_spec_bytes(self, tmp_path):
        import hashlib as _hl
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        env = handoff_envelope.build(spec, sidecar, None, None)
        expected = _hl.sha256(spec.read_bytes()).hexdigest()
        assert env["spec_sha256"] == expected

    def test_build_has_sidecar_sha256(self, tmp_path):
        env = _build_envelope(tmp_path)
        assert "sidecar_sha256" in env

    def test_build_sidecar_sha256_is_64_char_hex(self, tmp_path):
        env = _build_envelope(tmp_path)
        h = env["sidecar_sha256"]
        assert h is not None
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_build_sidecar_sha256_matches_sidecar_bytes(self, tmp_path):
        import hashlib as _hl
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        env = handoff_envelope.build(spec, sidecar, None, None)
        expected = _hl.sha256(sidecar.read_bytes()).hexdigest()
        assert env["sidecar_sha256"] == expected


class TestArtifactHashCoverage:
    """spec_sha256/sidecar_sha256 are inside the integrity_hash payload."""

    def test_mutating_spec_bytes_changes_spec_sha256(self, tmp_path):
        import hashlib as _hl
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        env = handoff_envelope.build(spec, sidecar, None, None)
        original_spec_sha256 = env["spec_sha256"]
        # Simulate spec mutation
        mutated_sha256 = _hl.sha256(b"# MUTATED\n").hexdigest()
        assert original_spec_sha256 != mutated_sha256

    def test_spec_sha256_is_covered_by_integrity_hash(self, tmp_path):
        """Changing spec_sha256 in the envelope changes compute_integrity_hash()."""
        env = _build_envelope(tmp_path)
        h1 = handoff_envelope.compute_integrity_hash(env)
        env["spec_sha256"] = "0" * 64
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 != h2

    def test_sidecar_sha256_is_covered_by_integrity_hash(self, tmp_path):
        """Changing sidecar_sha256 in the envelope changes compute_integrity_hash()."""
        env = _build_envelope(tmp_path)
        h1 = handoff_envelope.compute_integrity_hash(env)
        env["sidecar_sha256"] = "0" * 64
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 != h2


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

class TestValidate:
    def test_validate_accepts_well_formed_envelope(self, tmp_path):
        env = _build_envelope(tmp_path)
        violations = handoff_envelope.validate(env)
        assert violations == []

    def test_validate_missing_field_protocol_version(self, tmp_path):
        env = _build_envelope(tmp_path)
        del env["protocol_version"]
        violations = handoff_envelope.validate(env)
        assert any("missing field: protocol_version" in v for v in violations)

    def test_validate_missing_field_receiver(self, tmp_path):
        env = _build_envelope(tmp_path)
        del env["receiver"]
        violations = handoff_envelope.validate(env)
        assert any("missing field: receiver" in v for v in violations)

    def test_validate_missing_field_spec_path(self, tmp_path):
        env = _build_envelope(tmp_path)
        del env["spec_path"]
        violations = handoff_envelope.validate(env)
        assert any("missing field: spec_path" in v for v in violations)

    def test_validate_missing_field_integrity_hash(self, tmp_path):
        env = _build_envelope(tmp_path)
        del env["integrity_hash"]
        violations = handoff_envelope.validate(env)
        assert any("missing field: integrity_hash" in v for v in violations)

    def test_validate_wrong_type_protocol_version(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["protocol_version"] = 6  # int, not str
        violations = handoff_envelope.validate(env)
        assert any("wrong type for protocol_version" in v for v in violations)

    def test_validate_wrong_type_walker_yield_history(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["walker_yield_history"] = "not-a-list"
        violations = handoff_envelope.validate(env)
        assert any("wrong type for walker_yield_history" in v for v in violations)

    def test_validate_wrong_protocol_version_value(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["protocol_version"] = "0.5"
        violations = handoff_envelope.validate(env)
        assert any("protocol_version must be '0.6'" in v for v in violations)

    def test_validate_wrong_receiver_value(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["receiver"] = "someone-else"
        violations = handoff_envelope.validate(env)
        assert any("receiver must be 'claude-code-implementer'" in v for v in violations)

    def test_validate_contract_resolution_none_is_valid(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["contract_resolution"] = None
        violations = handoff_envelope.validate(env)
        assert violations == []

    def test_validate_contract_resolution_dict_is_valid(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["contract_resolution"] = {"steps": {}}
        violations = handoff_envelope.validate(env)
        assert violations == []

    def test_validate_contract_resolution_wrong_type(self, tmp_path):
        env = _build_envelope(tmp_path)
        env["contract_resolution"] = "not-a-dict"
        violations = handoff_envelope.validate(env)
        assert any("wrong type for contract_resolution" in v for v in violations)

    @pytest.mark.parametrize("field", list(handoff_envelope._REQUIRED_FIELDS.keys()))
    def test_validate_missing_field_produces_violation(self, tmp_path, field):
        env = _build_envelope(tmp_path)
        del env[field]
        violations = handoff_envelope.validate(env)
        assert f"missing field: {field}" in violations


# ---------------------------------------------------------------------------
# compute_integrity_hash()
# ---------------------------------------------------------------------------

class TestComputeIntegrityHash:
    def test_deterministic_same_input_same_hash(self, tmp_path):
        env = _build_envelope(tmp_path)
        h1 = handoff_envelope.compute_integrity_hash(env)
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 == h2

    def test_excludes_integrity_hash_field_itself(self, tmp_path):
        env = _build_envelope(tmp_path)
        h1 = handoff_envelope.compute_integrity_hash(env)
        # Mutate integrity_hash field — recomputed hash should NOT change
        env["integrity_hash"] = "x" * 64
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 == h2

    def test_mutating_non_hash_field_changes_hash(self, tmp_path):
        env = _build_envelope(tmp_path)
        h1 = handoff_envelope.compute_integrity_hash(env)
        env["spec_path"] = "/different/path.spec.md"
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 != h2

    def test_mutating_policy_hash_changes_integrity_hash(self, tmp_path):
        env = _build_envelope(tmp_path)
        h1 = handoff_envelope.compute_integrity_hash(env)
        env["policy_hash"] = "c" * 64
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 != h2

    def test_mutating_walker_yield_history_changes_hash(self, tmp_path):
        spec = _make_spec(tmp_path)
        sidecar = _make_sidecar(tmp_path)
        walk = _make_walk(tmp_path, yield_history=[1, 2])
        env = handoff_envelope.build(spec, sidecar, walk, None)
        h1 = handoff_envelope.compute_integrity_hash(env)
        env["walker_yield_history"] = [1, 2, 3]
        h2 = handoff_envelope.compute_integrity_hash(env)
        assert h1 != h2


# ---------------------------------------------------------------------------
# write() / read() — round-trip
# ---------------------------------------------------------------------------

class TestWriteRead:
    def test_round_trip_returns_equal_dict(self, tmp_path):
        env = _build_envelope(tmp_path)
        target = tmp_path / "out.envelope.json"
        handoff_envelope.write(env, target)
        loaded = handoff_envelope.read(target)
        assert loaded == env

    def test_write_creates_parent_dirs(self, tmp_path):
        env = _build_envelope(tmp_path)
        target = tmp_path / "nested" / "dir" / "out.envelope.json"
        handoff_envelope.write(env, target)
        assert target.exists()

    def test_write_atomic_original_untouched_on_failure(self, tmp_path):
        """If write raises mid-way, original file is preserved."""
        env = _build_envelope(tmp_path)
        target = tmp_path / "out.envelope.json"

        # Write original content
        original_content = json.dumps({"original": True})
        target.write_text(original_content, encoding="utf-8")

        # Monkey-patch json.dump to raise after fd is opened
        import unittest.mock as mock
        with mock.patch("json.dump", side_effect=OSError("simulated failure")):
            with pytest.raises(OSError, match="simulated failure"):
                handoff_envelope.write(env, target)

        # Original should still be intact
        assert target.read_text(encoding="utf-8") == original_content

    def test_write_no_temp_files_left_on_success(self, tmp_path):
        env = _build_envelope(tmp_path)
        target = tmp_path / "out.envelope.json"
        handoff_envelope.write(env, target)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []
