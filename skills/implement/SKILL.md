---
name: implement
description: State-aware spec executor — read the active spec, run the next step's action, gate on its verification, retry once on fail, advance the scratchpad. Halts on any unrecoverable failure with full negative knowledge.
disable-model-invocation: false
---

# Skill: /implement [check | auto] [<track>]

Triggered when the user types `/implement` (run next step), `/implement check` (verify current state without executing), or `/implement auto` (walk consecutive low-tier steps without re-prompting until a halt-worthy step). This is the **physical-build engine** of Spectre — it owns the action→verification→retry→advance cycle.

## §6.0 Environment policy

Spectre owns the Python virtual environment. **Specs must not declare PEP 668 strategy** (system Python, venv path, `--break-system-packages`, `pipx`, etc.) — that is the executor's responsibility, not the spec author's.

At the start of every `/implement` session the runner calls `ensure_venv` (see `bin/managed_venv.py`) which creates `state/.venv/` under the user's project root (mode 0700) on first use and is idempotent on subsequent calls. The resulting interpreter path is persisted to `state/scratchpad.json` as a top-level `venv_python` field so future sessions reuse it without re-running the venv check.

Every step's `action:` and `verification:` strings are passed through `normalize_action` before execution. This rewrites bare `python`, `python3`, `pip`, and `pip3` tokens to use the venv interpreter — top-level shell tokens only (shlex-parsed), so absolute paths, heredoc blocks, and nested quoted strings are left untouched. If `ensure_venv` fails for any reason (missing `python3-venv`, out of disk, etc.), the skill **HALTs** with a clear error — it never falls back to system Python.

## Hard rules (read every invocation)

- **All paths are user-project-cwd-relative.** Read `specs/.active` and `state/scratchpad.json` from the user's `pwd`, never from the plugin install dir (`${CLAUDE_PLUGIN_ROOT}` or `~/.claude/plugins/...`). If `pwd` looks like a plugin cache, HALT and tell the user to restart from their project directory.
- **Verification is the gate, not the action.** A non-zero `action:` exit is a failure; a zero-exit `action:` followed by a non-zero `verification:` is **also** a failure. Both halt or retry per Option B.
- **One step per invocation, except in auto mode.** Plain `/implement` runs exactly one step. `/implement auto` chains consecutive steps that classify as `silent` or `repo` tier with no never-autonomous match, no resource-lock contention, no verification failure, and no drift trigger. The first step that fails any of those conditions halts auto mode and reverts to per-step.
- **One retry, then halt.** Option B retry policy (see Retry phase below).
- **Hard halt on missing-binary errors.** `command not found`, `No such file or directory` for the binary itself → halt without retry.
- **Never edit the spec from `/implement`.** If the spec is wrong, halt and tell the user to re-run `/vision`.
- **Pre-flight check before executing Step N.** Run Step N-1's verification first if scratchpad says it passed; halt with a "Root-State Desync" message if it now fails.

## Protocol

### Phase: Mode routing

Parse the args. Recognized invocations:

  - `/implement` — run exactly one step.
  - `/implement check` — verify current state (no execution, no advance).
  - `/implement auto` — walk consecutive low-tier steps without re-prompting.
  - `/implement <track>` / `/implement auto <track>` / `/implement check <track>` — same, scoped to a named track.

In `auto` mode, the runner repeats the Track through Drift phases in a loop until any of the following triggers a halt:

  - Tier classifier returns `host` or `network`.
  - Tier classifier returns a `NEVER_AUTONOMOUS` label.
  - Resource-lock acquisition is queued (not granted on first try).
  - Verification fails (Path B retry is per-step interactive — auto mode hands control back at the prompt).
  - Drift checkpoint detects drift.
  - Spec is complete (`current_step > total_steps`).

When auto mode halts, print one line summarizing what triggered the halt, then proceed exactly as plain `/implement` would for that step. The user's next `/implement` can re-enter auto mode by passing `auto` again. Auto is opt-in — never the default.

### Phase: Track

`/implement` accepts an optional `<track>` argument. `/implement` (no arg) targets the `default` track. `/implement <track>` targets the named track; if the track does not yet exist in the v2 scratchpad's `tracks:` map, it is created with `track_default()` shape on first save.

Read the active spec from the **per-track** scratchpad: `state/scratchpad.json["tracks"][<track>]["active_spec"]`. If absent for that track, halt:

```
ERROR: track <name> has no active spec. Run /vision <track> first.
```

For backward compat: a v1 scratchpad is auto-migrated to v2 by the SessionStart hydrator. Plain `/implement` on the migrated `default` track works without further changes.

### Phase: Tier 0 envelope

Before reading the spec or executing any step, validate the handoff envelope:

```bash
spectre handoff_validator check --project-path .
```

