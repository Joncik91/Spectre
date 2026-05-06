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
