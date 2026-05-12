---
name: vision
description: Unified inception — distill a vague vision into a First-Principles spec with action/verification steps, then lock it as the active spec.
disable-model-invocation: false
---

# Skill: /vision <user_vision>

Triggered when the user types `/vision` followed by free-form text describing what they want built. Follow this protocol **exactly** — it is the only legitimate path from human intent to locked spec.

## PYTHONPATH note

Spectre's `bin/` modules live under the plugin install at `${CLAUDE_PLUGIN_ROOT}/bin/`, not on the user's project sys.path. Every `python3 -m bin.X` invocation in this skill prefixes with `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"`. Do not strip or alter this prefix when adapting commands.

## Hard rules (read every invocation)

- **All paths are user-project-cwd-relative.** Spec, scratchpad, and `.active` live under the user's current working directory at session start (e.g. `/home/foo/myproject/specs/...`), NEVER under the plugin's install path (`~/.claude/plugins/...` or `${CLAUDE_PLUGIN_ROOT}`). If you find yourself about to write into a plugin cache directory, STOP — that is a bug. Resolve cwd via `pwd` once at the start of Step 6 and use absolute paths from there.
- **One spec at a time.** Never write two `.active` files.
- **Step number is user-driven.** This skill resets `step` to 1; nothing else here writes to it.
- **No hedging, no "best practices," no industry preambles.** First-principles content only.
- **Never silently lock a spec.** If the user has not confirmed the draft, do not write the file or flip `.active`.
- **Refuse physically impossible visions.** Run a Feasibility Audit before drafting (step 2 below). If the request violates known physics, math, or logic, halt and explain — do not produce a spec.

## Protocol

### Step 0 — Codebase Fingerprint (silent, internal)

Before treating the user's text as a Spark, run the fingerprinter to surface prior art in the user's codebase:

```bash
python3 bin/fingerprint.py 2>&1 | tail -5
```

This writes `state/local-symbols.json`. Read the first 50 entries:

```bash
python3 -c "import json; d=json.load(open('state/local-symbols.json')); print(json.dumps(d[:50], indent=2))"
```

When the walker surfaces concerns in Step 4, scan the symbol map for any function/class/module conceptually related to the user's intent (e.g. intent says "fetch BTC price" → search for `fetch`, `price`, `http`, `bitcoin`, `btc`, `requests`). If you find a candidate, surface it via a `branch-resolution` concern: "We will NOT reinvent `<symbol_name>` at `<file>:<line>` — reuse it as the basis for step N." The "never reinvent the wheel" rule is enforced by construction here. Skipping Step 0 violates the rule silently.

**Template-import surfacing (v0.4.2+).** Also list any reusable spec/skill templates the user has previously exported:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.templates list --limit 10
```

Stdout: `TEMPLATES_AVAILABLE: N` followed by up to 10 ` <kind>: <name>` lines (e.g. `  spec: btc-poller`). Pass `--json` for the full descriptor list when you need the absolute path.

If templates exist, surface them as candidate starting points during Step 4's interrogation walk: "Your library has `<template_name>` (a `<kind>`). Import as a base for this spec? (import / no)". On `import`, call `templates.import_template(source_name=<name>, target_name=<slug>)`; the imported draft becomes the seed for the walk's draft materialization in Step 5.

### Step 0.5 — Cognitive-substrate wizard (v0.7)

Before §1 distillation, fire the substrate wizard. The wizard asks 4 mandatory questions to populate §8.2 (cognitive-substrate contract). Answers are cached at `~/.spectre/substrate-cache/<author-spec-hash>.json`; re-running /vision on an unchanged spec body skips re-prompting.

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.substrate_wizard run \
  --author-spec-hash "$(printf %s "$DRAFT_BODY_NO_82" | sha256sum | awk '{print $1}')"
```

Capture stdout — that's the §8.2 markdown block. Inject it after §8.1 in the spec template.

The 4 questions:
1. **Receiver fingerprint** — claude-code+human / claude-code-autonomous / non-claude-ai / human-only.
2. **Trust profile** — comma-separated subset of {untrusted-input, handles-secrets, touches-network, executes-generated-code} or "none".
3. **Contextual binding** — one-line description of what this spec is FOR (the evaluator refuses replay as something else).
4. **Provenance** — "none" or "derived-from <slug> <parent-envelope-sha256>".

