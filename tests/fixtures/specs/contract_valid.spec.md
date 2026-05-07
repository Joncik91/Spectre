# Contract Valid Spec (test fixture)

**Generated:** 2026-05-07
**Slug:** contract-valid

## 1. Hard Problem
A two-step install where step 2 explicitly depends on an artifact step 1 produces.

## 2. First Principles
- A package must be installed before it can be imported.
- Explicit contracts make inter-step dependencies machine-verifiable.

## 3. Algorithm Audit
- **Delete:** none
- **Simplify:** two-step dependency modelled as file produces/requires
- **Accelerate:** contract resolution is O(n) over steps

## 4. Speed-of-Light Limit
Install completes in under 5 seconds.

## 5. Physics Guardrails
- `/tmp/contract-valid/` must be writable.

## 6. Steps

```yaml
- step: 1
  why: "Install the package so it is importable in step 2."
  action: "pip install foo --target /tmp/contract-valid/"
  verification: "python3 -c 'import foo'"
  produces:
    - "package:foo"
    - "file:/tmp/contract-valid/foo/__init__.py"

- step: 2
  why: "Register the console script after the package is importable."
  action: "pip install foo[cli] --target /tmp/contract-valid/"
  verification: "foo-cli --version"
  requires:
    - "package:foo"
  produces:
    - "console-script:foo-cli"
```

## 7. Success Criteria
- [ ] package foo importable
- [ ] console-script foo-cli in PATH

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/contract-valid/
- `never-touches:` /home, /etc
- `decision-budget:` none
- `reboot-survival:` none
