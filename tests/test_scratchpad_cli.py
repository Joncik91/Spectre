"""CLI tests for bin/_scratchpad.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin._scratchpad <subcommand>` as a subprocess.
"""
import json
import pathlib
import subprocess
import sys


_CMD = [sys.executable, "-m", "bin._scratchpad"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


class TestSetPendingAdoptionCli:
    def test_set_exits_zero(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--track", "default",
            "--fingerprint", "abcdef0123456789",
            "--label", "permission-change: chmod",
            "--action", "chmod 644 /etc/foo",
        )
        assert r.returncode == 0

    def test_set_creates_scratchpad_file(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "abc",
            "--label", "lbl",
            "--action", "act",
        )
        assert sp.is_file()

    def test_set_persists_fingerprint_under_track(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--track", "feature-x",
            "--fingerprint", "ff112233",
            "--label", "lbl",
            "--action", "act",
        )
        data = json.loads(sp.read_text())
        prompt = data["tracks"]["feature-x"]["pending_adoption_prompt"]
        assert prompt["fingerprint"] == "ff112233"

    def test_set_persists_action(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "vim /etc/foo",
        )
        data = json.loads(sp.read_text())
        prompt = data["tracks"]["default"]["pending_adoption_prompt"]
        assert prompt["action"] == "vim /etc/foo"

    def test_set_persists_recorded_at(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        data = json.loads(sp.read_text())
        prompt = data["tracks"]["default"]["pending_adoption_prompt"]
        assert "recorded_at" in prompt

    def test_set_stdout_starts_with_persisted_marker(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "abcdef0123456789",
            "--label", "lbl",
            "--action", "act",
        )
        assert "scratchpad.pending_adoption_set" in r.stdout

    def test_set_promotes_v1_to_v2(self, tmp_path):
        """A pre-existing v1 scratchpad must auto-promote on set."""
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps({"step": 5, "active_spec": "specs/foo.spec.md"}))
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        data = json.loads(sp.read_text())
        assert data.get("version") == 2

    def test_set_preserves_sibling_tracks(self, tmp_path):
        from bin import _scratchpad as sp_mod
        sp = tmp_path / "scratchpad.json"
        # Pre-seed with another track.
        sp_mod.save_track(sp, "other", sp_mod.track_default())
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--track", "default",
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        data = json.loads(sp.read_text())
        assert "other" in data["tracks"]

    def test_set_missing_fingerprint_exits_2(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--label", "lbl",
            "--action", "act",
        )
        assert r.returncode == 2


class TestGetPendingAdoptionCli:
    def test_get_no_pending_returns_marker(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run(
            "get-pending-adoption",
            "--scratchpad", str(sp),
        )
        assert "scratchpad.no_pending_prompt" in r.stdout

    def test_get_after_set_shows_prompt_line(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "abcdef012345",
            "--label", "permission-change: chmod",
            "--action", "act",
        )
        r = _run("get-pending-adoption", "--scratchpad", str(sp))
        assert "scratchpad.pending_prompt" in r.stdout and "fingerprint=abcdef012345" in r.stdout

    def test_get_json_returns_full_dict(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        r = _run("get-pending-adoption", "--scratchpad", str(sp), "--json")
        prompt = json.loads(r.stdout)
        assert prompt["label"] == "lbl"

    def test_get_json_returns_null_when_absent(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text("{}")
        r = _run("get-pending-adoption", "--scratchpad", str(sp), "--json")
        assert json.loads(r.stdout) is None


class TestClearPendingAdoptionCli:
    def test_clear_after_set_resets_to_None(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        _run("clear-pending-adoption", "--scratchpad", str(sp))
        data = json.loads(sp.read_text())
        assert data["tracks"]["default"]["pending_adoption_prompt"] is None

    def test_clear_prints_PROMPT_CLEARED(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        r = _run("clear-pending-adoption", "--scratchpad", str(sp))
        assert "scratchpad.prompt_cleared" in r.stdout

    def test_clear_without_existing_track_prints_NO_TRACK(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps({"version": 2, "tracks": {}}))
        r = _run("clear-pending-adoption", "--scratchpad", str(sp), "--track", "default")
        assert "scratchpad.no_track_to_clear" in r.stdout

    def test_clear_idempotent_after_clear(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run(
            "set-pending-adoption",
            "--scratchpad", str(sp),
            "--fingerprint", "fp",
            "--label", "lbl",
            "--action", "act",
        )
        _run("clear-pending-adoption", "--scratchpad", str(sp))
        # Calling clear again should not raise.
        r = _run("clear-pending-adoption", "--scratchpad", str(sp))
        assert r.returncode == 0


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2
