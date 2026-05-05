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

When you draft the First-Principles Summary in Step 3, scan the symbol map for any function/class/module conceptually related to the user's vision (e.g. user wants "fetch BTC price" → search for `fetch`, `price`, `http`, `bitcoin`, `btc`, `requests`). If you find a candidate, surface it in the **Algorithm Audit (Delete)** section: "We will NOT reinvent `<symbol_name>` at `<file>:<line>` — we will reuse it as the basis for step N."

The "never reinvent the wheel" rule is enforced by construction here. Skipping Step 0 violates the rule silently.

### Step 1 — Receive

The user has typed `/vision <free-form text>`. Treat that text as the **Spark**, not the spec.

### Step 2 — Feasibility Audit (silent, internal)

Before drafting anything, evaluate:
- Is the request physically possible on the user's hardware/environment?
- Does it require breaking cryptography, exceeding network speed-of-light, time-traveling, or otherwise violating known constraints?
- Is the scope a single core hard problem, or is it 3+ unrelated subsystems?

If infeasible: halt and tell the user what's wrong. Do not draft a spec.
If multi-subsystem: tell the user the spec must be decomposed first; ask which sub-problem they want to lock in this round.

### Step 3 — Draft + Refinement Questions (multi-turn)

Output a **First-Principles Summary**:
- **Title** (≤8 words)
- **Hard Problem** (one paragraph, no analogies)
- **First Principles** (3-7 bullets — physical/logical constraints)
- **Algorithm Audit** (Delete / Simplify / Accelerate)
- **Speed-of-Light Limit** (one paragraph: the fastest version possible)
- **Physics Guardrails** (system invariants to preserve)

Then ask **2-3 Refinement Questions** about non-obvious edge cases. Examples of good questions:
- Persistence model (across reboot? session-only? user-namespaced?)
- Failure semantics (fail-closed vs fail-open?)
- Privilege boundary (root? user? sudoless?)
- Reversibility (idempotent? destructive?)

**Wait for the user's answers.** Do not continue until they respond.

### Step 4 — Draft Steps with why/action/verification triples

Once refinement is settled, draft the **Steps** section using the schema in `specs/template.spec.md`:

```yaml
- step: 1
  why: "<one-line first-principles justification — not analogy>"
  action: "<exact shell command>"
  verification: "<post-condition check command that exits 0 iff action succeeded>"
```

Rules for steps:
- **`why:` is mandatory.** It must be first-principles ("the byte sequence must persist on disk because the alias is invoked across shells") — never analogy ("this is how people usually do it"). If you can't articulate `why:`, the step shouldn't exist.
- Each `action` is a single shell command (chained with `&&` if atomic).
- Each `verification` is a separate command that proves the action's side effect. Examples:
  - `why: "Symlink resolves at kernel level — fastest possible aliasing primitive."`
    `action: ln -s /var/log/syslog /usr/local/bin/quick-log`
    `verification: "[ -L /usr/local/bin/quick-log ] && [ -e /usr/local/bin/quick-log ]"`
  - `why: "HTTP client must be importable in the runtime; pip install is the standard delivery path."`
    `action: pip install requests`
    `verification: python3 -c 'import requests'`
- 5-15 steps. If you need more, the spec is too big — decompose first.
- No "soft" verifications (`echo done`, `true`). They must observably check the action's effect.
- **Do not lock the spec if any step is missing `why:`.** Reject your own draft and iterate.

### Step 5 — Confirm with the user

Show the full draft (Hard Problem, First Principles, ..., Steps, Success Criteria). Ask:

> "Lock this as the active spec? (yes / refine / cancel)"

- `yes` → proceed to Step 6.
- `refine` → adjust per their feedback, repeat Step 5.
- `cancel` → halt, write nothing.

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
   - `yes` → continue to Step 6.5.
   - `refine "<change>"` → reopen the draft file, apply the requested change, atomically rewrite the .draft file, re-emit the one-line confirmation. Repeat until `yes`.
   - `cancel` → delete the .draft file, halt, write nothing else.

The draft-to-disk pattern eliminates the double-token-output friction (printing the full spec inline AND writing the file). The user reviews in their editor; we hold the spec in disk-only state until confirmed.

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
   ```

### Step 7 — Transition signal

Print exactly:

```
VISION LOCKED: specs/<slug>.spec.md (step 1)
Architecture locked. Ready for /implement?
```

Do **not** auto-invoke `/implement`. The user types `/implement` when ready — this preserves the human's veto right between spec-lock and execution.
