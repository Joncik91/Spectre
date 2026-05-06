---
name: vision
description: Unified inception — distill a vague vision into a First-Principles spec with action/verification steps, then lock it as the active spec.
disable-model-invocation: false
---

# Skill: /vision <user_vision>

Triggered when the user types `/vision` followed by free-form text describing what they want built. Follow this protocol **exactly** — it is the only legitimate path from human intent to locked spec.

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

### Step 1 — Receive intent

The user has typed `/vision <free-form text>`. Treat the text as **intent**, not as a spec. Anchor cwd via `pwd` to capture `$PROJECT`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/...`), HALT.

### Step 2 — Feasibility audit (silent, internal)

Same as v0.3.x — refuse physically impossible requests; if multi-subsystem, ask which sub-problem to lock first. Do NOT draft or interrogate further until this is settled.

### Step 3 — Initialize the walker

Resume an existing walk if one is live for this spec, otherwise initialize a new one:

```bash
python3 - <<'PY'
import sys, pathlib
sys.path.insert(0, ".")
from bin import walker

walk_path = pathlib.Path("state/.walk.json")
state = walker.load(walk_path)
if state is None:
    state = walker.init_walk(
        spec_intent="""<verbatim user intent>""",
        spec_draft_path=pathlib.Path("specs/<slug>.spec.md.draft"),
    )
    walker.persist(state, walk_path)
print(f"WALK: {state.round_count} rounds, {len(state.pending)} pending, stop={state.stop_reason}")
PY
```

### Step 4 — Walk loop (interrogation)

Repeat until the walker reports stop:

1. **Read next concern.** `walker.next_concern(state)`. If `None`, walker is exhausted; jump to Step 5.

2. **Render the structured concern as a natural-language question.** The concern's `summary` field is canonical structured text. The skill phrases it so the user understands. The structured concern is the data; the question text is presentation. If the user says "this question makes no sense," the debug surface is `state/.walk.json`, not the rendered prose.

   Render format:
   ```
   ROUND <N> · id: <concern_id> · receiver: <receivers> · kind: <kind>
   <natural-language question derived from concern.summary>
   (answer, or `revise <concern_id>` to amend an earlier answer, or `stop` to lock the walk)
   ```

   On `revise` without an id, list every concern in `state.asked` as `<id> | <one-line summary> | <answer-truncated>` so the user can pick which to amend.

3. **Capture user input.** Three branches:

   - **`stop`** — set `state.stop_reason = "author-arbitrated"`, persist, jump to Step 5.
   - **`revise <concern_id> <new_answer>`** — call `walker.revise_answer(state, concern_id=..., new_answer=...)`. Display the returned `invalidated` list to the user. Ask: "These concerns are now stale: <list>. Re-walk them or accept-stale?" On `re-walk`, leave the stale ids in place (walker will skip stale concerns in `next_concern`); the walker's emit logic for new concerns is the v0.4.1 surface — for v0.4.0 the human types fresh answers as new concerns are surfaced naturally.
   - **Anything else** — treat as the answer to the current concern. Call `walker.record_answer(state, concern_id=concern.id, answer=<text>)`.

4. **Run the Tier 3 yield-delta check** (only if `~/.spectre/reviewer.toml` has `[tier3] enabled = true` AND we have an in-progress draft):

   ```bash
   python3 - <<'PY'
   import sys, pathlib
   sys.path.insert(0, ".")
   from bin import spec_evaluator, walker

   walk_path = pathlib.Path("state/.walk.json")
   state = walker.load(walk_path)
   draft_path = pathlib.Path("<spec-draft path>")
   if draft_path.exists() and state.round_count > 0:
       config = pathlib.Path.home() / ".spectre" / "reviewer.toml"
       result = spec_evaluator.evaluate(draft_path, config_path=config, bundle_persist_dir=pathlib.Path("state"))
       new_t3 = sum(1 for f in result.findings if f.tier == 3 and f.kind != "tier3-unavailable")
       state.yield_history.append(new_t3)
       walker.persist(state, walk_path)
       print(f"YIELD: {new_t3} new T3 findings this round; history={state.yield_history[-5:]}")
   PY
   ```

5. **Check stop conditions.** `stop, reason = walker.should_stop(state)`. If `True`, set `state.stop_reason = reason` (the function is pure — does not mutate), persist, and proceed to Step 5. If `False`, loop back to Step 4.1.

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
   - `refine "<change>"` — if the change implies revising a prior concern, invoke `walker.revise_answer` first, then re-render the draft. Otherwise, edit the draft directly and re-run §6.4 (existing v0.3.2 behavior).
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
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import setup_wizard
target = setup_wizard.config_path_default()
result = setup_wizard.maybe_provision(target)
print(f"WIZARD: {result} ({target})")
PY
```

