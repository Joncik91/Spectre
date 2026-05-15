"""tests/test_llm_judge_run_fingerprint.py — v1.2 Fix P: Tier-3 run fingerprint.

Tests that _build_run_fingerprint / _emit_run_fingerprint produce correct,
stable, and input-sensitive fingerprints for non-determinism diagnosis.

Three required cases:
  1. fingerprint is present in status output (hash field populated)
  2. identical inputs → identical hash
  3. modified prompt → different hash
"""
from __future__ import annotations

import io
import sys

from bin.llm_judge import (
    JudgeConfig,
    _build_run_fingerprint,
    _emit_run_fingerprint,
    _CONTRADICTION_SYSTEM_PROMPT,
    _TIER3_PROVIDER,
    _TIER3_TEMPERATURE,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_MINIMAL_CONFIG = JudgeConfig(
    enabled=True,
    api_key_env="DEEPSEEK_API_KEY",
    model="deepseek-v4-flash",
)

_MINIMAL_SPEC = "# Test Spec\n\n**Spec-version:** 1.0\n\n## 6. Steps\n"

_MINIMAL_EXEMPLARS: list[str] = []


# ---------------------------------------------------------------------------
# Test 1: fingerprint is present in status output
# ---------------------------------------------------------------------------

def test_emit_run_fingerprint_outputs_hash(capsys):
    """_emit_run_fingerprint must emit a status line that contains hash= and hash_full=."""
    _emit_run_fingerprint(
        config=_MINIMAL_CONFIG,
        spec_text=_MINIMAL_SPEC,
        exemplar_slugs=_MINIMAL_EXEMPLARS,
    )
    captured = capsys.readouterr()
    # Output goes to stdout (info level, not quiet, not JSON mode)
    output = captured.out
    assert "tier3.run-fingerprint" in output, (
        "emitted line must contain the status code 'tier3.run-fingerprint'"
    )
    assert "hash=" in output, "emitted line must contain hash= field"
    assert "hash_full=" in output, "emitted line must contain hash_full= field"
    assert "model=" in output, "emitted line must contain model= field"
    assert "temperature=" in output, "emitted line must contain temperature= field"
    assert "provider=" in output, "emitted line must contain provider= field"


# ---------------------------------------------------------------------------
# Test 2: identical inputs → identical hash
# ---------------------------------------------------------------------------

def test_identical_inputs_produce_identical_hash():
    """Calling _build_run_fingerprint twice with identical inputs must return
    the same digest both times (deterministic hashing, no random component)."""
    kwargs = dict(
        config=_MINIMAL_CONFIG,
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT,
        exemplar_slugs=_MINIMAL_EXEMPLARS,
        spec_text=_MINIMAL_SPEC,
    )
    hash1 = _build_run_fingerprint(**kwargs)
    hash2 = _build_run_fingerprint(**kwargs)
    assert hash1 == hash2, (
        f"identical inputs must produce identical hash; got {hash1!r} vs {hash2!r}"
    )
    assert len(hash1) == 64, "fingerprint must be a 64-char hex SHA-256 digest"


# ---------------------------------------------------------------------------
# Test 3: modified prompt → different hash
# ---------------------------------------------------------------------------

def test_modified_system_prompt_produces_different_hash():
    """A spec with a different system prompt must produce a different fingerprint.

    Simulates the case where a prompt template is updated between runs —
    operators can see the hash change and attribute output differences to
    the prompt update rather than provider instability.
    """
    base_kwargs = dict(
        config=_MINIMAL_CONFIG,
        exemplar_slugs=_MINIMAL_EXEMPLARS,
        spec_text=_MINIMAL_SPEC,
    )
    hash_original = _build_run_fingerprint(
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT,
        **base_kwargs,
    )
    hash_modified = _build_run_fingerprint(
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT + "\n# MODIFIED",
        **base_kwargs,
    )
    assert hash_original != hash_modified, (
        "modified system prompt must produce a different fingerprint"
    )


# ---------------------------------------------------------------------------
# Test 4: modified spec → different hash
# ---------------------------------------------------------------------------

def test_modified_spec_produces_different_hash():
    """A different spec body must produce a different fingerprint.

    Simulates the case where the spec was edited between two Tier-3 runs.
    """
    hash_v1 = _build_run_fingerprint(
        config=_MINIMAL_CONFIG,
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT,
        exemplar_slugs=_MINIMAL_EXEMPLARS,
        spec_text=_MINIMAL_SPEC,
    )
    hash_v2 = _build_run_fingerprint(
        config=_MINIMAL_CONFIG,
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT,
        exemplar_slugs=_MINIMAL_EXEMPLARS,
        spec_text=_MINIMAL_SPEC + "\n- step: 99\n  why: added step\n  action: true\n  verification: true\n",
    )
    assert hash_v1 != hash_v2, (
        "modified spec text must produce a different fingerprint"
    )


# ---------------------------------------------------------------------------
# Test 5: exemplar set order-independence
# ---------------------------------------------------------------------------

def test_exemplar_set_hash_is_order_independent():
    """The exemplar_set_hash component must be insensitive to slug order.

    _build_run_fingerprint sorts slugs before hashing so that two runs with
    the same slugs in different order get the same fingerprint.
    """
    slugs_abc = ["alpha", "beta", "gamma"]
    slugs_cba = ["gamma", "beta", "alpha"]
    hash_abc = _build_run_fingerprint(
        config=_MINIMAL_CONFIG,
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT,
        exemplar_slugs=slugs_abc,
        spec_text=_MINIMAL_SPEC,
    )
    hash_cba = _build_run_fingerprint(
        config=_MINIMAL_CONFIG,
        system_prompt=_CONTRADICTION_SYSTEM_PROMPT,
        exemplar_slugs=slugs_cba,
        spec_text=_MINIMAL_SPEC,
    )
    assert hash_abc == hash_cba, (
        "exemplar slug order must not affect the fingerprint"
    )


# ---------------------------------------------------------------------------
# Test 6: SPECTRE_QUIET=1 suppresses the emission
# ---------------------------------------------------------------------------

def test_emit_run_fingerprint_suppressed_by_quiet(monkeypatch, capsys):
    """When SPECTRE_QUIET=1, tier3.run-fingerprint must not appear on stdout."""
    monkeypatch.setenv("SPECTRE_QUIET", "1")
    _emit_run_fingerprint(
        config=_MINIMAL_CONFIG,
        spec_text=_MINIMAL_SPEC,
        exemplar_slugs=_MINIMAL_EXEMPLARS,
    )
    captured = capsys.readouterr()
    assert "tier3.run-fingerprint" not in captured.out, (
        "tier3.run-fingerprint must be suppressed when SPECTRE_QUIET=1"
    )
