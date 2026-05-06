"""CLI tests for bin/auditor.py __main__ entrypoint (Phase 2C, issue #13).

Invokes the module via `python3 -m bin.auditor <subcommand>` as a subprocess.

Pragma guard: one assertion per test; no `_rejects_` / `_raises_` without
pytest.raises; no mocked exit.
"""
import json
import pathlib
import subprocess
import sys

import pytest

from bin import _scratchpad

_CMD = [sys.executable, "-m", "bin.auditor"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


# ── audit-action ──────────────────────────────────────────────────────────────

class TestAuditActionCli:
    def test_empty_paths_exits_zero(self):
        r = _run("audit-action", "--action", "echo hi", "--paths", "[]")
        assert r.returncode == 0

    def test_empty_paths_returns_noop(self):
        r = _run("audit-action", "--action", "echo hi", "--paths", "[]")
        summary = json.loads(r.stdout)
        assert summary["kinds"] == ["noop"]

    def test_missing_path_fails_path_exists(self, tmp_path):
        r = _run(
            "audit-action",
            "--action", "touch x",
            "--paths", json.dumps([str(tmp_path / "missing.txt")]),
        )
        summary = json.loads(r.stdout)
        assert summary["passed"] is False

    def test_existing_path_passes(self, tmp_path):
        p = tmp_path / "exists.txt"
        p.write_text("ok", encoding="utf-8")
        r = _run(
            "audit-action",
            "--action", "touch x",
            "--paths", json.dumps([str(p)]),
        )
        summary = json.loads(r.stdout)
        assert summary["passed"] is True

    def test_prose_format_matches_heredoc_output(self, tmp_path):
        p = tmp_path / "exists.txt"
        p.write_text("ok", encoding="utf-8")
        r = _run(
            "audit-action",
            "--action", "touch x",
            "--paths", json.dumps([str(p)]),
            "--prose",
        )
        assert "AUDIT:" in r.stdout

    def test_prose_format_includes_passed_true(self, tmp_path):
        p = tmp_path / "exists.txt"
        p.write_text("ok", encoding="utf-8")
        r = _run(
            "audit-action",
            "--action", "touch x",
            "--paths", json.dumps([str(p)]),
            "--prose",
        )
        assert "passed=True" in r.stdout

    def test_bad_paths_json_exits_1(self):
        r = _run("audit-action", "--action", "x", "--paths", "{not json")
        assert r.returncode == 1

    def test_paths_must_be_list(self):
        r = _run("audit-action", "--action", "x", "--paths", '"a-string"')
        assert r.returncode == 1

    def test_bad_properties_json_exits_1(self):
        r = _run(
            "audit-action",
            "--action", "x",
            "--paths", "[]",
            "--properties", "{not json",
        )
        assert r.returncode == 1

    def test_missing_action_exits_2(self):
        r = _run("audit-action", "--paths", "[]")
        assert r.returncode == 2


# ── audit-and-clear ───────────────────────────────────────────────────────────

class TestAuditAndClearCli:
    def _make_v2_scratchpad(self, sp_path: pathlib.Path, paths: list[str]):
        sp_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 2,
            "active_mission": "test",
            "tracks": {
                "default": {
                    **_scratchpad.track_default(),
                    "paths_touched": paths,
                }
            },
        }
        _scratchpad.atomic_write(sp_path, data)

    def test_happy_path_exits_zero(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        self._make_v2_scratchpad(sp, [])
        r = _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        assert r.returncode == 0

    def test_persists_last_audit_passed_true(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        self._make_v2_scratchpad(sp, [])
        _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        data = _scratchpad.load(sp)
        assert data["tracks"]["default"]["last_audit_passed"] is True

    def test_persists_last_audit_kinds(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        self._make_v2_scratchpad(sp, [])
        _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        data = _scratchpad.load(sp)
        assert data["tracks"]["default"]["last_audit_kinds"] == ["noop"]

    def test_v2_paths_touched_drives_audit(self, tmp_path):
        """Read paths_touched from v2 location (tracks.<track>.paths_touched).
        This is the bug class the §5.5 heredoc had — it read from the v1
        top-level key and silently got [] on every v2 scratchpad."""
        sp = tmp_path / "scratchpad.json"
        missing = tmp_path / "does-not-exist.txt"
        self._make_v2_scratchpad(sp, [str(missing)])
        r = _run(
            "audit-and-clear",
            "--action", "touch x",
            "--scratchpad", str(sp),
            "--track", "default",
            "--json",
        )
        summary = json.loads(r.stdout)
        # Should have failed: path_exists check on a missing path.
        assert summary["passed"] is False

    def test_persists_failures_to_track(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        missing = tmp_path / "missing.txt"
        self._make_v2_scratchpad(sp, [str(missing)])
        _run(
            "audit-and-clear",
            "--action", "touch x",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        data = _scratchpad.load(sp)
        assert len(data["tracks"]["default"]["last_audit_failures"]) >= 1

    def test_atomic_write_preserves_other_tracks(self, tmp_path):
        """audit-and-clear must not clobber siblings under tracks.<other>."""
        sp = tmp_path / "scratchpad.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 2,
            "active_mission": "test",
            "tracks": {
                "default": {
                    **_scratchpad.track_default(),
                    "paths_touched": [],
                },
                "other-track": {
                    **_scratchpad.track_default(),
                    "paths_touched": ["sentinel"],
                    "active_spec": "preserved",
                },
            },
        }
        _scratchpad.atomic_write(sp, data)
        _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        data2 = _scratchpad.load(sp)
        assert data2["tracks"]["other-track"]["active_spec"] == "preserved"

    def test_json_flag_emits_parseable_summary(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        self._make_v2_scratchpad(sp, [])
        r = _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
            "--json",
        )
        summary = json.loads(r.stdout)
        assert summary["passed"] is True

    def test_default_prose_format(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        self._make_v2_scratchpad(sp, [])
        r = _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        assert "AUDIT:" in r.stdout

    def test_round_trip_matches_heredoc_on_disk_state(self, tmp_path):
        """End-to-end: scratchpad on-disk shape must match what the §5.5
        heredoc would have produced (last_audit_kinds / passed / failures
        under tracks.<track>)."""
        sp = tmp_path / "scratchpad.json"
        ok_file = tmp_path / "ok.json"
        ok_file.write_text('{"k": 1}', encoding="utf-8")
        self._make_v2_scratchpad(sp, [str(ok_file)])
        _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        data = _scratchpad.load(sp)
        track = data["tracks"]["default"]
        assert track["last_audit_passed"] is True

    def test_missing_scratchpad_creates_default(self, tmp_path):
        """Missing scratchpad → load() returns DEFAULT (v1) → audit runs on []
        paths → produces noop result. The CLI must not crash."""
        sp = tmp_path / "missing.json"
        r = _run(
            "audit-and-clear",
            "--action", "echo hi",
            "--scratchpad", str(sp),
            "--track", "default",
        )
        assert r.returncode == 0

    def test_missing_action_exits_2(self):
        r = _run("audit-and-clear")
        assert r.returncode == 2

    def test_unknown_subcommand_exits_2(self):
        r = _run("does-not-exist")
        assert r.returncode == 2
