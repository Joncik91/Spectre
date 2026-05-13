"""CLI tests for bin/adr.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin.adr <subcommand>` as a subprocess.
"""
import pathlib
import re
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin.adr"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


class TestWriteCli:
    def test_write_exits_zero(self, tmp_path):
        decisions = tmp_path / "decisions"
        r = _run(
            "write",
            "--dir", str(decisions),
            "--title", "Use Postgres 16",
            "--body", "We pick Postgres 16 because of MERGE.",
        )
        assert r.returncode == 0

    def test_write_creates_file(self, tmp_path):
        decisions = tmp_path / "decisions"
        _run(
            "write", "--dir", str(decisions),
            "--title", "T", "--body", "B",
        )
        files = list(decisions.glob("*.md"))
        assert len(files) == 1

    def test_write_emits_adr_path(self, tmp_path):
        decisions = tmp_path / "decisions"
        r = _run(
            "write", "--dir", str(decisions),
            "--title", "Choose Vue", "--body", "Why",
        )
        assert "adr.write" in r.stdout
        assert "path=" in r.stdout

    def test_write_uses_today_date_by_default(self, tmp_path):
        from datetime import date
        decisions = tmp_path / "decisions"
        _run(
            "write", "--dir", str(decisions),
            "--title", "T", "--body", "B",
        )
        files = list(decisions.glob("*.md"))
        text = files[0].read_text()
        assert f"date: {date.today().isoformat()}" in text

    def test_write_persists_explicit_date(self, tmp_path):
        decisions = tmp_path / "decisions"
        _run(
            "write", "--dir", str(decisions),
            "--title", "T", "--body", "B",
            "--date", "2020-01-02",
        )
        files = list(decisions.glob("*.md"))
        text = files[0].read_text()
        assert "date: 2020-01-02" in text

    def test_write_persists_title_in_yaml(self, tmp_path):
        decisions = tmp_path / "decisions"
        _run(
            "write", "--dir", str(decisions),
            "--title", "Use Postgres 16",
            "--body", "B",
        )
        files = list(decisions.glob("*.md"))
        text = files[0].read_text()
        assert '"Use Postgres 16"' in text

    def test_write_status_accepted(self, tmp_path):
        decisions = tmp_path / "decisions"
        _run(
            "write", "--dir", str(decisions),
            "--title", "T", "--body", "B",
        )
        text = list(decisions.glob("*.md"))[0].read_text()
        assert "status: accepted" in text

    def test_write_supersedes_marks_old_file(self, tmp_path):
        decisions = tmp_path / "decisions"
        # Write an initial accepted ADR first.
        _run(
            "write", "--dir", str(decisions),
            "--title", "Use SQLite", "--body", "v0",
        )
        # Now write a superseder.
        _run(
            "write", "--dir", str(decisions),
            "--title", "Use Postgres", "--body", "v1",
            "--supersedes", "0001",
        )
        old = decisions / "0001-use-sqlite.md"
        assert "status: superseded" in old.read_text()

    def test_write_increments_id(self, tmp_path):
        decisions = tmp_path / "decisions"
        _run("write", "--dir", str(decisions), "--title", "A", "--body", "B")
        _run("write", "--dir", str(decisions), "--title", "C", "--body", "D")
        ids = sorted(re.match(r"^(\d{4})-", f.name).group(1) for f in decisions.glob("*.md"))
        assert ids == ["0001", "0002"]

    def test_write_missing_title_exits_2(self, tmp_path):
        decisions = tmp_path / "decisions"
        r = _run("write", "--dir", str(decisions), "--body", "B")
        assert r.returncode == 2

    def test_write_missing_body_exits_2(self, tmp_path):
        decisions = tmp_path / "decisions"
        r = _run("write", "--dir", str(decisions), "--title", "T")
        assert r.returncode == 2


class TestUpdateGraphCli:
    def test_update_graph_missing_manifest_is_noop(self, tmp_path):
        graph = tmp_path / ".graph.md"
        r = _run(
            "update-graph",
            "--graph", str(graph),
            "--new", "adr-0002", "--old", "adr-0001",
        )
        assert r.returncode == 0

    def test_update_graph_missing_node_is_noop(self, tmp_path):
        graph = tmp_path / ".graph.md"
        graph.write_text("")
        r = _run(
            "update-graph",
            "--graph", str(graph),
            "--new", "adr-0002", "--old", "adr-0001",
        )
        assert r.returncode == 0

    def test_update_graph_missing_new_arg_exits_2(self, tmp_path):
        graph = tmp_path / ".graph.md"
        r = _run("update-graph", "--graph", str(graph), "--old", "adr-0001")
        assert r.returncode == 2


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
