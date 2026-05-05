# Block-List Resources Format Spec (test fixture)

**Generated:** 2026-05-05
**Slug:** block-list-resources

## 1. Hard Problem
A step that binds port 8080 and declares its resource in block-list YAML format.

## 2. First Principles
- Port resources must be declared in the resources: field.
- Block-list format must parse equivalently to inline format.

## 3. Algorithm Audit
- **Delete:** unnecessary resource declarations
- **Simplify:** declare only the port that is actually used

## 4. Speed-of-Light Limit
Server starts in under 2 seconds.

## 5. Physics Guardrails
- Port 8080 must be free before the step runs.

## 6. Steps

```yaml
- step: 1
  why: "HTTP server must be started to serve the test request."
  action: "python3 -m http.server 8080"
  verification: "curl -sf http://127.0.0.1:8080"
  resources:
    - res-port-8080
```

## 7. Success Criteria
- [ ] HTTP server responds on port 8080.

## 8. Receiver Calibration

### 8.1 Hard contract (machine-enforced — `block` severity on violation)

- `mutates:` /tmp/
- `never-touches:` /home
- `decision-budget:` none
- `reboot-survival:` not-required

### 8.2 Human-facing notes (informational only — `info` severity, never blocks)

- `assumes:` port 8080 is free
- `runtime-flavor:` A8 (Debian 13)
