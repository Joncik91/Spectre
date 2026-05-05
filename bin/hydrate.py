#!/usr/bin/env python3
"""SessionStart hook: print the active spec body or a fallback signal."""
import sys
from pathlib import Path

# Allow running both as `python3 bin/hydrate.py` and via shebang.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bin import _scratchpad as sp  # noqa: E402
from bin import migrate_scratchpad_v1_to_v2 as _mig  # noqa: E402

SPECS = Path("specs")
ACTIVE = SPECS / ".active"
SCRATCH = Path("state") / "scratchpad.json"


def list_specs() -> str:
    if not SPECS.exists():
        return "(no specs/ directory)"
    files = sorted(p.name for p in SPECS.glob("*.spec.md"))
    return "\n".join(f"  - specs/{f}" for f in files) or "  (no spec files)"


def state_line() -> str:
    data = sp.load(SCRATCH)
    # Handle both v1 (top-level fields) and v2 (tracks.default) formats.
    if data.get("version") == 2:
        track = data.get("tracks", {}).get("default", {})
    else:
        track = data
    return (
        f"STATE: step={track.get('step')} "
        f"exit_code={track.get('exit_code')} "
        f"last_command={track.get('last_command')!r}"
    )


def main() -> int:
    # Auto-migrate v1 scratchpad on SessionStart, regardless of .active state.
    _result = _mig.migrate(SCRATCH)
    if _result == "migrated":
        print("MIGRATED: scratchpad v1 → v2 (existing track moved to 'default').")

    if not ACTIVE.exists():
        print("SIGNAL: No active spec. Run /vision to begin.")
        print("Available specs:")
        print(list_specs())
        print(state_line())
        return 0

    target = ACTIVE.read_text(encoding="utf-8").strip()
    target_path = Path(target)
    if not target_path.exists():
        print(f"ERROR: stale .active pointer ({target})")
        print("Available specs:")
        print(list_specs())
        print(state_line())
        return 0

    body = target_path.read_text(encoding="utf-8")
    print(f"--- ACTIVE SPEC: {target} ---")
    print(body, end="")
    if not body.endswith("\n"):
        print()
    print("--- END ACTIVE SPEC ---")
    print(state_line())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SIGNAL: hydrator error: {exc}")
        sys.exit(0)
