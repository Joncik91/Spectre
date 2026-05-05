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


def test_extract_shell_symbols_finds_function_form_one(tmp_path):
    f = tmp_path / "script.sh"
    f.write_text(
        "#!/bin/bash\n"
        "do_thing() {\n"
        "  echo hi\n"
        "}\n"
    )
    syms = fp.extract_shell_symbols(f)
    names = [s["name"] for s in syms if s["kind"] == "function"]
    assert "do_thing" in names


def test_extract_shell_symbols_finds_function_form_two(tmp_path):
    f = tmp_path / "script.sh"
    f.write_text(
        "function alt_form() {\n"
        "  echo alt\n"
        "}\n"
    )
    syms = fp.extract_shell_symbols(f)
    names = [s["name"] for s in syms if s["kind"] == "function"]
    assert "alt_form" in names


def test_extract_shell_symbols_records_line(tmp_path):
    f = tmp_path / "s.sh"
    f.write_text("\n\ndo_thing() {\n  :\n}\n")
    syms = fp.extract_shell_symbols(f)
    target = next(s for s in syms if s["name"] == "do_thing")
    assert target["line"] == 3


def test_extract_markdown_headers_h1(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Top\n## Sub\n")
    syms = fp.extract_markdown_headers(f)
    assert syms[0]["kind"] == "h1"
    assert syms[0]["name"] == "Top"


def test_extract_markdown_headers_h2(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Top\n## Sub\n")
    syms = fp.extract_markdown_headers(f)
    assert syms[1]["kind"] == "h2"
    assert syms[1]["name"] == "Sub"


def test_extract_markdown_headers_skips_h3_and_below(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(
        "# Top\n"
        "## Section A\n"
        "### Skipped\n"
        "## Section B\n"
    )
    syms = fp.extract_markdown_headers(f)
    titles = [s["name"] for s in syms]
    assert "Skipped" not in titles
    assert "Section A" in titles
    assert "Section B" in titles
