"""Per-project CDLC transition log. Stdlib only.

Records every Generate→Test→Lock→Implement→Halt→Adapt transition with
timestamps and structured payloads. The log is per-project (lives in
state/cdlc-ledger.json), append-only, atomically written. Read-only audit
surface — there is no user-facing command, the user reads the file directly.

Design: docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md §6.5.

Public API:
    LEDGER_VERSION
    KNOWN_TRANSITION_KINDS
    cdlc_ledger_path_default(project_path) -> pathlib.Path
    append_transition(*, kind, payload, project_path) -> None
    read_ledger(*, project_path) -> list[dict]
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone

LEDGER_VERSION = "0.4.2"
KNOWN_TRANSITION_KINDS: tuple[str, ...] = (
    "generate", "test", "lock", "implement", "halt", "adapt",
)


def cdlc_ledger_path_default(project_path: pathlib.Path) -> pathlib.Path:
    """Return the canonical ledger path for a project."""
    return pathlib.Path(project_path) / "state" / "cdlc-ledger.json"


def append_transition(
    *,
    kind: str,
    payload: dict,
    project_path: pathlib.Path,
) -> None:
    """Append a transition to the per-project ledger. Atomic write.

    Reads existing ledger (or initializes empty), appends new transition,
    writes via mkstemp + os.replace.
    """
    if kind not in KNOWN_TRANSITION_KINDS:
        raise ValueError(f"unknown transition kind: {kind!r}")

    target = cdlc_ledger_path_default(project_path)
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"version": LEDGER_VERSION, "transitions": []}
    else:
        data = {"version": LEDGER_VERSION, "transitions": []}

    data["transitions"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "payload": payload,
    })
    data["version"] = LEDGER_VERSION

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(target.parent), prefix=target.name, suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_ledger(*, project_path: pathlib.Path) -> list[dict]:
    """Return the list of transitions in append order. Empty list if missing."""
    target = cdlc_ledger_path_default(project_path)
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(data.get("transitions", []))
