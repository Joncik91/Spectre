"""Tests for Tier 1 Contract 3 checks (§50): verification-anchored-to-produces
and verification-upstream-only.

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _no_fire/_returns_empty/_passes naming.

Direct _check_verification_anchored calls are used for shape assertions so
Pragma can verify real return-value coverage.

Covers:
- verification-not-anchored-to-produces: fires when verification has no path
  token overlapping this step's produces:
- verification-upstream-only: fires when verification references only prior-step
  paths (not this step's)
- warn (not block) severity for both kinds
- no finding when verification references this step's own produced path
- no finding when step has no 'file:' produces
- no finding when verification is a tautology (soft-verify)
- multiple steps: correct per-step scoping
"""
import os
import pathlib
import tempfile

from bin import spec_ast

# ── Step helper for direct internal calls ────────────────────────────────────


def _step(
    n: int,
    verification: str = "",
    produces: list | None = None,
    action: str = "",
    requires: list | None = None,
) -> dict:
    return {
        "step": n,
        "why": "test",
        "action": action,
        "verification": verification,
        "produces": produces or [],
        "requires": requires or [],
        "negative_paths": [],
    }


def _anchored_findings(steps: list[dict]):
    return spec_ast._check_verification_anchored(steps)


def _findings_of_kind(steps: list[dict], kind: str):
    return [f for f in _anchored_findings(steps) if f.kind == kind]


# ── verification-not-anchored-to-produces: shape assertions ──────────────────


