# SDL Vision Engine

A Claude Code plugin that turns spec-driven development into a deterministic state machine.

It hijacks two lifecycle events:

- **SessionStart** → `bin/hydrate.py` reads `specs/.active` and re-injects the one currently-active spec into Claude's context. No mtime guessing, no implicit selection — an explicit pointer is the instruction register.
- **PostToolUse(Bash)** → `bin/compact.py` reads the Bash tool result, computes a filesystem-delta heuristic, updates `state/scratchpad.json`, and emits a compact `Delta + Anchor` block back as `additionalContext`. Raw terminal scroll-back never re-enters the conversation.

The `/vision` skill turns a vague vision into a `.spec.md`, atomically flips `specs/.active`, and resets the scratchpad. One spec at a time, ever.

**Requires:** Python 3.11+ (PEP 604 `str | None`, PEP 585 `dict[str, Any]`). Stdlib only — no third-party imports in production code.

## Install

Symlink or copy the repo into your Claude Code plugins directory. The manifest at `.claude-plugin/plugin.json` registers the two hooks and the `/vision` skill.

```bash
ln -s /path/to/Spectre ~/.claude/plugins/sdl-vision-engine
```

Restart your Claude Code session. SessionStart will fire `hydrate.py`; if no `.active` exists yet, you'll see `SIGNAL: No active spec. Run /vision to begin.`

## Use

1. **`/vision <free-form description>`** — Claude distills the request into a first-principles spec under `specs/<slug>.spec.md`, then atomically points `.active` at it and zeroes the scratchpad.
2. **Work normally.** Every Bash call you (or Claude) make produces a tight `Delta + Anchor` summary in context — never the full log.
3. **Across sessions** — re-launch Claude Code. The hydrator re-injects the same active spec; you resume mid-mission with the scratchpad's `step`, `last_command`, `exit_code`, and accumulated `failed_hypotheses` intact.

To switch missions, run `/vision` again with a new description; the previous spec stays on disk but `.active` flips to the new one.

## Layout

```
.claude-plugin/plugin.json   # manifest (hooks + skill)
bin/hydrate.py               # SessionStart: emit active spec body
bin/compact.py               # PostToolUse(Bash): emit additionalContext
bin/_scratchpad.py           # atomic JSON helpers (stdlib only)
skills/vision.md             # /vision <text> slash skill
specs/template.spec.md       # canonical spec structure
specs/.active                # one-line pointer (gitignored)
specs/<slug>.spec.md         # generated specs (gitignored)
state/scratchpad.json        # physical state + failed_hypotheses (gitignored)
docs/superpowers/specs/      # design doc
docs/superpowers/plans/      # implementation plan
tests/                       # 28 tests (pytest)
```

## What gets injected

**SessionStart hydration** (`hydrate.py` stdout):

```
--- ACTIVE SPEC: specs/order-sync.spec.md ---
<full spec body>
--- END ACTIVE SPEC ---
STATE: step=3 exit_code=0 last_command='pytest tests/'
```

If `.active` is missing or stale, the hydrator emits a `SIGNAL:` or `ERROR:` line plus a list of available specs — never silently picks an alternate.

**Per-Bash `additionalContext`** (`compact.py` stdout, capped under ~500 chars for typical commands):

```json
{"additionalContext": "COMMAND_RESULT: 1\nSTATE_DELTA: pytest\nANCHOR: Active Spec is 'specs/order-sync.spec.md'. Step 3.\nNEXT: scratchpad.json updated. 2 negative-knowledge entries."}
```

Non-zero exit codes are never softened. The first matching error line (`^(Error|error|fatal|E:|FAIL|Traceback)`) gets appended verbatim to `failed_hypotheses[]` so the agent accumulates negative knowledge over the session — what was tried, what broke, what the actual error said.

## Scratchpad schema

```json
{
  "active_spec": "specs/<slug>.spec.md",
  "step": 3,
  "last_command": "pytest tests/",
  "exit_code": 1,
  "delta": "pytest",
  "timestamp": "2026-05-05T14:22:01+00:00",
  "failed_hypotheses": [
    {"step": 2, "command": "pytest", "error": "ModuleNotFoundError: foo", "ts": "..."}
  ]
}
```

`step` is user-driven (set by `/vision`, advanced by you explicitly) — `compact.py` never increments it. This preserves determinism: the agent reports physical state, the human owns the instruction pointer.

## Failure modes (mitigated by design)

| Mode | Mitigation |
|---|---|
| Broad `PostToolUse` matcher catches every tool | Manifest matcher is the literal string `"Bash"`; `tests/test_manifest.py` asserts equality. |
| Hydrator bloat exceeds context window | Single-active-spec model. `ls`-fallback when missing or stale, never silent substitution. |
| Recursive failure (plugin breaks itself) | Both scripts have top-level `try/except`; stdlib-only; atomic writes via `tempfile.mkstemp` + `os.replace`. |
| Torn `.active` write under concurrency | The `/vision` skill writes to `.active.tmp` then renames — POSIX-atomic. |
| Compactor inflates context with logs | Logs go to scratchpad; only the heuristic delta + anchor hit `additionalContext`. |

## Develop

```bash
pytest tests/ -v        # 28 tests, ~0.45s
```

Test layout: `test_scratchpad.py` (atomic-write semantics + failure-branch coverage), `test_hydrate.py` (three branches: active / missing / stale), `test_compact.py` (delta heuristics + intellectual-honesty + scratchpad persistence + 500-char cap), `test_manifest.py` (Bash-only matcher locked), `test_e2e.py` (full hydrate → spec → compact-pass → compact-fail cycle).

## Status

v1.0.0 — all 28 tests green. The `/vision` skill is model-driven and not exercised by automated tests; manual smoke-test it once before relying on it in long missions. Manifest schema verified against the official Claude Code plugin docs (string matcher, `name` field, no `matcher` wrapper on `SessionStart`).
