---
name: implement
description: State-aware spec executor — read the active spec, run the next step's action, gate on its verification, retry once on fail, advance the scratchpad. Halts on any unrecoverable failure with full negative knowledge.
disable-model-invocation: false
---

# Skill: /implement [check]

Triggered when the user types `/implement` (run next step) or `/implement check` (verify current state without executing). This is the **physical-build engine** of the SDL Vision Engine — it owns the action→verification→retry→advance cycle.

## Hard rules (read every invocation)

- **All paths are user-project-cwd-relative.** Read `specs/.active` and `state/scratchpad.json` from the user's `pwd`, never from the plugin install dir (`${CLAUDE_PLUGIN_ROOT}` or `~/.claude/plugins/...`). If `pwd` looks like a plugin cache, HALT and tell the user to restart from their project directory.
- **Verification is the gate, not the action.** A non-zero `action:` exit is a failure; a zero-exit `action:` followed by a non-zero `verification:` is **also** a failure. Both halt or retry per Option B.
- **One step per invocation.** Never auto-chain `step N → N+1 → ...`. The user runs `/implement` once per step. This is the human's pause point.
- **One retry, then halt.** Option B retry policy (see §Retry below).
- **Hard halt on missing-binary errors.** `command not found`, `No such file or directory` for the binary itself → halt without retry.
- **Never edit the spec from `/implement`.** If the spec is wrong, halt and tell the user to re-run `/vision`.
- **Pre-flight check before executing Step N.** Run Step N-1's verification first if scratchpad says it passed; halt with a "Root-State Desync" message if it now fails.

## Protocol

### Step 1 — Read context

```bash
cat specs/.active   # → relative path to active spec
cat state/scratchpad.json   # → step, exit_code, failed_hypotheses
```

If `.active` is missing or stale → halt: `ERROR: no active spec. Run /vision first.`

Parse the active spec's `## 6. Steps` YAML block. Identify:
- `total_steps` = highest `step:` number in the YAML
- `current_step` = `scratchpad.step`
- `current_action` = the `action:` value at that step
- `current_verification` = the `verification:` value at that step
- `prev_verification` = the `verification:` from step `current_step - 1` (if any)

**Terminal state check:** if `current_step > total_steps`, halt:
```
SPEC COMPLETE: specs/<slug>.spec.md (all <N> steps verified).
To start a new mission, run /vision.
```
Do not execute anything further; do not modify the scratchpad.

### Step 2 — Pre-flight: re-verify previous step

If `current_step > 1` and `scratchpad.exit_code == 0`:
- Run `prev_verification`.
- If it now fails, halt with:
  ```
  ROOT-STATE DESYNC: Step <N-1> verification no longer passes.
  Reason: <stderr>
  Action: investigate manually, then re-run /implement when state is restored.
  ```

### Step 3 — Branch: `/implement check`

If the user invoked `/implement check`:
- Run `current_verification` (NOT the action).
- Print pass/fail + the verification command's output.
- Do NOT advance `step`. Do NOT modify scratchpad except for `last_command`/`exit_code`.
- Halt.

### Step 3.5 — Persistence-Tier classifier

Classify `current_action` by tier before executing. Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import tier
t, reasons, na = tier.classify("""<current_action>""")
halt = tier.should_halt(t, na)
print(f"TIER: {t}")
for r in reasons:
    print(f"  reason: {r}")
if na:
    print(f"NEVER_AUTONOMOUS: {na}")
print(f"HALT: {halt}")
PY
```

Substitute the literal action text for `<current_action>`. The classifier is in `bin/tier.py` and is the **single source of truth** for halt-vs-execute. Never substitute your own judgment about whether something is "safe enough" — if the classifier says halt, halt.

Interpret the output:

- `TIER: silent` and no `NEVER_AUTONOMOUS:` line → continue to Step 3.7 silently.
- `TIER: repo` and no `NEVER_AUTONOMOUS:` line → continue to Step 3.7 silently.
- `TIER: host`, `TIER: network`, OR any `NEVER_AUTONOMOUS:` line → halt with:

```
TIER GATE Step <N>: <action>
Tier: <silent|repo|host|network>
Reasons:
  - <reason 1>
  - <reason 2>
