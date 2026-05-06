"""Tests for bin/spec_lint.py — Tier 1.5 spec-author lints. Stdlib only."""
import pathlib
import pytest

from bin import spec_lint
from bin import findings as _findings


# ── runuser-no-cd ──────────────────────────────────────────────────────────────


def test_runuser_no_cd_warns_when_inner_lacks_cd_and_relative_path():
    action = "runuser -l user -c 'pytest tests/'"
    fs = spec_lint.lint_action(action, step=1)
    assert any(f.kind == "runuser-no-cd" for f in fs)


def test_runuser_no_cd_passes_when_cd_present():
    action = "runuser -l user -c 'cd /home/user/proj && pytest tests/'"
    fs = spec_lint.lint_action(action, step=1)
    assert not any(f.kind == "runuser-no-cd" for f in fs)


def test_runuser_no_cd_passes_when_inner_uses_absolute_path():
    action = "runuser -l user -c 'pytest /home/user/proj/tests/'"
    fs = spec_lint.lint_action(action, step=1)
    assert not any(f.kind == "runuser-no-cd" for f in fs)


def test_runuser_no_cd_passes_when_command_is_simple_no_path():
    """Pure `runuser -l user -c 'whoami'` has no path arg, nothing to lint."""
    action = "runuser -l user -c 'whoami'"
    fs = spec_lint.lint_action(action, step=1)
    assert not any(f.kind == "runuser-no-cd" for f in fs)


def test_runuser_no_cd_finding_has_warn_severity():
    action = "runuser -l user -c 'pytest tests/'"
    fs = spec_lint.lint_action(action, step=1)
    matching = [f for f in fs if f.kind == "runuser-no-cd"]
    assert matching[0].severity == "warn"


def test_runuser_no_cd_finding_carries_step_number():
    action = "runuser -l user -c 'pytest tests/'"
    fs = spec_lint.lint_action(action, step=4)
    matching = [f for f in fs if f.kind == "runuser-no-cd"]
    assert matching[0].location.step == 4


def test_runuser_no_cd_does_not_match_unrelated_action():
    action = "mkdir -p /tmp/foo"
    fs = spec_lint.lint_action(action, step=1)
    assert not any(f.kind == "runuser-no-cd" for f in fs)


def test_runuser_with_double_quoted_inner_command():
    """`runuser -l user -c "pytest tests/"` is the same trap with double quotes."""
    action = 'runuser -l user -c "pytest tests/"'
    fs = spec_lint.lint_action(action, step=1)
    assert any(f.kind == "runuser-no-cd" for f in fs)


# ── unsafe-heredoc ─────────────────────────────────────────────────────────────


def test_unsafe_heredoc_info_when_heredoc_lacks_set_e():
    action = "cat > /tmp/foo.sh <<EOF\necho hi\nrm bar\nEOF"
    fs = spec_lint.lint_action(action, step=1)
    assert any(f.kind == "unsafe-heredoc" for f in fs)


def test_unsafe_heredoc_passes_when_set_e_present():
    action = "cat > /tmp/foo.sh <<EOF\nset -euo pipefail\necho hi\nEOF"
    fs = spec_lint.lint_action(action, step=1)
    assert not any(f.kind == "unsafe-heredoc" for f in fs)


def test_unsafe_heredoc_passes_when_no_heredoc_present():
    action = "echo hi > /tmp/foo"
    fs = spec_lint.lint_action(action, step=1)
    assert not any(f.kind == "unsafe-heredoc" for f in fs)


def test_unsafe_heredoc_finding_has_info_severity():
    action = "cat > /tmp/foo.sh <<EOF\necho hi\nEOF"
    fs = spec_lint.lint_action(action, step=1)
    matching = [f for f in fs if f.kind == "unsafe-heredoc"]
    assert matching[0].severity == "info"


# ── lint_spec entry point ──────────────────────────────────────────────────────


def test_lint_spec_returns_list_of_findings(tmp_path):
    body = (
        "# Test\n"
        "**Generated:** 2026-05-06\n"
        "**Slug:** lint-test\n\n"
        "## 1. Hard Problem\nProbe.\n\n"
        "## 2. First Principles\n- only stdlib\n\n"
        "## 6. Steps\n\n"
        "```yaml\n"
        '- step: 1\n'
        '  why: "lint trigger"\n'
        '  action: "runuser -l user -c \'pytest tests/\'"\n'
        '  verification: "echo ok"\n'
        "```\n\n"
        "## 8. Receiver Calibration\n### 8.1 Hard contract\n"
        "- mutates: []\n- never-touches: [/etc, /usr]\n"
        "- decision-budget: 0 paid calls\n- reboot-survival: stateless\n"
    )
    spec_path = tmp_path / "lint.spec.md"
    spec_path.write_text(body, encoding="utf-8")
    fs = spec_lint.lint_spec(spec_path)
    assert isinstance(fs, list)


def test_lint_spec_emits_runuser_finding_for_step_1(tmp_path):
    body = (
        "# Test\n"
        "**Generated:** 2026-05-06\n"
        "**Slug:** lint-test\n\n"
        "## 1. Hard Problem\nProbe.\n\n"
        "## 2. First Principles\n- only stdlib\n\n"
        "## 6. Steps\n\n"
        "```yaml\n"
        '- step: 1\n'
        '  why: "lint trigger"\n'
        '  action: "runuser -l user -c \'pytest tests/\'"\n'
        '  verification: "echo ok"\n'
        "```\n\n"
        "## 8. Receiver Calibration\n### 8.1 Hard contract\n"
        "- mutates: []\n- never-touches: [/etc, /usr]\n"
        "- decision-budget: 0 paid calls\n- reboot-survival: stateless\n"
    )
    spec_path = tmp_path / "lint.spec.md"
    spec_path.write_text(body, encoding="utf-8")
    fs = spec_lint.lint_spec(spec_path)
    runuser_findings = [f for f in fs if f.kind == "runuser-no-cd"]
    assert any(f.location.step == 1 for f in runuser_findings)
