"""CLI tests for bin/tier.py __main__ entrypoint (Phase 2C, issue #13).

Invokes the module via `python3 -m bin.tier <subcommand>` as a subprocess.

Pragma guard: one assertion per test; no `_rejects_` / `_raises_` without
pytest.raises; no mocked exit.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_CMD = [sys.executable, "-m", "bin.tier"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


# ── classify ──────────────────────────────────────────────────────────────────

class TestClassifyCli:
    def test_silent_command_exits_zero(self):
        r = _run("classify", "--action", "echo hi")
        assert r.returncode == 0

    def test_silent_command_prints_tier_silent(self):
        r = _run("classify", "--action", "echo hi")
        assert "tier=silent" in r.stdout

    def test_host_path_prints_tier_host(self):
        r = _run("classify", "--action", "vim /etc/passwd")
        assert "tier=host" in r.stdout

    def test_never_autonomous_sudo_emits_label(self):
        r = _run("classify", "--action", "sudo apt-get install foo")
        assert "never_autonomous=" in r.stdout

    def test_missing_action_flag_exits_2(self):
        r = _run("classify")
        assert r.returncode == 2


# ── should-halt ───────────────────────────────────────────────────────────────

class TestShouldHaltCli:
    def test_silent_action_halts_false(self):
        r = _run("should-halt", "--action", "echo hi")
        assert "halt=false" in r.stdout

    def test_host_action_halts_true(self):
        r = _run("should-halt", "--action", "vim /etc/passwd")
        assert "halt=true" in r.stdout

    def test_locked_path_action_halts_true(self, tmp_path):
        spec = tmp_path / "x.spec.md"
        spec.write_text(
            "# x\n\n## 8. Boundary\n\n### 8.1 Hard Contract\n\n"
            "- mutates: /opt/myapp/\n"
            "- never-touches: /etc/\n",
            encoding="utf-8",
        )
        r = _run(
            "should-halt",
            "--action", "vim /etc/hosts",
            "--spec", str(spec),
        )
        assert "halt=true" in r.stdout

    def test_missing_action_flag_exits_2(self):
        r = _run("should-halt")
        assert r.returncode == 2


# ── evaluate-action ───────────────────────────────────────────────────────────

class TestEvaluateActionCli:
    def test_silent_action_exits_zero(self):
        r = _run("evaluate-action", "--action", "echo hi")
        assert r.returncode == 0

    def test_prose_output_contains_tier_line(self):
        r = _run("evaluate-action", "--action", "echo hi")
        assert "tier=silent" in r.stdout

    def test_prose_output_contains_halt_line(self):
        r = _run("evaluate-action", "--action", "echo hi")
        assert "halt=false" in r.stdout

    def test_json_output_parses(self):
        r = _run("evaluate-action", "--action", "vim /etc/passwd", "--json")
        payload = json.loads(r.stdout)
        assert payload["tier"] == "host"

    def test_json_output_includes_halt_field(self):
        r = _run("evaluate-action", "--action", "vim /etc/passwd", "--json")
        payload = json.loads(r.stdout)
        assert payload["halt"] is True

    def test_json_output_lists_locked_paths(self, tmp_path):
        spec = tmp_path / "y.spec.md"
        spec.write_text(
            "# y\n\n## 8. Boundary\n\n### 8.1 Hard Contract\n\n"
            "- mutates: /opt/myapp/, /var/lib/myapp/\n",
            encoding="utf-8",
        )
        r = _run(
            "evaluate-action",
            "--action", "echo hi",
            "--spec", str(spec),
            "--json",
        )
        payload = json.loads(r.stdout)
        assert "/opt/myapp/" in payload["spec_locked_paths"]

    def test_never_autonomous_in_json(self):
        r = _run(
            "evaluate-action",
            "--action", "sudo chmod 777 /tmp/foo",
            "--json",
        )
        payload = json.loads(r.stdout)
        assert payload["never_autonomous"] is not None

    def test_missing_spec_does_not_error(self):
        """A missing --spec path is treated as 'no locked paths', not an error."""
        r = _run(
            "evaluate-action",
            "--action", "echo hi",
            "--spec", "/does/not/exist.spec.md",
        )
        assert r.returncode == 0

    def test_round_trip_matches_prose_heredoc_behavior(self, tmp_path):
        """End-to-end: orchestrated CLI output must match what the §3.5 heredoc
        body would have produced for the same inputs (classify + locked-path
        read + should_halt)."""
        spec = tmp_path / "z.spec.md"
        spec.write_text(
            "# z\n\n## 8. Boundary\n\n### 8.1 Hard Contract\n\n"
            "- mutates: /etc/myapp/\n",
            encoding="utf-8",
        )
        r = _run(
            "evaluate-action",
            "--action", "vim /etc/myapp/conf",
            "--spec", str(spec),
            "--json",
        )
        payload = json.loads(r.stdout)
        # Heredoc would: classify('vim /etc/myapp/conf') → host
        # parse §8.1 → mutates: ['/etc/myapp/']
        # should_halt(host, None, ..., spec_locked_paths={'/etc/myapp/'}) → True
        # (locked-path immune from personal-rules override)
        assert payload["halt"] is True

    def test_missing_action_flag_exits_2(self):
        r = _run("evaluate-action")
        assert r.returncode == 2

    def test_unknown_subcommand_exits_2(self):
        r = _run("does-not-exist")
        assert r.returncode == 2
