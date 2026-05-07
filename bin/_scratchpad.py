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
        "venv_python": None,
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

    Legacy ``venv_python`` at top-level is migrated into the track dict so it
    is not lost during v1→v2 promotion.
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
    # Migrate legacy top-level venv_python into the track.
    if "venv_python" in v1 and not legacy.get("venv_python"):
        legacy["venv_python"] = v1["venv_python"]
        consumed.add("venv_python")
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


# ── CLI entrypoint ────────────────────────────────────────────────────────────


def _set_pending_adoption_prompt(
    scratchpad_path: Path,
    *,
    track: str,
    fingerprint: str,
    label: str,
    action: str,
) -> None:
    """Persist the §3.5 pending_adoption_prompt structured field to the track.

    Auto-promotes v1 → v2 if needed. Atomic write. Used by the implement skill
    to survive session restart / mid-execution compact between §3.5 and §6.
    """
    data = load(scratchpad_path)
    if data.get("version") != 2:
        data = expand_v1_to_v2(data)
    tracks = data.get("tracks")
    if not isinstance(tracks, dict):
        tracks = {}
    track_state = tracks.get(track) or track_default()
    track_state["pending_adoption_prompt"] = {
        "fingerprint": fingerprint,
        "label": label,
        "action": action,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    tracks[track] = track_state
    data["tracks"] = tracks
    atomic_write(scratchpad_path, data)


def _get_pending_adoption_prompt(
    scratchpad_path: Path, *, track: str
) -> dict[str, Any] | None:
    """Read the track's pending_adoption_prompt or None if absent."""
    data = load(scratchpad_path)
    tracks = data.get("tracks") or {}
    track_state = tracks.get(track) or {}
    return track_state.get("pending_adoption_prompt")


def _clear_pending_adoption_prompt(scratchpad_path: Path, *, track: str) -> bool:
    """Set the track's pending_adoption_prompt to None. Returns True if the
    track existed (write happened); False otherwise (no-op)."""
    data = load(scratchpad_path)
    tracks = data.get("tracks") or {}
    if track not in tracks:
        return False
    tracks[track]["pending_adoption_prompt"] = None
    data["tracks"] = tracks
    atomic_write(scratchpad_path, data)
    return True


def _reset_scratchpad(scratchpad_path: Path, *, active_spec: str) -> None:
    """Atomic write of a fresh v2 scratchpad with active_spec set.

    All track fields are set to their null/empty defaults.  Used by the
    /vision lock step so the agent never hand-rolls a v2 dict.
    """
    fresh_track = track_default()
    fresh_track["active_spec"] = active_spec
    new_data = dict(DEFAULT_V2)
    new_data["active_mission"] = active_spec
    new_data["tracks"] = {"default": fresh_track}
    atomic_write(scratchpad_path, new_data)


def _ensure_v2(scratchpad_path: Path) -> str:
    """Idempotent v1 → v2 migration.

    Returns 'migrated' | 'noop' | 'created'.
    Raises ValueError on malformed JSON (caller should exit 1).
    """
    path = Path(scratchpad_path)
    if not path.exists():
        atomic_write(path, dict(DEFAULT_V2))
        return "created"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON in {path}: {exc}") from exc
    if data.get("version") == 2:
        return "noop"
    new_data = expand_v1_to_v2(data)
    atomic_write(path, new_data)
    return "migrated"


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="_scratchpad",
        description=(
            "Scratchpad CLI — reset/ensure-v2 and set/get/clear pending_adoption_prompt."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    common_path = dict(
        default="state/scratchpad.json",
        help="Path to scratchpad.json (default: state/scratchpad.json).",
    )

    p_reset = sub.add_parser(
        "reset",
        help=(
            "Atomic write of a fresh v2 scratchpad with active_spec set. "
            "All track fields are null/empty defaults. Safe to call against v1 files."
        ),
    )
    p_reset.add_argument("--scratchpad", **common_path)
    p_reset.add_argument(
        "--active-spec",
        required=True,
        help="Path to the spec file to set as active_mission (e.g. specs/foo.spec.md).",
    )

    p_ev2 = sub.add_parser(
        "ensure-v2",
        help=(
            "Idempotent v1 → v2 migration. No-op if already v2. "
            "Creates a fresh v2 default if the file is missing. Exits 1 on malformed JSON."
        ),
    )
    p_ev2.add_argument("--scratchpad", **common_path)

    p_set = sub.add_parser(
        "set-pending-adoption",
        help=(
            "Persist pending_adoption_prompt = {fingerprint, label, action, "
            "recorded_at} to tracks.<track>. Atomic write; auto-promotes v1→v2."
        ),
    )
    p_set.add_argument("--scratchpad", **common_path)
    p_set.add_argument("--track", default="default", help="Track name (default: 'default').")
    p_set.add_argument("--fingerprint", required=True, help="Halt fingerprint (hex).")
    p_set.add_argument("--label", required=True, help="Classifier label.")
    p_set.add_argument("--action", required=True, help="Action text.")

    p_get = sub.add_parser(
        "get-pending-adoption",
        help=(
            "Print 'NO_PENDING_PROMPT' or "
            "'PROMPT: fp=<fp[:12]>... label=<label>'."
        ),
    )
    p_get.add_argument("--scratchpad", **common_path)
    p_get.add_argument("--track", default="default", help="Track name (default: 'default').")
    p_get.add_argument(
        "--json",
        action="store_true",
        help="Emit the full prompt dict as JSON (or 'null' when absent).",
    )

    p_clr = sub.add_parser(
        "clear-pending-adoption",
        help="Set tracks.<track>.pending_adoption_prompt = None and atomic-write.",
    )
    p_clr.add_argument("--scratchpad", **common_path)
    p_clr.add_argument("--track", default="default", help="Track name (default: 'default').")

    args = parser.parse_args()

    sp_path = Path(args.scratchpad)

    if args.cmd == "reset":
        try:
            _reset_scratchpad(sp_path, active_spec=args.active_spec)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"SCRATCHPAD_RESET: v2 written, active_spec={args.active_spec}")

    elif args.cmd == "ensure-v2":
        try:
            result = _ensure_v2(sp_path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"ENSURE_V2: {result}")

    elif args.cmd == "set-pending-adoption":
        try:
            _set_pending_adoption_prompt(
                sp_path,
                track=args.track,
                fingerprint=args.fingerprint,
                label=args.label,
                action=args.action,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"PENDING_ADOPTION_PROMPT_PERSISTED: {args.fingerprint[:12]}...")

    elif args.cmd == "get-pending-adoption":
        try:
            prompt = _get_pending_adoption_prompt(sp_path, track=args.track)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            import json as _json

            print(_json.dumps(prompt, indent=2))
        else:
            if not prompt:
                print("NO_PENDING_PROMPT")
            else:
                fp = prompt.get("fingerprint", "")
                label = prompt.get("label", "")
                print(f"PROMPT: fp={fp[:12]}... label={label}")

    elif args.cmd == "clear-pending-adoption":
        try:
            wrote = _clear_pending_adoption_prompt(sp_path, track=args.track)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if wrote:
            print("PROMPT_CLEARED")
        else:
            print("NO_TRACK_TO_CLEAR")
