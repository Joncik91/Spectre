"""Tests for v0.8 §42 self-cycle-produces Tier 1 check in bin/spec_ast.py.

Pragma guard: assertion-style names only. One assertion per test.
Tests asserting absence/emptiness use _returns_empty/_is_none/_no_ naming.
"""
import os
import pathlib
import tempfile

from bin import spec_ast

# ── Shared spec template ──────────────────────────────────────────────────────

_SPEC_HEADER = """\
# Self-Cycle Test Spec

**Generated:** 2026-05-11
**Slug:** self-cycle-test

## 1. Hard Problem
Testing self-cycle detection in step produces.

## 2. First Principles
- A step must not consume a file it also declares as its own output.

## 3. Algorithm Audit
- **Delete:** unnecessary steps
- **Simplify:** single check
- **Accelerate:** deterministic

## 4. Speed-of-Light Limit
Under 100ms.

## 5. Physics Guardrails
- Files must exist before being referenced.

## 6. Steps

```yaml
"""

_SPEC_FOOTER = """\
```

## 7. Success Criteria
- [ ] Self-cycle detected.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /home/joncik/apps/test-spectrere/
- `never-touches:` /etc
- `decision-budget:` none
- `reboot-survival:` none

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` linux
"""


def _write_spec(steps_yaml: str) -> pathlib.Path:
    content = _SPEC_HEADER + steps_yaml + _SPEC_FOOTER
    fd, path = tempfile.mkstemp(suffix=".spec.md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return pathlib.Path(path)


# ── Case 1: self-cycle — action consumes path it also produces, no prior producer ──

_SELF_CYCLE_YAML = """\
- step: 1
  why: "Bootstrap the manifest."
  action: "python3 -m myapp.classifier download --manifest src/myapp/_manifest.toml"
  verification: "test -f src/myapp/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/_manifest.toml"
  negative-paths:
    - trigger: "download fails"
      handler: "retry once"
"""


def test_self_cycle_emits_finding():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_self_cycle_severity_is_block():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.severity == "block"
    finally:
        p.unlink(missing_ok=True)


def test_self_cycle_location_step_number_is_correct():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.location.step == 1
    finally:
        p.unlink(missing_ok=True)


def test_self_cycle_location_scope_is_step():
    p = _write_spec(_SELF_CYCLE_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.location.scope == "step"
    finally:
        p.unlink(missing_ok=True)


# ── Case 2: earlier step produces the file — no finding ─────────────────────

_EARLIER_PRODUCER_YAML = """\
- step: 1
  why: "Generate the manifest by running the scaffolding tool."
  action: "python3 -m myapp.scaffold init"
  verification: "test -f src/myapp/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/_manifest.toml"
  negative-paths:
    - trigger: "scaffold fails"
      handler: "abort"

- step: 2
  why: "Download classifier artifacts using the already-generated manifest."
  action: "python3 -m myapp.classifier download --manifest src/myapp/_manifest.toml"
  verification: "test -f state/classifier/model.onnx"
  produces:
    - "file:/home/joncik/apps/test-spectrere/state/classifier/model.onnx"
  negative-paths:
    - trigger: "download fails"
      handler: "retry once"
"""


def test_no_self_cycle_when_earlier_step_produces_the_path_returns_empty():
    p = _write_spec(_EARLIER_PRODUCER_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Case 3: action mentions path not in produces — no finding ────────────────

_PATH_NOT_IN_PRODUCES_YAML = """\
- step: 1
  why: "Read the config."
  action: "python3 -m myapp.runner --config src/myapp/config.toml"
  verification: "test -f src/myapp/config.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/output.json"
  negative-paths:
    - trigger: "run fails"
      handler: "abort"
"""


def test_no_self_cycle_when_path_not_in_produces_returns_empty():
    p = _write_spec(_PATH_NOT_IN_PRODUCES_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


# ── Case 4: multiple paths in one action, one self-cycle one legitimate ───────

_MULTI_PATH_YAML = """\
- step: 1
  why: "Seed the registry with the base model."
  action: "python3 -m myapp.seeder --manifest src/myapp/_manifest.toml --config src/myapp/config.toml"
  verification: "test -f src/myapp/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/myapp/_manifest.toml"
    - "file:/home/joncik/apps/test-spectrere/state/registry.db"
  negative-paths:
    - trigger: "seed fails"
      handler: "abort"
"""


def test_multi_path_one_self_cycle_emits_exactly_one_finding():
    p = _write_spec(_MULTI_PATH_YAML)
    try:
        fs = spec_ast.classify(p)
        cycle_findings = [f for f in fs if f.kind == "self-cycle-produces"]
        assert len(cycle_findings) == 1
    finally:
        p.unlink(missing_ok=True)


# ── Case 5: relative action path / absolute produces path (gateway repro) ────

_GATEWAY_REPRO_YAML = """\
- step: 3
  why: "Download classifier and verify digest."
  action: "python3 -m llm_routing_gateway.classifier download --target state/classifier/ --manifest src/llm_routing_gateway/classifier/_manifest.toml --verify-digest"
  verification: "test -f src/llm_routing_gateway/classifier/_manifest.toml"
  produces:
    - "file:/home/joncik/apps/test-spectrere/src/llm_routing_gateway/classifier/_manifest.toml"
  negative-paths:
    - trigger: "download fails"
      handler: "retry once then abort"
"""


def test_gateway_repro_relative_action_absolute_produces_emits_finding():
    p = _write_spec(_GATEWAY_REPRO_YAML)
    try:
        fs = spec_ast.classify(p)
        assert any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)


def test_gateway_repro_finding_references_correct_step_number():
    p = _write_spec(_GATEWAY_REPRO_YAML)
    try:
        fs = spec_ast.classify(p)
        f = next(x for x in fs if x.kind == "self-cycle-produces")
        assert f.location.step == 3
    finally:
        p.unlink(missing_ok=True)


# ── Case 6: --target is a directory, not a file — no finding ─────────────────
# --target state/classifier/ has no file suffix and is not an input-option flag,
# so it must NOT trigger self-cycle even if the produces entry is under that dir.

_DIRECTORY_TARGET_YAML = """\
- step: 1
  why: "Download model artifacts into the classifier directory."
  action: "python3 -m myapp.downloader --target state/classifier/"
  verification: "test -d state/classifier/"
  produces:
    - "file:/home/joncik/apps/test-spectrere/state/classifier/encoder.onnx"
  negative-paths:
    - trigger: "download fails"
      handler: "abort"
"""


def test_no_self_cycle_for_directory_target_returns_empty():
    p = _write_spec(_DIRECTORY_TARGET_YAML)
    try:
        fs = spec_ast.classify(p)
        assert not any(f.kind == "self-cycle-produces" for f in fs)
    finally:
        p.unlink(missing_ok=True)
