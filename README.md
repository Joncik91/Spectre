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

Spectre overrides this with a deterministic state machine:

- `SessionStart` → `bin/hydrate.py` reads `specs/.active` (an explicit instruction-pointer file) and re-injects the one currently-active spec. No mtime guessing.
- `PostToolUse(Bash)` → `bin/compact.py` reads the Bash result, computes a filesystem-delta heuristic, updates `state/scratchpad.json`, emits a `Delta + Anchor` block as `additionalContext`. Raw logs never re-enter context.
- `/vision` skill → distills a vague vision into a `.spec.md`, atomically flips `.active`, resets the scratchpad. One spec at a time.

Five named failure modes — broad matcher, hydrator bloat, recursive failure, torn writes, log inflation — each have a code-level mitigation and a test.

## Install

Requires Python 3.11+ (PEP 604 / PEP 585 syntax). Stdlib only — no third-party imports in production code.

```bash
git clone https://github.com/Joncik91/Spectre.git
ln -s "$PWD/Spectre" ~/.claude/plugins/sdl-vision-engine
```

Restart Claude Code. SessionStart fires `hydrate.py`; with no `.active` yet you'll see `SIGNAL: No active spec. Run /vision to begin.`

## Usage

```bash
# In a Claude Code session:
/vision Build a real-time order sync between Shopify and our warehouse

# Then work normally — every Bash call produces a tight Delta+Anchor in context.
# Across sessions, the hydrator re-injects the same active spec; you resume mid-mission.
```

To switch missions, run `/vision` again. The previous spec stays on disk; `.active` flips.

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

### Skill

`/vision <free-form description>` — distill, write `specs/<slug>.spec.md`, atomically flip `specs/.active`, reset `state/scratchpad.json`. Defined in `skills/vision.md`.

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
.claude-plugin/plugin.json   manifest (hooks + skill)
bin/hydrate.py               SessionStart hook
bin/compact.py               PostToolUse(Bash) hook
bin/_scratchpad.py           atomic JSON helpers
skills/vision.md             /vision slash skill
specs/template.spec.md       canonical spec structure
tests/                       28 pytest tests
docs/superpowers/            design + plan
```

## Maintainers

[@Joncik91](https://github.com/Joncik91)

## Contributing

Issues and PRs welcome. This README follows the [Standard-Readme](https://github.com/RichardLitt/standard-readme) spec.

## License

Unlicensed — private repo, all rights reserved by the maintainer.
