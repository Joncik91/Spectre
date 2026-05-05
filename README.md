# SDL Vision Engine

Claude Code plugin: deterministic spec hydration + post-Bash delta/anchor injection.

**Requires:** Python 3.11+ (uses PEP 604 `str | None` and PEP 585 `dict[str, Any]` syntax).

## Install

Symlink or copy this directory into your Claude Code plugins path. The manifest at `.claude-plugin/plugin.json` registers two hooks and one skill.

## Layout

- `.claude-plugin/plugin.json` — manifest
- `bin/hydrate.py` — SessionStart: emits the active spec body
- `bin/compact.py` — PostToolUse(Bash): emits `additionalContext` JSON
- `skills/vision.md` — `/vision <text>` slash skill
- `specs/.active` — one-line pointer to current spec
- `state/scratchpad.json` — physical state + failed_hypotheses

## Test

`pytest tests/ -v`
