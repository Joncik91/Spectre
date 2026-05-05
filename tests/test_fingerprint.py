import json
from pathlib import Path

import pytest

from bin import fingerprint as fp


def test_extract_python_symbols_finds_top_level_function(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def hello():\n    return 1\n")
    syms = fp.extract_python_symbols(f)
    assert any(s["name"] == "hello" and s["kind"] == "function" for s in syms)


def test_extract_python_symbols_finds_top_level_class(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("class Widget:\n    pass\n")
    syms = fp.extract_python_symbols(f)
    assert any(s["name"] == "Widget" and s["kind"] == "class" for s in syms)


def test_extract_python_symbols_records_file_and_line(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("\ndef target():\n    pass\n")
    syms = fp.extract_python_symbols(f)
    target = next(s for s in syms if s["name"] == "target")
    assert target["file"] == str(f)
    assert target["line"] == 2


def test_extract_python_symbols_captures_module_docstring(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text('"""Top-level module purpose."""\ndef x(): pass\n')
    syms = fp.extract_python_symbols(f)
    module = next(s for s in syms if s["kind"] == "module")
    assert "Top-level module purpose" in module["doc"]


def test_extract_python_symbols_skips_nested_definitions(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        pass\n"
    )
    syms = fp.extract_python_symbols(f)
    names = [s["name"] for s in syms if s["kind"] == "function"]
    assert "outer" in names
    assert "inner" not in names


def test_extract_python_symbols_returns_empty_on_syntax_error(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def oops(:\n")
    syms = fp.extract_python_symbols(f)
    assert syms == []
