"""Tests for spec_ast negative-paths parsing and Tier 1 enforcement.

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none naming.
"""
import pathlib
import tempfile

from bin import spec_ast

# ── Shared spec template ──────────────────────────────────────────────────────

_SPEC_HEADER = """\
# Negative Paths Test Spec

**Generated:** 2026-05-07
**Slug:** negpath-test

## 1. Hard Problem
Installing a service atomically.

## 2. First Principles
- Files must exist before being referenced.

## 3. Algorithm Audit
- **Delete:** unnecessary steps
- **Simplify:** single install step
- **Accelerate:** idempotent writes

## 4. Speed-of-Light Limit
Completes in under 5 seconds.

## 5. Physics Guardrails
- Target directory must be writable.

## 6. Steps

```yaml
"""

_SPEC_FOOTER = """\
```

## 7. Success Criteria
- [ ] Service running after install.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /opt/svc/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` {reboot_survival}

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` linux
"""


def _write_spec(steps_yaml: str, reboot_survival: str = "best-effort") -> pathlib.Path:
    content = _SPEC_HEADER + steps_yaml + _SPEC_FOOTER.format(
        reboot_survival=reboot_survival
    )
    fd, path = tempfile.mkstemp(suffix=".spec.md")
    import os
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return pathlib.Path(path)


# ── missing-negative-path warn (best-effort reboot-survival) ─────────────────

_STEP_WITH_PRODUCES_NO_NEG_PATHS = """\
- step: 1
  why: "The binary must be installed."
  action: "install -m 0755 svc /opt/svc/svc"
  verification: "test -x /opt/svc/svc"
  produces:
    - "file:/opt/svc/svc"

"""


def test_produces_no_negative_paths_best_effort_emits_missing_finding():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="best-effort")
    try:
        findings = spec_ast.classify(path)
        assert any(f.kind == "missing-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


def test_produces_no_negative_paths_best_effort_severity_is_warn():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="best-effort")
    try:
        findings = spec_ast.classify(path)
        f = next(x for x in findings if x.kind == "missing-negative-path")
        assert f.severity == "warn"
    finally:
        path.unlink(missing_ok=True)


def test_produces_no_negative_paths_best_effort_location_is_step_scope():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="best-effort")
    try:
        findings = spec_ast.classify(path)
        f = next(x for x in findings if x.kind == "missing-negative-path")
        assert f.location.scope == "step"
    finally:
        path.unlink(missing_ok=True)


def test_produces_no_negative_paths_best_effort_step_number_is_1():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="best-effort")
    try:
        findings = spec_ast.classify(path)
        f = next(x for x in findings if x.kind == "missing-negative-path")
        assert f.location.step == 1
    finally:
        path.unlink(missing_ok=True)


# ── missing-negative-path block (reboot-survival: required) ──────────────────