Outcomes: `exists` (no-op), `enabled` (key found, user opted in), `declined` (key found, user opted out), `no-key` (no key anywhere — Tier 3 unavailable until user adds one and edits the TOML). After the wizard runs, `~/.spectre/reviewer.toml` is guaranteed to exist; §6.4 always passes that path to the evaluator.

### Step 6.4 — Pre-lock spec evaluator (CDLC Evaluate phase, v0.3+)

After the user replies `yes` (or `refine`), run the spec evaluator over a *review bundle* (preview ADRs + preview Resource nodes + preview tier classifications materialized but not committed). Tiers 1+2 always run (deterministic, local). Tier 3 (DeepSeek `deepseek-reasoner` adversarial reviewer) runs only when `~/.spectre/reviewer.toml` has `[tier3] enabled = true` AND the configured API key is present in the environment. When Tier 3 is unavailable for any reason, the evaluator emits an info-severity `tier3-unavailable` finding so the skip is **visible**, never silent.

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, ".")
from pathlib import Path
from bin import spec_evaluator

CONFIG = Path.home() / ".spectre" / "reviewer.toml"
result = spec_evaluator.evaluate(
    Path("specs/<slug>.spec.md.draft"),
    config_path=CONFIG,
    bundle_persist_dir=Path("state"),
)
out = [{
    "tier": f.tier, "kind": f.kind, "severity": f.severity,
    "scope": f.location.scope, "step": f.location.step,
    "ref": f.location.ref, "message": f.message, "fix": f.suggested_fix,
    "dismissable": f.dismissable,
} for f in result.findings]
print(json.dumps(out, indent=2))
print(f"TIERS_RUN: {result.sidecar_payload['tiers_run']}")
print(f"MAX_SEVERITY: {result.max_severity}")
PY
```

After running, surface a one-line tier status block before the findings:

```
tier 1: PASS (n findings)
tier 2: PASS (n findings)
tier 3: PASS (n findings)        # if tiers_run includes 3
tier 3: SKIPPED (<reason>)        # if a tier3-unavailable finding is present
```

Reasons for SKIPPED come from the `tier3-unavailable` finding's `message` field: `config-missing`, `disabled-in-config`, or `no-api-key`. The user should always see one line per tier — the goal is to make Tier 3 status as visible as Tiers 1 and 2.

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

The fingerprint is the SHA-256 hex from `bin.findings.fingerprint(f)` — printable from the JSON output above (compute it via `python3 -c "from bin import findings as F; ..."` if needed). Re-running §6.4 will skip the dismissed finding; the dismissal is recorded in the `.eval.json` sidecar after lock so audits can see what was suppressed and why.

`dismissable: false` findings (Tier 1+2 block-severity) CANNOT be dismissed via this mechanism — they must be fixed via `refine`.

### Step 6.5 — ADR generation (conditional)

Scan the locked spec's `## 2. First Principles` bullets and step `why:` lines for explicit decision markers. A decision marker is any line that:

- starts with `decision:` (case-insensitive), OR
- contains the phrase `we choose <X> because`, OR
- contains the phrase `<X> over <Y>` with a comparative justification.

For each decision found:

1. Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import adr
from pathlib import Path
p = adr.write_adr(
    Path("decisions"),
    title="<extracted decision title>",
    date="<today ISO>",
    body="<one paragraph: the decision + the why from the spec>",
    supersedes=None,  # set to "NNNN" only if this contradicts an existing ADR
)
print(f"ADR: {p}")
PY
```

2. **Supersedes detection.** Before writing each ADR, list `decisions/*.md` and look for an existing ADR whose title or body contradicts the new decision (e.g. new ADR says "Use Postgres 16" and an existing ADR says "Use SQLite"). If found, pass `supersedes="<old_id>"`. If unsure, do NOT supersede — false positives are worse than missing supersedes (a missed supersedes can be retro-fixed; a wrong supersedes invalidates downstream work).

3. **Graph wiring.** If `specs/.graph.md` exists AND both new and old ADRs are represented as nodes, run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, ".")
from bin import adr
from pathlib import Path
adr.update_graph_for_supersedes(
    Path("specs/.graph.md"),
    new_adr_id="adr-NNNN",
    old_adr_id="adr-MMMM",
)
PY
```

In v0.2.1 the graph manifest may not have ADR nodes yet. The `update_graph_for_supersedes` call is a no-op when nodes are absent, so it is safe to always invoke after a supersede write.

### Step 6.6 — Resource node inference (read from bundle)

The §6.4 evaluator already computed `preview_resources` in the bundle. Read that list (don't re-compute):

```bash
python3 - <<'PY'
import sys, json
sys.path.insert(0, ".")
from pathlib import Path
from bin import spec_evaluator, graph

draft = Path("specs/<slug>.spec.md.draft")
draft_text = draft.read_text(encoding="utf-8")
import hashlib
draft_sha = hashlib.sha256(draft_text.encode()).hexdigest()

bundle = spec_evaluator.load_persisted_bundle(
    Path("state/.eval-bundle.json"),
    draft_sha256=draft_sha,
    draft_path=draft,
)
if bundle is None:
    print("BUNDLE_MISMATCH: rebuilding")
    # Fallback: rebuild on the fly. Should not happen in normal flow.
    bundle = spec_evaluator.build_bundle(draft)

for r in bundle.preview_resources:
    print(f"{r['id']} ({r['kind']}:{r['identifier']})")
PY
```

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

3. Reset `$PROJECT/state/scratchpad.json` to:

   ```json
   {
     "version": 2,
     "active_mission": "specs/<slug>.spec.md",
     "tracks": {
       "<track or 'default'>": {
         "active_spec": "specs/<slug>.spec.md",
         "step": 1,
         "last_command": null,
         "exit_code": null,
         "delta": null,
         "timestamp": null,
         "failed_hypotheses": [],
         "paths_touched": [],
         "last_drift_check_step": 0,
         "last_audit_kinds": [],
         "last_audit_passed": null,
         "last_audit_failures": []
       }
     },
     "decisions_index": "decisions/",
     "graph_snapshot": "specs/.graph.md"
   }
   ```

   If the user invoked `/vision <track>`, use that track name; otherwise use `"default"`. Preserve any other tracks already in the scratchpad (read-modify-write via `bin/_scratchpad.save_track`).

4. **Write the `.eval.json` sidecar** (v0.3+, post-§6.4 evaluator). The evaluator's `result.sidecar_payload` carries the policy hash, tiers run, dismissals, findings summary, and DeepSeek model version. Persist next to the locked spec:

   ```bash
   python3 - <<'PY'
   import sys
   sys.path.insert(0, ".")
   from pathlib import Path
   from bin import eval_metadata, spec_evaluator

   draft = Path("specs/<slug>.spec.md.draft")  # already renamed to .spec.md by step 1
   spec = Path("specs/<slug>.spec.md")
   # Re-load sidecar_payload from the persisted bundle (or recompute via evaluate())
   # The cleanest path: the calling code captured `result.sidecar_payload` from §6.4.
   eval_metadata.write_sidecar(
       spec,
       evaluator_version=spec_evaluator.EVALUATOR_VERSION,
       tiers_run=result.sidecar_payload["tiers_run"],
       findings=result.findings,
       dismissals=result.sidecar_payload.get("dismissals", []),
       config_path=Path.home() / ".spectre" / "reviewer.toml",
       config_hash=result.sidecar_payload.get("config_hash"),
       deepseek_model_version=result.sidecar_payload.get("deepseek_model_version"),
       policy_hash=result.sidecar_payload["policy_hash"],
   )
   PY
   ```

5. **Clear the persisted bundle** — lock is complete, the bundle is no longer needed:

   ```bash
   python3 -c "from bin import spec_evaluator; from pathlib import Path; spec_evaluator.clear_bundle(Path('state/.eval-bundle.json'))"
   ```

### Step 7 — Transition signal

Print exactly:

```
VISION LOCKED: specs/<slug>.spec.md (step 1)
Architecture locked. Ready for /implement?
```

Do **not** auto-invoke `/implement`. The user types `/implement` when ready — this preserves the human's veto right between spec-lock and execution.