Stdout: `RESULT envelope.check status=ok` when valid, or `WARN envelope.check status=missing detail=...` / `HALT envelope.check status=tampered detail=...` for violations. Exit code: `0` on OK or warn-only findings, `1` on block-severity violations.

Behavior:
- **`status=missing`** (warn, exit 0) — pre-v0.6 locked spec; print the warning and continue. Re-run `/vision` to upgrade.
- **`status=tampered`** (block, exit 1) — spec/sidecar/contracts modified after lock. HALT. Tell the user to re-run `/vision`.
- **`no active spec`** (block, exit 1) — HALT. Tell the user to run `/vision` first.
- **schema violation** (block, exit 1) — HALT. The envelope file itself is malformed.

### Phase: Context read

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

### Phase: Environment

After reading the active spec and before classifying the action, ensure the executor-owned venv exists and normalize the step's invocations.

**Once per `/implement` session** (skip if `venv_python` is already set in the scratchpad for this session):

```bash
spectre managed_venv ensure \
    --project-path . \
    --scratchpad state/scratchpad.json
```

Stdout: `OK venv.ensure python=<absolute-path>`. The CLI creates `state/.venv/` (mode 0700) on first call, is idempotent on subsequent calls, and writes the interpreter path to `state/scratchpad.json["tracks"][<track>]["venv_python"]` via atomic write.

If this command exits non-zero → **HALT immediately** with its stderr. Do not fall back to system Python.

**On every step**, rewrite the step's `action:` and `verification:` strings through `normalize_action` **before** tier classification and before execution:

```bash
spectre managed_venv normalize \
    --action "<step action verbatim>" \
    --venv-python "<venv_python from scratchpad>"
```

The rewritten string (stdout) is what gets executed and verified. Original spec text is unchanged.

### Phase: Pre-flight

If `current_step > 1` and `scratchpad.exit_code == 0`:
- Run `prev_verification`.
- If it now fails, halt with:
  ```
  ROOT-STATE DESYNC: Step <N-1> verification no longer passes.
  Reason: <stderr>
  Action: investigate manually, then re-run /implement when state is restored.
  ```

### Phase: Check mode

If the user invoked `/implement check`:
- Run `current_verification` (NOT the action).
- Print pass/fail + the verification command's output.
- Do NOT advance `step`. Do NOT modify scratchpad except for `last_command`/`exit_code`.
- Halt.

### Phase: Tier classifier

Classify `normalized_action` (the post-rewrite string from the Environment phase — not the raw spec text) by tier before executing. Run:

```bash
spectre tier evaluate-action \
    --action "<normalized_action verbatim>" \
    --spec "specs/<active spec name>.spec.md"
```

The CLI wraps the tier orchestration in a single call: it invokes `tier.classify`, reads §8.1 locked paths from the spec via `coverage_gate.parse_81_block`, then runs `tier.should_halt` and emits the output. Pass `--json` instead to get a structured payload (`{"tier","reasons","never_autonomous","halt","spec_locked_paths"}`).

Stdout (no `--json`):
- `RESULT tier.classify tier=<silent|repo|host|network>` — exactly one line.
- `RESULT tier.gate halt=<true|false>` — exactly one line.
- `RESULT tier.classify never_autonomous=<label>` — present only when an intent-based override matched.

Exit codes: `0` success (parse stdout for the answer), `1` runtime error, `2` argparse error. Missing `--spec` or a missing spec file is **not** an error — locked paths default to empty.

`bin/tier.py` is the **single source of truth** for halt-vs-execute. Never substitute your own judgment about whether something is "safe enough" — if `halt=true`, halt. The `should_halt` semantics consult `~/.spectre/personal-rules.toml` and respect §8.1 spec-locked paths (personal rules cannot override halts whose reason references a locked path).

Interpret the output:

- `tier=silent` and no `never_autonomous=` → continue to Resource acquire silently.
- `tier=repo` and no `never_autonomous=` → continue to Resource acquire silently.
- `tier=host`, `tier=network`, OR any `never_autonomous=` → halt with:

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
spectre observations record-halt \
    --action "<current_action>" \
    --label "<the first reason from the classifier output>" \
    --spec-slug "<active spec slug from .active>"
```

Stdout: `OK observation.record fingerprint=<fp[:12]>...`. The CLI computes the SHA-256 fingerprint, appends a JSONL record to `~/.spectre/observations.jsonl`, and best-effort writes a CDLC ledger `halt` transition to `<cwd>/state/cdlc-ledger.json`. The fingerprint is what personal-rules.toml keys against.

**Append to CDLC ledger.** Every TIER GATE halt — regardless of yes/halt/skip — also records a `halt` transition:

```bash
spectre cdlc_ledger append --kind halt \
    --payload-kv "fingerprint=<fp from observation block>" \
    --payload-kv "label=<label>" \
    --payload-kv "action=<current_action>" \
    --payload-kv "user_answer=<yes|halt|skip>"
