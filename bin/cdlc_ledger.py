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


# ── CLI entrypoint ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    import sys
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="cdlc_ledger",
        description="CDLC ledger CLI — append transitions, read transitions.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_app = sub.add_parser(
        "append",
        help=(
            "Append a transition to state/cdlc-ledger.json under --project. "
            "Payload is read from --payload (JSON file path or '-' for stdin) "
            "or built from --payload-key=value flags. Prints the appended "
            "transition's timestamp on success."
        ),
    )
    p_app.add_argument(
        "--kind",
        required=True,
        choices=KNOWN_TRANSITION_KINDS,
        help=f"Transition kind (one of: {', '.join(KNOWN_TRANSITION_KINDS)}).",
    )
    p_app.add_argument(
        "--project",
        default=".",
        help="Project root (default: cwd '.'). Ledger is at <project>/state/cdlc-ledger.json.",
    )
    p_app.add_argument(
        "--payload",
        default=None,
        help=(
            "Payload JSON: file path, '-' for stdin, or inline JSON string. "
            "Mutually exclusive with --payload-kv."
        ),
    )
    p_app.add_argument(
        "--payload-kv",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Build payload from key=value pairs (repeatable). String values "
            "only. Use --payload for typed/nested payloads."
        ),
    )

    p_read = sub.add_parser(
        "read",
        help="Print all transitions as a JSON array on stdout.",
    )
    p_read.add_argument(
        "--project",
        default=".",
        help="Project root (default: cwd '.').",
    )

    args = parser.parse_args()

    if args.cmd == "append":
        if args.payload is not None and args.payload_kv:
            _status.emit("error", "ledger.bad_args", dest="stderr",
                         reason="--payload and --payload-kv are mutually exclusive",
                         remediation="pass --payload OR --payload-kv, not both")
            sys.exit(1)
        payload: dict
        if args.payload is not None:
            raw: str
            if args.payload == "-":
                raw = sys.stdin.read()
            else:
                p = pathlib.Path(args.payload)
                if p.is_file():
                    raw = p.read_text(encoding="utf-8")
                else:
                    raw = args.payload
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                _status.emit("error", "ledger.bad_payload_json", dest="stderr", reason=str(exc),
                         remediation="fix JSON syntax in --payload value")
                sys.exit(1)
            if not isinstance(payload, dict):
                _status.emit("error", "ledger.bad_payload_type", dest="stderr",
                             reason="must be JSON object",
                             remediation="verify --ledger-path exists and is readable")
                sys.exit(1)
        else:
            payload = {}
            for kv in args.payload_kv:
                if "=" not in kv:
                    _status.emit("error", "ledger.bad_payload_kv", dest="stderr",
                                 kv=kv, reason="expected KEY=VALUE",
                                 remediation="use form KEY=VALUE (e.g. --field reason=author-arbitrated)")
                    sys.exit(1)
                k, _, v = kv.partition("=")
                payload[k] = v

        try:
            append_transition(
                kind=args.kind,
                payload=payload,
                project_path=pathlib.Path(args.project),
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "ledger.append", dest="stderr", reason=str(exc),
                         remediation="check filesystem permissions on the project ledger file")
            sys.exit(1)
        _status.emit("ok", "ledger.append", kind=args.kind)

    elif args.cmd == "read":
        try:
            txs = read_ledger(project_path=pathlib.Path(args.project))
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "ledger.read", dest="stderr", reason=str(exc),
                         remediation="check that the ledger file exists and is valid JSON")
            sys.exit(1)
        print(json.dumps(txs, indent=2))
