"""One-shot v1 → v2 scratchpad migration. Idempotent. Stdlib only."""
import json
import sys
from pathlib import Path

# v1.1.1 Fix G: see bin/walker.py for the rationale on this sys.path shim.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bin import _scratchpad as sp  # noqa: E402


def migrate(path: Path) -> str:
    """Returns 'migrated' | 'noop' | 'created'."""
    path = Path(path)
    if not path.exists():
        sp.atomic_write(path, dict(sp.DEFAULT_V2))
        return "created"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"cannot parse scratchpad at {path}: {e}") from e
    if data.get("version") == 2:
        return "noop"
    new_data = sp.expand_v1_to_v2(data)
    sp.atomic_write(path, new_data)
    return "migrated"


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state/scratchpad.json")
    result = migrate(target)
    print(f"{result}: {target}")