```

The CLI exits non-zero on JSON-corruption / disk-full / unwritable-state errors; capture stderr but DO NOT propagate the failure to the user. **Ledger write is non-blocking.**

- `yes` → continue to Resource acquire then Execute. After Path A succeeds, run the Post-halt-success prompt.
- `halt` → stop. No scratchpad change.
- `skip` → advance `step` by 1 (no execution, no verification). Use only when the step was already done out-of-band; rare.

**Persist pending_adoption_prompt for durability.**

```bash
spectre _scratchpad set-pending-adoption \
    --scratchpad state/scratchpad.json \
    --track "<active track from invocation, default 'default'>" \
    --fingerprint "<fp from tier classifier observation block>" \
    --label "<label from tier classifier observation block>" \
    --action "<current_action>"
```

Stdout: `OK scratchpad.pending_adoption_set fingerprint=<fp[:12]>...`. The CLI atomic-writes via `_scratchpad.atomic_write`, auto-promotes a v1 scratchpad to v2 if needed, and stamps `recorded_at`. This survives session restart and any mid-execution compact.

**Post-halt-success prompt.** After Path A (verification passes) completes successfully, READ `pending_adoption_prompt` from `state/scratchpad.json` for the active track. If `None`, skip this prompt entirely — no halt was queued. If present, fire the prompt using the persisted structured fields.

```bash
spectre _scratchpad get-pending-adoption \
    --scratchpad state/scratchpad.json \
    --track "<active track from invocation, default 'default'>"
```

Stdout (one of): `OK scratchpad.no_pending_prompt` (skip prompt entirely) or `RESULT scratchpad.pending_prompt fingerprint=<fp[:12]> label=<label>`. For the full structured prompt (action, recorded_at), pass `--json` and parse the result; `null` means no prompt is pending.

**Clear pending_adoption_prompt FIRST.** As soon as the prompt is read successfully and BEFORE running the adopt/once-only/never-ask-again branches, clear the field unconditionally:

```bash
spectre _scratchpad clear-pending-adoption \
    --scratchpad state/scratchpad.json \
    --track "<active track from invocation, default 'default'>"
```

Stdout: `OK scratchpad.prompt_cleared` (track existed and was cleared) or `OK scratchpad.no_track_to_clear` (track absent — no-op). Clearing FIRST means: if the `adopt` branch raises an exception during `personal_rules.adopt`, the field is already cleared. The user sees the adopt-write error and can fix their config, but next /implement will not re-prompt for the same halt.

After Path A completes successfully, emit:

```
The TIER GATE halted you on this action class. Adopt as personal-rule-skip going forward?
   adopt          — write to ~/.spectre/personal-rules.toml; future runs of this fingerprint will not halt.
   once-only      — no rule written. Same trigger halts again next time.
   never-ask-again — write a "user-declined" placeholder; this fingerprint never re-prompts (but still halts at TIER GATE).
```

If `adopt`: run

```bash
spectre personal_rules adopt \
    --label "<label>" \
    --fingerprint "<fp>" \
    --reason "<one-line user reason>" \
    --scratchpad state/scratchpad.json \
    --track "<active track, default 'default'>"
```

Stdout (one of): `OK personal_rules.adopt session_count=N max=3` (TOML written, persistent counter bumped) or `HALT personal_rules.brake session_count=N max=3 remediation=~/.spectre/personal-rules.toml` (the brake — TOML untouched, counter not bumped). The CLI consults the persistent counter at `tracks.<track>.session_adoption_count` BEFORE writing.

If `once-only`: do nothing — the halt fires again on the next run.

If `never-ask-again`: treat as `once-only` for now. Print "Note: never-ask-again is pending; treating as once-only."

**Sandbox-paradox brake.** The CLI consults the persistent counter against `DEFAULT_BRAKE_THRESHOLD` (default 3) BEFORE writing the TOML; if the counter is already at threshold, the CLI prints the BRAKE message and exits 0 without bumping anything. The brake is session-scoped via `state/scratchpad.json`'s `tracks.<track>.session_adoption_count` field — restarting Claude Code (or starting a new spec/track) resets it on the next `/vision`. The threshold is read dynamically from `DEFAULT_BRAKE_THRESHOLD` rather than hardcoded.

**v1.0 — `satisfies:` step field.** v1.0 specs may declare an optional `satisfies:` array on individual steps (e.g. `satisfies: [human-user-help-text, operator-log-format]`) naming which view contracts the step's output is meant to fulfill. When present, Tier-3 (if enabled) will inject the bound exemplar's conventions into its contradiction prompt for that step — this is mechanical; no skill action is required beyond preserving the field on round-trip. The Tier-3 prompt extension fires automatically from `bin/llm_judge._build_exemplar_context` when the spec's frontmatter declares `**Spec-version:** 1.0` and the view binds an exemplar. The tier classifier itself does NOT route differently based on `satisfies:` — view-specific routing is deferred to v1.1 once dogfooding reveals how view-bound implementations fail.

### Phase: Resource acquire

If `current_resources` is non-empty, acquire each Resource via the supervisor before executing. Run:

```bash
spectre track acquire \
    --track "<current track>" \
    --resources "<comma-joined current_resources, e.g. port:8080,db:postgres>"
