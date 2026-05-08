"""Tests for bin/substrate_wizard.py — schema versioning + cache helpers."""
import json
import pathlib

import pytest

from bin import substrate_wizard


def test_schema_version_constant_is_0_7():
    """SUBSTRATE_WIZARD_VERSION is the canonical schema string."""
    assert substrate_wizard.SUBSTRATE_WIZARD_VERSION == "0.7"


def test_cache_dir_default_is_user_spectre(monkeypatch, tmp_path):
    """Cache lives under ~/.spectre/substrate-cache/."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    p = substrate_wizard.cache_dir_default()
    assert p == tmp_path / ".spectre" / "substrate-cache"


def test_cache_path_for_hash_returns_named_file(monkeypatch, tmp_path):
    """Cache file name is <author-spec-hash>.json under the cache dir."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    p = substrate_wizard.cache_path_for_hash("abc123")
    assert p.name == "abc123.json"
    assert p.parent.name == "substrate-cache"


def test_write_cache_creates_file_at_mode_0600(monkeypatch, tmp_path):
    """Cache writes are atomic + 0600."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers = {
        "receiver-fingerprint": "claude-code+human",
        "trust-profile": ["untrusted-input"],
        "contextual-binding": "test",
        "provenance": {"kind": "none"},
    }
    p = substrate_wizard.write_cache("abc123", answers)
    assert p.exists()
    assert oct(p.stat().st_mode)[-3:] == "600"
    body = json.loads(p.read_text())
    assert body["schema_version"] == "0.7"
    assert body["answers"] == answers


def test_read_cache_returns_none_when_missing(monkeypatch, tmp_path):
    """Cache read on missing file returns None, not exception."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    assert substrate_wizard.read_cache("missing-hash") is None


def test_read_cache_returns_none_on_schema_mismatch(monkeypatch, tmp_path):
    """Stale schema_version means cache is unusable; return None."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    cache_dir = tmp_path / ".spectre" / "substrate-cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "abc.json").write_text(
        json.dumps({"schema_version": "0.6", "answers": {}})
    )
    assert substrate_wizard.read_cache("abc") is None


def test_read_cache_returns_answers_when_fresh(monkeypatch, tmp_path):
    """Matching schema + present file → return parsed answers dict."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers = {"receiver-fingerprint": "claude-code+human"}
    substrate_wizard.write_cache("abc", answers)
    got = substrate_wizard.read_cache("abc")
    assert got == answers


def test_compute_author_spec_hash_excludes_82_block():
    """Author hash is over draft body MINUS the auto-injected ### 8.2 block."""
    body_no_82 = "# Spec\n\n## 1. Hard Problem\nfoo\n## 8. Receiver\n### 8.1 ...\n"
    body_with_82 = body_no_82 + "\n### 8.2 Cognitive-substrate contract\n- foo: bar\n"
    assert substrate_wizard.compute_author_spec_hash(body_no_82) == \
           substrate_wizard.compute_author_spec_hash(body_with_82)
