---
name: vision
description: Unified inception — distill a vague vision into a First-Principles spec with action/verification steps, then lock it as the active spec.
disable-model-invocation: false
---

# Skill: /vision <user_vision>

Triggered when the user types `/vision` followed by free-form text describing what they want built. Follow this protocol **exactly** — it is the only legitimate path from human intent to locked spec.

## Hard rules (read every invocation)

- **All paths are user-project-cwd-relative.** Spec, scratchpad, and `.active` live under the user's current working directory at session start (e.g. `/home/foo/myproject/specs/...`), NEVER under the plugin's install path (`~/.claude/plugins/...` or `${CLAUDE_PLUGIN_ROOT}`). If you find yourself about to write into a plugin cache directory, STOP — that is a bug. Resolve cwd via `pwd` once at the start of the Lock phase and use absolute paths from there.
- **One spec at a time.** Never write two `.active` files.
- **Step number is user-driven.** This skill resets `step` to 1; nothing else here writes to it.
- **No hedging, no "best practices," no industry preambles.** First-principles content only.
- **Never silently lock a spec.** If the user has not confirmed the draft, do not write the file or flip `.active`.
- **Refuse physically impossible visions.** Run a Feasibility Audit before drafting. If the request violates known physics, math, or logic, halt and explain — do not produce a spec.

## Protocol

### Phase: Fingerprint (silent, internal)

Before treating the user's text as a Spark, run the fingerprinter to surface prior art in the user's codebase:

```bash
python3 bin/fingerprint.py 2>&1 | tail -5
```

This writes `state/local-symbols.json`. Read the first 50 entries:

```bash
python3 -c "import json; d=json.load(open('state/local-symbols.json')); print(json.dumps(d[:50], indent=2))"
```

When the walker surfaces concerns in the Walker loop phase, scan the symbol map for any function/class/module conceptually related to the user's intent (e.g. intent says "fetch BTC price" → search for `fetch`, `price`, `http`, `bitcoin`, `btc`, `requests`). If you find a candidate, surface it via a `branch-resolution` concern: "We will NOT reinvent `<symbol_name>` at `<file>:<line>` — reuse it as the basis for step N." The "never reinvent the wheel" rule is enforced by construction here. Skipping this phase violates the rule silently.

**Template-import surfacing.** Also list any reusable spec/skill templates the user has previously exported:

```bash
spectre templates list --limit 10
```

Stdout: `RESULT templates.list count=N items=spec:name,...`. Pass `--json` for the full descriptor list when you need the absolute path.

If templates exist, surface them as candidate starting points during the Walker loop's interrogation walk: "Your library has `<template_name>` (a `<kind>`). Import as a base for this spec? (import / no)". On `import`, call `templates.import_template(source_name=<name>, target_name=<slug>)`; the imported draft becomes the seed for the walk's draft materialization in the Draft phase.

### Phase: Wizard

Before §1 distillation, fire the substrate wizard to populate §8.2 (cognitive-substrate contract). Answers are cached at `~/.spectre/substrate-cache/<author-spec-hash>.json`; re-running /vision on an unchanged spec body skips re-prompting (cache hit exits 0 immediately, flags are ignored unless `--force` is passed).

**Step 1 — compute the author-spec hash** (over the draft body MINUS any existing §8.2 block):

```bash
AUTHOR_SPEC_HASH="$(printf %s "$DRAFT_BODY_NO_82" | sha256sum | awk '{print $1}')"
```

**Step 2 — ask the user the 4 questions** (via the conversation, not via a TTY):

Ask the user these four questions and capture their answers as shell variables:

1. **Receiver fingerprint** — which execution context will implement this spec?
   Accepted values: `claude-code+human` | `claude-code-autonomous` | `non-claude-ai` | `human-only`
   Store as `$RECEIVER`.

2. **Trust profile** — which risk categories apply? Comma-separated subset of:
   `untrusted-input` | `handles-secrets` | `touches-network` | `executes-generated-code`
   Or the literal `none` for no risk flags.
   Store as `$TRUST_PROFILE`.

3. **Contextual binding** — one-line description of what this spec is FOR (the evaluator refuses replay as something else). Must be non-empty.
   Store as `$BINDING`.

4. **Provenance** — is this a fresh spec or derived from an existing locked spec?
   Accepted values: `none` (fresh spec) | `derived-from <slug> <parent-envelope-sha256>` (fork).
   Store as `$PROVENANCE`.

