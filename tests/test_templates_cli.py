"""CLI tests for bin/templates.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin.templates <subcommand>` as a subprocess.
HOME is redirected to tmp_path so tests don't read the host's ~/.spectre.
"""
import json
import os
import pathlib
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin.templates"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


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


def _isolate_home(tmp_path):
    return {"HOME": str(tmp_path)}


class TestListCli:
    def test_list_empty_returns_zero(self, tmp_path):
        r = _run("list", env=_isolate_home(tmp_path))
        assert r.returncode == 0

    def test_list_empty_shows_builtin_count(self, tmp_path):
        """With no user templates, count= reflects built-in templates only."""
        r = _run("list", env=_isolate_home(tmp_path))
        assert "count=1" in r.stdout  # one builtin: template

    def test_list_one_spec_shows_count_including_builtin(self, tmp_path):
        spec_dir = tmp_path / ".spectre" / "templates" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "auth.spec.md").write_text("# auth")
        r = _run("list", env=_isolate_home(tmp_path))
        assert "count=2" in r.stdout  # 1 user spec + 1 builtin

    def test_list_includes_spec_name(self, tmp_path):
        spec_dir = tmp_path / ".spectre" / "templates" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "auth.spec.md").write_text("# auth")
        r = _run("list", env=_isolate_home(tmp_path))
        assert "spec:auth" in r.stdout

    def test_list_includes_skill_name(self, tmp_path):
        skill_dir = tmp_path / ".spectre" / "templates" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "review.md").write_text("# review")
        r = _run("list", env=_isolate_home(tmp_path))
        assert "skill:review" in r.stdout

    def test_list_limit_truncates(self, tmp_path):
        spec_dir = tmp_path / ".spectre" / "templates" / "specs"
        spec_dir.mkdir(parents=True)
        for n in range(5):
            (spec_dir / f"t{n}.spec.md").write_text("x")
        r = _run("list", "--limit", "2", env=_isolate_home(tmp_path))
        # Total count line + 2 entries.
        assert r.stdout.count("spec:") == 2

    def test_list_limit_zero_prints_only_header(self, tmp_path):
        spec_dir = tmp_path / ".spectre" / "templates" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "auth.spec.md").write_text("x")
        r = _run("list", "--limit", "0", env=_isolate_home(tmp_path))
        assert "spec:" not in r.stdout

    def test_list_json_returns_array(self, tmp_path):
        spec_dir = tmp_path / ".spectre" / "templates" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "auth.spec.md").write_text("x")
        r = _run("list", "--json", env=_isolate_home(tmp_path))
        data = json.loads(r.stdout)
        assert isinstance(data, list) and len(data) == 2  # 1 user spec + 1 builtin

    def test_list_json_schema_has_kind(self, tmp_path):
        spec_dir = tmp_path / ".spectre" / "templates" / "specs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "auth.spec.md").write_text("x")
        r = _run("list", "--json", env=_isolate_home(tmp_path))
        data = json.loads(r.stdout)
        user_specs = [t for t in data if t["kind"] == "spec"]
        assert user_specs[0]["kind"] == "spec"


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
