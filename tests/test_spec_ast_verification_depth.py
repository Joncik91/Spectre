"""Tests for v1.1 Fix 3 — verification-too-shallow-for-claim Tier-1 check.

Pragma guard: positive assertion names; one real assertion per test.
Absence tests use _no_ / _returns_no_ naming conventions.
"""
import pathlib

import pytest

from bin import spec_ast

from tests.fixtures.spec_template import write_spec_file as _write_spec_helper


def _write_spec(steps_yaml: str) -> pathlib.Path:
    return _write_spec_helper(
        steps_yaml,
        title="Verification Depth Test Spec",
        slug="verification-depth-test",
        problem="Testing behavioral-claim vs structural-only verification.",
        first_principles="- Verification must exercise behavior, not just symbol existence.",
        guardrails="- None.",
        success_criteria="- [ ] Check fires correctly.",
        mutates="/tmp/spectre-tests/",
    )


# ── Test 1: trigger verb + test -f fires warn ─────────────────────────────────

_TRIGGER_TEST_F_YAML = """\
- step: 1
  why: "trigger recalibration at N=5 illegibility events"
  action: "node scripts/build-lexicon.mjs"
  verification: "test -f x.ts"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_trigger_with_test_f_fires_warn():
    p = _write_spec(_TRIGGER_TEST_F_YAML)
    try:
        fs = spec_ast.classify(p)
        depth_findings = [f for f in fs if f.kind == "verification-too-shallow-for-claim"]
        assert len(depth_findings) == 1
    finally:
        p.unlink(missing_ok=True)


def test_trigger_with_test_f_severity_is_warn():
    p = _write_spec(_TRIGGER_TEST_F_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "verification-too-shallow-for-claim")
        assert f.severity == "warn"
    finally:
        p.unlink(missing_ok=True)


def test_trigger_with_test_f_kind_matches():
    p = _write_spec(_TRIGGER_TEST_F_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 2: prevent verb + grep -q fires warn ─────────────────────────────────

_PREVENT_GREP_Q_YAML = """\
- step: 1
  why: "prevent drift via recalibration when illegibility spikes"
  action: "node scripts/build-lexicon.mjs"
  verification: "grep -q shouldRecalibrate x.ts"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_prevent_with_grep_q_fires_warn():
    p = _write_spec(_PREVENT_GREP_Q_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 3: Vidence step 13 exact repro fires warn ───────────────────────────

_VIDENCE_REPRO_YAML = """\
- step: 13
  why: "the lexicon seeds a baseline vocabulary; a count-based recalibration trigger (N=5 illegibility events) prevents drift"
  action: "node scripts/build-lexicon.mjs"
  verification: "test -f packages/core/src/lexicon.ts && grep -q shouldRecalibrate packages/core/src/lexicon.ts"
  produces:
    - "file:/tmp/spectre-tests/packages/core/src/lexicon.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_vidence_repro_fires_warn():
    p = _write_spec(_VIDENCE_REPRO_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 4: behavioral why + pnpm vitest → no finding ────────────────────────

_BEHAVIORAL_VITEST_YAML = """\
- step: 1
  why: "trigger recalibration when N=5 illegibility events accumulate"
  action: "node scripts/build-lexicon.mjs"
  verification: "pnpm exec vitest run lexicon.test.ts"
  produces:
    - "file:/tmp/spectre-tests/lexicon.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_behavioral_with_pnpm_vitest_returns_no_finding():
    p = _write_spec(_BEHAVIORAL_VITEST_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 5: descriptive why + structural verification → no finding ────────────

_DESCRIPTIVE_WHY_YAML = """\
- step: 1
  why: "the lexicon module stores baseline vocabulary for text processing"
  action: "node scripts/build-lexicon.mjs"
  verification: "test -f x.ts"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_descriptive_why_with_structural_verification_returns_no_finding():
    p = _write_spec(_DESCRIPTIVE_WHY_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 6: empty why → no finding ───────────────────────────────────────────

_EMPTY_WHY_YAML = """\
- step: 1
  why: ""
  action: "node scripts/build-lexicon.mjs"
  verification: "test -f x.ts"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_empty_why_returns_no_finding():
    p = _write_spec(_EMPTY_WHY_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 7: empty verification → no finding ───────────────────────────────────

_EMPTY_VERIFICATION_YAML = """\
- step: 1
  why: "ensures atomic write to the output file"
  action: "node scripts/build-lexicon.mjs"
  verification: ""
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_empty_verification_returns_no_finding():
    p = _write_spec(_EMPTY_VERIFICATION_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 8: chained structural probes fire warn ───────────────────────────────

_CHAINED_STRUCTURAL_YAML = """\
- step: 1
  why: "the write must be atomic to prevent partial reads by the consumer"
  action: "node scripts/write-files.mjs"
  verification: "test -f x.ts && test -f y.ts"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
    - "file:/tmp/spectre-tests/y.ts"
  negative-paths:
    - trigger: "write fails"
      handler: "abort"
"""


def test_chained_structural_only_fires_warn():
    p = _write_spec(_CHAINED_STRUCTURAL_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 9: structural chained with runtime → no finding ─────────────────────

_STRUCTURAL_THEN_RUNTIME_YAML = """\
- step: 1
  why: "ensures atomic write completes before consumer reads"
  action: "node scripts/write-files.mjs"
  verification: "test -f x.ts && node verify.mjs"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "write fails"
      handler: "abort"
"""


def test_structural_chained_with_runtime_returns_no_finding():
    p = _write_spec(_STRUCTURAL_THEN_RUNTIME_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "verification-too-shallow-for-claim" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Test 10: all 10 behavioral verbs each fire once ──────────────────────────

_BEHAVIORAL_VERBS = [
    "trigger",
    "prevent",
    "ensure",
    "validate",
    "enforce",
    "coalesce",
    "refuse",
    "halt",
    "debounce",
    "atomic",
]

_VERB_STEPS_YAML_TEMPLATE = """\
- step: {n}
  why: "the module will {verb} the operation at runtime"
  action: "node scripts/build.mjs"
  verification: "test -f x.ts"
  produces:
    - "file:/tmp/spectre-tests/x.ts"
  negative-paths:
    - trigger: "build fails"
      handler: "abort"
"""


def test_each_behavioral_verb_fires():
    total_findings = 0
    for n, verb in enumerate(_BEHAVIORAL_VERBS, start=1):
        steps_yaml = _VERB_STEPS_YAML_TEMPLATE.format(n=n, verb=verb)
        p = _write_spec(steps_yaml)
        try:
            fs = spec_ast.classify(p)
            count = sum(1 for f in fs if f.kind == "verification-too-shallow-for-claim")
            total_findings += count
        finally:
            p.unlink(missing_ok=True)
    assert total_findings == 10