**Step 3 — invoke the wizard CLI with flags:**

```bash
spectre substrate_wizard run \
  --author-spec-hash "$AUTHOR_SPEC_HASH" \
  --receiver "$RECEIVER" \
  --trust-profile "$TRUST_PROFILE" \
  --binding "$BINDING" \
  --provenance "$PROVENANCE"
```

Capture stdout — that's the §8.2 markdown block. Inject it after §8.1 in the spec template.

**Failure modes:**
- `error wizard.substrate reason=missing_flags missing=<list>` — Claude did not populate all four flags. Fix: ensure all four variables are set before invoking.
- `error wizard.substrate reason=invalid_<which> ...` — a flag value failed validation. Fix: correct the value per the accepted-values list above and re-invoke.
- Exit 0 with cached output — cache hit; `$BINDING`, `$RECEIVER`, etc. from this run are ignored (cached values win). Pass `--force` to override.

If `trust-profile` includes `untrusted-input` or `handles-secrets`, every step that produces an artifact MUST declare `untrusted-input: yes/no` and (when relevant) `sanitizes:` covering its sanitized OUTPUT. The evaluator's Tier 1 will block on missing annotations.

### Phase: Intent

The user has typed `/vision <free-form text>`. Treat the text as **intent**, not as a spec. Anchor cwd via `pwd` to capture `$PROJECT`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/...`), HALT.

**Open-question markers.** The intent text may declare known unknowns in two formats:

*YAML frontmatter (preferred):*
```
---
open_questions:
  - daemon lifecycle (start/stop/restart/owner)
  - prompt failure-mode handling on malformed JSON
---
<rest of intent prose>
```

*Inline markers in prose:*
```
We need a code legibility daemon. open: should it run as systemd or pm2?
The auth strategy is unresolved: OAuth or API key?
```

The walker parses these markers automatically when you pass the intent to `init-or-resume`. **Pass the raw intent text verbatim** — do NOT paraphrase first. The walker extracts markers and tracks them as `open_questions` in state. Each detected open question gets a stable `oq-N` id. The walker refuses `author-arbitrated` stop until every open question is resolved or deferred.

### Phase: Feasibility

Refuse physically impossible requests; if multi-subsystem, ask which sub-problem to lock first. Do NOT draft or interrogate further until this is settled.

### Phase: Walker loop

Resume an existing walk if one is live for this spec, otherwise initialize a new one. Derive the canonical draft path from the slug via the spec-evaluator CLI (never substitute `<slug>` into a `Path("specs/...")` literal inline):

```bash
SPEC_PATH="$(spectre spec_evaluator slug-to-path --slug "<slug>")"
DRAFT_PATH="${SPEC_PATH}.draft"
spectre walker init-or-resume \
    --intent "<verbatim user intent>" \
    --draft "$DRAFT_PATH" \
    --state-path state/.walk.json
