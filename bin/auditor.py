"""Post-execution State Auditor + PBT-lite checks. Stdlib only.

The auditor runs after a step's action+verification both pass. It derives
structural checks from the action's path captures and (optionally) runs a
list of property-based checks declared on the spec step.

Returns a list of AuditResult dataclasses with kind, passed, message.
"""
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AuditResult:
    kind: str
    passed: bool
    message: str


_TYPE_MAP: dict[str, type] = {
    "dict": dict,
    "list": list,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def _audit_path_exists(path: str) -> AuditResult:
    p = Path(path)
    exists = p.exists()
    return AuditResult(
        kind="path_exists",
        passed=exists,
        message=f"{path}: {'exists' if exists else 'missing'}",
    )


def _audit_json_parses(path: str) -> AuditResult:
    p = Path(path)
    if not p.exists():
        return AuditResult(kind="json_parses", passed=False, message=f"{path}: missing")
    try:
        json.loads(p.read_text(encoding="utf-8"))
        return AuditResult(kind="json_parses", passed=True, message=f"{path}: valid JSON")
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return AuditResult(kind="json_parses", passed=False, message=f"{path}: {e}")


def _audit_python_ast_parses(path: str) -> AuditResult:
    p = Path(path)
    if not p.exists():
        return AuditResult(
            kind="python_ast_parses", passed=False, message=f"{path}: missing"
        )
    try:
        ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        return AuditResult(
            kind="python_ast_parses", passed=True, message=f"{path}: valid Python"
        )
    except (SyntaxError, OSError, UnicodeDecodeError) as e:
        return AuditResult(
            kind="python_ast_parses", passed=False, message=f"{path}: {e}"
        )


def _load_json(target: str) -> tuple[bool, Any, str]:
    p = Path(target)
    if not p.exists():
        return False, None, f"{target}: missing"
    try:
        return True, json.loads(p.read_text(encoding="utf-8")), ""
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return False, None, f"{target}: {e}"


def _resolve_field(data: Any, field_path: str) -> tuple[bool, Any]:
    """Resolve a dotted field path on a JSON object. Returns (found, value)."""
    cur = data
    for part in field_path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _check_type(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    expected = prop.get("expected", "")
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="type", passed=False, message=err)
    expected_type = _TYPE_MAP.get(expected)
    if expected_type is None:
        return AuditResult(
            kind="type", passed=False, message=f"unknown type literal: {expected}"
        )
    passed = isinstance(data, expected_type)
    return AuditResult(
        kind="type",
        passed=passed,
        message=f"{target}: expected {expected}, got {type(data).__name__}",
    )


def _check_schema(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    required = prop.get("required_keys", [])
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="schema", passed=False, message=err)
    if not isinstance(data, dict):
        return AuditResult(
            kind="schema",
            passed=False,
            message=f"{target}: top-level not a dict",
        )
    missing = [k for k in required if k not in data]
    passed = not missing
    return AuditResult(
        kind="schema",
        passed=passed,
        message=f"{target}: missing keys {missing}" if missing else f"{target}: all keys present",
    )


def _check_length(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    field_path = prop.get("target_field", "")
    min_v = prop.get("min", 0)
    max_v = prop.get("max")
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="length", passed=False, message=err)
    found, value = _resolve_field(data, field_path)
    if not found:
        return AuditResult(
            kind="length", passed=False, message=f"{target}: field {field_path!r} missing"
        )
    if not isinstance(value, (list, dict)):
        return AuditResult(
            kind="length",
            passed=False,
            message=f"{target}.{field_path}: value type {type(value).__name__} not list/dict",
        )
    n = len(value)
    if n < min_v:
        return AuditResult(
            kind="length",
            passed=False,
            message=f"{target}.{field_path}: length {n} < min {min_v}",
        )
    if max_v is not None and n > max_v:
        return AuditResult(
            kind="length",
            passed=False,
            message=f"{target}.{field_path}: length {n} > max {max_v}",
        )
    return AuditResult(
        kind="length",
        passed=True,
        message=f"{target}.{field_path}: length {n} within [{min_v}, {max_v}]",
    )


def _check_range(prop: dict[str, Any]) -> AuditResult:
    target = prop.get("target", "")
    field_path = prop.get("target_field", "")
    min_v = prop.get("min")
    max_v = prop.get("max")
    ok, data, err = _load_json(target)
    if not ok:
        return AuditResult(kind="range", passed=False, message=err)
    found, value = _resolve_field(data, field_path)
    if not found:
        return AuditResult(
            kind="range", passed=False, message=f"{target}: field {field_path!r} missing"
        )
    if not isinstance(value, (int, float)):
        return AuditResult(
            kind="range",
            passed=False,
            message=f"{target}.{field_path}: value not numeric",
        )
    if min_v is not None and value < min_v:
        return AuditResult(
            kind="range",
            passed=False,
            message=f"{target}.{field_path}: {value} < min {min_v}",
        )
    if max_v is not None and value > max_v:
        return AuditResult(
            kind="range",
            passed=False,
            message=f"{target}.{field_path}: {value} > max {max_v}",
        )
    return AuditResult(
        kind="range",
        passed=True,
        message=f"{target}.{field_path}: {value} within [{min_v}, {max_v}]",
    )


_PBT_DISPATCH = {
    "type": _check_type,
    "schema": _check_schema,
    "length": _check_length,
    "range": _check_range,
}


def audit_action(
    command: str,
    *,
    paths_touched: list[str],
    properties: list[dict[str, Any]] | None,
) -> list[AuditResult]:
    """Run all derived structural checks + PBT-lite checks.

    Returns a list of AuditResult dataclasses. Empty paths_touched + no
    properties → returns a single noop result.
    """
    results: list[AuditResult] = []
    if not paths_touched and not properties:
        return [AuditResult(kind="noop", passed=True, message="no structured check derivable")]
    for path in paths_touched:
        results.append(_audit_path_exists(path))
        if path.endswith(".json"):
            results.append(_audit_json_parses(path))
        elif path.endswith(".py"):
            results.append(_audit_python_ast_parses(path))
    if properties:
        for prop in properties:
            kind = prop.get("kind", "")
            check = _PBT_DISPATCH.get(kind)
            if check is None:
                results.append(
                    AuditResult(
                        kind=kind,
                        passed=False,
                        message=f"unknown property kind: {kind!r}",
                    )
                )
                continue
            results.append(check(prop))
    return results


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _results_to_summary(results: list[AuditResult]) -> dict[str, Any]:
    """Shape AuditResult list into the §5.5 prose-format summary dict."""
    return {
        "kinds": [r.kind for r in results],
        "passed": all(r.passed for r in results),
        "failures": [
            {"kind": r.kind, "message": r.message} for r in results if not r.passed
        ],
    }


if __name__ == "__main__":
    import argparse
    import sys
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="auditor",
        description="State Auditor CLI — audit-action, audit-and-clear.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── audit-action ──────────────────────────────────────────────────────────
    p_aa = sub.add_parser(
        "audit-action",
        help=(
            "Run audit_action(action, paths_touched, properties) and emit the "
            "result. Pure check — does NOT touch the scratchpad."
        ),
    )
    p_aa.add_argument("--action", required=True, help="The current action text.")
    p_aa.add_argument(
        "--paths",
        default="[]",
        help='JSON array of paths_touched, e.g. \'["foo.json", "bar.py"]\'.',
    )
    p_aa.add_argument(
        "--properties",
        default=None,
        help="JSON array of property dicts (PBT-lite). Omit / null for none.",
    )
    p_aa.add_argument(
        "--prose",
        action="store_true",
        help=(
            "Emit the §5.5 prose-format output (AUDIT: N checks, passed=... + "
            "FAIL lines) instead of JSON."
        ),
    )

    # ── audit-and-clear ───────────────────────────────────────────────────────
    p_ac = sub.add_parser(
        "audit-and-clear",
        help=(
            "Single-call orchestration for §5.5: load scratchpad, read "
            "paths_touched for --track, run audit_action, persist last_audit_* "
            "fields back to the track, atomic-write the scratchpad. Emits the "
            "§5.5 prose-format output (or JSON with --json)."
        ),
    )
    p_ac.add_argument("--action", required=True, help="The current action text.")
    p_ac.add_argument(
        "--scratchpad",
        default="state/scratchpad.json",
        help="Path to scratchpad.json (default: state/scratchpad.json).",
    )
    p_ac.add_argument(
        "--track",
        default="default",
        help="Track name to read paths_touched from / write last_audit_* to.",
    )
    p_ac.add_argument(
        "--properties",
        default=None,
        help="JSON array of property dicts (PBT-lite). Omit / null for none.",
    )
    p_ac.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON summary instead of the §5.5 prose-format output.",
    )

    args = parser.parse_args()

    def _parse_properties(raw: str | None):
        if raw is None or raw == "" or raw == "null":
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            _status.emit("error", "audit.bad_properties_json", dest="stderr", reason=str(exc))
            sys.exit(1)
        if parsed is None:
            return None
        if not isinstance(parsed, list):
            _status.emit("error", "audit.bad_properties_type", dest="stderr",
                         reason="must be JSON array of dicts or null")
            sys.exit(1)
        return parsed

    if args.cmd == "audit-action":
        try:
            paths = json.loads(args.paths)
        except json.JSONDecodeError as exc:
            _status.emit("error", "audit.bad_paths_json", dest="stderr", reason=str(exc))
            sys.exit(1)
        if not isinstance(paths, list):
            _status.emit("error", "audit.bad_paths_type", dest="stderr",
                         reason="must be JSON array of strings")
            sys.exit(1)
        properties = _parse_properties(args.properties)

        try:
            results = audit_action(
                args.action, paths_touched=paths, properties=properties
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "audit.run", dest="stderr", reason=str(exc))
            sys.exit(1)

        summary = _results_to_summary(results)
        if args.prose:
            _status.emit("result", "audit.summary",
                         checks=len(results),
                         passed=str(summary["passed"]).lower(),
                         failures=len(summary["failures"]))
            for failure in summary["failures"]:
                _status.emit("warn", "audit.fail",
                             kind=failure["kind"],
                             message=failure["message"])
        else:
            print(json.dumps(summary, indent=2))

    elif args.cmd == "audit-and-clear":
        # Lazy import — keeps audit_action callable without _scratchpad.
        from bin import _scratchpad as _sp

        sp_path = Path(args.scratchpad)
        try:
            sp = _sp.load(sp_path)
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "audit.scratchpad_load", dest="stderr", reason=str(exc))
            sys.exit(1)
        paths = _sp.get_paths_touched(sp, track=args.track)
        properties = _parse_properties(args.properties)

        try:
            results = audit_action(
                args.action, paths_touched=paths, properties=properties
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "audit.run", dest="stderr", reason=str(exc))
            sys.exit(1)

        summary = _results_to_summary(results)

        # Persist last_audit_* on the track. Mirror the §5.5 heredoc shape.
        if "tracks" not in sp or not isinstance(sp.get("tracks"), dict):
            sp["tracks"] = {}
        track_data = sp["tracks"].get(args.track, {})
        if not isinstance(track_data, dict):
            track_data = {}
        track_data["last_audit_kinds"] = summary["kinds"]
        track_data["last_audit_passed"] = summary["passed"]
        track_data["last_audit_failures"] = summary["failures"]
        sp["tracks"][args.track] = track_data

        try:
            _sp.atomic_write(sp_path, sp)
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "audit.scratchpad_write", dest="stderr", reason=str(exc))
            sys.exit(1)

        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            _status.emit("result", "audit.summary",
                         checks=len(results),
                         passed=str(summary["passed"]).lower(),
                         failures=len(summary["failures"]))
            for failure in summary["failures"]:
                _status.emit("warn", "audit.fail",
                             kind=failure["kind"],
                             message=failure["message"])
