---
name: implement
description: State-aware spec executor — read the active spec, run the next step's action, gate on its verification, retry once on fail, advance the scratchpad. Halts on any unrecoverable failure with full negative knowledge.
disable-model-invocation: false
---

# Skill: /implement [check | auto] [<track>]

Triggered when the user types `/implement` (run next step), `/implement check` (verify current state without executing), or `/implement auto` (walk consecutive low-tier steps without re-prompting until a halt-worthy step). This is the **physical-build engine** of the SDL Vision Engine — it owns the action→verification→retry→advance cycle.

## Hard rules (read every invocation)

- **All paths are user-project-cwd-relative.** Read `specs/.active` and `state/scratchpad.json` from the user's `pwd`, never from the plugin install dir (`${CLAUDE_PLUGIN_ROOT}` or `~/.claude/plugins/...`). If `pwd` looks like a plugin cache, HALT and tell the user to restart from their project directory.
- **Verification is the gate, not the action.** A non-zero `action:` exit is a failure; a zero-exit `action:` followed by a non-zero `verification:` is **also** a failure. Both halt or retry per Option B.
- **One step per invocation, except in auto mode.** Plain `/implement` runs exactly one step. `/implement auto` chains consecutive steps that classify as `silent` or `repo` tier with no never-autonomous match, no resource-lock contention, no verification failure, and no drift trigger. The first step that fails any of those conditions halts auto mode and reverts to per-step.
- **One retry, then halt.** Option B retry policy (see §Retry below).
- **Hard halt on missing-binary errors.** `command not found`, `No such file or directory` for the binary itself → halt without retry.
- **Never edit the spec from `/implement`.** If the spec is wrong, halt and tell the user to re-run `/vision`.
- **Pre-flight check before executing Step N.** Run Step N-1's verification first if scratchpad says it passed; halt with a "Root-State Desync" message if it now fails.

## Protocol

### Step 0 — Mode routing (v0.3.1+)

Parse the args. Recognized invocations:

  - `/implement` — run exactly one step.
  - `/implement check` — verify current state (no execution, no advance).
  - `/implement auto` — walk consecutive low-tier steps without re-prompting.
  - `/implement <track>` / `/implement auto <track>` / `/implement check <track>` — same, scoped to a named track.

In `auto` mode, the runner repeats Steps 2–7.5 in a loop until any of the following triggers a halt:

  - Tier classifier returns `host` or `network`.
  - Tier classifier returns a `NEVER_AUTONOMOUS` label.
  - Resource-lock acquisition is queued (not granted on first try).
  - Verification fails (Path B retry is per-step interactive — auto mode hands control back at the prompt).
  - Drift checkpoint at §6.5 detects drift.
  - Spec is complete (`current_step > total_steps`).

When auto mode halts, print one line summarizing what triggered the halt, then proceed exactly as plain `/implement` would for that step (e.g., emit the `TIER GATE` prompt). The user's next `/implement` can re-enter auto mode by passing `auto` again. Auto is opt-in — never the default — so the human-veto right at risky steps is preserved.

### Step 0.5 — Track selection

`/implement` accepts an optional `<track>` argument. `/implement` (no arg) targets the `default` track. `/implement <track>` targets the named track; if the track does not yet exist in the v2 scratchpad's `tracks:` map, it is created with `track_default()` shape on first save.

Read the active spec from the **per-track** scratchpad: `state/scratchpad.json["tracks"][<track>]["active_spec"]`. If absent for that track, halt:

```
ERROR: track <name> has no active spec. Run /vision <track> first.
```

For backward compat: a v1 scratchpad is auto-migrated to v2 by the SessionStart hydrator. Plain `/implement` on the migrated `default` track works without further changes.

### Step 1 — Read context

```bash
cat specs/.active   # → relative path to active spec
cat state/scratchpad.json   # → step, exit_code, failed_hypotheses (look under tracks.<track>)
```

If `.active` is missing or stale → halt: `ERROR: no active spec. Run /vision first.`

Parse the active spec's `## 6. Steps` YAML block. Identify:
- `total_steps` = highest `step:` number in the YAML
- `current_step` = `scratchpad.tracks.<track>.step`
- `current_action` = the `action:` value at that step
- `current_verification` = the `verification:` value at that step
- `current_resources` = the optional `resources:` list at that step (default `[]`)
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
import sys, pathlib, re
sys.path.insert(0, ".")
from bin import tier

