"""tests/test_glossary_completeness.py — sync invariant between emit sites and glossary.

AST-walks every .py file in bin/, extracts _status.emit(...) literal codes,
and asserts:
1. Every literal status code has a glossary entry (no undocumented emit).
2. Every status-kind glossary entry has a corresponding emit site (no orphans).
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
