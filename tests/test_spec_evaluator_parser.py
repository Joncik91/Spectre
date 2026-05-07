"""Tests for §8.1 parser fixes: h2/h3 acceptance, brace expansion, markdown stripping.

Closes #24: Tier 1 parser fragility with h3 §8.1, brace expansion, bold markers.

Coverage:
  - test_section_81_accepts_h2
  - test_section_81_accepts_h3
  - test_section_81_accepts_h2_with_parenthetical
  - test_mutates_brace_expansion_two_choices
  - test_mutates_brace_expansion_nested
  - test_mutates_brace_expansion_single_no_comma_passthrough
  - test_mutates_strips_bold_markers
  - test_mutates_strips_inline_code_markers
  - test_mutates_numeric_range_kept_literal_with_warning
  - test_no_brace_passthrough
  - test_roundtrip_all_fragility_patterns_zero_false_positives  (integration)
"""
import io
import pathlib
import sys
import tempfile

import pytest

from bin import coverage_gate
from bin import spec_ast

# ── Minimal spec templates ────────────────────────────────────────────────────
# All tests that call spec_ast.classify() or coverage_gate.classify() need a
# structurally valid spec file on disk (those functions take a pathlib.Path).
# Tests that call parse_81_block() directly can work with raw strings.

_SPEC_PREAMBLE = """\
# Test Spec

## 1. Hard Problem
Testing.

## 2. First Principles
- Keep it simple.

## 3. Algorithm Audit
- N/A.

## 4. Speed-of-Light Limit
Under 1 second.

## 5. Physics Guardrails
- None.

## 6. Steps

```yaml
- step: 1
  why: "Needed for the service to exist."
  action: "cp /tmp/foo.service /etc/systemd/system/foo.service"
  verification: "test -f /etc/systemd/system/foo.service"

- step: 2
  why: "Needed for the timer to exist."
  action: "cp /tmp/foo.timer /etc/systemd/system/foo.timer"
  verification: "test -f /etc/systemd/system/foo.timer"
```

## 7. Success Criteria
- [ ] Service installed.

## 8. Receiver Calibration

"""

_SECTION_81_SUFFIX = """\
- `mutates:` /etc/systemd/system/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` none

### 8.2 Human notes

- `assumes:` knows-systemd
"""


def _make_spec(tmp_path: pathlib.Path, section_81_heading: str, mutates_line: str = None) -> pathlib.Path:
    """Write a spec to disk with the given §8.1 heading and optional mutates override."""
    if mutates_line is None:
        body_81 = (
            f"{section_81_heading}\n\n"
            f"- `mutates:` /etc/systemd/system/\n"
            f"- `never-touches:` /home\n"
            f"- `decision-budget:` none\n"
            f"- `reboot-survival:` none\n"
        )
    else:
        body_81 = (
            f"{section_81_heading}\n\n"
            f"{mutates_line}\n"
            f"- `never-touches:` /home\n"
            f"- `decision-budget:` none\n"
            f"- `reboot-survival:` none\n"
        )
    content = _SPEC_PREAMBLE + body_81
    p = tmp_path / "test.spec.md"
    p.write_text(content, encoding="utf-8")
    return p


# ── §8.1 heading acceptance ───────────────────────────────────────────────────

def test_section_81_accepts_h2(tmp_path):
    """## 8.1 heading (h2) must not produce missing-receiver-calibration."""
    spec = _make_spec(tmp_path, "## 8.1 Hard contract")
    findings = spec_ast.classify(spec)
    assert not any(f.kind == "missing-receiver-calibration" for f in findings)


def test_section_81_accepts_h3(tmp_path):
    """### 8.1 heading (h3) must not produce missing-receiver-calibration."""
    spec = _make_spec(tmp_path, "### 8.1 Hard contract")
    findings = spec_ast.classify(spec)
    assert not any(f.kind == "missing-receiver-calibration" for f in findings)


def test_section_81_accepts_h2_with_parenthetical(tmp_path):
    """## 8.1 Hard contract (machine-enforced) must be accepted."""
    spec = _make_spec(tmp_path, "## 8.1 Hard contract (machine-enforced)")
    findings = spec_ast.classify(spec)
    assert not any(f.kind == "missing-receiver-calibration" for f in findings)


# ── Brace expansion ───────────────────────────────────────────────────────────

