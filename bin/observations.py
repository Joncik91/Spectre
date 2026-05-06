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