If `trust-profile` includes `untrusted-input` or `handles-secrets`, every step that produces an artifact MUST declare `untrusted-input: yes/no` and (when relevant) `sanitizes:` covering its sanitized OUTPUT. The evaluator's Tier 1 will block on missing annotations.

### Step 1 — Receive intent

The user has typed `/vision <free-form text>`. Treat the text as **intent**, not as a spec. Anchor cwd via `pwd` to capture `$PROJECT`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/...`), HALT.

### Step 2 — Feasibility audit (silent, internal)

Same as v0.3.x — refuse physically impossible requests; if multi-subsystem, ask which sub-problem to lock first. Do NOT draft or interrogate further until this is settled.

### Step 3 — Initialize the walker

Resume an existing walk if one is live for this spec, otherwise initialize a new one. Derive the canonical draft path from the slug via the Phase 2A CLI (never substitute `<slug>` into a `Path("specs/...")` literal inline):

```bash
SPEC_PATH="$(PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.spec_evaluator slug-to-path --slug "<slug>")"
DRAFT_PATH="${SPEC_PATH}.draft"
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker init-or-resume \
    --intent "<verbatim user intent>" \
    --draft "$DRAFT_PATH" \
    --state-path state/.walk.json
```

Stdout: `WALK: N rounds, M pending, stop=<reason|none>`. The `--intent` value is ignored on resume (existing walk's intent wins); on first run it is persisted into `state/.walk.json` along with five seed concerns covering §8.1 mutates, never-touches, decision-budget, and reboot-survival fields.

### Step 4 — Walk loop (interrogation)

Repeat until the walker reports stop:

1. **Read next concern.** Fetch the next pending concern body via the CLI:

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker peek-pending \
       --state-path state/.walk.json \
       --json
   ```

   Stdout: a JSON object with `id`, `kind`, `receiver`, `summary`, and `round` fields, or `null` when the walk is exhausted. If `null`, jump to Step 5.

2. **Render the structured concern as a natural-language question.** The concern's `summary` field is canonical structured text. The skill phrases it so the user understands. The structured concern is the data; the question text is presentation. If the user says "this question makes no sense," the debug surface is `state/.walk.json` (inspect via `get-state` below), not the rendered prose.

   Render format:
   ```
   ROUND <N> · id: <concern_id> · receiver: <receivers> · kind: <kind>
   <natural-language question derived from concern.summary>
   (answer, or `revise <concern_id>` to amend an earlier answer, or `stop` to lock the walk)
   ```

   On `revise` without an id, fetch full state to list asked concerns:

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker get-state \
       --state-path state/.walk.json \
       --json
   ```

   Parse `answered` from the JSON and display each as `<id> | <one-line summary> | <answer-truncated>` so the user can pick which to amend.

3. **Capture user input.** Three branches:

   - **`stop`** — record stop via:
     ```bash
     PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker stop \
         --reason author-arbitrated \
         --state-path state/.walk.json
     ```
     Stdout: `STOPPED: reason=author-arbitrated`. Jump to Step 5.
   - **`revise <concern_id> <new_answer>`** — record the revised answer and ask the user about stale concerns:
     ```bash
     PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker answer-concern \
         --id <concern_id> \
         --answer "<new_answer>" \
         --state-path state/.walk.json
     ```
     Stdout: `ANSWERED: <concern_id>`. Re-run `get-state` to surface any now-stale sibling concerns. Ask: "These concerns are now stale: <list>. Re-walk them or accept-stale?" On `re-walk`, the walker's `peek-pending` will surface them in the next round naturally.
   - **Anything else** — treat as the answer to the current concern:
     ```bash
     PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker answer-concern \
         --id <concern_id> \
         --answer "<user text>" \
         --state-path state/.walk.json
     ```
     Stdout: `ANSWERED: <concern_id>`.

4. **Run the Tier 3 yield-delta check** (only if `~/.spectre/reviewer.toml` has `[tier3] enabled = true` AND we have an in-progress draft):

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker yield-check \
       --draft "$DRAFT_PATH" \
       --state-path state/.walk.json
   ```

   Stdout: `YIELD: N new T3 findings this round; history=[...]` on a real evaluation, or `YIELD: skipped (<reason>)` when preconditions fail (no walk state, draft missing, `round_count=0`). The CLI uses `~/.spectre/reviewer.toml` and `state/` as the bundle dir by default; override with `--config` and `--bundle-dir` when needed.

