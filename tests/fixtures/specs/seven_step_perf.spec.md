# Seven Step Performance Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** seven-step-perf

## 1. Hard Problem
Installing a multi-component service requires seven ordered steps; partial completion leaves the host broken.

## 2. First Principles
- Each step must be individually verifiable.
- Steps must be ordered by dependency.

## 3. Algorithm Audit
- **Delete:** redundant intermediate state checks
- **Simplify:** linear dependency chain

## 4. Speed-of-Light Limit
Full install completes in under 30 seconds.

## 5. Physics Guardrails
- /opt/myapp/ must exist before binary install.
- /etc/myapp/ must exist before config write.

## 6. Steps

```yaml
- step: 1
  why: "Binary must exist before the service unit can reference it."
  action: "install -m 0755 myapp /opt/myapp/myapp"
  verification: "test -x /opt/myapp/myapp"

- step: 2
  why: "Config directory must exist before config file write."
  action: "mkdir -p /etc/myapp"
  verification: "test -d /etc/myapp"

- step: 3
  why: "Config file must exist before service reads it."
  action: "cp myapp.conf /etc/myapp/myapp.conf"
  verification: "test -f /etc/myapp/myapp.conf"

- step: 4
  why: "Service unit must exist before systemd can manage it."
  action: "cp myapp.service /etc/systemd/system/myapp.service"
  verification: "test -f /etc/systemd/system/myapp.service"

- step: 5
  why: "Daemon-reload required for systemd to see the new unit."
  action: "systemctl daemon-reload"
  verification: "systemctl cat myapp.service | grep -q Description"

- step: 6
  why: "Service must be enabled for reboot-survival."
  action: "systemctl enable myapp.service"
  verification: "systemctl is-enabled myapp.service"

- step: 7
  why: "Service must be started for immediate effect."
  action: "systemctl start myapp.service"
  verification: "systemctl is-active myapp.service"
```

## 7. Success Criteria
- [ ] myapp binary installed and executable.
- [ ] Config file present.
- [ ] Service active and enabled.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /opt/myapp/, /etc/myapp/, /etc/systemd/system/
- `never-touches:` /home, /etc/passwd, /etc/shadow
- `decision-budget:` none
- `reboot-survival:` required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` knows-systemd, knows-linux-filesystem
- `runtime-flavor:` A8 (Debian 13)
