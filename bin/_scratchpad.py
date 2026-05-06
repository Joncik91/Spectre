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
    "pending_findings": [],
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
        "pending_adoption_prompt": None,
    }


def load_track(path: Path, track: str) -> dict[str, Any]:
    data = load(path)
    tracks = data.get("tracks") or {}
    return tracks.get(track, track_default())


_V2_RESERVED_TOP_KEYS = {"version", "active_mission", "tracks", "decisions_index", "graph_snapshot"}


def expand_v1_to_v2(v1: dict[str, Any]) -> dict[str, Any]:
    """Promote v1 top-level fields into tracks.default, preserving in-flight state.

    Unknown v1 keys (not in track_default and not v2-reserved) survive under
    tracks.default._v1_unknown so user-authored fields are not silently dropped.
    """
    new_data = dict(DEFAULT_V2)
    new_data["tracks"] = {}
    legacy = track_default()
    consumed: set[str] = set()
    for k in legacy:
        if k in v1:
            legacy[k] = v1[k]
            consumed.add(k)
    if v1.get("active_spec"):
        new_data["active_mission"] = v1["active_spec"]
    unknown = {
        k: v for k, v in v1.items()
        if k not in consumed and k not in _V2_RESERVED_TOP_KEYS and k != "active_spec"
    }
    if unknown:
        legacy["_v1_unknown"] = unknown
    new_data["tracks"]["default"] = legacy
    return new_data


# Backward-compat alias (was the private name in earlier commits)
_expand_v1_to_v2 = expand_v1_to_v2


def get_paths_touched(data: dict[str, Any], track: str = "default") -> list[str]:
    """Return paths_touched for *track* from a loaded scratchpad dict.

    Handles both schema versions:
    - v2: data["tracks"][track]["paths_touched"]
    - v1: data["paths_touched"]  (top-level)

    Returns [] when neither key is present — never raises.
    """
    # v2 path (preferred)
    tracks = data.get("tracks")
    if isinstance(tracks, dict):
        track_data = tracks.get(track, {})
        v2_val = track_data.get("paths_touched")
        if isinstance(v2_val, list):
            return v2_val
    # v1 fallback (top-level)
    v1_val = data.get("paths_touched")
    if isinstance(v1_val, list):
        return v1_val
    return []


def save_track(path: Path, track: str, track_data: dict[str, Any]) -> None:
    data = load(path)
    if data.get("version") != 2:
        data = expand_v1_to_v2(data)
    if not isinstance(data.get("tracks"), dict):
        data["tracks"] = {}
    data["tracks"][track] = track_data
    atomic_write(path, data)