5. **Check stop conditions.** Re-run `peek-pending` (Step 4.1) — if it returns `null`, the walk is exhausted; proceed to Step 5. Alternatively, check the `stop` field in the full state dump:

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.walker get-state \
       --state-path state/.walk.json \
       --json
   ```

   If `stop` is non-null in the returned JSON, proceed to Step 5. Otherwise, loop back to Step 4.1.

### Step 5 — Materialize draft + confirm

The walk has stopped. Render the draft from accumulated `state.answered` plus `state.spec_intent`:

1. **Slugify the title** (lowercase, `[^a-z0-9]+ → -`, trim).
2. **Write the draft file** atomically at `$PROJECT/specs/<slug>.spec.md.draft` using the answers as Steps + First Principles + §8 Receiver Calibration content. The exact mapping from concerns to spec sections lives in your judgment of what the answers tell you; the skill does not impose a 1:1 mapping. Standard `## 1. Hard Problem` through `## 8. Receiver Calibration` structure per `specs/template.spec.md`.
3. **Print the one-line confirmation:**
   ```
   DRAFT: specs/<slug>.spec.md.draft (N steps; walked R rounds; stop=<stop_reason>). Reply: yes / refine "<change>" / cancel
   ```
4. **Wait for the user.**
   - `yes` → continue to Step 6.3a (existing v0.3.2 setup wizard) → Step 6.4 evaluator (existing).
   - `refine "<change>"` — if the change implies revising a prior concern, call `answer-concern` with the updated answer first (same CLI as Step 4.3), then re-render the draft. Otherwise, edit the draft directly and re-run §6.4 (existing v0.3.2 behavior).
   - `cancel` → delete the draft AND `state/.walk.json` AND `state/.eval-bundle.json`. Halt.

The walker's invalidation set + dependency graph are never re-rendered for the user post-confirmation; they exist only to drive interrogation cycles. After the user says `yes` and §6.4 passes, `state/.walk.json` may be retained as audit trail or cleared (skill author's choice; v0.4.0 keeps it).

### Step 6 — Draft-to-disk

The user said `yes` in Step 5. Do NOT print the full spec body again — write it directly to disk so the user can review in their editor.

1. **Anchor to the user's project cwd FIRST.** Run `pwd` to capture the absolute path (e.g. `/home/foo/myproject`). Call this `$PROJECT`. All file paths in the rest of this step are `$PROJECT/specs/...`, `$PROJECT/state/...`, and `$PROJECT/decisions/...`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/`, `${CLAUDE_PLUGIN_ROOT}`, or contains `plugins/cache/`), HALT and tell the user to restart Claude Code from their project directory.
2. `mkdir -p "$PROJECT/specs" "$PROJECT/state" "$PROJECT/decisions"` to ensure the dirs exist.
3. Slugify the title: lowercase, replace non-alphanumerics with `-`, collapse repeats, strip leading/trailing `-`.
4. Set frontmatter `Generated:` to today's ISO date and `Slug:` to the computed slug.
5. **Write the draft file at `$PROJECT/specs/<slug>.spec.md.draft`.** Use atomic write: write to `<draft>.tmp` then `mv` to `<draft>`.
6. Print exactly one line:

```
DRAFT: specs/<slug>.spec.md.draft (N steps). Reply: yes / refine "<change>" / cancel
```

7. **Wait for the user.**
   - `yes` → continue to Step 6.4 (evaluator pass).
   - `refine "<change>"` → reopen the draft file, apply the requested change, atomically rewrite the .draft file, re-run Step 6.4 evaluator (bundle is keyed by draft hash so it auto-rebuilds), re-emit the one-line confirmation. Repeat until `yes`.
   - `cancel` → delete the .draft file AND clear `state/.eval-bundle.json`, halt, write nothing else.

The draft-to-disk pattern eliminates the double-token-output friction (printing the full spec inline AND writing the file). The user reviews in their editor; we hold the spec in disk-only state until confirmed.

### Step 6.3a — First-run setup wizard (v0.3.1+)

