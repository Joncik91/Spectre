# Decision With ADR Ref Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** decision-with-adr-ref

## 1. Hard Problem
Installing a service requires choosing between systemd and supervisord.

## 2. First Principles
- decision: use systemd over supervisord for service management
- Systemd is native to the target OS; supervisord adds a dep.

## 3. Algorithm Audit
- **Delete:** supervisord config
- **Simplify:** one service manager

## 4. Speed-of-Light Limit
Service activates in under 3 seconds.

## 5. Physics Guardrails
- systemd must be running as PID 1.

## 6. Steps

```yaml
- step: 1
  why: "Service file must exist before systemctl can manage it."
  action: "cp hello.service /etc/systemd/system/hello.service"
  verification: "test -f /etc/systemd/system/hello.service"

- step: 2
  why: "Daemon-reload required for systemd to see the new unit."
  action: "systemctl daemon-reload"
  verification: "systemctl cat hello.service | grep -q Description"
```

## 7. Success Criteria
- [ ] Service manageable via systemctl.

`adr-ref:` 0042-pick-x

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /etc/systemd/system/
- `never-touches:` /home, /etc/passwd
- `decision-budget:` none
- `reboot-survival:` required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` knows-systemd
- `runtime-flavor:` A8 (Debian 13)
