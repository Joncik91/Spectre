"""Adapt's auto-template-patch proposer. Stdlib only.

When `observations.find_recurrences(threshold=3)` returns recurring
fingerprints AND those fingerprints are NOT already covered by a
personal-rules adoption, propose a markdown patch to the project's
specs/template.spec.md. Patches land at
~/.spectre/template-patches/proposed/<slug>.md and are NEVER auto-merged
— the user moves the file to .accepted/ or .rejected/ manually.

Design: docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md §6.5
"Adapt's auto-template-patch proposal".

Public API:
    PATCHER_VERSION
    DEFAULT_RECURRENCE_THRESHOLD
    detect_patch_candidates(*, threshold=3) -> list[dict]
    propose_patch(candidate) -> pathlib.Path
    list_proposed_patches() -> list[pathlib.Path]
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tempfile
from datetime import datetime, timezone

PATCHER_VERSION = "0.4.2"
DEFAULT_RECURRENCE_THRESHOLD = 3


def detect_patch_candidates(
    *,
    threshold: int = DEFAULT_RECURRENCE_THRESHOLD,
) -> list[dict]:
    """Return recurring fingerprints not already covered by personal rules.

    Each candidate dict: {fingerprint, classifier_label (if known), kind,
    count, action (most recent), spec_slug (most recent)}.
    """
    from bin import observations, personal_rules
    recurrences = observations.find_recurrences(threshold=threshold)
    out: list[dict] = []
    for rec in recurrences:
        label = rec.get("classifier_label")
        fp = rec["fingerprint"]
        if label is not None and personal_rules.is_classifier_halt_overridden(
            classifier_label=label, fingerprint=fp,
        ):
            continue
        out.append({
            "fingerprint": fp,
            "classifier_label": label,
            "kind": rec.get("kind"),
            "count": rec.get("count", 0),
            "action": rec.get("action"),
            "spec_slug": rec.get("spec_slug"),
        })
    return out