```

Stdout: `OK walker.init rounds=N pending=M stop=<reason|none>`. The `--intent` value is ignored on resume (existing walk's intent wins); on first run it is persisted into `state/.walk.json` along with five seed concerns covering §8.1 mutates, never-touches, decision-budget, and reboot-survival fields.

Repeat until the walker reports stop:

1. **Read next concern.** Fetch the next pending concern body via the CLI:

   ```bash
   spectre walker peek-pending \
       --state-path state/.walk.json \
       --json
   ```

   Stdout: a JSON object with `id`, `kind`, `receiver`, `summary`, and `round` fields, or `null` when the walk is exhausted. If `null`, jump to the Draft phase.

2. **Render the structured concern as a natural-language question.** The concern's `summary` field is canonical structured text. The skill phrases it so the user understands. The structured concern is the data; the question text is presentation. If the user says "this question makes no sense," the debug surface is `state/.walk.json` (inspect via `get-state` below), not the rendered prose.

   Render format:
   ```
   ROUND <N> · id: <concern_id> · receiver: <receivers> · kind: <kind>
   <natural-language question derived from concern.summary>
   (answer, or `revise <concern_id>` to amend an earlier answer, or `stop` to lock the walk)
   ```

   On `revise` without an id, fetch full state to list asked concerns:

   ```bash
   spectre walker get-state \
       --state-path state/.walk.json \
       --json
   ```

   Parse `answered` from the JSON and display each as `<id> | <one-line summary> | <answer-truncated>` so the user can pick which to amend.

3. **Capture user input.** Three branches:

   - **`stop`** — record stop via:
     ```bash
     spectre walker stop \
         --reason author-arbitrated \
         --state-path state/.walk.json
     ```
     Jump to the Draft phase. If the walker emits `WARN walker.open-questions-unresolved count=K ids=...`, the gate fired — K open questions must be answered or deferred before you can stop. To defer an open question to a later ADR:
     ```bash
     spectre walker defer-open-question \
         --id oq-2 \
         --adr adr-0007 \
         --state-path state/.walk.json
     ```
     Stdout: `OK walker.open-question-deferred id=oq-2 adr=adr-0007`.
   - **`revise <concern_id> <new_answer>`** — record the revised answer and ask the user about stale concerns:
     ```bash
     spectre walker answer-concern \
         --id <concern_id> \
         --answer "<new_answer>" \
         --state-path state/.walk.json
     ```
     Re-run `get-state` to surface any now-stale sibling concerns. Ask: "These concerns are now stale: <list>. Re-walk them or accept-stale?" On `re-walk`, the walker's `peek-pending` will surface them in the next round naturally.
   - **Anything else** — treat as the answer to the current concern:
     ```bash
     spectre walker answer-concern \
         --id <concern_id> \
         --answer "<user text>" \
         --state-path state/.walk.json
     ```

4. **Run the Tier 3 yield-delta check** (only if `~/.spectre/reviewer.toml` has `[tier3] enabled = true` AND we have an in-progress draft):

   ```bash
   spectre walker yield-check \
       --draft "$DRAFT_PATH" \
       --state-path state/.walk.json
   ```

   Stdout: `OK walker.yield new_t3=N history=[...]` on a real evaluation, or `OK walker.yield_skipped reason=<reason>` when preconditions fail (no walk state, draft missing, `round_count=0`). The CLI uses `~/.spectre/reviewer.toml` and `state/` as the bundle dir by default; override with `--config` and `--bundle-dir` when needed.

   **Recommend-stop transition.** If `answer-concern` emits `RESULT walker.recommend-stop reason=coverage-complete`, surface this to the operator inline:

   > Walker recommends stopping: coverage is complete. Reply `stop` to lock, or continue answering to refine further.

   This emission is idempotent — it fires exactly once when coverage transitions from incomplete to complete. It does NOT fire again if the user continues and coverage stays complete.

   **Concern rendering with prefab options.** When a concern has non-empty `prefab_options`, display them as numbered choices before the open-answer prompt. Rules:
   - If the concern's `kind` is NOT `receiver-clarification` and `"defer to later layer"` is not already in the list, append it as the last choice.
   - Before displaying, drop any prefab option that contradicts a prior `state.answered` entry. Contradiction rule: the option shares ≥ 2 content tokens with an answered value that contains a negation word (`not`, `no`, `never`, `without`, `excluding`, `vendor-agnostic`). Example: if a prior answer says "vendor-agnostic, no DeepSeek-only options", drop a prefab containing "deepseek". Apply this in prose — the walker library exposes no helper for this in v0.8.2.

5. **Check stop conditions.** Re-run `peek-pending` — if it returns `null`, the walk is exhausted; proceed to the Draft phase. Alternatively, check the `stop` field in the full state dump:

   ```bash
   spectre walker get-state \
       --state-path state/.walk.json \
       --json
   ```

   If `stop` is non-null in the returned JSON, proceed to the Draft phase. Otherwise, loop back.

### Phase: Draft

The walk has stopped. Render the draft from accumulated `state.answered` plus `state.spec_intent`:

1. **Slugify the title** (lowercase, `[^a-z0-9]+ → -`, trim).
2. **Write the draft file** atomically at `$PROJECT/specs/<slug>.spec.md.draft` using the answers as Steps + First Principles + §8 Receiver Calibration content. The exact mapping from concerns to spec sections lives in your judgment of what the answers tell you; the skill does not impose a 1:1 mapping. Standard `## 1. Hard Problem` through `## 8. Receiver Calibration` structure per `specs/template.spec.md`.
3. **Print the one-line confirmation:**
   ```
   DRAFT: specs/<slug>.spec.md.draft (N steps; walked R rounds; stop=<stop_reason>). Reply: yes / refine "<change>" / cancel
   ```