current_action = """<current_action verbatim>"""
t, reasons, na = tier.classify(current_action)

# Read the active spec's §8.1 hard contract to populate spec_locked_paths.
# Format: lines beginning with "- mutates:" or "- never-touches:" inside §8.1.
spec_locked_paths = set()
active_spec_path = pathlib.Path("specs") / "<active spec name>.spec.md"
if active_spec_path.is_file():
    text = active_spec_path.read_text(encoding="utf-8")
    in_8_1 = False
    for line in text.splitlines():
        if line.strip().startswith("### 8.1"):
            in_8_1 = True
            continue
        if in_8_1 and line.startswith("##"):
            break
        if in_8_1:
            m = re.match(r"^\s*-\s*(?:mutates|never-touches):\s*(.+)$", line)
            if m:
                # Comma-separated paths; strip whitespace
                for p in m.group(1).split(","):
                    p = p.strip().strip("`").strip()
                    if p and p != "[]":
                        spec_locked_paths.add(p)

halt = tier.should_halt(
    t,
    na,
    action=current_action,
    reasons=reasons,
    spec_locked_paths=frozenset(spec_locked_paths),
)
print(f"TIER: {t}")
for r in reasons:
    print(f"  reason: {r}")
if na:
    print(f"NEVER_AUTONOMOUS: {na}")
print(f"HALT: {halt}")
PY
```

Substitute the literal action text for `<current_action>` and the actual spec filename for `<active spec name>`. The classifier is in `bin/tier.py` and is the **single source of truth** for halt-vs-execute. Never substitute your own judgment about whether something is "safe enough" — if the classifier says halt, halt. The v0.4.1 `should_halt` signature consults `~/.spectre/personal-rules.toml` and respects §8.1 spec-locked paths (rules cannot override halts whose reason references a locked path).

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

**Record observation BEFORE accepting input:** every TIER GATE halt — regardless of the user's answer — produces a fingerprint and an observation row. Run:

```bash
python3 - <<'PY'
import sys, pathlib
sys.path.insert(0, ".")
from bin import observations

label = "<the first reason from the classifier output>"
action = """<current_action>"""
fp = observations.fingerprint_halt(action=action, classifier_label=label)
observations.record_halt(
    kind="tier-gate",
    fingerprint=fp,
    project_path=str(pathlib.Path.cwd()),
    spec_slug="<active spec slug from .active>",
    action=action,
    classifier_label=label,
)
print(f"OBSERVED: {fp[:12]}...")
PY
```

The fingerprint is what personal-rules.toml keys against. Future runs with the same fingerprint may skip the halt automatically (per v0.4.1 personal-rules consultation in `tier.should_halt`).

- `yes` → continue to Step 3.6 then 3.7 then Step 4 (execute). After §6 Path A succeeds, run §Step 3.5b (post-halt-success prompt).
- `halt` → stop. No scratchpad change.
- `skip` → advance `step` by 1 (no execution, no verification). Use only when the step was already done out-of-band; rare.

### Step 3.5b — Post-halt-success prompt (v0.4.1+)

If §3.5 fired a TIER GATE halt AND the user replied `yes`, schedule a **deferred prompt** to run AFTER §6 Path A (verification passes). If §3.5 didn't halt, or the user said `halt` / `skip`, this step does nothing.

After §6 Path A completes successfully — i.e. the action ran AND verification confirmed it worked — emit:

```
The TIER GATE halted you on this action class. Adopt as personal-rule-skip going forward?
   adopt          — write to ~/.spectre/personal-rules.toml; future runs of this fingerprint will not halt.
   once-only      — no rule written. Same trigger halts again next time.
   never-ask-again — write a "user-declined" placeholder; this fingerprint never re-prompts (but still halts at TIER GATE).
```

If `adopt`: run

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import personal_rules

if personal_rules.adoption_count_this_session() >= personal_rules.DEFAULT_BRAKE_THRESHOLD:
    print("BRAKE: 3 adoptions this session. Edit ~/.spectre/personal-rules.toml to review or remove. Skipping prompt.")
    sys.exit(0)

personal_rules.append_adoption(
    classifier_label="<label>",
    fingerprint="<fp>",
    reason="<one-line user reason>",
)
print(f"ADOPTED. ({personal_rules.adoption_count_this_session()}/3 this session)")
PY
```

If `once-only`: do nothing — the halt fires again on the next run.

If `never-ask-again`: in v0.4.1, treat as `once-only` (the placeholder schema lands in v0.4.2). Print "Note: never-ask-again is v0.4.2; treating as once-only."

