# spectre

> SDL Vision Engine — a Claude Code plugin for deterministic spec hydration and post-Bash Delta+Anchor injection.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [API](#api)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

Default Claude Code auto-memory drifts during long sessions: spec-level intent gets buried under terminal scroll-back, and "what did I just change on disk" answers require re-reading logs that have already aged out of context.

Spectre overrides this with a deterministic state machine that drives an unbroken vision → spec → implement → verify chain:

- `SessionStart` → `bin/hydrate.py` reads `specs/.active` (an explicit instruction-pointer file) and re-injects the one currently-active spec. No mtime guessing.
- `PostToolUse(Bash)` → `bin/compact.py` reads the Bash result, computes a filesystem-delta heuristic, updates `state/scratchpad.json`, emits a `Delta + Anchor` block as `additionalContext`. Raw logs never re-enter context.
- `/vision` skill → multi-turn inception: distills a vague vision into a `.spec.md` with explicit `action:`/`verification:` per step, atomically flips `.active`, resets the scratchpad. Includes a Feasibility Audit; refuses physically impossible visions.
- `/implement` skill → state-aware execution: reads the active spec, runs the next step's `action`, gates on its `verification`, applies one Option B retry with diagnosis on fail, advances `step` on pass. Pre-flight re-verifies the previous step to catch root-state desync.

Five named failure modes — broad matcher, hydrator bloat, recursive failure, torn writes, log inflation — each have a code-level mitigation and a test.

## Install

Requires Python 3.11+ (PEP 604 / PEP 585 syntax). Stdlib only — no third-party imports in production code.

**Recommended — via Claude Code marketplace:**

```text
/plugins
→ Browse Marketplaces
→ Add Marketplace: https://github.com/Joncik91/Spectre
→ Install: sdl-vision-engine
```

The repo ships its own `.claude-plugin/marketplace.json` so the GitHub URL is also the marketplace URL.

**Manual symlink (for local development):**

```bash
git clone https://github.com/Joncik91/Spectre.git
ln -s "$PWD/Spectre" ~/.claude/plugins/sdl-vision-engine
```

Restart Claude Code. SessionStart fires `hydrate.py`; with no `.active` yet you'll see `SIGNAL: No active spec. Run /vision to begin.`

## Usage

```bash
# In a Claude Code session:
/vision Build a real-time order sync between Shopify and our warehouse
# → Claude returns a First-Principles Summary + 2-3 refinement questions.
# → After you answer, Claude drafts the full spec (action/verification per step).
# → On confirmation, .active is locked and the scratchpad resets.

/implement
# → Reads the active spec, runs Step N's action, then its verification.
# → On verification fail: one diagnosis + corrected action proposal (Option B).
# → On pass: scratchpad step advances. Halts; you run /implement again for Step N+1.

/implement check
# → Re-runs the current step's verification only. No execution, no scratchpad write.
```

Across sessions, the hydrator re-injects the same active spec and the scratchpad's `step` — you resume mid-mission. To switch missions, run `/vision` again.

Run the test suite:

```bash
pytest tests/ -v   # 28 tests, ~0.5s
```

## API

### Hooks (registered by `.claude-plugin/plugin.json`)

| Event | Command | Output |
|---|---|---|
| `SessionStart` | `python3 bin/hydrate.py` | stdout: active spec body wrapped in `--- ACTIVE SPEC ---` markers, plus `STATE:` line. Or `SIGNAL:` / `ERROR:` fallback. |
| `PostToolUse` (matcher: `"Bash"`) | `python3 bin/compact.py` | stdout: JSON `{"additionalContext": "..."}`. |

### Skills

| Skill | Purpose |
|---|---|
| `/vision <text>` | Multi-turn inception. Feasibility audit → First-Principles draft → 2-3 refinement Qs → action/verification step pairs → atomic `.active` flip + scratchpad reset. Defined in `skills/vision.md`. |
| `/implement` | Run the active spec's next step. Action → verification gate → Option B retry on fail (one diagnosis + corrected action) → advance `step` on pass. Halts on missing-binary errors, spec gaps, or root-state desync. Defined in `skills/implement.md`. |
| `/implement check` | Re-run the current step's verification only. No execution, no advance. |

### Spec step schema

Each step in a generated spec is an atomic transaction:

```yaml
- step: 1
  action: "ln -sf /var/log/syslog /usr/local/bin/quick-log"
  verification: "[ -L /usr/local/bin/quick-log ] && [ -e /usr/local/bin/quick-log ]"
```

The `verification` command is canonical — `/implement` may retry the `action` but never the `verification`. Soft verifications (`echo done`, `true`) are forbidden by `/vision`'s rules.

### `additionalContext` payload (per Bash call)

```text
COMMAND_RESULT: <exit_code>
STATE_DELTA: <heuristic delta>
ANCHOR: Active Spec is '<path>'. Step <N>.
NEXT: scratchpad.json updated. <count> negative-knowledge entries.
```

Capped under ~500 chars for typical commands. Non-zero exits append to `failed_hypotheses[]` with the first matching error line (`^(Error|error|fatal|E:|FAIL|Traceback)`) — never softened.

### Scratchpad schema (`state/scratchpad.json`)

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

`step` is user-driven — `compact.py` reports state but never advances it.

### Layout

```text
.claude-plugin/plugin.json     plugin manifest (metadata only)
.claude-plugin/marketplace.json marketplace manifest (self-hosted)
hooks/hooks.json               hook bindings (uses ${CLAUDE_PLUGIN_ROOT})
bin/hydrate.py                 SessionStart command
bin/compact.py                 PostToolUse(Bash) command
bin/_scratchpad.py             atomic JSON helpers
skills/vision/SKILL.md         /vision slash skill
skills/implement/SKILL.md      /implement slash skill
specs/template.spec.md         canonical spec structure (action/verification schema)
tests/                         30 pytest tests
docs/superpowers/              design + plan
```

## Maintainers

[@Joncik91](https://github.com/Joncik91)

## Contributing

Issues and PRs welcome. This README follows the [Standard-Readme](https://github.com/RichardLitt/standard-readme) spec.

## License

[MIT](./LICENSE) © Joncik91
