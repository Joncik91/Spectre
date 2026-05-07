---
name: implement
description: State-aware spec executor — read the active spec, run the next step's action, gate on its verification, retry once on fail, advance the scratchpad. Halts on any unrecoverable failure with full negative knowledge.
disable-model-invocation: false
---

# Skill: /implement [check | auto] [<track>]

Triggered when the user types `/implement` (run next step), `/implement check` (verify current state without executing), or `/implement auto` (walk consecutive low-tier steps without re-prompting until a halt-worthy step). This is the **physical-build engine** of Spectre — it owns the action→verification→retry→advance cycle.

## §6.0 Environment policy (v0.5.2+)

Spectre owns the Python virtual environment. **Specs must not declare PEP 668 strategy** (system Python, venv path, `--break-system-packages`, `pipx`, etc.) — that is the executor's responsibility, not the spec author's.

At the start of every `/implement` session the runner calls `ensure_venv` (see `bin/managed_venv.py`) which creates `state/.venv/` under the user's project root (mode 0700) on first use and is idempotent on subsequent calls. The resulting interpreter path is persisted to `state/scratchpad.json` as a top-level `venv_python` field so future sessions reuse it without re-running the venv check.

Every step's `action:` and `verification:` strings are passed through `normalize_action` before execution. This rewrites bare `python`, `python3`, `pip`, and `pip3` tokens to use the venv interpreter — top-level shell tokens only (shlex-parsed), so absolute paths, heredoc blocks, and nested quoted strings are left untouched. If `ensure_venv` fails for any reason (missing `python3-venv`, out of disk, etc.), the skill **HALTs** with a clear error — it never falls back to system Python.

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

### Step 0.7 — Tier 0 handoff integrity check (v0.6+)

Before reading the spec or executing any step, validate the handoff envelope:

```bash
python3 -m bin.handoff_validator check --project-path .
```

Stdout: one finding per line (e.g. `envelope-missing: pre-v0.6 spec, continuing`) or `ENVELOPE OK` when the envelope is present and valid. Exit code: `0` on OK or warn-only findings, `1` on block-severity violations.

Behavior:
- **`envelope-missing:`** (warn, exit 0) — pre-v0.6 locked spec; print the warning and continue. Re-run `/vision` to upgrade.
- **`envelope-tampered:`** (block, exit 1) — spec/sidecar/contracts modified after lock. HALT. Tell the user to re-run `/vision`.
- **`no active spec`** (block, exit 1) — HALT. Tell the user to run `/vision` first.
- **schema violation** (block, exit 1) — HALT. The envelope file itself is malformed.

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

### Step 1.5 — Environment setup (v0.5.2+)

After reading the active spec (Step 1) and before classifying the action (Step 3.5), ensure the executor-owned venv exists and normalize the step's invocations.

**Once per `/implement` session** (skip if `venv_python` is already set in the scratchpad for this session):

```bash
python3 -m bin.managed_venv ensure \
    --project-path . \
    --scratchpad state/scratchpad.json
```

Stdout: `VENV_PYTHON: <absolute-path>`. The CLI creates `state/.venv/` (mode 0700) on first call, is idempotent on subsequent calls, and writes the interpreter path to `state/scratchpad.json["tracks"][<track>]["venv_python"]` via atomic write.

If this command exits non-zero → **HALT immediately** with its stderr. Do not fall back to system Python.

**On every step**, rewrite the step's `action:` and `verification:` strings through `normalize_action` **before** tier classification (Step 3.5) and before execution. The result is the `normalized_action` used for all subsequent steps. Use the `normalize` subcommand:

```bash
python3 -m bin.managed_venv normalize \
    --action "<step action verbatim>" \
    --venv-python "<venv_python from scratchpad>"
```

The rewritten string (stdout) is what gets executed and verified. Original spec text is unchanged.

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

Classify `normalized_action` (the post-rewrite string from Step 1.5 — not the raw spec text) by tier before executing. Run:

```bash
python3 -m bin.tier evaluate-action \
    --action "<normalized_action verbatim>" \
    --spec "specs/<active spec name>.spec.md"
```

