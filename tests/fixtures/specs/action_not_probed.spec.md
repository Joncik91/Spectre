# Action Not Probed Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** action-not-probed

## 1. Hard Problem
Writing a config file but verifying an unrelated condition means the write is not actually confirmed.

## 2. First Principles
- Verification must probe the post-action state, not a proxy.
- File writes must be confirmed by checking the file itself.

## 3. Algorithm Audit
- **Delete:** redundant proxy checks
- **Simplify:** direct file existence check suffices
- **Accelerate:** file checks are sub-millisecond

## 4. Speed-of-Light Limit
Config write completes in under 100ms.

## 5. Physics Guardrails
- `/tmp/` is writable by all users.

## 6. Steps

```yaml
- step: 1
  why: "Write the config file to the expected path before the service reads it."
  action: "echo 'key=value' > /tmp/foo/config.conf"
  verification: "test -d /tmp"

- step: 2
  why: "Confirm the service directory exists before writing the unit file."
  action: "mkdir -p /opt/myservice"
  verification: "test -d /opt/myservice"
```

## 7. Success Criteria
- [ ] Config file written at `/tmp/foo/config.conf`.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/foo/, /opt/myservice/
- `never-touches:` /home, /etc/passwd
- `decision-budget:` none
- `reboot-survival:` none

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` knows-linux-filesystem
- `runtime-flavor:` A8 (Debian 13, Ryzen 7 8745HS)
