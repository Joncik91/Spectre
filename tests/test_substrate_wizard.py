"""Tests for bin/substrate_wizard.py — schema versioning + cache helpers."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from bin import substrate_wizard
from bin.substrate_wizard import WizardValidationError


def test_schema_version_constant_is_0_7():
    """SUBSTRATE_WIZARD_VERSION is the canonical schema string."""
    assert substrate_wizard.SUBSTRATE_WIZARD_VERSION == "0.7"


def test_cache_dir_default_is_user_spectre(monkeypatch, tmp_path):
    """Cache lives under ~/.spectre/substrate-cache/."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    p = substrate_wizard.cache_dir_default()
    assert p == tmp_path / ".spectre" / "substrate-cache"


_VALID_HASH_A = "a" * 64
_VALID_HASH_B = "b" * 64
_VALID_HASH_C = "c" * 64
_VALID_HASH_D = "d" * 64
_VALID_HASH_E = "e" * 64


def test_cache_path_for_hash_returns_named_file(monkeypatch, tmp_path):
    """Cache file name is <author-spec-hash>.json under the cache dir."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    p = substrate_wizard.cache_path_for_hash(_VALID_HASH_A)
    assert p.name == f"{_VALID_HASH_A}.json"
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
    p = substrate_wizard.write_cache(_VALID_HASH_A, answers)
    assert p.exists()
    assert oct(p.stat().st_mode)[-3:] == "600"
    body = json.loads(p.read_text())
    assert body["schema_version"] == "0.7"
    assert body["answers"] == answers


def test_read_cache_returns_none_when_missing(monkeypatch, tmp_path):
    """Cache read on missing file returns None, not exception."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    assert substrate_wizard.read_cache(_VALID_HASH_B) is None


def test_read_cache_returns_none_on_schema_mismatch(monkeypatch, tmp_path):
    """Stale schema_version means cache is unusable; return None."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    cache_dir = tmp_path / ".spectre" / "substrate-cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{_VALID_HASH_C}.json").write_text(
        json.dumps({"schema_version": "0.6", "answers": {}})
    )
    assert substrate_wizard.read_cache(_VALID_HASH_C) is None


def test_read_cache_returns_answers_when_fresh(monkeypatch, tmp_path):
    """Matching schema + present file → return parsed answers dict."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers = {"receiver-fingerprint": "claude-code+human"}
    substrate_wizard.write_cache(_VALID_HASH_D, answers)
    got = substrate_wizard.read_cache(_VALID_HASH_D)
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
    """Wizard with mock prompts returns a complete §8.2 block.

    After the 4 core questions, the wizard prompts for each ``<...>``
    placeholder in the rendered block (ux-contract fields, assumptions-killed,
    requires-situated-judgment, roi-budget).  All six are provided here so the
    iterator is not exhausted.
    """
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers_iter = iter([
        "1",                                  # receiver: claude-code+human
        "untrusted-input,touches-network",    # trust-profile
        "fetch external metadata for indexer",  # contextual-binding
        "none",                               # provenance
        # placeholder substitutions:
        "indexer ready",                      # on-success
        "indexer failed, check logs",         # on-failure + remediation
        "stderr",                             # log-target
        "polling instead of streaming",       # assumptions-killed
        "3, 5",                               # requires-situated-judgment
        "high yield low scaffolding",         # roi-budget
    ])

    def fake_prompt(question: str) -> str:
        return next(answers_iter)

    block = substrate_wizard.run(_VALID_HASH_A, prompt_fn=fake_prompt)
    assert "### 8.2 Cognitive-substrate contract" in block
    assert "claude-code+human" in block
    assert "untrusted-input" in block
    assert "touches-network" in block
    assert "fetch external metadata for indexer" in block
    assert "kind: none" in block
    # placeholders must be gone
    assert "<" not in block or all(
        tok not in block for tok in ["<one-line", "<path or stream", "<list of", "<yield-curve"]
    )


