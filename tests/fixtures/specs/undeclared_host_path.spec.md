# Undeclared Host Path Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** undeclared-host-path

## 1. Hard Problem
Writing a config file to /etc requires the path to be declared in the calibration contract.

## 2. First Principles
- All host-tier paths written must appear in mutates:.
- Verification must confirm the file is present post-write.

## 3. Algorithm Audit
- **Delete:** manual file copy
- **Simplify:** echo-redirect to target path

## 4. Speed-of-Light Limit
Config write completes in under 1 second.

## 5. Physics Guardrails
- /etc must be writable by root.

## 6. Steps

```yaml
- step: 1
  why: "Config file must exist before the service reads it on start."
  action: "echo '[settings]' > /etc/foo.conf"
  verification: "test -f /etc/foo.conf"
```

## 7. Success Criteria
- [ ] Config file exists at /etc/foo.conf.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` not-required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` running as root
- `runtime-flavor:` A8 (Debian 13)
