# Spectre — Design

**Date:** 2026-05-05
**Status:** Draft (awaiting user review)
**Repo:** `/home/joncik/apps/Spectre`

## 1. Problem

Claude Code's default auto-memory drifts during long sessions: spec-level intent gets buried under terminal scroll-back, and "what did I just change on disk" answers require re-reading logs that have already aged out of context. We want a deterministic state machine that survives long sessions and tool-call storms.

## 2. Goals & Non-Goals

**Goals**
- Deterministic re-hydration of the *one* active spec at session start.
- After every `Bash` call, inject a tight `Delta + Anchor` block — never raw logs.
- Persist physical state and negative knowledge ("what we tried that failed") on disk.
- `/vision` skill turns a vague vision into a `.spec.md` and atomically points `.active` at it.

**Non-Goals**
- Replacing Claude's own conversation memory.
- Hooking non-Bash tools (Edit, Read, Write, MCP). Strictly Bash, per the spec's "Ghost in the Machine" failure mode.
- Multi-spec parallel tracks. One active spec at a time.

## 3. Architecture

```
.claude-plugin/
  plugin.json                # manifest (hooks + skill registration)
bin/
  hydrate.py                 # SessionStart: read .active, print spec body
  compact.py                 # PostToolUse(Bash): stdin → additionalContext
  _scratchpad.py             # shared read/write helpers for state JSON
skills/
  vision.md                  # /vision <user_vision> → writes spec + flips .active
specs/
  .active                    # one line: relative path to active spec
  template.spec.md           # canonical structure
  *.spec.md                  # generated specs
state/
  scratchpad.json            # {last_command, exit_code, delta, failed_hypotheses[], step}
```

### 3.1 Hooks (Locked: Option B for both)

| Hook | Trigger | Script | Output contract |
|---|---|---|---|
| `SessionStart` | every session start | `bin/hydrate.py` | stdout = `--- ACTIVE SPEC: <path> ---\n<body>\n--- END ---` or fallback signal |
| `PostToolUse` (matcher: `Bash`) | after every Bash call | `bin/compact.py` | stdout = JSON `{additionalContext: "..."}` |

`PostToolUse` matcher is exactly `{"tool_name": "Bash"}` — never broader.

### 3.2 Hydrator (Option B — Active Pointer)

1. Read `specs/.active`. If missing → emit `SIGNAL: No active spec. Run /vision to begin.` plus `ls specs/*.spec.md` so the agent can offer choices.
2. If `.active` points to a missing file → emit `ERROR: stale .active pointer (<path>)` and the same `ls` fallback. Do **not** silently pick another spec.
3. If valid → print the **full** body of the active spec wrapped in delimiters. Atomic integrity: never truncate.
4. Also emit a one-line `STATE` summary from `state/scratchpad.json` (current step + last exit code) so the session resumes mid-mission.

### 3.3 Compactor (Option B — Delta + Anchor)

Stdin is the PostToolUse JSON event from Claude Code (contains `tool_input`, `tool_response.{stdout,stderr,exit_code}`).

Behavior:
1. Parse exit code, stdout tail (last 20 lines), stderr tail (last 20 lines).
2. Compute filesystem delta heuristically: parse common verbs from `tool_input.command` (`mkdir`, `touch`, `rm`, `mv`, `cp`, `git commit`, `apt install`, `pip install`, `npm install`, file redirects). If no heuristic matches, delta = `"unknown — see scratchpad"`.
3. Update `state/scratchpad.json` (atomic write via tmp+rename):
   - `last_command`, `exit_code`, `delta`, `timestamp`.
   - On non-zero exit: append a structured entry to `failed_hypotheses[]` with the first stderr line that looks like an error (regex: `^(Error|error|fatal|E:|FAIL|Traceback)`).
4. Emit JSON to stdout:
   ```json
   {
     "additionalContext": "COMMAND_RESULT: <code>\nSTATE_DELTA: <delta>\nANCHOR: Active Spec is '<path>'. Step <N>.\nNEXT: scratchpad.json updated. <failed_hypotheses count> negative-knowledge entries."
   }
   ```
5. **Intellectual honesty rule:** non-zero exit codes are NEVER softened to success. The exact stderr line goes into `failed_hypotheses[]` verbatim.

### 3.4 `/vision` Skill

`disable-model-invocation: false` (model can call it directly when user says "build me X").

Steps the skill prescribes:
1. Distill the vision into a `.spec.md` using the `template.spec.md` structure (Hard Problem, First Principles, Algorithm Audit, Success Criteria).
2. Slug the title → `specs/<slug>.spec.md`.
3. Write the file.
4. **Atomically** update `specs/.active` (write to `.active.tmp`, `os.replace` to `.active`) → no torn reads if a concurrent session starts.
5. Reset `state/scratchpad.json` to `{step: 1, failed_hypotheses: [], last_command: null, exit_code: null}`.

### 3.5 Scratchpad Schema

```json
{
  "active_spec": "specs/foo.spec.md",
  "step": 3,
  "last_command": "pytest tests/",
  "exit_code": 1,
  "delta": "no fs change",
  "timestamp": "2026-05-05T14:22:01Z",
  "failed_hypotheses": [
    {"step": 2, "command": "...", "error": "ModuleNotFoundError: foo", "ts": "..."}
  ]
}
```

`step` is incremented only by the `/vision` skill or by an explicit helper (out of scope for v1) — not by `compact.py`. `compact.py` is a pure reporter, not a stepper. This preserves determinism: step transitions are user-driven.

## 4. Failure Modes & Mitigations

| Mode | Mitigation |
|---|---|
| Broad PostToolUse matcher fires on every tool | Hard-coded matcher `{"tool_name": "Bash"}`; verified by integration test. |
| Hydrator blows context window | Active-spec-only injection; `ls` fallback when missing; spec template enforces ≤500 lines (advisory). |
| Recursive failure (plugin breaks itself) | `bin/*.py` are stdlib-only, no third-party imports; both scripts have a top-level `try/except` that prints a degraded-but-valid response so a buggy plugin never crashes a session. |
| Torn `.active` write during concurrent sessions | `os.replace` atomic rename. |
| Compactor inflates context with logs | 20-line tail cap on stdout/stderr; logs go to scratchpad, only the *summary* hits `additionalContext`. |
| Stale scratchpad after manual reset | Hydrator surfaces `STATE` line; user sees stale step number and can re-run `/vision`. |

## 5. Testing

- **Unit:** `pytest` covers `compact.py` parse/delta/honesty rules, `hydrate.py` three branches (active/missing/stale), atomic writes.
- **Integration:** dispatch a fake PostToolUse JSON event via stdin, assert stdout JSON shape.
- **Manual:** install the plugin in a throwaway dir, run a `/vision` cycle, run a few Bash commands (one passing, one failing), inspect scratchpad.

## 6. Success Criteria (from spec)

- ✅ Agent answers "current physical state?" from scratchpad without re-reading scroll-back.
- ✅ `/vision` produces a spec a human architect would approve.
- ✅ Active context usage stays bounded — `additionalContext` per Bash call ≤ 500 chars.
- ✅ Non-zero exit codes always surface as failures, never silently summarized.

## 7. Out of Scope (v1)

- Multi-spec stacking / branch-per-spec.
- Auto-stepping (compactor advancing `step`).
- Hooks for non-Bash tools.
- Token-budgeted hydration (revisit if active specs routinely exceed 500 lines).