Never autonomous: <label if any, else "n/a">
Reasoning: <one-line first-principles "why this halts — what state changes irreversibly or beyond the repo">
Proceed? (yes / halt / skip)
```

- `yes` → continue to Step 3.7 then Step 4 (execute).
- `halt` → stop. No scratchpad change.
- `skip` → advance `step` by 1 (no execution, no verification). Use only when the step was already done out-of-band; rare.

### Step 3.7 — Reasoning-in-Public WHY emit

Print the step's `why:` line BEFORE the action so it lands in conversation context AND in the next compact's `additionalContext`:

```
WHY: <why text from spec>
```

If the spec step is missing `why:`, halt with `HALT: Step <N> has no why: field. Re-run /vision to add it.` — do not fabricate a justification.

### Step 4 — Execute action

Print the action and run it via Bash:

```
EXECUTING Step <N>: <action>
```

The PostToolUse(Bash) hook will compact the result into Delta+Anchor automatically. Do not summarize stdout/stderr yourself.

### Step 5 — Verification gate

Immediately after the action returns, run `current_verification` via Bash:

```
VERIFYING Step <N>: <verification>
```

### Step 5.5 — State Auditor (informational)

After verification passes but before the step advances, run the State Auditor for structural sanity. The auditor is **informational on first pass — it does NOT block step advance**. Its job is to surface structural drift across many steps; the spec's own verification is the gate.

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, ".")
from bin import auditor

with open("state/scratchpad.json") as f:
    sp = json.load(f)
paths = sp.get("paths_touched", [])
# If the active spec's current step has a `properties:` YAML block, populate
# `properties` with that list of dicts before invoking. Otherwise leave None.
properties = None
results = auditor.audit_action("<current_action>", paths_touched=paths, properties=properties)
out = {
    "kinds": [r.kind for r in results],
    "passed": all(r.passed for r in results),
    "failures": [{"kind": r.kind, "message": r.message} for r in results if not r.passed],
}
sp["last_audit_kinds"] = out["kinds"]
sp["last_audit_passed"] = out["passed"]
sp["last_audit_failures"] = out["failures"]
with open("state/scratchpad.json", "w") as f:
    json.dump(sp, f, indent=2)
print(f"AUDIT: {len(results)} checks, passed={out['passed']}")
for f in out["failures"]:
    print(f"  FAIL: {f['kind']} — {f['message']}")
PY
```

If audits fail repeatedly across multiple steps in the same spec, halt and tell the user the spec needs `properties:` declarations or the actions are creating malformed artifacts. Otherwise, the failures sit in scratchpad and surface in the next compact's `additionalContext` for human review.

### Step 6 — Branch on verification result

**Path A — verification exits 0:**
- Print: `VERIFICATION PASSED: Step <N>.`
- Update scratchpad: increment `step` by 1, clear any retry state.
- Run §Step 6.5 Drift checkpoint.
- Print: `Ready for next /implement.`
- Halt (do not auto-run Step N+1).

**Path B — verification exits non-zero (Option B retry):**
- This is the agent's ONE allowed retry.
- Read the verification's stderr.
- Diagnose: write a 1-line `diagnosis` to scratchpad explaining what likely went wrong (e.g. `"symlink target wrong: /var/log/messages does not exist on Debian, should be /var/log/syslog"`).
- Propose a corrected `action` (NOT a corrected verification — the spec's verification is canonical).
- Print:
  ```
  VERIFICATION FAILED: Step <N>.
  Diagnosis: <one line>
  Retry action: <proposed corrected command>
  Run? (yes / halt)
  ```
- Wait for user. If `yes`, run the corrected action, then re-run the original verification.
  - If verification now passes → Path A.
  - If verification still fails → halt (no second retry):
    ```
    HALT: Step <N> verification failed twice. See state/scratchpad.json failed_hypotheses[].
    ```
- If `halt`, halt.

**Hard halt without retry — when:**
- The action's stderr matches `command not found`, `No such file or directory: '<binary>'`, `Permission denied` for the binary itself.
- The verification command itself errors out structurally (unparseable, missing).
- Any spec field is missing for the current step.

### Step 6.5 — Drift checkpoint

After advancing `step`, check if a drift audit is due:

- Read `last_drift_check_step` from scratchpad (default 0).
- Let `new_step = scratchpad.step` (after the increment in Path A).
- If `(new_step - last_drift_check_step) >= 5` AND `new_step <= total_steps`:

  1. Re-read the spec's `## 1. Hard Problem` section verbatim.
  2. Read the `action:` and `why:` for steps `new_step .. min(new_step + 4, total_steps)`.
  3. Self-audit silently: "Do these remaining actions still serve the Hard Problem? Articulate one reason yes and one reason no."
  4. If you can articulate any plausible "no" — e.g. the actions have drifted into a different subsystem, scope expanded, the Hard Problem is no longer being addressed — halt with:
     ```
     DRIFT DETECTED at Step <N>.
     Hard Problem: <quoted from spec>
     Concern: <one-line — what drifted, in first-principles terms>
     Options: (continue / edit-spec)
     ```
     - `continue` → update `last_drift_check_step` to `new_step`. Do NOT modify the spec.
     - `edit-spec` → halt. Tell the user to re-run `/vision` with current scratchpad context so the new spec inherits accumulated state.
  5. If clean (no drift) → silently update `last_drift_check_step` to `new_step` and proceed.

- If less than 5 steps since last check → no audit, no scratchpad write to `last_drift_check_step`.

### Step 7 — Failure logging

Whether the failure halts or retries, the `compact.py` hook already appends to `failed_hypotheses[]`. The `/implement` skill doesn't write to scratchpad directly except to advance `step` on success or store `diagnosis` on retry.

## Output contract

On success:
```
EXECUTING Step <N>: <action>
VERIFYING Step <N>: <verification>
VERIFICATION PASSED: Step <N>.
Ready for next /implement.
```

On `/implement check`:
```
CHECK Step <N>: <verification>
RESULT: PASS | FAIL — <stderr if fail>
```

On halt:
```
HALT: <reason>
<actionable next step for the user>
```

## Why this shape

The action-verification split forces **intellectual honesty**: the spec author commits, in writing, to what "this step worked" means before any code runs. The agent cannot retroactively redefine success. Option B retry catches typos and missing-flag mistakes (one bounded chance to self-correct) without thrashing on real bugs. The pre-flight re-verification of step N-1 catches "user manually deleted a file" desyncs before they snowball.
