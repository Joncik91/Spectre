"""tests/test_glossary_completeness.py — sync invariant between emit sites and glossary.

AST-walks every .py file in bin/, extracts _status.emit(...) literal codes,
and asserts:
1. Every literal status code has a glossary entry (no undocumented emit).
2. Every status-kind glossary entry has a corresponding emit site (no orphans).
3. Every warn/halt/error emit code has a non-empty user_action: field in the glossary.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Iterable

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "bin"


def _iter_py_files() -> Iterable[pathlib.Path]:
    return sorted(_BIN_DIR.glob("*.py"))


def _extract_emit_codes(path: pathlib.Path) -> set[str]:
    """AST-walk a .py file and extract literal string codes from _status.emit calls.

    Handles both:
      _status.emit("ok", "some.code", ...)
      emit("ok", "some.code", ...)  — after `from bin import _status as _s` etc.

    Only static string literals are extracted. Dynamic codes (variables) are skipped.
    """
    codes: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return codes

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match _status.emit(...) or _s.emit(...) attribute calls
        is_emit_attr = (
            isinstance(func, ast.Attribute)
            and func.attr == "emit"
        )
        # Match bare emit(...) calls (less common but possible)
        is_emit_name = isinstance(func, ast.Name) and func.id == "emit"

        if not (is_emit_attr or is_emit_name):
            continue

        # emit(level, code, ...) — need at least 2 positional args
        args = node.args
        if len(args) < 2:
            continue

        code_arg = args[1]
        if isinstance(code_arg, ast.Constant) and isinstance(code_arg.value, str):
            codes.add(code_arg.value)
        # If it's not a literal constant (e.g. a variable), skip it

    return codes


def _all_emit_codes() -> set[str]:
    """Collect all literal emit codes across all bin/*.py files."""
    codes: set[str] = set()
    for py_file in _iter_py_files():
        codes |= _extract_emit_codes(py_file)
    return codes


def _load_glossary_codes() -> set[str]:
    """Load the real glossary and return all status-kind codes."""
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    return _g.all_codes()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_every_emit_code_has_glossary_entry():
    """Every literal _status.emit code must appear in the glossary."""
    emit_codes = _all_emit_codes()
    glossary_codes = _load_glossary_codes()

    missing = emit_codes - glossary_codes
    assert not missing, (
        f"These emit codes are missing from docs/glossary.md:\n"
        + "\n".join(f"  {c}" for c in sorted(missing))
    )


def test_no_orphan_entries():
    """Every status-kind glossary entry must have a corresponding emit site."""
    emit_codes = _all_emit_codes()
    glossary_codes = _load_glossary_codes()

    orphans = glossary_codes - emit_codes
    assert not orphans, (
        f"These glossary entries have no matching emit site in bin/*.py:\n"
        + "\n".join(f"  {c}" for c in sorted(orphans))
    )


def _warn_halt_error_codes() -> dict[str, set[str]]:
    """Return mapping of code → set of levels for warn/halt/error emit sites."""
    code_levels: dict[str, set[str]] = {}
    for py_file in _iter_py_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_emit_attr = isinstance(func, ast.Attribute) and func.attr == "emit"
            is_emit_name = isinstance(func, ast.Name) and func.id == "emit"
            if not (is_emit_attr or is_emit_name):
                continue
            args = node.args
            if len(args) < 2:
                continue
            level_arg = args[0]
            code_arg = args[1]
            if not isinstance(level_arg, ast.Constant):
                continue
            if level_arg.value not in ("warn", "halt", "error"):
                continue
            if isinstance(code_arg, ast.Constant) and isinstance(code_arg.value, str):
                code = code_arg.value
                code_levels.setdefault(code, set()).add(level_arg.value)
    return code_levels


def test_warn_halt_error_codes_have_user_action_field():
    """Every warn/halt/error emit code must have a non-empty user_action: in the glossary."""
    import bin._glossary as _g
    _g._GLOSSARY_CACHE = None
    entries = _g.load_glossary()

    code_levels = _warn_halt_error_codes()
    missing_user_action: list[str] = []

    for code in sorted(code_levels):
        entry = entries.get(code)
        if entry is None:
            # Already caught by test_every_emit_code_has_glossary_entry.
            continue
        ua = (entry.user_action or "").strip()
        if not ua:
            levels = ",".join(sorted(code_levels[code]))
            missing_user_action.append(f"  {code}  (level={levels})")

    assert not missing_user_action, (
        "These warn/halt/error codes have an empty user_action: in glossary.md:\n"
        + "\n".join(missing_user_action)
    )
