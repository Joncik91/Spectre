"""CLI tests for bin/personal_rules.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin.personal_rules <subcommand>` as a subprocess.
"""
import json
import os
import pathlib
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin.personal_rules"]
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


class TestAdoptCli:
    def test_adopt_exits_zero(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "permission-change: chmod",
            "--fingerprint", "abc123",
            "--reason", "ok-for-tmp-dirs",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert r.returncode == 0

    def test_adopt_writes_personal_rules_toml(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "lbl",
            "--fingerprint", "fp",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        toml = tmp_path / ".spectre" / "personal-rules.toml"
        assert toml.is_file()

    def test_adopt_persists_label_in_overrides(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "permission-change: chmod",
            "--fingerprint", "fp1",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        toml = tmp_path / ".spectre" / "personal-rules.toml"
        text = toml.read_text()
        assert "permission-change: chmod" in text

    def test_adopt_bumps_persistent_counter(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "lbl",
            "--fingerprint", "fp",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        data = json.loads(sp.read_text())
        assert data["tracks"]["default"]["session_adoption_count"] == 1

    def test_adopt_stdout_shows_count(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "lbl",
            "--fingerprint", "fp",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert "personal_rules.adopt" in r.stdout
        assert "session_count=1" in r.stdout

    def test_adopt_brake_at_threshold(self, tmp_path):
        """When persistent counter ≥ 3, the CLI must skip the write and emit brake."""
        sp = tmp_path / "scratchpad.json"
        # Pre-seed the counter to 3.
        sp.write_text(json.dumps({
            "version": 2,
            "tracks": {"default": {"session_adoption_count": 3}},
        }))
        r = _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "lbl",
            "--fingerprint", "fp",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert "personal_rules.brake" in r.stdout

    def test_adopt_brake_does_not_write_toml(self, tmp_path):
        """When BRAKE fires, ~/.spectre/personal-rules.toml must not be created."""
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps({
            "version": 2,
            "tracks": {"default": {"session_adoption_count": 5}},
        }))
        _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "lbl",
            "--fingerprint", "fp",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        toml = tmp_path / ".spectre" / "personal-rules.toml"
        assert not toml.exists()

    def test_adopt_missing_label_exits_2(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "adopt", "--scratchpad", str(sp),
            "--fingerprint", "fp", "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        assert r.returncode == 2

    def test_adopt_persists_track_argument(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "adopt",
            "--scratchpad", str(sp),
            "--track", "feature-x",
            "--label", "lbl",
            "--fingerprint", "fp",
            "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        data = json.loads(sp.read_text())
        assert data["tracks"]["feature-x"]["session_adoption_count"] == 1


class TestSessionCountCli:
    def test_count_zero_when_missing_scratchpad(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run("session-count", "--scratchpad", str(sp))
        assert r.stdout.strip() == "0"

    def test_count_after_adopt_returns_one(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "adopt",
            "--scratchpad", str(sp),
            "--label", "lbl", "--fingerprint", "fp", "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        r = _run("session-count", "--scratchpad", str(sp))
        assert r.stdout.strip() == "1"

    def test_count_per_track(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "adopt", "--scratchpad", str(sp),
            "--track", "alpha",
            "--label", "lbl", "--fingerprint", "fp", "--reason", "r",
            cwd=tmp_path,
            env=_isolate_home(tmp_path),
        )
        r = _run("session-count", "--scratchpad", str(sp), "--track", "beta")
        assert r.stdout.strip() == "0"


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
