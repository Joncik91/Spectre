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


def test_walk_repo_collects_python_function(tmp_path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    out = fp.walk_repo(tmp_path)
    assert any(s["kind"] == "function" and s["name"] == "f" for s in out)


def test_walk_repo_collects_shell_function(tmp_path):
    (tmp_path / "b.sh").write_text("g() { :; }\n")
    out = fp.walk_repo(tmp_path)
    assert any(s["kind"] == "function" and s["name"] == "g" for s in out)


def test_walk_repo_collects_markdown_h1(tmp_path):
    (tmp_path / "c.md").write_text("# Title\n## Sub\n")
    out = fp.walk_repo(tmp_path)
    assert any(s["kind"] == "h1" and s["name"] == "Title" for s in out)


def test_walk_repo_collects_markdown_h2(tmp_path):
    (tmp_path / "c.md").write_text("# Title\n## Sub\n")
    out = fp.walk_repo(tmp_path)
    assert any(s["kind"] == "h2" and s["name"] == "Sub" for s in out)


def test_walk_repo_skips_dot_git(tmp_path):
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "x.py").write_text("def secret(): pass\n")
    out = fp.walk_repo(tmp_path)
    assert all(s["name"] != "secret" for s in out)


def test_walk_repo_skips_pycache(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "x.py").write_text("def cached(): pass\n")
    out = fp.walk_repo(tmp_path)
    assert all(s["name"] != "cached" for s in out)


def test_walk_repo_skips_state_dir(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "y.py").write_text("def stateful(): pass\n")
    out = fp.walk_repo(tmp_path)
    assert all(s["name"] != "stateful" for s in out)


def test_save_symbols_round_trip(tmp_path):
    target = tmp_path / "syms.json"
    syms = [{"kind": "function", "name": "x", "file": "a.py", "line": 1, "doc": ""}]
    fp.save_symbols(target, syms)
    loaded = json.loads(target.read_text())
    assert loaded == syms


def test_save_symbols_no_tmp_left_behind(tmp_path):
    target = tmp_path / "syms.json"
    syms = [{"kind": "function", "name": "x", "file": "a.py", "line": 1, "doc": ""}]
    fp.save_symbols(target, syms)
    leftovers = list(tmp_path.glob("syms.json*.tmp"))
    assert leftovers == []


def test_cli_writes_symbols_json(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    fp.main()
    out_path = state_dir / "local-symbols.json"
    assert out_path.exists()


def test_cli_output_json_contains_extracted_symbol(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    (tmp_path / "state").mkdir()
    monkeypatch.chdir(tmp_path)
    fp.main()
    data = json.loads((tmp_path / "state" / "local-symbols.json").read_text())
    assert any(s["name"] == "hello" for s in data)


def test_cli_emits_summary_to_stdout(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    (tmp_path / "state").mkdir()
    monkeypatch.chdir(tmp_path)
    fp.main()
    captured = capsys.readouterr()
    assert "FINGERPRINT" in captured.out
    assert "symbols" in captured.out.lower()