Substitute the normalized action text for `<normalized_action>` and the actual spec filename for `<active spec name>`. The CLI wraps the §3.5 orchestration in a single call: it invokes `tier.classify`, reads §8.1 locked paths from the spec via `coverage_gate.parse_81_block` (the canonical permissive parser — handles both `- mutates: /etc/` and `- `mutates:` /etc/` syntax), then runs `tier.should_halt` and emits the §3.5 prose-format output. Pass `--json` instead to get a structured payload (`{"tier","reasons","never_autonomous","halt","spec_locked_paths"}`).

Stdout (no `--json`):
- `TIER: <silent|repo|host|network>` — exactly one line.
- `  reason: <reason text>` — one line per classifier reason.
- `NEVER_AUTONOMOUS: <label>` — present only when an intent-based override matched.
- `HALT: true` / `HALT: false` — exactly one line.

Exit codes: `0` success (parse stdout for the answer), `1` runtime error, `2` argparse error. Missing `--spec` or a missing spec file is **not** an error — locked paths default to empty.

`bin/tier.py` is the **single source of truth** for halt-vs-execute. Never substitute your own judgment about whether something is "safe enough" — if `HALT: true`, halt. The v0.4.1 `should_halt` semantics consult `~/.spectre/personal-rules.toml` and respect §8.1 spec-locked paths (personal rules cannot override halts whose reason references a locked path).

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
python3 -m bin.observations record-halt \
    --action "<current_action>" \
    --label "<the first reason from the classifier output>" \
    --spec-slug "<active spec slug from .active>"
```

Stdout: `OBSERVED: <fp[:12]>...`. The CLI computes the SHA-256 fingerprint, appends a JSONL record to `~/.spectre/observations.jsonl`, and best-effort writes a CDLC ledger `halt` transition to `<cwd>/state/cdlc-ledger.json` (ledger-write errors are swallowed — observation persistence is the load-bearing write). The fingerprint is what personal-rules.toml keys against. Future runs with the same fingerprint may skip the halt automatically (per v0.4.1 personal-rules consultation in `tier.should_halt`).

**Append to CDLC ledger (v0.4.2+).** Every TIER GATE halt — regardless of yes/halt/skip — also records a `halt` transition in `state/cdlc-ledger.json` with the user's answer captured:

```bash
python3 -m bin.cdlc_ledger append --kind halt \
    --payload-kv "fingerprint=<fp from observation block>" \
    --payload-kv "label=<label>" \
    --payload-kv "action=<current_action>" \
    --payload-kv "user_answer=<yes|halt|skip>"
```

Stdout: `APPENDED: kind=halt`. The CLI exits non-zero on JSON-corruption / disk-full / unwritable-state errors; capture stderr but DO NOT propagate the failure to the user. **Ledger write is non-blocking.** A failure here does not abort the skill — the user-answer dispatch and the pending_adoption_prompt persistence below MUST still run. Note that `record-halt` above already best-effort-wrote a smaller ledger entry (no `user_answer`, no `label`) inside `observations.record_halt`; this dedicated CLI call is the structural place to record the user's answer post-prompt.

- `yes` → continue to Step 3.6 then 3.7 then Step 4 (execute). After §6 Path A succeeds, run §Step 3.5b (post-halt-success prompt).
- `halt` → stop. No scratchpad change.
- `skip` → advance `step` by 1 (no execution, no verification). Use only when the step was already done out-of-band; rare.

**Persist pending_adoption_prompt for §3.5b durability (v0.4.2+).**

```bash
python3 -m bin._scratchpad set-pending-adoption \
    --scratchpad state/scratchpad.json \
    --track "<active track from invocation, default 'default'>" \
    --fingerprint "<fp from §3.5 observation block>" \
    --label "<label from §3.5 observation block>" \
    --action "<current_action>"
