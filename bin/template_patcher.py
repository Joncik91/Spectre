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


def _proposed_dir() -> pathlib.Path:
    return pathlib.Path.home() / ".spectre" / "template-patches" / "proposed"


def propose_patch(candidate: dict) -> pathlib.Path:
    """Write a markdown patch proposal for a recurring halt fingerprint.

    The proposal documents the recurring trigger and suggests a
    template-level mitigation (e.g. add a §8.1 mutates path, add a
    spec_lint rule, etc.). The user reviews and either moves the file
    to .accepted/ to apply manually OR moves to .rejected/ to dismiss.

    Returns the path to the written proposal.
    """
    target_dir = _proposed_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    fp = candidate["fingerprint"]
    short = fp[:8]
    label = candidate.get("classifier_label") or "unknown"
    safe_label = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:40]
    filename = f"{safe_label}-{short}.md"
    target = target_dir / filename

    body = (
        f"# Template-patch proposal: {label}\n\n"
        f"**Fingerprint:** `{fp}`\n"
        f"**Recurrence count:** {candidate.get('count', 'unknown')}\n"
        f"**Trigger kind:** {candidate.get('kind', 'unknown')}\n"
        f"**Most recent action:** `{candidate.get('action', 'unknown')}`\n"
        f"**Most recent spec slug:** `{candidate.get('spec_slug', 'unknown')}`\n"
        f"**Proposed at:** {datetime.now(timezone.utc).isoformat()}\n\n"
        f"---\n\n"
        f"## Why this proposal\n\n"
        f"This halt class has fired {candidate.get('count', 'multiple')} times "
        f"across your projects without being adopted as a personal-rule. The "
        f"recurrence suggests the project's `specs/template.spec.md` is missing "
        f"a field, lint, or §8.1 entry that would have surfaced this earlier.\n\n"
        f"## Suggested template additions\n\n"
        f"Review the recurring action and consider:\n\n"
        f"- Adding the affected path(s) to §8.1 `mutates:` or `never-touches:`.\n"
        f"- Adding a spec_lint rule that catches this pattern at lock-time.\n"
        f"- Adding a §1 Hard Problem reminder about the runtime constraint.\n\n"
        f"## How to apply\n\n"
        f"1. Edit `specs/template.spec.md` in your project.\n"
        f"2. Move this file to `~/.spectre/template-patches/accepted/{filename}` "
        f"once you've made the change.\n"
        f"3. To dismiss without applying, move to "
        f"`~/.spectre/template-patches/rejected/{filename}` instead.\n"
    )

    fd, tmp = tempfile.mkstemp(
        dir=str(target_dir), prefix=target.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return target


def list_proposed_patches() -> list[pathlib.Path]:
    """Return list of unaccepted proposal files in
    ~/.spectre/template-patches/proposed/."""
    target_dir = _proposed_dir()
    if not target_dir.is_dir():
        return []
    return sorted(p for p in target_dir.iterdir() if p.is_file() and p.suffix == ".md")
