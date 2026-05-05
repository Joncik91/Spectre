"""One-shot v1 → v2 scratchpad migration. Idempotent. Stdlib only."""
import json
from pathlib import Path
from bin import _scratchpad as sp


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
    # v1 shape: move top-level fields to tracks.default
    track_data = sp.track_default()
    for k in track_data:
        if k in data:
            track_data[k] = data[k]
    new_data = {
        "version": 2,
        "active_mission": None,
        "tracks": {},
        "decisions_index": "decisions/",
        "graph_snapshot": "specs/.graph.md",
    }
    new_data["tracks"]["default"] = track_data
    if "active_spec" in data:
        new_data["active_mission"] = data["active_spec"]
    sp.atomic_write(path, new_data)
    return "migrated"


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state/scratchpad.json")
    result = migrate(target)
    print(f"{result}: {target}")
