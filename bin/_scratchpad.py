"""Atomic JSON read/write helpers for state/scratchpad.json. Stdlib only."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT = {
    "active_spec": None,
    "step": 1,
    "last_command": None,
    "exit_code": None,
    "delta": None,
    "timestamp": None,
    "failed_hypotheses": [],
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
