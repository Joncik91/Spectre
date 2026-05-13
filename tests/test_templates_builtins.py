"""tests/test_templates_builtins.py — builtin template discovery and import (Axis C, v0.9.0)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CMD = [sys.executable, "-m", "bin.templates"]


def _run(*args, cwd=None, env=None):
    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(_REPO)
    if env:
        base_env.update(env)
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd if cwd is not None else _REPO,
        env=base_env,
    )


# ---------------------------------------------------------------------------
# Unit tests for list_builtins() and builtin_template_path()
# ---------------------------------------------------------------------------

class TestListBuiltins:
    def test_builtin_template_path_resolves(self):
        from bin.templates import builtin_template_path
        p = builtin_template_path()
        assert p.is_file(), f"builtin template not found: {p}"

    def test_list_builtins_returns_one_entry(self):
        from bin.templates import list_builtins
        builtins = list_builtins()
        assert len(builtins) == 1

    def test_list_builtins_has_builtin_kind(self):
        from bin.templates import list_builtins
        assert list_builtins()[0]["kind"] == "builtin"

    def test_list_builtins_name_is_template(self):
        from bin.templates import list_builtins
        assert list_builtins()[0]["name"] == "template"

    def test_list_templates_includes_builtin(self, tmp_path):
        """list_templates() merges user templates and builtins."""
        from bin import templates
        # Redirect home so no ~/.spectre templates interfere
        original = templates.templates_dir_default
        templates.templates_dir_default = lambda: tmp_path / ".spectre" / "templates"
        try:
            ts = templates.list_templates()
        finally:
            templates.templates_dir_default = original
        kinds = {t["kind"] for t in ts}
        assert "builtin" in kinds


# ---------------------------------------------------------------------------
# CLI: templates list --json includes builtin
# ---------------------------------------------------------------------------

class TestListCliBuiltin:
    def test_list_includes_builtin_in_json(self, tmp_path):
        r = _run("list", "--json", env={"HOME": str(tmp_path)})
        assert r.returncode == 0
        data = json.loads(r.stdout)
        builtins = [t for t in data if t.get("kind") == "builtin"]
        assert builtins, "Expected at least one builtin entry in JSON output"

    def test_list_builtin_entry_has_name_template(self, tmp_path):
        r = _run("list", "--json", env={"HOME": str(tmp_path)})
        data = json.loads(r.stdout)
        builtins = [t for t in data if t.get("kind") == "builtin"]
        assert builtins[0]["name"] == "template"

    def test_list_count_includes_builtin(self, tmp_path):
        """Non-JSON list output reflects the builtin in the count."""
        r = _run("list", env={"HOME": str(tmp_path)})
        assert "count=1" in r.stdout  # only the builtin, no user templates


# ---------------------------------------------------------------------------
# CLI: templates import-builtin
# ---------------------------------------------------------------------------

class TestImportBuiltinCli:
    def test_import_builtin_writes_draft(self, tmp_path):
        r = _run("import-builtin", "--name", "template", "--slug", "my-test",
                 cwd=tmp_path)
        assert r.returncode == 0
        draft = tmp_path / "specs" / "my-test.spec.md.draft"
        assert draft.is_file(), "Draft file not created"

    def test_import_builtin_draft_content_matches_builtin(self, tmp_path):
        from bin.templates import builtin_template_path
        r = _run("import-builtin", "--name", "template", "--slug", "content-test",
                 cwd=tmp_path)
        assert r.returncode == 0
        expected = builtin_template_path().read_text(encoding="utf-8")
        actual = (tmp_path / "specs" / "content-test.spec.md.draft").read_text(encoding="utf-8")
        assert actual == expected

    def test_import_builtin_emits_ok_status(self, tmp_path):
        r = _run("import-builtin", "--name", "template", "--slug", "ok-test",
                 cwd=tmp_path)
        assert "templates.import_builtin" in r.stdout

    def test_import_builtin_slug_collision_exits_nonzero(self, tmp_path):
        """Second call with same slug exits 1 and emits error reason=exists."""
        _run("import-builtin", "--name", "template", "--slug", "dup", cwd=tmp_path)
        r2 = _run("import-builtin", "--name", "template", "--slug", "dup", cwd=tmp_path)
        assert r2.returncode == 1
        assert "reason=exists" in r2.stderr

    def test_import_builtin_unknown_name_exits_1(self, tmp_path):
        r = _run("import-builtin", "--name", "nonexistent", "--slug", "x",
                 cwd=tmp_path)
        assert r.returncode == 1

    def test_import_builtin_creates_specs_dir(self, tmp_path):
        """specs/ dir is created automatically if absent."""
        r = _run("import-builtin", "--name", "template", "--slug", "auto-dir",
                 cwd=tmp_path)
        assert r.returncode == 0
        assert (tmp_path / "specs").is_dir()
