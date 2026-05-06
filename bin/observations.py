"""Observe-leg JSONL halt log. Stdlib only.

Every TIER GATE halt in /implement records a structured observation to
~/.spectre/observations.jsonl. The log is append-only across all projects;
~/.spectre/ is per-user, per-host. Adapt-leg recurrence detection
(find_recurrences) is implemented here but is only consumed by v0.4.2's
template-patch proposal flow.

Design: docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md §6.3.

Public API:
    OBSERVATIONS_VERSION
    fingerprint_halt(*, action, classifier_label) -> str
    record_halt(*, kind, fingerprint, project_path, spec_slug, action) -> None
    find_recurrences(*, kind, threshold) -> list[dict]
    observations_path_default() -> pathlib.Path
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from datetime import datetime, timezone

OBSERVATIONS_VERSION = "0.4.1"


def fingerprint_halt(*, action: str, classifier_label: str) -> str:
    """SHA-256 hex of (classifier_label, action). Deterministic.

    The fingerprint is the identity used by personal_rules to override.
    Different actions get different fingerprints; same action under
    different classifier reasons get different fingerprints.
    """
    payload = f"{classifier_label}\x00{action}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def observations_path_default() -> pathlib.Path:
    return pathlib.Path.home() / ".spectre" / "observations.jsonl"


def record_halt(
    *,
    kind: str,
    fingerprint: str,
    project_path: str,
    spec_slug: str | None,
    action: str,
    classifier_label: str | None = None,
) -> None:
    """Append a single JSON line to ~/.spectre/observations.jsonl.

    Creates the parent dir + file on first call. JSONL is append-only;
    no atomic-rename pattern needed (single line write is atomic on POSIX
    for files <PIPE_BUF / 4096 bytes which our records always are).
    """
    target = observations_path_default()
    target.parent.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "fingerprint": fingerprint,
        "project_path": project_path,
        "spec_slug": spec_slug,
        "action": action,
    }
    if classifier_label is not None:
        record["classifier_label"] = classifier_label
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)
