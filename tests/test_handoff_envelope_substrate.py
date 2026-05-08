"""Tests for substrate_sha256 field in handoff envelope (v0.7)."""
import hashlib
import json
import pathlib

import pytest

from bin import handoff_envelope


def _write_spec(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    p = tmp_path / "test.spec.md"
    p.write_text(body, encoding="utf-8")
    return p


def _write_sidecar(tmp_path: pathlib.Path) -> pathlib.Path:
    data = {
        "evaluator_version": "0.6.0",
        "tiers_run": [1],
        "policy_hash": "a" * 64,
        "findings_summary": {"block_count": 0, "warn_count": 0, "info_count": 0, "dismissed_t3_count": 0},
        "dismissals": [],
        "deepseek_model_version": None,
        "locked_at": "2026-05-07T00:00:00Z",
    }
    p = tmp_path / "test.spec.md.eval.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _82_block_text() -> str:
    return (
        "\n### 8.2 Cognitive-substrate contract\n\n"
        "- receiver-fingerprint: claude-code+human\n"
        "- trust-profile: none\n"
        "- contextual-binding: test\n"
        "- provenance: { kind: none }\n"
        "- ux-contract:\n"
        "    on-success: ok\n"
        "    on-failure: fail; check\n"
        "    log-target: /tmp/log\n"
    )


def test_build_envelope_includes_substrate_sha256(tmp_path):
    spec = _write_spec(tmp_path, "# spec\n" + _82_block_text())
    sidecar = _write_sidecar(tmp_path)
    walk = tmp_path / ".walk.json"
    walk.write_text(json.dumps({"yield_history": [], "stop_reason": None}))
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    env = handoff_envelope.build(spec, sidecar, walk, decisions_dir)
    assert "substrate_sha256" in env
    assert len(env["substrate_sha256"]) == 64


def test_substrate_sha256_matches_82_block_bytes(tmp_path):
    body = "# spec\n" + _82_block_text()
    spec = _write_spec(tmp_path, body)
    sidecar = _write_sidecar(tmp_path)
    walk = tmp_path / ".walk.json"
    walk.write_text(json.dumps({"yield_history": [], "stop_reason": None}))
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    env = handoff_envelope.build(spec, sidecar, walk, decisions_dir)
    expected = hashlib.sha256(_82_block_text().encode("utf-8")).hexdigest()
    assert env["substrate_sha256"] == expected


def test_envelope_without_82_block_has_empty_substrate_sha256(tmp_path):
    """Pre-v0.7 spec (no §8.2) → substrate_sha256 is empty string sentinel."""
    spec = _write_spec(tmp_path, "# spec\nno 8.2\n")
    sidecar = _write_sidecar(tmp_path)
    walk = tmp_path / ".walk.json"
    walk.write_text(json.dumps({"yield_history": [], "stop_reason": None}))
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    env = handoff_envelope.build(spec, sidecar, walk, decisions_dir)
    assert env["substrate_sha256"] == ""


def test_integrity_hash_includes_substrate_sha256_in_payload(tmp_path):
    """substrate_sha256 IS in the integrity hash domain — same as spec_sha256
    and sidecar_sha256 in v0.6. Post-lock §8.2 byte tampering changes
    integrity_hash and gets caught at Tier 0 verify."""
    spec = _write_spec(tmp_path, "# spec\n")
    sidecar = _write_sidecar(tmp_path)
    walk = tmp_path / ".walk.json"
    walk.write_text("{}")
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    env = handoff_envelope.build(spec, sidecar, walk, decisions_dir)
    h1 = handoff_envelope.compute_integrity_hash(env)
    env["substrate_sha256"] = "a" * 64
    h2 = handoff_envelope.compute_integrity_hash(env)
    assert h1 != h2, "substrate_sha256 must be in the integrity-hash domain"