**Sandbox-paradox brake.** If `personal_rules.adoption_count_this_session()` already ≥ `personal_rules.DEFAULT_BRAKE_THRESHOLD` (default 3), the skill MUST skip the prompt entirely and print: "BRAKE: 3 adoptions this session. Edit ~/.spectre/personal-rules.toml to review or remove." The brake is session-scoped — restarting Claude Code resets it. Read the threshold dynamically from `personal_rules.DEFAULT_BRAKE_THRESHOLD` rather than hardcoding 3, so v0.4.2 schema bumps stay backward-compatible.

**Why the brake exists.** Per `research/developing-a-safe.md` (vault), HITL approval gates create permission-fatigue: users rage-bypass safety once prompts feel persistent. The 3-adoption cap forces the user to re-read their personal-rules file rather than reflexively saying yes to everything.

### Step 3.6 — Resource lock acquire

If `current_resources` is non-empty, acquire each Resource via the supervisor before executing. Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from pathlib import Path
from bin import track
track.ensure_supervisor_running(Path("."))
for rid in [<list from current_resources>]:
    resp = track.acquire(Path("."), track_name="<current track>", resource_id=rid)
    if not resp["granted"]:
        print(f"QUEUED: {rid} (position {resp['queued_position']})")
        sys.exit(1)
    print(f"ACQUIRED: {rid}")
PY
```

If any Resource is queued (not granted) → halt with:

```
RESOURCE QUEUED Step <N>: <track> waiting on <resource_id>
Position: <queued_position>
Action: another track holds this. Wait, then re-run /implement <track>.
```

The supervisor will grant the lock when the holding track releases. The track must re-invoke `/implement <track>` — the supervisor does NOT auto-resume. Resume is the human's call.

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

### Step 6.7 — Resource lock release

If `current_resources` is non-empty AND verification passed (Path A) OR the step halted permanently (no further retries possible), release every Resource the step acquired:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from pathlib import Path
from bin import track
for rid in [<list from current_resources>]:
    track.release(Path("."), track_name="<current track>", resource_id=rid)
PY
```

Do NOT release on retry-mid-flight (Path B retry pending) — the track still owns the lock. Only release on terminal step state (advance OR halt).

### Step 7 — Failure logging

Whether the failure halts or retries, the `compact.py` hook already appends to `failed_hypotheses[]`. The `/implement` skill doesn't write to scratchpad directly except to advance `step` on success or store `diagnosis` on retry.

### Step 7.5 — Spectre-finding capture (v0.3.1+)

Triggered when **Path B retry succeeded** — verification failed on the first run, the agent diagnosed and proposed a corrected action, the user said `yes`, and verification passed on the corrected action. This signal pattern reliably identifies "the spec author didn't anticipate something about the runtime environment" — the spec said one thing, reality demanded another, and the fix was an invocation tweak rather than a logic change. That's almost always a Spectre-itself finding (classifier gap, skill-prose gap, environment quirk), not a project-architecture choice.

Prompt:

```
FINDING: <one-line summary of what the corrected action revealed>
Detected: verification-fail-recover
Category? (project / spectre)
  - project → decisions/<NNNN>-<slug>.md in the active project
  - spectre → gh issue comment 1 --repo Joncik91/Spectre with auto-drafted body
```

Default category is `spectre` because the trigger is an invocation correction, not a design choice.

On `spectre`:

```bash
gh issue comment 1 --repo Joncik91/Spectre --body "$(cat <<EOF
## Finding from /implement (auto-captured)

**Spec:** <slug>
**Step:** <N>
**Original action:** <action from spec>
**Corrected action:** <agent's diagnosis-driven retry>
**Diagnosis:** <one-line>

Captured from a real /implement run where Path B retry succeeded — i.e. the
spec author's invocation didn't account for the runtime quirk surfaced here.
EOF
)"
```

If `gh` is unavailable or the command fails, write the draft to `decisions/<NNNN>-DRAFT-<slug>.md` with a `# DRAFT: TO-BE-FILED-UPSTREAM` header banner, AND append a record to scratchpad's `pending_findings: []` queue so the user can file later. Never lose a finding to a network/auth blip.

On `project`:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from bin import adr
adr.write_adr(slug="<slug>", title="<title>", body="<body with finding>")
PY
```

Skip Step 7.5 entirely on `silent`/`repo`-tier steps that pass on first try — those have no signal worth capturing.

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