def test_mutates_brace_expansion_two_choices():
    """foo.{service,timer} → ['foo.service', 'foo.timer']."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` /etc/systemd/system/foo.{service,timer}\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    assert set(result["mutates"]) == {
        "/etc/systemd/system/foo.service",
        "/etc/systemd/system/foo.timer",
    }


def test_mutates_brace_expansion_nested():
    """{x,y}.{a,b} → 4 paths (cartesian product)."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` /etc/{foo,bar}.{conf,d}\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    assert set(result["mutates"]) == {
        "/etc/foo.conf",
        "/etc/foo.d",
        "/etc/bar.conf",
        "/etc/bar.d",
    }


def test_mutates_brace_expansion_single_no_comma_passthrough():
    """foo.{bar} — single choice, no comma — braces are stripped, literal path kept."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` /etc/systemd/system/foo.{service}\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    assert result["mutates"] == ["/etc/systemd/system/foo.service"]


# ── Markdown formatter stripping ──────────────────────────────────────────────

def test_mutates_strips_bold_markers():
    """**path** bold markers are stripped before path matching."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` **/etc/systemd/system/**\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    assert result["mutates"] == ["/etc/systemd/system/"]


def test_mutates_strips_inline_code_markers():
    """`path` inline-code backticks are stripped before path matching."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` `/etc/systemd/system/`\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    assert result["mutates"] == ["/etc/systemd/system/"]


def test_mutates_numeric_range_kept_literal_with_warning(capsys):
    """foo.{1..10} emits a stderr warning and keeps the literal path (not expanded)."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` /var/log/app.{1..10}.log\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    captured = capsys.readouterr()
    # Must keep the literal path (not expand it)
    assert result["mutates"] == ["/var/log/app.{1..10}.log"]
    # Must emit a warning to stderr
    assert "warning" in captured.err.lower()


def test_no_brace_passthrough():
    """Paths with no braces are returned unchanged."""
    spec_text = (
        "### 8.1 Hard contract\n"
        "- `mutates:` /etc/systemd/system/\n"
        "- `never-touches:` /home\n"
        "- `decision-budget:` none\n"
        "- `reboot-survival:` none\n"
    )
    result = coverage_gate.parse_81_block(spec_text)
    assert result["mutates"] == ["/etc/systemd/system/"]


# ── Round-trip integration: all three fragility patterns → 0 false positives ──

_ROUNDTRIP_SPEC = """\
# YT-Condenser Spec (integration test fixture — issue #24 repro)

## 1. Hard Problem
Deploy yt-condenser as a systemd service+timer pair.

## 2. First Principles
- Service units must be owned by root.
- Timer complements the service.

## 3. Algorithm Audit
- N/A.

## 4. Speed-of-Light Limit
Under 10 seconds.

## 5. Physics Guardrails
- /etc/systemd/system/ must be writable.

## 6. Steps

```yaml
- step: 1
  why: "Service unit must exist before it can be enabled."
  action: "cp /tmp/yt-condenser.service /etc/systemd/system/yt-condenser.service"
  verification: "test -f /etc/systemd/system/yt-condenser.service"

- step: 2
  why: "Timer unit must exist to schedule runs."
  action: "cp /tmp/yt-condenser.timer /etc/systemd/system/yt-condenser.timer"
  verification: "test -f /etc/systemd/system/yt-condenser.timer"
```

## 7. Success Criteria
- [ ] Service and timer installed.

## 8. Receiver Calibration

## 8.1 Hard contract (machine-enforced)

- `mutates:` yt-condenser*.{service,timer}, /etc/systemd/system/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` none
"""


def test_roundtrip_all_fragility_patterns_zero_false_positives(tmp_path):
    """Spec with h2 §8.1 + brace expansion + literal paths → 0 block findings.

    Reproduces the 39-false-positive cascade from issue #24:
    - §8.1 is written as h2 with parenthetical
    - mutates: uses brace shorthand yt-condenser*.{service,timer}
    The evaluator must resolve this to actual paths and produce 0 blocks.
    """
    spec = tmp_path / "yt-condenser.spec.md"
    spec.write_text(_ROUNDTRIP_SPEC, encoding="utf-8")

    from bin import spec_evaluator
    result = spec_evaluator.evaluate(spec, bundle_persist_dir=tmp_path)
    block_findings = [f for f in result.findings if f.severity == "block"]
    assert len(block_findings) == 0
