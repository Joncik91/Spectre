---
description: Transforms a vague vision into a First-Principles spec and locks it as the active spec.
disable-model-invocation: false
---

# Skill: /vision <user_vision>

When invoked, follow these steps **exactly** — do not improvise structure.

## Inputs

`<user_vision>`: free-form text describing what the user wants built.

## Procedure

1. **Distill.** Read `<user_vision>` and produce these five fields:
   - **Title** (≤8 words)
   - **Hard Problem** (one paragraph: the non-obvious thing that makes this hard — no analogies)
   - **First Principles** (3-7 bullets: physical/logical constraints)
   - **Algorithm Audit** (Delete / Simplify / Accelerate)
   - **Steps** (numbered, 5-15 items, each one binary-verifiable)
   - **Success Criteria** (3-6 binary pass/fail checks)

2. **Slugify.** Lowercase the title, replace non-alphanumerics with `-`, collapse repeats, strip leading/trailing `-`. Example: "Real-Time Order Sync" → `real-time-order-sync`. Filename: `specs/<slug>.spec.md`.

3. **Write spec.** Use `specs/template.spec.md` as the structural skeleton. Fill in the five fields. Set the **Generated** field to today's ISO date and **Slug** to the computed slug.

4. **Atomically flip `.active`.** Write the relative path (e.g. `specs/<slug>.spec.md`) to `specs/.active.tmp`, then rename to `specs/.active`. Use a single Bash call:

   ```bash
   printf 'specs/<slug>.spec.md\n' > specs/.active.tmp && mv specs/.active.tmp specs/.active
   ```

5. **Reset scratchpad.** Overwrite `state/scratchpad.json` with:

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

6. **Confirm.** Print one line: `VISION LOCKED: specs/<slug>.spec.md (step 1)`.

## Hard rules

- One spec at a time. Never write two `.active` files.
- Never edit `step` here beyond resetting to 1.
- Never include hedging, "best practices," or industry-standard preambles in the spec body. Only first-principles content.