Before running the evaluator, ensure `~/.spectre/reviewer.toml` exists. If it doesn't, the wizard auto-creates it — detecting any DeepSeek API key in the live environment, then optionally in a `.env`-style secrets file pointed to by the `SPECTRE_SECRETS_FILE` env var, and prompting once for opt-in. The TOML is always written (with `enabled=false` if the user declines or no key is found) so subsequent runs don't re-prompt.

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.setup_wizard provision
```

Stdout: `WIZARD: <result> (<target>)`. Outcomes: `exists` (no-op), `enabled` (DeepSeek API key found in env or `~/.spectre/secrets.env`, Tier 3 enabled), `setup-skipped` (no key found anywhere — placeholder `enabled=false` written so subsequent runs do not re-prompt). After the wizard runs, `~/.spectre/reviewer.toml` is guaranteed to exist; §6.4 always passes that path to the evaluator.

### Step 6.4 — Pre-lock spec evaluator (CDLC Evaluate phase, v0.3+)

After the user replies `yes` (or `refine`), run the spec evaluator over a *review bundle* (preview ADRs + preview Resource nodes + preview tier classifications materialized but not committed). Tiers 1+2 always run (deterministic, local). Tier 3 (DeepSeek `deepseek-v4-flash` adversarial reviewer) runs only when `~/.spectre/reviewer.toml` has `[tier3] enabled = true` AND the configured API key is present in the environment. When Tier 3 is unavailable for any reason, the evaluator emits an info-severity `tier3-unavailable` finding so the skip is **visible**, never silent.

First derive the canonical draft path from the slug — never substitute the slug into a `Path("specs/<slug>...")` literal inline. Use the Phase 2A CLI, which validates the slug and emits the spec-file path (the draft path is the same string with `.draft` appended):

```bash
SPEC_PATH="$(PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.spec_evaluator slug-to-path --slug "<slug>")"
DRAFT_PATH="${SPEC_PATH}.draft"
```

Then run the evaluator and capture the full result (findings + `sidecar_payload`) to `state/.eval-result.json` so §6.7 can re-use the same `policy_hash`/`tiers_run` without re-running the evaluator:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.spec_evaluator evaluate \
  --spec "$DRAFT_PATH" \
  --config "$HOME/.spectre/reviewer.toml" \
  --bundle-dir state \
  --output state/.eval-result.json
```

The output JSON has top-level keys `findings` (list), `max_severity` (string), and `sidecar_payload` (dict — feeds §6.7). The bundle is also persisted at `state/.eval-bundle.json` for §6.6. Read `state/.eval-result.json` to surface findings; the `tiers_run` value is at `sidecar_payload.tiers_run` and `max_severity` is the top-level field.

After running, surface a one-line tier status block before the findings:

```
tier 1: PASS (n findings)
tier 2: PASS (n findings)
tier 3: PASS (n findings)        # if tiers_run includes 3
tier 3: SKIPPED (<reason>)        # if a tier3-unavailable finding is present
```

Reasons for SKIPPED come from the `tier3-unavailable` finding's `message` field: `config-missing`, `disabled-in-config`, `no-api-key`, `auth failure (HTTP 401/403 …)`, `provider error (HTTP 5xx)`, `bad request`, or `socket-timeout`. The user should always see one line per tier — the goal is to make Tier 3 status as visible as Tiers 1 and 2.

