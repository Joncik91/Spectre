"""CLI tests for bin/observations.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin.observations <subcommand>` as a subprocess.
"""
import json
import os
import pathlib
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin.observations"]
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
    """Return env-vars that point HOME at tmp_path so ~/.spectre/ is per-test."""
    return {"HOME": str(tmp_path)}


class TestRecordHaltCli:
    def test_record_halt_exits_zero(self, tmp_path):
        r = _run(
            "record-halt",
            "--action", "rm -rf /tmp/test",
            "--label", "destructive-delete: rm -rf",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert r.returncode == 0

    def test_record_halt_writes_observations_file(self, tmp_path):
        _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "no filesystem path detected",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        assert target.is_file()

    def test_record_halt_writes_one_line(self, tmp_path):
        _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "test-label",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        lines = target.read_text().splitlines()
        assert len(lines) == 1

    def test_record_halt_persists_action(self, tmp_path):
        _run(
            "record-halt",
            "--action", "vim /etc/passwd",
            "--label", "path '/etc/passwd' → host",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        rec = json.loads(target.read_text().splitlines()[0])
        assert rec["action"] == "vim /etc/passwd"

    def test_record_halt_persists_classifier_label(self, tmp_path):
        _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "my-label",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        rec = json.loads(target.read_text().splitlines()[0])
        assert rec["classifier_label"] == "my-label"

    def test_record_halt_default_kind_is_tier_gate(self, tmp_path):
        _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "my-label",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        rec = json.loads(target.read_text().splitlines()[0])
        assert rec["kind"] == "tier-gate"

    def test_record_halt_custom_kind(self, tmp_path):
        _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "my-label",
            "--kind", "custom-kind",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        rec = json.loads(target.read_text().splitlines()[0])
        assert rec["kind"] == "custom-kind"

    def test_record_halt_stdout_shows_observation_record(self, tmp_path):
        r = _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "my-label",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert "observation.record" in r.stdout
        assert "fingerprint=" in r.stdout

    def test_record_halt_fingerprint_deterministic(self, tmp_path):
        """Same action + label → same fingerprint twice."""
        from bin.observations import fingerprint_halt
        expected = fingerprint_halt(action="echo x", classifier_label="silent")
        _run(
            "record-halt",
            "--action", "echo x",
            "--label", "silent",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        target = tmp_path / ".spectre" / "observations.jsonl"
        rec = json.loads(target.read_text().splitlines()[0])
        assert rec["fingerprint"] == expected

    def test_record_halt_missing_action_exits_2(self, tmp_path):
        r = _run(
            "record-halt", "--label", "x",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert r.returncode == 2

    def test_record_halt_missing_label_exits_2(self, tmp_path):
        r = _run(
            "record-halt", "--action", "x",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert r.returncode == 2


class TestFindRecurrencesCli:
    def test_find_recurrences_empty_returns_empty_array(self, tmp_path):
        r = _run(
            "find-recurrences",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert json.loads(r.stdout) == []

    def test_find_recurrences_below_threshold_returns_empty(self, tmp_path):
        # Record once with threshold default 3 — should not surface.
        _run(
            "record-halt",
            "--action", "echo hi",
            "--label", "label-a",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        r = _run(
            "find-recurrences",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert json.loads(r.stdout) == []

    def test_find_recurrences_at_threshold_surfaces(self, tmp_path):
        for _ in range(3):
            _run(
                "record-halt",
                "--action", "vim /etc/x",
                "--label", "host",
                cwd=tmp_path,
                env=_isolate_home(tmp_path),
            )
        r = _run(
            "find-recurrences", "--threshold", "3",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert len(json.loads(r.stdout)) == 1


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
