# Undeclared Resource Port Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** undeclared-resource-port

## 1. Hard Problem
Serving static files requires binding to a network port; port conflicts silently break the service.

## 2. First Principles
- A server must bind to an explicit port to be addressable.
- Verification must confirm the port is actually in use.

## 3. Algorithm Audit
- **Delete:** implicit port fallback
- **Simplify:** single-step serve

## 4. Speed-of-Light Limit
Server starts in under 2 seconds.

## 5. Physics Guardrails
- Port 8080 must not be in use before launch.

## 6. Steps

```yaml
- step: 1
  why: "Serving static files requires a bound port; 8080 is the agreed non-privileged port."
  action: "python3 -m http.server 8080"
  resources: []
  verification: "curl -s http://localhost:8080/ | grep -q html"
```

## 7. Success Criteria
- [ ] Server responds on port 8080.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /etc/, /root/
- `decision-budget:` none
- `reboot-survival:` not-required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` python3 installed
- `runtime-flavor:` A8 (Debian 13)