```

Stdout: `PENDING_ADOPTION_PROMPT_PERSISTED: <fp[:12]>...`. The CLI atomic-writes via `_scratchpad.atomic_write`, auto-promotes a v1 scratchpad to v2 if needed, and stamps `recorded_at` with the current UTC ISO timestamp inside the function (so the heredoc's `__import__("datetime")` fragility is gone). This survives session restart and any mid-execution compact between §3.5 and §6 Path A. §3.5b reads and clears the field.

### Step 3.5b — Post-halt-success prompt (v0.4.1+; v0.4.2 durability hardening)

After §6 Path A (verification passes) completes successfully, READ `pending_adoption_prompt` from `state/scratchpad.json` for the active track. If `None`, skip §3.5b entirely — no halt was queued. If present, fire the prompt using the persisted structured fields (fingerprint, label, action). The field is read once and CLEARED immediately after the prompt runs (regardless of adopt/once-only/never-ask-again). This survives compact/restart since scratchpad.json is durable across sessions.

```bash
python3 -m bin._scratchpad get-pending-adoption \
    --scratchpad state/scratchpad.json \
    --track "<active track from invocation, default 'default'>"
```

Stdout (one of): `NO_PENDING_PROMPT` (skip §3.5b entirely) or `PROMPT: fp=<fp[:12]>... label=<label>`. For the full structured prompt (action, recorded_at), pass `--json` and parse the result; `null` means no prompt is pending.

**Clear pending_adoption_prompt FIRST (v0.4.2+).** As soon as §3.5b reads the field successfully and BEFORE running the adopt/once-only/never-ask-again branches, clear the field unconditionally:

```bash
python3 -m bin._scratchpad clear-pending-adoption \
    --scratchpad state/scratchpad.json \
    --track "<active track from invocation, default 'default'>"
```

Stdout: `PROMPT_CLEARED` (track existed and was cleared) or `NO_TRACK_TO_CLEAR` (track absent — no-op). Clearing FIRST means: if the user's chosen branch (adopt) raises an exception during `personal_rules.adopt` (e.g. permissions error on ~/.spectre/personal-rules.toml), the field is already cleared. The user sees the adopt-write error and can fix their config, but next /implement will not re-prompt for the same already-handled halt. Loss-of-clear was the v0.4.1 failure mode the durability hardening was meant to prevent — clearing first preserves that property.

The rest of §3.5b (the adopt / once-only / never-ask-again branches + sandbox-paradox brake from v0.4.1) is unchanged.

After §6 Path A completes successfully — i.e. the action ran AND verification confirmed it worked — emit:

```
The TIER GATE halted you on this action class. Adopt as personal-rule-skip going forward?
   adopt          — write to ~/.spectre/personal-rules.toml; future runs of this fingerprint will not halt.
   once-only      — no rule written. Same trigger halts again next time.
   never-ask-again — write a "user-declined" placeholder; this fingerprint never re-prompts (but still halts at TIER GATE).
```

If `adopt`: run

```bash
python3 -m bin.personal_rules adopt \
    --label "<label>" \
    --fingerprint "<fp>" \
    --reason "<one-line user reason>" \
    --scratchpad state/scratchpad.json \
    --track "<active track, default 'default'>"
```

Stdout (one of): `ADOPTED. (N/3 this session)` (TOML written, persistent counter bumped) or `BRAKE: <N> adoptions this session. Edit ~/.spectre/personal-rules.toml to review or remove. Skipping prompt.` (the brake — TOML untouched, counter not bumped). The CLI consults the persistent counter at `tracks.<track>.session_adoption_count` BEFORE writing — same disk-backed counter as `personal_rules.adoption_count_this_session_persistent()`, which is the only counter that survives across `python3 -m` invocations.

If `once-only`: do nothing — the halt fires again on the next run.

If `never-ask-again`: in v0.4.1, treat as `once-only` (the placeholder schema lands in v0.4.2). Print "Note: never-ask-again is v0.4.2; treating as once-only."

**Sandbox-paradox brake.** The CLI consults the persistent counter via `personal_rules.adoption_count_this_session_persistent()` against `personal_rules.DEFAULT_BRAKE_THRESHOLD` (default 3) BEFORE writing the TOML; if the counter is already at threshold, the CLI prints the BRAKE message and exits 0 without bumping anything. The brake is session-scoped via `state/scratchpad.json`'s `tracks.<track>.session_adoption_count` field — restarting Claude Code (or starting a new spec/track) resets it on the next `/vision`. The threshold is read dynamically from `DEFAULT_BRAKE_THRESHOLD` rather than hardcoded so v0.4.2 schema bumps stay backward-compatible.

**Why the brake exists.** Per `research/developing-a-safe.md` (vault), HITL approval gates create permission-fatigue: users rage-bypass safety once prompts feel persistent. The 3-adoption cap forces the user to re-read their personal-rules file rather than reflexively saying yes to everything.

### Step 3.6 — Resource lock acquire

If `current_resources` is non-empty, acquire each Resource via the supervisor before executing. Run:

```bash
python3 -m bin.track acquire \
    --track "<current track>" \
    --resources "<comma-joined current_resources, e.g. port:8080,db:postgres>"
