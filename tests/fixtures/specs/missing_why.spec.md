# Missing Why Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** missing-why

## 1. Hard Problem
Installing a small service requires writing to three locations atomically; partial writes leave the host in an inconsistent state.

## 2. First Principles
- Systemd service units must be owned by root and world-readable.
- Service activation requires daemon-reload before enable/start.
- Verification must probe the live post-action state, not the input.

## 3. Algorithm Audit
- **Delete:** manual package manager calls (use apt-get only where needed)
- **Simplify:** three write locations collapse to one install step
- **Accelerate:** daemon-reload is idempotent; safe to call repeatedly

## 4. Speed-of-Light Limit
Install completes in under 5 seconds on a warmed package cache.

## 5. Physics Guardrails
- `/opt/hello/` must exist before the service file is written.
- systemd unit directory `/etc/systemd/system/` must be writable by root.

## 6. Steps

```yaml
- step: 1
  why: "The binary must exist on-disk before the service unit can reference it."
  action: "install -m 0755 hello /opt/hello/hello"
  verification: "test -x /opt/hello/hello"

- step: 2
  action: "cp hello.service /etc/systemd/system/hello.service && systemctl daemon-reload"
  verification: "systemctl cat hello.service | grep -q /opt/hello/hello"

- step: 3
  why: "Service must be enabled for reboot-survival and started for immediate effect."
  action: "systemctl enable --now hello.service"
  verification: "systemctl is-active hello.service"
```

## 7. Success Criteria
- [ ] Binary installed at `/opt/hello/hello` and executable.
- [ ] Service active and enabled after each reboot.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /opt/hello/, /etc/systemd/system/
- `never-touches:` /home, /etc/passwd, /etc/shadow
- `decision-budget:` none
- `reboot-survival:` required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` knows-systemd, knows-linux-filesystem
- `runtime-flavor:` A8 (Debian 13, Ryzen 7 8745HS)
- `expected-author-skill:` senior backend engineer