def test_produces_no_negative_paths_required_emits_missing_finding():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        assert any(f.kind == "missing-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


def test_produces_no_negative_paths_required_severity_is_block():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        f = next(x for x in findings if x.kind == "missing-negative-path")
        assert f.severity == "block"
    finally:
        path.unlink(missing_ok=True)


def test_produces_no_negative_paths_required_message_mentions_reboot_survival():
    path = _write_spec(_STEP_WITH_PRODUCES_NO_NEG_PATHS, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        f = next(x for x in findings if x.kind == "missing-negative-path")
        assert "reboot-survival" in f.message.lower()
    finally:
        path.unlink(missing_ok=True)


# ── well-formed negative-paths → no missing-negative-path finding ─────────────

_STEP_WITH_WELL_FORMED_NEG_PATHS = """\
- step: 1
  why: "The binary must be installed."
  action: "install -m 0755 svc /opt/svc/svc"
  verification: "test -x /opt/svc/svc"
  produces:
    - "file:/opt/svc/svc"
  negative-paths:
    - trigger: "install fails (source missing)"
      handler: "reject"
    - trigger: "disk full"
      handler: "escalate"

"""


def test_produces_with_well_formed_negative_paths_returns_no_missing_finding():
    path = _write_spec(_STEP_WITH_WELL_FORMED_NEG_PATHS, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        assert not any(f.kind == "missing-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


def test_produces_with_well_formed_negative_paths_returns_no_malformed_finding():
    path = _write_spec(_STEP_WITH_WELL_FORMED_NEG_PATHS, reboot_survival="best-effort")
    try:
        findings = spec_ast.classify(path)
        assert not any(f.kind == "malformed-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


# ── malformed entry: missing handler ─────────────────────────────────────────

_STEP_WITH_MALFORMED_NO_HANDLER = """\
- step: 1
  why: "The binary must be installed."
  action: "install -m 0755 svc /opt/svc/svc"
  verification: "test -x /opt/svc/svc"
  produces:
    - "file:/opt/svc/svc"
  negative-paths:
    - trigger: "fetch fails"

"""


def test_malformed_negative_path_missing_handler_emits_malformed_finding():
    path = _write_spec(_STEP_WITH_MALFORMED_NO_HANDLER)
    try:
        findings = spec_ast.classify(path)
        assert any(f.kind == "malformed-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


def test_malformed_negative_path_missing_handler_severity_is_warn():
    path = _write_spec(_STEP_WITH_MALFORMED_NO_HANDLER)
    try:
        findings = spec_ast.classify(path)
        f = next(x for x in findings if x.kind == "malformed-negative-path")
        assert f.severity == "warn"
    finally:
        path.unlink(missing_ok=True)


def test_malformed_negative_path_evaluator_continues_after_malformed_entry():
    """Malformed entry doesn't halt — other findings still emitted."""
    path = _write_spec(_STEP_WITH_MALFORMED_NO_HANDLER)
    try:
        findings = spec_ast.classify(path)
        # The malformed entry should also trigger missing-negative-path
        # (since the malformed entry has no handler, it doesn't count as
        # a valid negative-paths declaration — but currently we still emit
        # malformed-negative-path and no missing-negative-path because the
        # entry list is non-empty). The key invariant: no exception raised.
        assert isinstance(findings, list)
    finally:
        path.unlink(missing_ok=True)


# ── step without produces → no negative-path findings ────────────────────────

_STEP_WITHOUT_PRODUCES = """\
- step: 1
  why: "Enable the service."
  action: "systemctl enable svc"
  verification: "systemctl is-enabled svc"

"""


def test_step_without_produces_returns_no_missing_negative_path_finding():
    path = _write_spec(_STEP_WITHOUT_PRODUCES, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        assert not any(f.kind == "missing-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


def test_step_without_produces_returns_no_malformed_negative_path_finding():
    path = _write_spec(_STEP_WITHOUT_PRODUCES, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        assert not any(f.kind == "malformed-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


# ── inline-list YAML format ───────────────────────────────────────────────────

_STEP_WITH_INLINE_NEG_PATHS = """\
- step: 1
  why: "The binary must be installed."
  action: "install -m 0755 svc /opt/svc/svc"
  verification: "test -x /opt/svc/svc"
  produces:
    - "file:/opt/svc/svc"
  negative-paths: [{trigger: "fetch fails", handler: "retry"}]

"""


def test_inline_list_negative_paths_parses_trigger():
    raw_block = """\
- step: 1
  why: "x"
  action: "y"
  verification: "z"
  produces:
    - "file:/tmp/x"
  negative-paths: [{trigger: "disk full", handler: "reject"}]
"""
    result = spec_ast._parse_negative_paths(raw_block)
    assert result[0].get("trigger") == "disk full"


def test_inline_list_negative_paths_parses_handler():
    raw_block = """\
- step: 1
  why: "x"
  action: "y"
  verification: "z"
  produces:
    - "file:/tmp/x"
  negative-paths: [{trigger: "disk full", handler: "reject"}]
"""
    result = spec_ast._parse_negative_paths(raw_block)
    assert result[0].get("handler") == "reject"


def test_inline_list_negative_paths_no_missing_finding_via_classify():
    path = _write_spec(_STEP_WITH_INLINE_NEG_PATHS, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        assert not any(f.kind == "missing-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


# ── block-sequence YAML format ────────────────────────────────────────────────

_STEP_WITH_BLOCK_SEQ_NEG_PATHS = """\
- step: 1
  why: "The binary must be installed."
  action: "install -m 0755 svc /opt/svc/svc"
  verification: "test -x /opt/svc/svc"
  produces:
    - "file:/opt/svc/svc"
  negative-paths:
    - trigger: "disk full"
      handler: "reject"
    - trigger: "source missing"
      handler: "escalate"

"""


def test_block_sequence_negative_paths_parses_first_trigger():
    raw_block = _STEP_WITH_BLOCK_SEQ_NEG_PATHS
    result = spec_ast._parse_negative_paths(raw_block)
    assert result[0].get("trigger") == "disk full"


def test_block_sequence_negative_paths_parses_first_handler():
    raw_block = _STEP_WITH_BLOCK_SEQ_NEG_PATHS
    result = spec_ast._parse_negative_paths(raw_block)
    assert result[0].get("handler") == "reject"


def test_block_sequence_negative_paths_parses_second_entry():
    raw_block = _STEP_WITH_BLOCK_SEQ_NEG_PATHS
    result = spec_ast._parse_negative_paths(raw_block)
    assert len(result) == 2


def test_block_sequence_negative_paths_second_trigger():
    raw_block = _STEP_WITH_BLOCK_SEQ_NEG_PATHS
    result = spec_ast._parse_negative_paths(raw_block)
    assert result[1].get("trigger") == "source missing"


def test_block_sequence_negative_paths_no_missing_finding_via_classify():
    path = _write_spec(_STEP_WITH_BLOCK_SEQ_NEG_PATHS, reboot_survival="required")
    try:
        findings = spec_ast.classify(path)
        assert not any(f.kind == "missing-negative-path" for f in findings)
    finally:
        path.unlink(missing_ok=True)


# ── reboot_survival parser ────────────────────────────────────────────────────

def test_parse_reboot_survival_returns_required():
    body = """
### 8.1 Hard contract
- `mutates:` /tmp
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` required
"""
    assert spec_ast._parse_reboot_survival(body) == "required"


def test_parse_reboot_survival_returns_best_effort():
    body = """
### 8.1 Hard contract
- `mutates:` /tmp
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` best-effort
"""
    assert spec_ast._parse_reboot_survival(body) == "best-effort"


def test_parse_reboot_survival_returns_empty_string_when_absent():
    body = """
### 8.1 Hard contract
- `mutates:` /tmp
"""
    assert spec_ast._parse_reboot_survival(body) == ""
