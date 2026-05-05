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

### Step 4 — Draft Steps with action/verification pairs

Once refinement is settled, draft the **Steps** section using the schema in `specs/template.spec.md`:

```yaml
- step: 1
  action: "<exact shell command>"
  verification: "<post-condition check command that exits 0 iff action succeeded>"
```

Rules for steps:
- Each `action` is a single shell command (chained with `&&` if atomic).
- Each `verification` is a separate command that proves the action's side effect. Examples:
  - `action: ln -s /var/log/syslog /usr/local/bin/quick-log`
    `verification: "[ -L /usr/local/bin/quick-log ] && [ -e /usr/local/bin/quick-log ]"`
  - `action: pip install requests`
    `verification: python3 -c 'import requests'`
- 5-15 steps. If you need more, the spec is too big — decompose first.
- No "soft" verifications (`echo done`, `true`). They must observably check the action's effect.

### Step 5 — Confirm with the user

Show the full draft (Hard Problem, First Principles, ..., Steps, Success Criteria). Ask:

> "Lock this as the active spec? (yes / refine / cancel)"

- `yes` → proceed to Step 6.
- `refine` → adjust per their feedback, repeat Step 5.
- `cancel` → halt, write nothing.

### Step 6 — Slugify + Write + Lock

1. **Anchor to the user's project cwd FIRST.** Run `pwd` to capture the absolute path (e.g. `/home/foo/myproject`). Call this `$PROJECT`. All file paths in the rest of this step are `$PROJECT/specs/...` and `$PROJECT/state/...`. If `$PROJECT` looks like a plugin cache (`/root/.claude/plugins/`, `${CLAUDE_PLUGIN_ROOT}`, or contains `plugins/cache/`), HALT and tell the user to restart Claude Code from their project directory.
2. `mkdir -p "$PROJECT/specs" "$PROJECT/state"` to ensure the dirs exist.
3. Slugify the title: lowercase, replace non-alphanumerics with `-`, collapse repeats, strip leading/trailing `-`.
4. Filename: `$PROJECT/specs/<slug>.spec.md`.
5. Set frontmatter `Generated:` to today's ISO date and `Slug:` to the computed slug.
6. Write the spec file at the absolute path.
7. Atomically flip `.active`:

   ```bash
   printf 'specs/<slug>.spec.md\n' > "$PROJECT/specs/.active.tmp" && mv "$PROJECT/specs/.active.tmp" "$PROJECT/specs/.active"
   ```

8. Reset `$PROJECT/state/scratchpad.json` to:

   ```json
   {
     "active_spec": "specs/<slug>.spec.md",
     "step": 1,
     "last_command": null,
     "exit_code": null,
     "delta": null,
     "timestamp": null,
     "failed_hypotheses": []
   }
   ```

### Step 7 — Transition signal

Print exactly:

```
VISION LOCKED: specs/<slug>.spec.md (step 1)
Architecture locked. Ready for /implement?
```

Do **not** auto-invoke `/implement`. The user types `/implement` when ready — this preserves the human's veto right between spec-lock and execution.