def test_not_anchored_kind_is_correct():
    steps = [
        _step(1,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert fs[0].kind == "verification-not-anchored-to-produces"


def test_not_anchored_severity_is_warn():
    steps = [
        _step(1,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert fs[0].severity == "warn"


def test_not_anchored_tier_is_1():
    steps = [
        _step(1,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert fs[0].tier == 1


def test_not_anchored_location_step_matches():
    steps = [
        _step(2,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert fs[0].location.step == 2


def test_not_anchored_location_ref_is_verification():
    steps = [
        _step(1,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert fs[0].location.ref == "verification"


def test_not_anchored_suggested_fix_is_non_empty():
    steps = [
        _step(1,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert fs[0].suggested_fix and len(fs[0].suggested_fix) > 0


# ── verification-not-anchored-to-produces: fire conditions ───────────────────


def test_not_anchored_fires_when_verification_has_no_path_overlap():
    """Verification checks a service; produces declares a config file — no overlap."""
    steps = [
        _step(1,
              verification="systemctl is-active myservice",
              produces=["file:/etc/app/config.toml"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert len(fs) == 1


def test_not_anchored_fires_for_unrelated_path_in_verification():
    """Verification references a completely different path than produces."""
    steps = [
        _step(1,
              verification="test -f /tmp/other.txt",
              produces=["file:/etc/app/myapp.conf"]),
    ]
    fs = _findings_of_kind(steps, "verification-not-anchored-to-produces")
    assert len(fs) == 1


# ── verification-not-anchored-to-produces: no-fire conditions ────────────────


def test_not_anchored_no_fire_when_verification_references_full_path():
    steps = [
        _step(1,
              verification="test -f /etc/app/config.toml",
              produces=["file:/etc/app/config.toml"]),
    ]
    result = _anchored_findings(steps)
    not_anch = [f for f in result if f.kind == "verification-not-anchored-to-produces"]
    assert not_anch == []


def test_not_anchored_no_fire_when_verification_references_basename():
    """Basename match counts as anchored."""
    steps = [
        _step(1,
              verification="test -f config.toml",
              produces=["file:/etc/app/config.toml"]),
    ]
    result = _anchored_findings(steps)
    not_anch = [f for f in result if f.kind == "verification-not-anchored-to-produces"]
    assert not_anch == []


def test_not_anchored_no_fire_when_no_file_produces():
    """Only 'file:' produces entries are considered; package: is not."""
    steps = [
        _step(1,
              verification="pip show myapp",
              produces=["package:myapp"]),
    ]
    result = _anchored_findings(steps)
    assert result == []


def test_not_anchored_no_fire_when_no_produces():
    steps = [
        _step(1, verification="test -f /tmp/out"),
    ]
    result = _anchored_findings(steps)
    assert result == []


def test_not_anchored_no_fire_when_verification_is_tautology():
    """Tautology verifications are skipped entirely."""
    steps = [
        _step(1,
              verification="true",
              produces=["file:/etc/app/config.toml"]),
    ]
    result = _anchored_findings(steps)
    assert result == []


def test_not_anchored_no_fire_when_verification_is_empty():
    steps = [
        _step(1, verification="", produces=["file:/etc/app/config.toml"]),
    ]
    result = _anchored_findings(steps)
    assert result == []


# ── verification-upstream-only: shape assertions ─────────────────────────────


def test_upstream_only_kind_is_correct():
    steps = [
        _step(1, verification="echo setup", produces=["file:/etc/setup.conf"]),
        _step(2,
              verification="test -f /etc/setup.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    fs = _findings_of_kind(steps, "verification-upstream-only")
    assert fs[0].kind == "verification-upstream-only"


def test_upstream_only_severity_is_warn():
    steps = [
        _step(1, verification="echo setup", produces=["file:/etc/setup.conf"]),
        _step(2,
              verification="test -f /etc/setup.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    fs = _findings_of_kind(steps, "verification-upstream-only")
    assert fs[0].severity == "warn"


def test_upstream_only_tier_is_1():
    steps = [
        _step(1, verification="echo setup", produces=["file:/etc/setup.conf"]),
        _step(2,
              verification="test -f /etc/setup.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    fs = _findings_of_kind(steps, "verification-upstream-only")
    assert fs[0].tier == 1


def test_upstream_only_location_step_matches():
    steps = [
        _step(1, verification="echo setup", produces=["file:/etc/setup.conf"]),
        _step(3,
              verification="test -f /etc/setup.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    fs = _findings_of_kind(steps, "verification-upstream-only")
    assert fs[0].location.step == 3


# ── verification-upstream-only: fire conditions ───────────────────────────────


def test_upstream_only_fires_when_verification_references_only_prior_step_path():
    """Step 2 verification only references Step 1's produced path."""
    steps = [
        _step(1, verification="echo setup", produces=["file:/etc/setup.conf"]),
        _step(2,
              verification="test -f /etc/setup.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    fs = _findings_of_kind(steps, "verification-upstream-only")
    assert len(fs) == 1


# ── verification-upstream-only: no-fire conditions ───────────────────────────


def test_upstream_only_no_fire_when_verification_references_own_path():
    """Step 2 verification references its own produced path — anchored."""
    steps = [
        _step(1, verification="echo setup", produces=["file:/etc/setup.conf"]),
        _step(2,
              verification="test -f /etc/app/main.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    result = _anchored_findings(steps)
    upstream = [f for f in result if f.kind == "verification-upstream-only"]
    assert upstream == []


def test_upstream_only_no_fire_on_first_step_with_prior_paths():
    """First step can't have 'upstream-only' — no prior steps exist."""
    steps = [
        _step(1,
              verification="test -f /etc/setup.conf",
              produces=["file:/etc/app/main.conf"]),
    ]
    result = _anchored_findings(steps)
    upstream = [f for f in result if f.kind == "verification-upstream-only"]
    assert upstream == []


# ── Multi-step scoping ────────────────────────────────────────────────────────


def test_findings_scoped_per_step_each_step_emits_own_finding():
    """Two steps each with unanchored verification → two findings (one per step).

    Uses pgrep (real command, no path tokens) rather than echo so the soft-
    verification gate doesn't preempt the anchored check.
    """
    steps = [
        _step(1,
              verification="pgrep mydaemon1",
              produces=["file:/etc/a.conf"]),
        _step(2,
              verification="pgrep mydaemon2",
              produces=["file:/etc/b.conf"]),
    ]
    fs = [f for f in _anchored_findings(steps)
          if f.kind == "verification-not-anchored-to-produces"]
    assert len(fs) == 2


def test_findings_step_numbers_are_distinct_in_multi_step():
    steps = [
        _step(1,
              verification="pgrep mydaemon1",
              produces=["file:/etc/a.conf"]),
        _step(2,
              verification="pgrep mydaemon2",
              produces=["file:/etc/b.conf"]),
    ]
    fs = [f for f in _anchored_findings(steps)
          if f.kind == "verification-not-anchored-to-produces"]
    step_nums = {f.location.step for f in fs}
    assert step_nums == {1, 2}


def test_only_failing_step_gets_finding_when_one_step_anchored():
    """Step 1 is properly anchored; step 2 is not — only step 2 gets a finding."""
    steps = [
        _step(1,
              verification="test -f /etc/a.conf",
              produces=["file:/etc/a.conf"]),
        _step(2,
              verification="pgrep mydaemon2",
              produces=["file:/etc/b.conf"]),
    ]
    fs = [f for f in _anchored_findings(steps)
          if f.kind == "verification-not-anchored-to-produces"]
    assert fs[0].location.step == 2


# ── Classify() integration ────────────────────────────────────────────────────

# §1-§8 skeleton lives in tests/fixtures/spec_template.py.
from tests.fixtures.spec_template import write_spec_file as _write_spec_helper


def _write_spec(steps_yaml: str) -> pathlib.Path:
    return _write_spec_helper(
        steps_yaml,
        title="Verification Anchored Test Spec",
        slug="verif-anchored-test",
        problem="Testing Contract 3 verification checks.",
        first_principles="- Verification should probe this step's own outputs.",
        success_criteria="- [ ] Check passes.",
        mutates="/etc/app/",
        never_touches="/etc/passwd",
    )




_UNANCHORED_YAML = """\
- step: 1
  why: "Write config file."
  action: "cat > /etc/app/config.toml << EOF\\n[app]\\nport=8080\\nEOF"
  verification: "systemctl is-active myservice"
  produces:
    - "file:/etc/app/config.toml"
  negative-paths:
    - trigger: "disk full"
      handler: "escalate"
"""

_ANCHORED_YAML = """\
- step: 1
  why: "Write config file."
  action: "cat > /etc/app/config.toml << EOF\\n[app]\\nport=8080\\nEOF"
  verification: "test -f /etc/app/config.toml"
  produces:
    - "file:/etc/app/config.toml"
  negative-paths:
    - trigger: "disk full"
      handler: "escalate"
"""


def test_classify_emits_not_anchored_finding_for_unanchored_step():
    p = _write_spec(_UNANCHORED_YAML)
    fs = [f for f in spec_ast.classify(p)
          if f.kind == "verification-not-anchored-to-produces"]
    assert fs[0].kind == "verification-not-anchored-to-produces"


def test_classify_no_not_anchored_finding_for_anchored_step():
    p = _write_spec(_ANCHORED_YAML)
    fs = [f for f in spec_ast.classify(p)
          if f.kind == "verification-not-anchored-to-produces"]
    assert fs == []
