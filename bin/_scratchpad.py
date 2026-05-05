"""Atomic JSON read/write helpers for state/scratchpad.json. Stdlib only."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PATHS_TOUCHED_CAP = 200

DEFAULT = {
    "active_spec": None,
    "step": 1,
    "last_command": None,
    "exit_code": None,
    "delta": None,
    "timestamp": None,
    "failed_hypotheses": [],
    "paths_touched": [],
    "last_drift_check_step": 0,
    "last_audit_kinds": [],
    "last_audit_passed": None,
    "last_audit_failures": [],
}

DEFAULT_V2 = {
    "version": 2,
    "active_mission": None,
    "tracks": {},
    "decisions_index": "decisions/",
    "graph_snapshot": "specs/.graph.md",
}


def load(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return dict(DEFAULT)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT)


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_failed_hypothesis(path: Path, *, step: int, command: str, error: str) -> None:
    data = load(path)
    data.setdefault("failed_hypotheses", []).append({
        "step": step,
        "command": command,
        "error": error,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    atomic_write(path, data)


def track_default() -> dict[str, Any]:
    return {
        "active_spec": None,
        "step": 1,
        "last_command": None,
        "exit_code": None,
        "delta": None,
        "timestamp": None,
        "failed_hypotheses": [],
        "paths_touched": [],
        "last_drift_check_step": 0,
        "last_audit_kinds": [],
        "last_audit_passed": None,
        "last_audit_failures": [],
    }


def load_track(path: Path, track: str) -> dict[str, Any]:
    data = load(path)
    tracks = data.get("tracks", {})
    return tracks.get(track, track_default())


def save_track(path: Path, track: str, track_data: dict[str, Any]) -> None:
    data = load(path)
    if data.get("version") != 2:
        # First save into a v1 scratchpad → expand to v2 in place
        data = dict(DEFAULT_V2)
    data.setdefault("tracks", {})[track] = track_data
    atomic_write(path, data)