**v0.6.2 (#37) — auth-failure prominence.** When the `tier3-unavailable` message contains the substring `auth failure`, prepend a separate banner ABOVE the tier status block so the user can act on it without scanning findings:

```
⚠ Tier 3 unavailable due to auth — fix ~/.spectre/secrets.env or DEEPSEEK_API_KEY then re-run /vision.
```

The banner must precede the `tier 1/2/3` lines and be visible regardless of how many other findings the evaluator emitted. This catches the "Tier 3 silently degraded after a stale-config migration" failure mode.

Interpret the result:

- **`MAX_SEVERITY: block`** — list every `block`-severity finding to the user. The spec CANNOT lock until refine resolves them. Halt with:

  ```
  EVALUATOR HALT: <N> block findings, <M> warn, <K> info.
    [1] tier <X> · <kind> · step <S> · <message>
    [2] tier <X> · <kind> · step <S> · <message>
    ...
  Reply: refine "<change>" / cancel
  ```

  Do NOT proceed to §6.5. The bundle stays persisted at `state/.eval-bundle.json` keyed by the current draft hash; on `refine`, the rewritten draft will produce a new bundle automatically.

- **`MAX_SEVERITY: warn`** — surface warnings to the user, ask once: `Proceed to lock with N warn findings? (yes / refine / cancel)`. On `yes`, continue to §6.5.

- **`MAX_SEVERITY: info`** — surface findings briefly (≤3 lines) and proceed to §6.5 silently.

**Tier 3 false-positive dismissal:** if a Tier 3 finding has `dismissable: true` and the user wants to accept the risk, they can append a block at the bottom of the spec body:

```
# tier3-dismissed: <fingerprint> "one-line reason"
```

The fingerprint is the SHA-256 hex from `bin.findings.fingerprint(f)` — printable from the JSON output above (compute it via `python3 -c "from bin import findings as F; ..."` if needed). Re-running §6.4 will skip the dismissed finding; the dismissal is recorded in the `<slug>.spec.md.eval.json` sidecar after lock so audits can see what was suppressed and why.

`dismissable: false` findings (Tier 1+2 block-severity) CANNOT be dismissed via this mechanism — they must be fixed via `refine`.

### Step 6.5 — ADR generation (conditional)

Scan the locked spec's `## 2. First Principles` bullets and step `why:` lines for explicit decision markers. A decision marker is any line that:

- starts with `decision:` (case-insensitive), OR
- contains the phrase `we choose <X> because`, OR
- contains the phrase `<X> over <Y>` with a comparative justification.

For each decision found:

1. Run:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.adr write \
    --dir decisions \
    --title "<extracted decision title>" \
    --body "<one paragraph: the decision + the why from the spec>"
```

Stdout: `ADR: <path>`. Pass `--supersedes "NNNN"` only when this decision contradicts an existing ADR (see step 2). The `--date` flag defaults to today's ISO date when omitted.

2. **Supersedes detection.** Before writing each ADR, list `decisions/*.md` and look for an existing ADR whose title or body contradicts the new decision (e.g. new ADR says "Use Postgres 16" and an existing ADR says "Use SQLite"). If found, pass `supersedes="<old_id>"`. If unsure, do NOT supersede — false positives are worse than missing supersedes (a missed supersedes can be retro-fixed; a wrong supersedes invalidates downstream work).

3. **Graph wiring.** If `specs/.graph.md` exists AND both new and old ADRs are represented as nodes, run:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.adr update-graph \
    --graph specs/.graph.md \
    --new adr-NNNN \
    --old adr-MMMM
```

In v0.2.1 the graph manifest may not have ADR nodes yet. The CLI (and underlying `update_graph_for_supersedes`) is a no-op when nodes are absent or the manifest is missing, so it is safe to always invoke after a supersede write.

### Step 6.6 — Resource node inference (read from bundle)

The §6.4 evaluator already computed `preview_resources` in the bundle. Read that list (don't re-compute):

§6.4 already persisted the bundle to `state/.eval-bundle.json` keyed by the draft's SHA-256, so the file on disk is current by the time §6.6 runs. Use the native `Read` tool on `state/.eval-bundle.json` and parse out the `preview_resources` array — each entry is an object `{"id": ..., "kind": ..., "identifier": ...}`. If the bundle file is missing (rare — only happens if §6.4 was skipped or `clear-bundle` was run), re-run the §6.4 evaluator command first to repopulate it.

For each unique Resource:

1. Check `specs/.graph.md` for an existing node with the same `id`. If absent, append a new node block via `bin/graph.serialize_node(...)` (Node with `type="resource"`, `title=f"{kind}:{identifier}"`).
2. Append the Resource ID to that step's `resources:` list in the spec file (atomic rewrite).

Plan C only auto-detects `port:N` style. DB connections, file locks, and API quotas need user-authored Resource nodes (manually added `Resource:` block in the graph manifest). The supervisor's lazy `register_resource(capacity=1)` will fall back if the node is missing — but a missing node also means no capacity-other-than-1 declaration is possible, so explicit declaration is preferred.

### Step 6.7 — Lock the spec

Now that the user confirmed and ADRs are written:

1. Atomic rename: `mv "$PROJECT/specs/<slug>.spec.md.draft" "$PROJECT/specs/<slug>.spec.md"`.
2. Atomically flip `.active`:

   ```bash
   printf 'specs/<slug>.spec.md\n' > "$PROJECT/specs/.active.tmp" && mv "$PROJECT/specs/.active.tmp" "$PROJECT/specs/.active"
   ```

3. Reset `$PROJECT/state/scratchpad.json` for the active spec. Use the CLI to ensure v2 schema and reset the track atomically:

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin._scratchpad ensure-v2 \
       --scratchpad state/scratchpad.json
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin._scratchpad reset \
       --active-spec specs/<slug>.spec.md \
       --scratchpad state/scratchpad.json
   ```

   `ensure-v2` promotes a v1 scratchpad to v2 (no-op if already v2). `reset` atomically writes the track's initial state (`step=1`, all counters zeroed) under the `default` track (or the named track if the user invoked `/vision <track>`), preserving any other tracks already present. Both commands emit a confirmation line on stdout.

4. **Write the `<slug>.spec.md.eval.json` sidecar** (v0.3+, post-§6.4 evaluator). The sidecar filename is always the spec filename with `.eval.json` appended (append-suffix, not replace-suffix — `eval_metadata.sidecar_path_for(spec)` returns the canonical path). The evaluator's `result.sidecar_payload` carries the policy hash, tiers run, dismissals, findings summary, and DeepSeek model version. Persist next to the locked spec:

   Use the Phase 2A CLI. Derive the locked-spec path from the slug (the same `slug-to-path` helper §6.4 used) and feed the `sidecar_payload` block §6.4 already saved to `state/.eval-result.json` straight into `write-sidecar`. Augmenting the payload with `config_path` keeps the sidecar's `config_path` field populated:

   ```bash
   SPEC_PATH="$(PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.spec_evaluator slug-to-path --slug "<slug>")"
   python3 -c 'import json,sys; d=json.load(open("state/.eval-result.json"))["sidecar_payload"]; d["config_path"]=sys.argv[1]; json.dump(d,sys.stdout)' \
     "$HOME/.spectre/reviewer.toml" \
     | PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.eval_metadata write-sidecar --spec "$SPEC_PATH"
   ```

   The CLI prints the written sidecar path on stdout. `policy_hash`, `tiers_run`, `dismissals`, `findings_summary`, `evaluator_version`, `config_hash`, and `deepseek_model_version` are all carried verbatim from §6.4's `sidecar_payload` — there is no re-computation, no inline `Path("specs/<slug>...")` substitution, and no policy-hash drift between §6.4 and §6.7.

5. **Clear the persisted bundle** — lock is complete, the bundle is no longer needed:

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.spec_evaluator clear-bundle --bundle state/.eval-bundle.json
   ```

6. **Write the handoff envelope** (v0.6+). The envelope is the Vision→Implement handoff artifact: it carries a SHA-256 integrity hash over the locked spec, sidecar, contract resolution, and indexed ADR paths. `/implement` verifies this hash at Tier 0 on startup — a mismatch halts execution before any spec content is read. Re-running `/vision` is the only legitimate way to regenerate the envelope. The envelope file is additive (does not replace the sidecar) and sits alongside it at `specs/<slug>.envelope.json`. Per v0.6 design — see CHANGELOG.

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.eval_metadata write-envelope \
       --spec "$SPEC_PATH" \
       --walk state/.walk.json \
       --decisions-dir decisions
   ```

   Stdout: `ENVELOPE: specs/<slug>.envelope.json` on success. If the envelope is invalid (schema violation, integrity hash mismatch), the CLI exits non-zero and prints `ENVELOPE INVALID: <violations>` — treat as a lock failure and halt. Do not lock the spec if the envelope write fails.

**Append CDLC ledger transition (v0.4.2+).** Record a `generate` transition (lock event):

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m bin.cdlc_ledger append --kind generate \
    --payload-kv "spec_slug=<slug>" \
    --payload-kv "round_count=<walker round_count from state/.walk.json>" \
    --payload-kv "tiers_run=<tiers_run from <slug>.spec.md.eval.json sidecar>"
```

The CLI writes to `state/cdlc-ledger.json` under the project cwd (override with `--project`). Stdout: `APPENDED: kind=generate`. For typed/nested payloads, use `--payload <json>` instead of `--payload-kv`.

### Step 7 — Transition signal

Print exactly:

```
VISION LOCKED: specs/<slug>.spec.md (step 1)
Architecture locked. Ready for /implement?
```

Do **not** auto-invoke `/implement`. The user types `/implement` when ready — this preserves the human's veto right between spec-lock and execution.