4. **Wait for the user.**
   - `yes` → continue to the Wizard phase (setup wizard) → Evaluator gate.
   - `refine "<change>"` — if the change implies revising a prior concern, call `answer-concern` with the updated answer first (same CLI as Walker loop phase), then re-render the draft. Otherwise, edit the draft directly and re-run the evaluator.
   - `cancel` → delete the draft AND `state/.walk.json` AND `state/.eval-bundle.json`. Halt.

The walker's invalidation set + dependency graph are never re-rendered for the user post-confirmation; they exist only to drive interrogation cycles. After the user says `yes` and the evaluator passes, `state/.walk.json` may be retained as audit trail or cleared.

**Draft-to-disk.** The user said `yes`. Do NOT print the full spec body again — write it directly to disk so the user can review in their editor.

1. **Anchor to the user's project cwd FIRST.** Run `pwd` to capture the absolute path (e.g. `/home/foo/myproject`). Call this `$PROJECT`. All file paths in the rest of this phase are `$PROJECT/specs/...`, `$PROJECT/state/...`, and `$PROJECT/decisions/...`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/`, `${CLAUDE_PLUGIN_ROOT}`, or contains `plugins/cache/`), HALT and tell the user to restart Claude Code from their project directory.
2. `mkdir -p "$PROJECT/specs" "$PROJECT/state" "$PROJECT/decisions"` to ensure the dirs exist.
3. Slugify the title: lowercase, replace non-alphanumerics with `-`, collapse repeats, strip leading/trailing `-`.
4. Set frontmatter `Generated:` to today's ISO date and `Slug:` to the computed slug.
5. **Write the draft file at `$PROJECT/specs/<slug>.spec.md.draft`.** Use atomic write: write to `<draft>.tmp` then `mv` to `<draft>`.
6. Print exactly one line:

```
DRAFT: specs/<slug>.spec.md.draft (N steps). Reply: yes / refine "<change>" / cancel
```

7. **Wait for the user.**
   - `yes` → continue to the Evaluator gate.
   - `refine "<change>"` → reopen the draft file, apply the requested change, atomically rewrite the .draft file, re-run the evaluator, re-emit the one-line confirmation. Repeat until `yes`.
   - `cancel` → delete the .draft file AND clear `state/.eval-bundle.json`, halt, write nothing else.

### Phase: Evaluator gate — setup wizard

Before running the evaluator, ensure `~/.spectre/reviewer.toml` exists. If it doesn't, the wizard auto-creates it — detecting any DeepSeek API key in the live environment, then optionally in a `.env`-style secrets file pointed to by the `SPECTRE_SECRETS_FILE` env var. The TOML is always written (with `enabled=false` if no key is found) so subsequent runs don't re-prompt.

```bash
spectre setup_wizard provision
```

Stdout: `OK wizard.setup result=<result> target=<path>`. Outcomes: `result=exists` (no-op), `result=enabled` (DeepSeek API key found), `result=setup-skipped` (no key found — placeholder `enabled=false` written). After the wizard runs, `~/.spectre/reviewer.toml` is guaranteed to exist; the evaluator always passes that path.

### Phase: Evaluator gate — spec evaluation

After the user replies `yes` (or `refine`), run the spec evaluator over a *review bundle* (preview ADRs + preview Resource nodes + preview tier classifications materialized but not committed). Tiers 1+2 always run (deterministic, local). Tier 3 (DeepSeek `deepseek-v4-flash` adversarial reviewer) runs only when `~/.spectre/reviewer.toml` has `[tier3] enabled = true` AND the configured API key is present in the environment. When Tier 3 is unavailable for any reason, the evaluator emits an info-severity `tier3-unavailable` finding so the skip is **visible**, never silent.

First derive the canonical draft path from the slug — never substitute the slug into a `Path("specs/<slug>...")` literal inline:

```bash
SPEC_PATH="$(spectre spec_evaluator slug-to-path --slug "<slug>")"
DRAFT_PATH="${SPEC_PATH}.draft"
```

Then run the evaluator and capture the full result (findings + `sidecar_payload`) to `state/.eval-result.json` so the Lock phase can re-use the same `policy_hash`/`tiers_run` without re-running the evaluator:

