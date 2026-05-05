"""Tests for bin/spec_ast.py — Tier 1 deterministic classifier.

All tests have one assertion per the pragma test-gaming guard.
Tests asserting absence/emptiness use _returns_empty/_is_none/_returns_false naming.
Tests with 'rejects/raises/refuses/denies' would use pytest.raises (none here — Tier 1
never raises on bad input; it returns findings).
"""
import time
import pathlib
import unittest.mock
import pytest

from bin import spec_ast

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "specs"


# ── good_minimal: clean baseline ────────────────────────────────────────────

def test_good_minimal_returns_empty_finding_list():
    result = spec_ast.classify(FIXTURES / "good_minimal.spec.md")
    assert result == []


# ── missing-why ─────────────────────────────────────────────────────────────

def test_missing_why_produces_missing_why_finding():
    fs = spec_ast.classify(FIXTURES / "missing_why.spec.md")
    assert any(f.kind == "missing-why" for f in fs)


def test_missing_why_severity_is_block():
    fs = spec_ast.classify(FIXTURES / "missing_why.spec.md")
    f = next(x for x in fs if x.kind == "missing-why")
    assert f.severity == "block"


def test_missing_why_location_is_step_scope():
    fs = spec_ast.classify(FIXTURES / "missing_why.spec.md")
    f = next(x for x in fs if x.kind == "missing-why")
    assert f.location.scope == "step"


def test_missing_why_location_ref_is_why():
    fs = spec_ast.classify(FIXTURES / "missing_why.spec.md")
    f = next(x for x in fs if x.kind == "missing-why")
    assert f.location.ref == "why"


# ── soft-verification ────────────────────────────────────────────────────────

def test_gamed_soft_verify_detected():
    fs = spec_ast.classify(FIXTURES / "gamed_soft_verify.spec.md")
    assert any(f.kind == "soft-verification" for f in fs)


def test_soft_verification_severity_is_block():
    fs = spec_ast.classify(FIXTURES / "gamed_soft_verify.spec.md")
    f = next(x for x in fs if x.kind == "soft-verification")
    assert f.severity == "block"


def test_soft_verification_location_ref_is_verification():
    fs = spec_ast.classify(FIXTURES / "gamed_soft_verify.spec.md")
    f = next(x for x in fs if x.kind == "soft-verification")
    assert f.location.ref == "verification"


def test_soft_verify_detects_bare_true():
    # gamed_soft_verify.spec.md has step 2 with verification: "true"
    fs = spec_ast.classify(FIXTURES / "gamed_soft_verify.spec.md")
    soft_verifs = [f for f in fs if f.kind == "soft-verification"]
    step_numbers = [f.location.step for f in soft_verifs]
    assert 2 in step_numbers


def test_soft_verify_detects_echo_done():
    # gamed_soft_verify.spec.md has step 3 with verification: "echo done"
    fs = spec_ast.classify(FIXTURES / "gamed_soft_verify.spec.md")
    soft_verifs = [f for f in fs if f.kind == "soft-verification"]
    step_numbers = [f.location.step for f in soft_verifs]
    assert 3 in step_numbers


def test_soft_verify_detects_colon():
    """Verification consisting of just ':' (shell no-op) must be flagged."""
    import tempfile, pathlib
    spec_text = """# Test
**Slug:** colon-test
## 1. Hard Problem
x
## 2. First Principles
- x
## 3. Algorithm Audit
- **Delete:** x
- **Simplify:** x
- **Accelerate:** x
## 4. Speed-of-Light Limit
x
## 5. Physics Guardrails
- x
## 6. Steps

```yaml
- step: 1
  why: "because x"
  action: "echo hello"
  verification: ":"
```

## 7. Success Criteria
- [ ] x

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` none
"""
    with tempfile.NamedTemporaryFile(suffix=".spec.md", mode="w", delete=False) as f:
        f.write(spec_text)
        tmp = pathlib.Path(f.name)
    try:
        fs = spec_ast.classify(tmp)
        assert any(f.kind == "soft-verification" for f in fs)
    finally:
        tmp.unlink(missing_ok=True)


def test_soft_verify_detects_bracket_1_eq_1():
    """Verification '[ 1 -eq 1 ]' must be flagged as soft-verification."""
    import tempfile, pathlib
    spec_text = """# Test
**Slug:** bracket-test
## 1. Hard Problem
x
## 2. First Principles
- x
## 3. Algorithm Audit
- **Delete:** x
- **Simplify:** x
- **Accelerate:** x
## 4. Speed-of-Light Limit
x
## 5. Physics Guardrails
- x
## 6. Steps

```yaml
- step: 1
  why: "because x"
  action: "echo hello"
  verification: "[ 1 -eq 1 ]"
```

## 7. Success Criteria
- [ ] x

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` none
"""
    with tempfile.NamedTemporaryFile(suffix=".spec.md", mode="w", delete=False) as f:
        f.write(spec_text)
        tmp = pathlib.Path(f.name)
    try:
        fs = spec_ast.classify(tmp)
        assert any(f.kind == "soft-verification" for f in fs)
    finally:
        tmp.unlink(missing_ok=True)


# ── missing-receiver-calibration ─────────────────────────────────────────────

def test_missing_calibration_returns_finding_when_section_absent():
    fs = spec_ast.classify(FIXTURES / "missing_calibration.spec.md")
    assert any(f.kind == "missing-receiver-calibration" for f in fs)


def test_missing_calibration_severity_is_block():
    fs = spec_ast.classify(FIXTURES / "missing_calibration.spec.md")
    f = next(x for x in fs if x.kind == "missing-receiver-calibration")
    assert f.severity == "block"


def test_missing_calibration_location_is_spec_wide():
    fs = spec_ast.classify(FIXTURES / "missing_calibration.spec.md")
    f = next(x for x in fs if x.kind == "missing-receiver-calibration")
    assert f.location.scope == "spec-wide"


def test_missing_calibration_when_mutates_field_absent():
    # missing_mutates_field.spec.md has §8.1 but no mutates: field
    fs = spec_ast.classify(FIXTURES / "missing_mutates_field.spec.md")
    assert any(f.kind == "missing-receiver-calibration" for f in fs)


# ── action-not-probed ────────────────────────────────────────────────────────

def test_action_not_probed_warn_when_path_in_action_not_in_verification():
    # action_not_probed.spec.md: step 1 action writes /tmp/foo/config.conf,
    # verification only checks "test -d /tmp" (path /tmp/foo not in verification)
    fs = spec_ast.classify(FIXTURES / "action_not_probed.spec.md")
    assert any(f.kind == "action-not-probed" for f in fs)


# ── performance ──────────────────────────────────────────────────────────────

def test_classify_runs_under_100ms():
    start = time.monotonic()
    spec_ast.classify(FIXTURES / "good_minimal.spec.md")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 100


# ── separation of concerns (Copilot review #3) ──────────────────────────────

def test_classify_does_not_call_bin_tier_classify():
    """Tier 1 must not invoke bin.tier.classify (that's Tier 2's job)."""
    with unittest.mock.patch("bin.tier.classify") as mock_tier:
        spec_ast.classify(FIXTURES / "good_minimal.spec.md")
        assert mock_tier.call_count == 0


def test_classify_does_not_call_bin_resources_extract():
    """Tier 1 must not invoke bin.resources.extract_resources_from_action."""
    with unittest.mock.patch("bin.resources.extract_resources_from_action") as mock_res:
        spec_ast.classify(FIXTURES / "good_minimal.spec.md")
        assert mock_res.call_count == 0
