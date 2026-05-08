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


def test_compute_author_spec_hash_excludes_82_block_followed_by_another_heading():
    """§8.2 block in the MIDDLE of a spec (followed by ## 9. ...) is also stripped."""
    body_no_82 = (
        "# Spec\n"
        "## 8. Receiver\n"
        "### 8.1 Hard contract\n"
        "- foo: bar\n"
        "## 9. Out of scope\n"
        "- nothing\n"
    )
    body_with_82 = (
        "# Spec\n"
        "## 8. Receiver\n"
        "### 8.1 Hard contract\n"
        "- foo: bar\n"
        "\n### 8.2 Cognitive-substrate contract\n"
        "- receiver-fingerprint: claude-code+human\n"
        "## 9. Out of scope\n"
        "- nothing\n"
    )
    assert (
        substrate_wizard.compute_author_spec_hash(body_no_82)
        == substrate_wizard.compute_author_spec_hash(body_with_82)
    )


def test_run_with_all_answers_returns_82_markdown(monkeypatch, tmp_path):
    """Wizard with mock prompts returns a complete §8.2 block."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers_iter = iter([
        "1",                                  # receiver: claude-code+human
        "untrusted-input,touches-network",    # trust-profile
        "fetch external metadata for indexer",  # contextual-binding
        "none",                                # provenance
    ])

    def fake_prompt(question: str) -> str:
        return next(answers_iter)

    block = substrate_wizard.run("hash-abc", prompt_fn=fake_prompt)
    assert "### 8.2 Cognitive-substrate contract" in block
    assert "claude-code+human" in block
    assert "untrusted-input" in block
    assert "touches-network" in block
    assert "fetch external metadata for indexer" in block
    assert "kind: none" in block


def test_run_writes_cache(monkeypatch, tmp_path):
    """A successful run persists answers to the cache."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers_iter = iter(["1", "none", "test", "none"])
    substrate_wizard.run(
        "hash-cache", prompt_fn=lambda _q: next(answers_iter)
    )
    cached = substrate_wizard.read_cache("hash-cache")
    assert cached is not None
    assert cached["receiver-fingerprint"] == "claude-code+human"


def test_run_uses_cache_when_present(monkeypatch, tmp_path):
    """If a fresh cache exists, run() uses it without re-prompting."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    substrate_wizard.write_cache("hash-fresh", {
        "receiver-fingerprint": "claude-code-autonomous",
        "trust-profile": [],
        "contextual-binding": "x",
        "provenance": {"kind": "none"},
    })

    def fail_prompt(_q):
        raise AssertionError("should not prompt when cache is fresh")

    block = substrate_wizard.run("hash-fresh", prompt_fn=fail_prompt)
    assert "claude-code-autonomous" in block


def test_run_raises_runtime_error_on_eof(monkeypatch, tmp_path):
    """EOFError from prompt_fn raises RuntimeError signalling 'deferred'."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)

    def eof_prompt(_q):
        raise EOFError()

    with pytest.raises(RuntimeError, match="deferred"):
        substrate_wizard.run("hash-eof", prompt_fn=eof_prompt)


def test_run_provenance_with_parent_envelope_hash(monkeypatch, tmp_path):
    """Provenance answer in 'derived-from <slug> <sha>' form parses both fields."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    parent_sha = "f" * 64
    answers_iter = iter([
        "1",
        "none",
        "derived spec",
        f"derived-from foo-bar {parent_sha}",
    ])
    block = substrate_wizard.run(
        "hash-deriv", prompt_fn=lambda _q: next(answers_iter)
    )
    assert "kind: derived-from" in block
    assert "parent-slug: foo-bar" in block
    assert f"parent-envelope-sha256: {parent_sha}" in block