```bash
spectre spec_evaluator evaluate \
  --spec "$DRAFT_PATH" \
  --config "$HOME/.spectre/reviewer.toml" \
  --bundle-dir state \
  --output state/.eval-result.json
```

The output JSON has top-level keys `findings` (list), `max_severity` (string), and `sidecar_payload` (dict). The bundle is also persisted at `state/.eval-bundle.json`. Read `state/.eval-result.json` to surface findings; the `tiers_run` value is at `sidecar_payload.tiers_run` and `max_severity` is the top-level field.

After running, surface a one-line tier status block before the findings:

```
tier 1: PASS (n findings)
tier 2: PASS (n findings)
tier 3: PASS (n findings)        # if tiers_run includes 3
tier 3: SKIPPED (<reason>)        # if a tier3-unavailable finding is present
```

Reasons for SKIPPED come from the `tier3-unavailable` finding's `message` field: `config-missing`, `disabled-in-config`, `no-api-key`, `auth failure (HTTP 401/403 …)`, `provider error (HTTP 5xx)`, `bad request`, or `socket-timeout`. The user should always see one line per tier — the goal is to make Tier 3 status as visible as Tiers 1 and 2.

**Auth-failure prominence.** When the `tier3-unavailable` message contains the substring `auth failure`, prepend a separate banner ABOVE the tier status block so the user can act on it without scanning findings:

```
⚠ Tier 3 unavailable due to auth — fix ~/.spectre/secrets.env or DEEPSEEK_API_KEY then re-run /vision.
```

The banner must precede the `tier 1/2/3` lines and be visible regardless of how many other findings the evaluator emitted.

Interpret the result (read `max_severity` from the JSON):

- **`max_severity == "block"`** — list every `block`-severity finding to the user. The spec CANNOT lock until refine resolves them. Halt with:

  ```
  RESULT eval.summary block=N warn=M info=K
    [1] tier <X> · <kind> · step <S> · <message>
    [2] tier <X> · <kind> · step <S> · <message>
    ...
  Reply: refine "<change>" / cancel
  ```

  Do NOT proceed to Lock. The bundle stays persisted at `state/.eval-bundle.json` keyed by the current draft hash; on `refine`, the rewritten draft will produce a new bundle automatically.

- **`max_severity == "warn"`** — surface warnings to the user, ask once: `Proceed to lock with N warn findings? (yes / refine / cancel)`. On `yes`, continue to Lock.

- **`max_severity == "info"` or `"none"`** — surface findings briefly (≤3 lines) and proceed to Lock silently.

**Tier 3 false-positive dismissal:** if a Tier 3 finding has `dismissable: true` and the user wants to accept the risk, they can append a block at the bottom of the spec body:

```
# tier3-dismissed: <fingerprint> "one-line reason"
```

The fingerprint is the SHA-256 hex from `bin.findings.fingerprint(f)` — printable from the JSON output above. Re-running the evaluator will skip the dismissed finding; the dismissal is recorded in the `<slug>.spec.md.eval.json` sidecar after lock so audits can see what was suppressed and why.

`dismissable: false` findings (Tier 1+2 block-severity) CANNOT be dismissed via this mechanism — they must be fixed via `refine`.

### Phase: Evaluator gate — ADR generation (conditional)

Scan the locked spec's `## 2. First Principles` bullets and step `why:` lines for explicit decision markers. A decision marker is any line that:

- starts with `decision:` (case-insensitive), OR
- contains the phrase `we choose <X> because`, OR
- contains the phrase `<X> over <Y>` with a comparative justification.

For each decision found:

1. Run:

```bash
spectre adr write \
    --dir decisions \
    --title "<extracted decision title>" \
    --body "<one paragraph: the decision + the why from the spec>"
```

Stdout: `OK adr.write path=<path>`. Pass `--supersedes "NNNN"` only when this decision contradicts an existing ADR. The `--date` flag defaults to today's ISO date when omitted.

2. **Supersedes detection.** Before writing each ADR, list `decisions/*.md` and look for an existing ADR whose title or body contradicts the new decision. If found, pass `supersedes="<old_id>"`. If unsure, do NOT supersede.

3. **Graph wiring.** If `specs/.graph.md` exists AND both new and old ADRs are represented as nodes, run:

```bash
spectre adr update-graph \
    --graph specs/.graph.md \
    --new adr-NNNN \
    --old adr-MMMM
```

The CLI is a no-op when nodes are absent or the manifest is missing, so it is safe to always invoke after a supersede write.

