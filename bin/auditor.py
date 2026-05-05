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