def test_run_writes_cache(monkeypatch, tmp_path):
    """A successful run persists answers to the cache.

    Provides answers for the 4 core questions plus the 6 placeholder fields
    surfaced by _substitute_placeholders after rendering.
    """
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    answers_iter = iter([
        "1", "none", "test binding", "none",   # 4 core questions
        "ok", "failed", "stderr", "none", "1", "low",  # 6 placeholder fields
    ])
    substrate_wizard.run(
        _VALID_HASH_B, prompt_fn=lambda _q: next(answers_iter)
    )
    cached = substrate_wizard.read_cache(_VALID_HASH_B)
    assert cached is not None
    assert cached["receiver-fingerprint"] == "claude-code+human"


def test_run_uses_cache_when_present(monkeypatch, tmp_path):
    """If a fresh cache exists, run() skips the 4 core questions.

    Placeholder fields (ux-contract, assumptions-killed, etc.) are still
    prompted because they are not part of the cached answers.
    """
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    substrate_wizard.write_cache(_VALID_HASH_C, {
        "receiver-fingerprint": "claude-code-autonomous",
        "trust-profile": [],
        "contextual-binding": "x",
        "provenance": {"kind": "none"},
    })

    # Provide answers only for the placeholder fields — NOT for the 4 core
    # questions, confirming those are not re-asked on a cache hit.
    placeholder_answers = iter(["ok", "failed", "stderr", "none", "2", "low"])

    block = substrate_wizard.run(_VALID_HASH_C, prompt_fn=lambda _q: next(placeholder_answers))
    assert "claude-code-autonomous" in block
    assert "<" not in block or all(
        tok not in block for tok in ["<one-line", "<path or stream", "<list of", "<yield-curve"]
    )


def test_run_raises_runtime_error_on_eof(monkeypatch, tmp_path):
    """EOFError from prompt_fn raises RuntimeError signalling 'deferred'."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)

    def eof_prompt(_q):
        raise EOFError()

    with pytest.raises(RuntimeError, match="deferred"):
        substrate_wizard.run(_VALID_HASH_D, prompt_fn=eof_prompt)


def test_run_provenance_with_parent_envelope_hash(monkeypatch, tmp_path):
    """Provenance answer in 'derived-from <slug> <sha>' form parses both fields."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    parent_sha = "f" * 64
    answers_iter = iter([
        "1",
        "none",
        "derived spec",
        f"derived-from foo-bar {parent_sha}",
        # placeholder answers:
        "ok", "failed", "stderr", "none", "2", "low",
    ])
    block = substrate_wizard.run(
        _VALID_HASH_E, prompt_fn=lambda _q: next(answers_iter)
    )
    assert "kind: derived-from" in block
    assert "parent-slug: foo-bar" in block
    assert f"parent-envelope-sha256: {parent_sha}" in block


def test_cli_run_prints_82_block(tmp_path, monkeypatch):
    """CLI 'run' subcommand with flags prints §8.2 markdown to stdout."""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-m", "bin.substrate_wizard", "run",
         "--author-spec-hash", "c" * 64,
         "--receiver", "claude-code+human",
         "--trust-profile", "none",
         "--binding", "test binding",
         "--provenance", "none"],
        capture_output=True,
        text=True,
        env={**env, "PYTHONPATH": "."},
    )
    assert result.returncode == 0
    assert "### 8.2 Cognitive-substrate contract" in result.stdout
    assert "claude-code+human" in result.stdout


# ---------------------------------------------------------------------------
# TestNonInteractiveFlags
# ---------------------------------------------------------------------------

_REPO_ROOT = str(pathlib.Path(__file__).resolve().parent.parent)

_GOOD_HASH = "0" * 64
_ALT_HASH = "1" * 64

_BASE_FLAGS = [
    "--receiver", "claude-code+human",
    "--trust-profile", "untrusted-input,touches-network",
    "--binding", "Test binding for non-interactive path",
    "--provenance", "none",
]


def _run_wizard(tmp_path, extra_args, stdin_data=None):
    """Helper: invoke substrate_wizard run via subprocess with isolated HOME."""
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": _REPO_ROOT}
    return subprocess.run(
        [sys.executable, "-m", "bin.substrate_wizard", "run"] + extra_args,
        input=stdin_data,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
    )


