# Never-Touches Collision Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** never-touches-collision

## 1. Hard Problem
An action touches /home/x which is in the never-touches list — this must block.

## 2. First Principles
- Paths listed in never-touches must not be written by any action.
- Verification must confirm the desired state, not the input.

## 3. Algorithm Audit
- **Delete:** unnecessary breadth of writes
- **Simplify:** write only to declared paths

## 4. Speed-of-Light Limit
Write completes in under 1 second.

## 5. Physics Guardrails
- /home must remain untouched.

## 6. Steps

```yaml
- step: 1
  why: "Config file needed for user session setup."
  action: "cp config /home/x/.config"
  verification: "test -f /home/x/.config"
```

## 7. Success Criteria
- [ ] User config present.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` not-required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` running as root
- `runtime-flavor:` A8 (Debian 13)
