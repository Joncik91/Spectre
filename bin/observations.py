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

    # v0.4.2: also append to per-project CDLC ledger.
    try:
        from bin import cdlc_ledger as _ledger
        _ledger.append_transition(
            kind="halt",
            payload={
                "fingerprint": fingerprint,
                "kind": kind,
                "spec_slug": spec_slug,
                "action": action,
            },
            project_path=pathlib.Path.cwd(),
        )
    except Exception:
        # Ledger write must not break the halt path.
        pass


def find_recurrences(*, kind: str | None = None, threshold: int = 3) -> list[dict]:
    """Return one record per fingerprint that recurs ≥ threshold times.

    Optionally filter by kind. The returned records are flattened: one row
    per recurring fingerprint with the most-recent observation's fields
    plus a `count` key.
    """
    target = observations_path_default()
    if not target.exists():
        return []

    counts: dict[str, list[dict]] = {}
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kind is not None and rec.get("kind") != kind:
                continue
            counts.setdefault(rec["fingerprint"], []).append(rec)

    out: list[dict] = []
    for fp, records in counts.items():
        if len(records) >= threshold:
            most_recent = records[-1]
            out.append({**most_recent, "count": len(records)})
    return out


# ── CLI entrypoint ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    import sys
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="observations",
        description="Observe-leg CLI — record-halt, find-recurrences.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser(
        "record-halt",
        help=(
            "Compute the (action, classifier-label) fingerprint and append a "
            "halt observation to ~/.spectre/observations.jsonl. Prints "
            "`OBSERVED: <fp[:12]>...` on success. Also writes a CDLC ledger "
            "halt transition (best-effort; errors swallowed)."
        ),
    )
    p_rec.add_argument("--action", required=True, help="The action text that halted.")
    p_rec.add_argument(
        "--label",
        required=True,
        help="Classifier label (the first reason from the tier classifier).",
    )
    p_rec.add_argument(
        "--kind",
        default="tier-gate",
        help='Observation kind (default: "tier-gate").',
    )
    p_rec.add_argument(
        "--project",
        default=None,
        help=(
            "Project path for the observation record (default: cwd). "
            "Stored verbatim; the ledger writer always uses cwd."
        ),
    )
    p_rec.add_argument(
        "--spec-slug",
        default=None,
        help="Active spec slug from .active (optional).",
    )

    p_rec_q = sub.add_parser(
        "find-recurrences",
        help=(
            "Find fingerprints that recur ≥ --threshold times across "
            "~/.spectre/observations.jsonl. Prints JSON list."
        ),
    )
    p_rec_q.add_argument("--kind", default=None, help="Filter by observation kind.")
    p_rec_q.add_argument(
        "--threshold",
        type=int,
        default=3,
        help="Minimum recurrence count (default: 3).",
    )

    args = parser.parse_args()

    if args.cmd == "record-halt":
        project_path = args.project if args.project is not None else str(pathlib.Path.cwd())
        try:
            fp = fingerprint_halt(action=args.action, classifier_label=args.label)
            record_halt(
                kind=args.kind,
                fingerprint=fp,
                project_path=project_path,
                spec_slug=args.spec_slug,
                action=args.action,
                classifier_label=args.label,
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "observation.record", dest="stderr", reason=str(exc),
                         remediation="verify filesystem permissions on the observations store")
            sys.exit(1)
        _status.emit("ok", "observation.record", fingerprint=fp[:12])

    elif args.cmd == "find-recurrences":
        try:
            recs = find_recurrences(kind=args.kind, threshold=args.threshold)
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "observation.find_recurrences", dest="stderr", reason=str(exc),
                         remediation="open an issue with the full halt output")
            sys.exit(1)
        print(json.dumps(recs, indent=2))