class TestNonInteractiveFlags:
    def test_all_flags_writes_cache_and_emits_block(self, tmp_path):
        """All four flags → cache written, stdout contains §8.2 block, exit 0."""
        result = _run_wizard(tmp_path, ["--author-spec-hash", _GOOD_HASH] + _BASE_FLAGS)
        assert result.returncode == 0, result.stderr
        assert "### 8.2 Cognitive-substrate contract" in result.stdout
        cache_file = (
            tmp_path / ".spectre" / "substrate-cache" / f"{_GOOD_HASH}.json"
        )
        assert cache_file.exists()
        body = json.loads(cache_file.read_text())
        assert body["answers"]["receiver-fingerprint"] == "claude-code+human"
        assert "untrusted-input" in body["answers"]["trust-profile"]
        assert body["answers"]["contextual-binding"] == "Test binding for non-interactive path"

    def test_all_flags_cache_hit_returns_cached(self, tmp_path, monkeypatch):
        """Cache hit (no --force) → cached values returned, not flag values."""
        # Pre-write cache with specific values.
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        cached_answers = {
            "receiver-fingerprint": "human-only",
            "trust-profile": [],
            "contextual-binding": "Cached binding original",
            "provenance": {"kind": "none"},
        }
        substrate_wizard.write_cache(_GOOD_HASH, cached_answers)

        # Invoke with DIFFERENT flag values (no --force).
        different_flags = [
            "--receiver", "claude-code-autonomous",
            "--trust-profile", "handles-secrets",
            "--binding", "New binding that should be ignored",
            "--provenance", "none",
        ]
        result = _run_wizard(tmp_path, ["--author-spec-hash", _GOOD_HASH] + different_flags)
        assert result.returncode == 0, result.stderr
        # Cached value must appear, new flag value must NOT appear.
        assert "human-only" in result.stdout
        assert "Cached binding original" in result.stdout
        assert "claude-code-autonomous" not in result.stdout
        assert "New binding that should be ignored" not in result.stdout

    def test_force_bypasses_cache(self, tmp_path, monkeypatch):
        """--force ignores cache and uses flag values; cache is overwritten."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        cached_answers = {
            "receiver-fingerprint": "human-only",
            "trust-profile": [],
            "contextual-binding": "Old cached binding",
            "provenance": {"kind": "none"},
        }
        substrate_wizard.write_cache(_GOOD_HASH, cached_answers)

        new_flags = [
            "--receiver", "claude-code+human",
            "--trust-profile", "touches-network",
            "--binding", "Forced new binding",
            "--provenance", "none",
            "--force",
        ]
        result = _run_wizard(tmp_path, ["--author-spec-hash", _GOOD_HASH] + new_flags)
        assert result.returncode == 0, result.stderr
        assert "Forced new binding" in result.stdout
        assert "human-only" not in result.stdout
        # Cache must reflect new values.
        fresh = substrate_wizard.read_cache(_GOOD_HASH)
        assert fresh["contextual-binding"] == "Forced new binding"
        assert fresh["receiver-fingerprint"] == "claude-code+human"

    def test_partial_flags_in_non_tty_errors_missing_flags(self, tmp_path):
        """Only --receiver provided → missing_flags error listing the 3 absent flags, exit 1."""
        result = _run_wizard(
            tmp_path,
            ["--author-spec-hash", _ALT_HASH, "--receiver", "claude-code+human"],
            stdin_data=None,  # no stdin — non-TTY subprocess is inherently non-TTY
        )
        assert result.returncode == 1
        assert "ERROR wizard.substrate" in result.stderr
        assert "missing_flags" in result.stderr
        # All three missing flags must appear in the missing= list.
        assert "trust-profile" in result.stderr
        assert "binding" in result.stderr
        assert "provenance" in result.stderr

    def test_invalid_receiver_errors(self, tmp_path, monkeypatch):
        """--receiver bogus → WizardValidationError with field='receiver', exit 1 from CLI."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        with pytest.raises(WizardValidationError) as exc_info:
            substrate_wizard.run_with_flags(
                _ALT_HASH,
                receiver="bogus",
                trust_profile="none",
                binding="test",
                provenance="none",
            )
        assert exc_info.value.field == "receiver"
        assert "invalid receiver" in exc_info.value.message

    def test_invalid_receiver_cli_errors(self, tmp_path):
        """CLI --receiver bogus → error wizard.substrate reason=invalid_receiver, exit 1."""
        result = _run_wizard(
            tmp_path,
            ["--author-spec-hash", _ALT_HASH,
             "--receiver", "bogus",
             "--trust-profile", "none",
             "--binding", "test",
             "--provenance", "none"],
        )
        assert result.returncode == 1
        assert "ERROR wizard.substrate" in result.stderr
        assert "invalid_receiver" in result.stderr

    def test_invalid_trust_profile_errors(self, tmp_path, monkeypatch):
        """--trust-profile foo,bar → WizardValidationError with field='trust_profile'."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        with pytest.raises(WizardValidationError) as exc_info:
            substrate_wizard.run_with_flags(
                _ALT_HASH,
                receiver="claude-code+human",
                trust_profile="foo,bar",
                binding="test",
                provenance="none",
            )
        assert exc_info.value.field == "trust_profile"
        assert "unknown trust token" in exc_info.value.message

    def test_empty_binding_errors(self, tmp_path, monkeypatch):
        """--binding '' → WizardValidationError with field='binding'."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        with pytest.raises(WizardValidationError) as exc_info:
            substrate_wizard.run_with_flags(
                _ALT_HASH,
                receiver="claude-code+human",
                trust_profile="none",
                binding="",
                provenance="none",
            )
        assert exc_info.value.field == "binding"
        assert "contextual-binding must not be empty" in exc_info.value.message

    def test_invalid_provenance_errors(self, tmp_path, monkeypatch):
        """--provenance 'derived-from foo notahex' → WizardValidationError with field='provenance'."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        with pytest.raises(WizardValidationError) as exc_info:
            substrate_wizard.run_with_flags(
                _ALT_HASH,
                receiver="claude-code+human",
                trust_profile="none",
                binding="test binding",
                provenance="derived-from foo notahex",
            )
        assert exc_info.value.field == "provenance"

    def test_trust_profile_none_token_returns_empty_list(self, tmp_path, monkeypatch):
        """--trust-profile none → trust-profile=[], §8.2 block shows 'none'."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        block = substrate_wizard.run_with_flags(
            _GOOD_HASH,
            receiver="claude-code+human",
            trust_profile="none",
            binding="test trust none",
            provenance="none",
        )
        assert "trust-profile: none" in block
        cached = substrate_wizard.read_cache(_GOOD_HASH)
        assert cached["trust-profile"] == []

    def test_zero_flags_non_tty_errors(self, tmp_path):
        """Zero flags + non-TTY stdin → missing_flags error listing all four, exit 1."""
        result = _run_wizard(
            tmp_path,
            ["--author-spec-hash", _ALT_HASH],
            stdin_data="",  # piped empty string → not a TTY
        )
        assert result.returncode == 1
        assert "ERROR wizard.substrate" in result.stderr
        assert "missing_flags" in result.stderr
        # All four must appear.
        for flag in ("receiver", "trust-profile", "binding", "provenance"):
            assert flag in result.stderr

    # ------------------------------------------------------------------
    # Path-traversal guard: --author-spec-hash validation
    # ------------------------------------------------------------------

    def test_invalid_author_spec_hash_traversal_rejected(self, tmp_path):
        """--author-spec-hash traversal string → error wizard.substrate reason=invalid_author_spec_hash, exit 1."""
        result = _run_wizard(
            tmp_path,
            ["--author-spec-hash", "../../etc/passwd"] + _BASE_FLAGS,
        )
        assert result.returncode == 1
        assert "ERROR wizard.substrate" in result.stderr
        assert "invalid_author_spec_hash" in result.stderr
        # No file must be written outside the test HOME.
        cache_dir = tmp_path / ".spectre" / "substrate-cache"
        written = list(cache_dir.rglob("*")) if cache_dir.exists() else []
        assert written == [], f"Unexpected files written: {written}"

    def test_invalid_author_spec_hash_short_rejected(self, tmp_path):
        """--author-spec-hash 'abc123' (too short) → error wizard.substrate reason=invalid_author_spec_hash, exit 1."""
        result = _run_wizard(
            tmp_path,
            ["--author-spec-hash", "abc123"] + _BASE_FLAGS,
        )
        assert result.returncode == 1
        assert "ERROR wizard.substrate" in result.stderr
        assert "invalid_author_spec_hash" in result.stderr

    def test_invalid_author_spec_hash_uppercase_rejected(self, tmp_path):
        """--author-spec-hash with 64 UPPERCASE hex chars → rejected (we require lowercase)."""
        uppercase_hash = "A" * 64
        result = _run_wizard(
            tmp_path,
            ["--author-spec-hash", uppercase_hash] + _BASE_FLAGS,
        )
        assert result.returncode == 1
        assert "ERROR wizard.substrate" in result.stderr
        assert "invalid_author_spec_hash" in result.stderr

    def test_write_cache_rejects_invalid_hash(self, tmp_path, monkeypatch):
        """write_cache() raises ValueError for a non-hex hash (library caller bypass)."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        with pytest.raises(ValueError, match="author-spec hash"):
            substrate_wizard.write_cache("../../evil", {})

    # ------------------------------------------------------------------
    # Trust-profile regression: mixed "untrusted-input,none" must be accepted
    # ------------------------------------------------------------------

    def test_trust_profile_mixed_with_none_token(self, tmp_path, monkeypatch):
        """'untrusted-input,none' must be accepted and the 'none' token kept (v0.8.0 semantics)."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        block = substrate_wizard.run_with_flags(
            _GOOD_HASH,
            receiver="claude-code+human",
            trust_profile="untrusted-input,none",
            binding="mixed trust test",
            provenance="none",
        )
        # Both tokens appear in the rendered block.
        assert "untrusted-input" in block
        assert "none" in block
        # Cache stores both tokens.
        cached = substrate_wizard.read_cache(_GOOD_HASH)
        assert "untrusted-input" in cached["trust-profile"]
        assert "none" in cached["trust-profile"]