```

Stdout: one `ACQUIRED: <rid>` line per granted lock, or `QUEUED: <rid> (position N)` followed by exit code 1 on the first queued resource. The CLI ensures the supervisor is running (idempotent — reuses an existing live process) and acquires resources in the listed order. A non-zero exit means the skill must halt with the RESOURCE QUEUED message below.

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
python3 -m bin.auditor audit-and-clear \
    --action "<current_action>" \
    --scratchpad state/scratchpad.json \
    --track "<current_track>"
```

If the active spec's current step declares a `properties:` YAML block, pass it as a JSON array via `--properties '[{"kind":"type","target":"out.json","expected":"dict"}, ...]'`. Otherwise omit the flag.

The CLI wraps the full §5.5 orchestration in a single atomic call: load `state/scratchpad.json` via `_scratchpad.load`, read `paths_touched` for the track via `_scratchpad.get_paths_touched` (handles both v1 top-level and v2 `tracks.<track>.paths_touched` schemas — a silent v2-schema bypass was the bug class behind the v0.4.2.6 fix), run `auditor.audit_action`, persist `last_audit_kinds` / `last_audit_passed` / `last_audit_failures` back to the track, and atomic-write the scratchpad via `_scratchpad.atomic_write` (no raw `json.dump` — corruption-safe under interrupt). Other tracks in the scratchpad are preserved.

Stdout:
- `AUDIT: N checks, passed=<True|False>` — exactly one summary line.
- `  FAIL: <kind> — <message>` — one line per failed check (omitted if all passed).

Pass `--json` instead to get the same `{"kinds","passed","failures"}` summary as a JSON object. Exit codes: `0` success (parse stdout), `1` runtime error (scratchpad load/write failure), `2` argparse error. A missing scratchpad is **not** an error — `_scratchpad.load` returns the v1 default and the auditor runs against an empty `paths_touched` list.

If audits fail repeatedly across multiple steps in the same spec, halt and tell the user the spec needs `properties:` declarations or the actions are creating malformed artifacts. Otherwise, the failures sit in scratchpad and surface in the next compact's `additionalContext` for human review.

### Step 6 — Branch on verification result

**Path A — verification exits 0:**
- Print: `VERIFICATION PASSED: Step <N>.`
- Update scratchpad: increment `step` by 1, clear any retry state.

**Append CDLC ledger transition (v0.4.2+).** Record an `implement` transition for this successful step:

```bash
python3 -m bin.cdlc_ledger append --kind implement \
    --payload-kv "step=<step number that just succeeded — the pre-increment value, i.e. current_step from §1>" \
    --payload-kv "spec_slug=<active spec slug from .active>" \
    --payload-kv "action=<current_action>"
```

Stdout: `APPENDED: kind=implement`. The CLI writes to `state/cdlc-ledger.json` under cwd; failure here does NOT roll back the step increment (see "Why the ledger fires AFTER the increment" below).

**Why the ledger fires AFTER the increment.** The increment must be durable before any audit write — if the ledger write fails (disk full), we'd rather have the step advanced (so the user re-runs and sees the action already succeeded) than not advanced (replaying a successful action). Ledger writes are advisory; step advancement is load-bearing.

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
python3 -m bin.track release \
    --track "<current track>" \
    --resources "<comma-joined current_resources>"
```

Stdout: `RELEASED: <rid>` per resource. The CLI is idempotent — releasing a resource the track does not own is a no-op on the supervisor side. Do NOT call this on retry-mid-flight (Path B retry pending) — the track still owns the lock. Only release on terminal step state (advance OR halt).

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
python3 -m bin.adr write \
    --dir decisions \
    --title "<title>" \
    --body "<body with finding>"
```

Stdout: `ADR: decisions/<NNNN>-<slug>.md`. The slug is auto-derived from the title via `adr.slugify()`; no need to pass it separately.

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