### Phase: Lock

Before invoking the evaluator (§6.4 prep), check coverage:

```bash
spectre walker coverage \
    --state-path state/.walk.json \
    --draft "$DRAFT_PATH"
```

Stdout: `RESULT walker.coverage answered=N pending=M deferred=K undefined-invariants=L recommended-stop=yes|no rounds=R`. Surface this line to the operator. If `recommended-stop=no`, ask:

> Coverage incomplete. Continue to lock anyway? (yes / refine)

On `refine`, re-enter the Walker loop. On `yes`, proceed.

Now that the user confirmed and ADRs are written:

1. Atomic rename: `mv "$PROJECT/specs/<slug>.spec.md.draft" "$PROJECT/specs/<slug>.spec.md"`.
2. Atomically flip `.active`:

   ```bash
   printf 'specs/<slug>.spec.md\n' > "$PROJECT/specs/.active.tmp" && mv "$PROJECT/specs/.active.tmp" "$PROJECT/specs/.active"
   ```

3. Reset `$PROJECT/state/scratchpad.json` for the active spec:

   ```bash
   spectre _scratchpad ensure-v2 \
       --scratchpad state/scratchpad.json
   spectre _scratchpad reset \
       --active-spec specs/<slug>.spec.md \
       --scratchpad state/scratchpad.json
   ```

   `ensure-v2` promotes a v1 scratchpad to v2 (no-op if already v2). `reset` atomically writes the track's initial state (`step=1`, all counters zeroed) under the `default` track (or the named track if the user invoked `/vision <track>`), preserving any other tracks already present. Both commands emit a confirmation line on stdout.

4. **Write the `<slug>.spec.md.eval.json` sidecar.** The sidecar filename is always the spec filename with `.eval.json` appended. The evaluator's `result.sidecar_payload` carries the policy hash, tiers run, dismissals, findings summary, and DeepSeek model version. Persist next to the locked spec:

   ```bash
   SPEC_PATH="$(spectre spec_evaluator slug-to-path --slug "<slug>")"
   python3 -c 'import json,sys; d=json.load(open("state/.eval-result.json"))["sidecar_payload"]; d["config_path"]=sys.argv[1]; json.dump(d,sys.stdout)' \
     "$HOME/.spectre/reviewer.toml" \
     | spectre eval_metadata write-sidecar --spec "$SPEC_PATH"
   ```

   `policy_hash`, `tiers_run`, `dismissals`, `findings_summary`, `evaluator_version`, `config_hash`, and `deepseek_model_version` are all carried verbatim from the evaluator's `sidecar_payload` — there is no re-computation.

5. **Clear the persisted bundle** — lock is complete, the bundle is no longer needed:

   ```bash
   spectre spec_evaluator clear-bundle --bundle state/.eval-bundle.json
   ```

6. **Write the handoff envelope.** The envelope is the Vision→Implement handoff artifact: it carries a SHA-256 integrity hash over the locked spec, sidecar, contract resolution, and indexed ADR paths. `/implement` verifies this hash at Tier 0 on startup — a mismatch halts execution before any spec content is read. Re-running `/vision` is the only legitimate way to regenerate the envelope.

   ```bash
   spectre eval_metadata write-envelope \
       --spec "$SPEC_PATH" \
       --walk state/.walk.json \
       --decisions-dir decisions
   ```

   Stdout: `OK eval.envelope_written path=<path>` on success. If the envelope write fails (CLI exits non-zero), treat as a lock failure and halt.

**Append CDLC ledger transition.** Record a `generate` transition (lock event):

```bash
spectre cdlc_ledger append --kind generate \
    --payload-kv "spec_slug=<slug>" \
    --payload-kv "round_count=<walker round_count from state/.walk.json>" \
    --payload-kv "tiers_run=<tiers_run from <slug>.spec.md.eval.json sidecar>"
```

The CLI writes to `state/cdlc-ledger.json` under the project cwd (override with `--project`). For typed/nested payloads, use `--payload <json>` instead of `--payload-kv`.

### Phase: Transition

Print exactly:

```
VISION LOCKED: specs/<slug>.spec.md (step 1)
Architecture locked. Ready for /implement?
```

Do **not** auto-invoke `/implement`. The user types `/implement` when ready — this preserves the human's veto right between spec-lock and execution.