def _run_per_view(tmp_path, extra_args):
    """Helper: invoke `substrate_wizard run-per-view` via subprocess with isolated HOME."""
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": _REPO_ROOT}
    return subprocess.run(
        [sys.executable, "-m", "bin.substrate_wizard", "run-per-view"] + extra_args,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
    )


class TestRunPerViewCLI:
    """CLI surface for §§8.3-8.7 per-view substrate blocks (v1.0.2)."""

    def test_in_scope_view_emits_8x_block(self, tmp_path):
        """Valid view + receiver + flags → stdout contains a §8.x block, exit 0."""
        result = _run_per_view(
            tmp_path,
            [
                "--view", "human-user",
                "--receiver", "cli-power-user",
                "--trust-profile", "none",
                "--binding", "Power-user CLI surface",
            ],
        )
        assert result.returncode == 0, result.stderr
        assert "### 8.5" in result.stdout and "human-user" in result.stdout.lower()
        assert "cli-power-user" in result.stdout

    def test_not_applicable_emits_degenerate_block(self, tmp_path):
        """--receiver not-applicable + --not-applicable-reason → degenerate block, exit 0."""
        result = _run_per_view(
            tmp_path,
            [
                "--view", "integrator",
                "--receiver", "not-applicable",
                "--not-applicable-reason", "no programmatic consumer",
            ],
        )
        assert result.returncode == 0, result.stderr
        assert "### 8.6" in result.stdout and "integrator" in result.stdout.lower()
        assert "not-applicable: no programmatic consumer" in result.stdout

    def test_not_applicable_without_reason_errors(self, tmp_path):
        """--receiver not-applicable without --not-applicable-reason → exit 1, error emit."""
        result = _run_per_view(
            tmp_path,
            ["--view", "integrator", "--receiver", "not-applicable"],
        )
        assert result.returncode == 1
        assert "missing_not_applicable_reason" in result.stderr

    def test_unknown_view_errors(self, tmp_path):
        """Unknown view name → exit 1, invalid_view error emit."""
        result = _run_per_view(
            tmp_path,
            [
                "--view", "made-up-view",
                "--receiver", "cli-power-user",
                "--binding", "x",
            ],
        )
        assert result.returncode == 1
        assert "invalid_view" in result.stderr

    def test_invalid_receiver_for_view_errors(self, tmp_path):
        """Receiver value not in view's vocabulary → exit 1, invalid_receiver-fingerprint error emit."""
        result = _run_per_view(
            tmp_path,
            [
                "--view", "human-user",
                "--receiver", "programmatic-trusted",  # belongs to product-input
                "--binding", "x",
            ],
        )
        assert result.returncode == 1
        assert "invalid_receiver-fingerprint" in result.stderr