```

Stdout: one `OK track.acquire resource=<rid>` line per granted lock, or `HALT track.queue resource=<rid> position=N` followed by exit code 1 on the first queued resource. A non-zero exit means the skill must halt with the RESOURCE QUEUED message below.

If any Resource is queued (not granted) → halt with:

```
RESOURCE QUEUED Step <N>: <track> waiting on <resource_id>
Position: <queued_position>
Action: another track holds this. Wait, then re-run /implement <track>.
```

### Phase: Reasoning emit

Print the step's `why:` line BEFORE the action so it lands in conversation context AND in the next compact's `additionalContext`:

```
WHY: <why text from spec>
```

If the spec step is missing `why:`, halt with `HALT: Step <N> has no why: field. Re-run /vision to add it.` — do not fabricate a justification.

### Phase: Execute

Print the action and run it via Bash:

```
EXECUTING Step <N>: <action>
```

The PostToolUse(Bash) hook will compact the result into Delta+Anchor automatically. Do not summarize stdout/stderr yourself.

### Phase: Verify

Immediately after the action returns, run `current_verification` via Bash:

```
VERIFYING Step <N>: <verification>
```

**State Auditor (informational).** After verification passes but before the step advances, run the State Auditor for structural sanity. The auditor is **informational on first pass — it does NOT block step advance**:

```bash
spectre auditor audit-and-clear \
    --action "<current_action>" \
    --scratchpad state/scratchpad.json \
    --track "<current_track>"
```

If the active spec's current step declares a `properties:` YAML block, pass it as a JSON array via `--properties '[{"kind":"type","target":"out.json","expected":"dict"}, ...]'`. Otherwise omit the flag.

Stdout: `RESULT audit.summary checks=N passed=<true|false>`. Plus `WARN audit.fail kind=... message=...` per failed check. Pass `--json` instead to get `{"kinds","passed","failures"}` as a JSON object.

### Phase: Branch on verification

**Path A — verification exits 0:**
- Print: `VERIFICATION PASSED: Step <N>.`
- Update scratchpad: increment `step` by 1, clear any retry state.

**Append CDLC ledger transition.** Record an `implement` transition for this successful step:

```bash
spectre cdlc_ledger append --kind implement \
    --payload-kv "step=<step number that just succeeded — the pre-increment value>" \
    --payload-kv "spec_slug=<active spec slug from .active>" \
    --payload-kv "action=<current_action>"
```

Failure here does NOT roll back the step increment — the step is the durable state.

- Run the Drift phase.
- Print: `Ready for next /implement.`
- Halt (do not auto-run Step N+1).

**Path B — verification exits non-zero (Option B retry):**
- This is the agent's ONE allowed retry.
- Read the verification's stderr.
- Diagnose: write a 1-line `diagnosis` to scratchpad explaining what likely went wrong.
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

### Phase: Drift

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

### Phase: Resource release

If `current_resources` is non-empty AND verification passed (Path A) OR the step halted permanently (no further retries possible), release every Resource the step acquired:

```bash
spectre track release \
    --track "<current track>" \
    --resources "<comma-joined current_resources>"
```

Stdout: `OK track.release resource=<rid>` per resource. The CLI is idempotent — releasing a resource the track does not own is a no-op on the supervisor side. Do NOT call this on retry-mid-flight (Path B retry pending) — the track still owns the lock. Only release on terminal step state (advance OR halt).

### Phase: Failure log

Whether the failure halts or retries, the `compact.py` hook already appends to `failed_hypotheses[]`. The `/implement` skill doesn't write to scratchpad directly except to advance `step` on success or store `diagnosis` on retry.

### Phase: Finding capture

Triggered when **Path B retry succeeded** — verification failed on the first run, the agent diagnosed and proposed a corrected action, the user said `yes`, and verification passed on the corrected action. This signal pattern reliably identifies "the spec author didn't anticipate something about the runtime environment."

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
spectre adr write \
    --dir decisions \
    --title "<title>" \
    --body "<body with finding>"
```

Stdout: `OK adr.write path=decisions/<NNNN>-<slug>.md`. The slug is auto-derived from the title via `adr.slugify()`; no need to pass it separately.

Skip this phase entirely on `silent`/`repo`-tier steps that pass on first try — those have no signal worth capturing.

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