# ── Fix I: placeholder substitution ──────────────────────────────────────────

class TestPlaceholderSubstitution:
    """Fix I: <...> stubs in rendered blocks are replaced by prompt_fn answers."""

    _HASH = "2" * 64

    def _make_placeholder_answers(self, extras=None):
        """Return an iterator covering all placeholder labels in a §8.2 block.

        §8.2 placeholders (implementing-agent view):
          on-success, on-failure+remediation, log-target,
          assumptions-killed, requires-situated-judgment, roi-budget
        """
        base = ["ready", "failed, retry", "/var/log/x", "polling ruled out", "3", "low"]
        if extras:
            base.extend(extras)
        return iter(base)

    def test_run_with_prompt_fn_produces_no_placeholders(self, monkeypatch, tmp_path):
        """run() with a prompt_fn must emit zero <...> tokens."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        answers_iter = iter([
            "1", "none", "fetch metadata", "none",  # 4 core questions
            "ready", "failed, retry", "/var/log/x", "polling ruled out", "3", "low",
        ])
        block = substrate_wizard.run(
            self._HASH, prompt_fn=lambda _q: next(answers_iter)
        )
        import re
        assert not re.search(r"<[^<>\n]+>", block), f"placeholder found in block:\n{block}"

    def test_run_per_view_with_prompt_fn_produces_no_placeholders(self, monkeypatch, tmp_path):
        """run_per_view() with prompt_fn substitutes all <...> tokens."""
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        answers_iter = iter([
            "product ready", "product failed", "stdout", "sync ruled out",
        ])
        block, _findings = substrate_wizard.run_per_view(
            view="product-output",
            receiver="human-reader",
            trust_profile="schema-stable",
            binding="export CSV report",
            prompt_fn=lambda _q: next(answers_iter),
        )
        import re
        assert not re.search(r"<[^<>\n]+>", block), f"placeholder found in block:\n{block}"

    def test_run_per_view_without_prompt_fn_leaves_placeholders(self):
        """Without prompt_fn, <...> tokens are left in-place (backward-compat)."""
        block, _findings = substrate_wizard.run_per_view(
            view="operator",
            receiver="on-call-engineer",
            trust_profile="paging-required",
            binding="production deployment runbook",
        )
        import re
        assert re.search(r"<[^<>\n]+>", block), "expected placeholders when no prompt_fn"

    def test_substitute_placeholders_deduplicates_labels(self, monkeypatch, tmp_path):
        """Each unique placeholder label is asked exactly once."""
        _DEDUP_HASH = "9" * 64
        monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
        call_count = {"n": 0}

        def counting_prompt(_q):
            call_count["n"] += 1
            return "answer"

        # _format_82_block has 6 distinct placeholder labels; run() core questions
        # also call prompt_fn, so we need to feed those first.
        answers_iter = iter(["1", "none", "binding text", "none"])

        def combined_prompt(q):
            try:
                return next(answers_iter)
            except StopIteration:
                return counting_prompt(q)

        substrate_wizard.run(_DEDUP_HASH, prompt_fn=combined_prompt)
        # 6 distinct placeholder labels in §8.2 implementing-agent view
        assert call_count["n"] == 6

    def test_substitute_placeholders_direct(self):
        """_substitute_placeholders replaces every token and deduplicates."""
        block = "foo: <x>\nbar: <y>\nbaz: <x>"
        answers = iter(["val-x", "val-y"])
        result = substrate_wizard._substitute_placeholders(block, lambda _q: next(answers))
        assert "val-x" in result
        assert "val-y" in result
        assert "<x>" not in result
        assert "<y>" not in result
