"""Tests for bin/_scratchpad.py reset + ensure-v2 subcommands (issue #26).

Invokes the module via `python3 -m bin._scratchpad <subcommand>` as a subprocess.
"""
import json
import pathlib
import subprocess
import sys

_CMD = [sys.executable, "-m", "bin._scratchpad"]
_REPO = pathlib.Path(__file__).resolve().parent.parent

# Canonical v1 fixture shape (top-level fields, no version key).
_V1_FIXTURE = {
    "active_spec": "specs/old.spec.md",
    "step": 5,
    "last_command": "pytest",
    "exit_code": 0,
    "delta": "pytest",
    "timestamp": "2026-01-01T00:00:00+00:00",
    "failed_hypotheses": [],
    "paths_touched": ["src/foo.py", "tests/test_foo.py"],
    "last_drift_check_step": 3,
    "last_audit_kinds": ["lint"],
    "last_audit_passed": True,
    "last_audit_failures": [],
    "pending_findings": [],
}

# Canonical v2 fixture with non-null track fields (used for overwrite tests).
_V2_FIXTURE = {
    "version": 2,
    "active_mission": "specs/old.spec.md",
    "decisions_index": "decisions/",
    "graph_snapshot": "specs/.graph.md",
    "tracks": {
        "default": {
            "active_spec": "specs/old.spec.md",
            "step": 7,
            "last_command": "make build",
            "exit_code": 0,
            "delta": "make build",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "failed_hypotheses": [{"step": 3, "command": "bad", "error": "oops", "ts": "x"}],
            "paths_touched": ["src/main.py"],
            "last_drift_check_step": 5,
            "last_audit_kinds": ["type-check"],
            "last_audit_passed": False,
            "last_audit_failures": ["mypy failed"],
            "pending_adoption_prompt": {
                "fingerprint": "abc123",
                "label": "perm",
                "action": "chmod",
                "recorded_at": "2026-01-01T00:00:00+00:00",
            },
        }
    },
}


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


# ---------------------------------------------------------------------------
# reset subcommand tests
# ---------------------------------------------------------------------------


class TestResetSubcommand:
    def test_reset_writes_fresh_v2_with_active_spec(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run("reset", "--scratchpad", str(sp), "--active-spec", "specs/foo.spec.md")
        assert r.returncode == 0, r.stderr
        data = json.loads(sp.read_text())
        assert data["version"] == 2
        assert data["active_mission"] == "specs/foo.spec.md"
        assert "decisions_index" in data
        assert "graph_snapshot" in data
        assert "tracks" in data
        track = data["tracks"]["default"]
        # active_spec inside track set, all null/empty defaults
        assert track["active_spec"] == "specs/foo.spec.md"
        assert track["step"] == 1
        assert track["last_command"] is None
        assert track["exit_code"] is None
        assert track["delta"] is None
        assert track["timestamp"] is None
        assert track["failed_hypotheses"] == []
        assert track["paths_touched"] == []
        assert track["last_drift_check_step"] == 0
        assert track["last_audit_kinds"] == []
        assert track["last_audit_passed"] is None
        assert track["last_audit_failures"] == []
        assert track["pending_adoption_prompt"] is None

    def test_reset_overwrites_existing_v1(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V1_FIXTURE))
        r = _run("reset", "--scratchpad", str(sp), "--active-spec", "specs/new.spec.md")
        assert r.returncode == 0, r.stderr
        data = json.loads(sp.read_text())
        assert data["version"] == 2
        # No v1 top-level keys at root (other than v2 reserved keys)
        v2_reserved = {"version", "active_mission", "tracks", "decisions_index", "graph_snapshot"}
        assert set(data.keys()) <= v2_reserved
        assert data["active_mission"] == "specs/new.spec.md"

    def test_reset_overwrites_existing_v2(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V2_FIXTURE))
        r = _run("reset", "--scratchpad", str(sp), "--active-spec", "specs/fresh.spec.md")
        assert r.returncode == 0, r.stderr
        data = json.loads(sp.read_text())
        track = data["tracks"]["default"]
        # All mutable fields must be back to null/empty defaults
        assert track["step"] == 1
        assert track["last_command"] is None
        assert track["exit_code"] is None
        assert track["failed_hypotheses"] == []
        assert track["paths_touched"] == []
        assert track["last_audit_passed"] is None
        assert track["last_audit_failures"] == []
        assert track["pending_adoption_prompt"] is None
        assert data["active_mission"] == "specs/fresh.spec.md"

    def test_reset_stdout_contains_marker(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run("reset", "--scratchpad", str(sp), "--active-spec", "specs/x.spec.md")
        assert "SCRATCHPAD_RESET" in r.stdout

    def test_reset_missing_active_spec_exits_2(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run("reset", "--scratchpad", str(sp))
        assert r.returncode == 2


# ---------------------------------------------------------------------------
# ensure-v2 subcommand tests
# ---------------------------------------------------------------------------


class TestEnsureV2Subcommand:
    def test_ensure_v2_migrates_v1_to_v2(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V1_FIXTURE))
        r = _run("ensure-v2", "--scratchpad", str(sp))
        assert r.returncode == 0, r.stderr
        data = json.loads(sp.read_text())
        assert data["version"] == 2
        assert "tracks" in data
        track = data["tracks"]["default"]
        # Migration is lossless — paths_touched preserved under tracks.default
        assert track["paths_touched"] == _V1_FIXTURE["paths_touched"]
        assert track["step"] == _V1_FIXTURE["step"]
        assert track["active_spec"] == _V1_FIXTURE["active_spec"]

    def test_ensure_v2_noop_on_existing_v2(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V2_FIXTURE))
        original_bytes = sp.read_bytes()
        r = _run("ensure-v2", "--scratchpad", str(sp))
        assert r.returncode == 0, r.stderr
        assert "ENSURE_V2: noop" in r.stdout
        # File must be semantically identical (content unchanged)
        data_after = json.loads(sp.read_text())
        assert data_after["version"] == 2
        assert data_after["tracks"]["default"]["step"] == _V2_FIXTURE["tracks"]["default"]["step"]

    def test_ensure_v2_noop_idempotent_second_call(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V2_FIXTURE))
        _run("ensure-v2", "--scratchpad", str(sp))
        r2 = _run("ensure-v2", "--scratchpad", str(sp))
        assert r2.returncode == 0
        assert "ENSURE_V2: noop" in r2.stdout

    def test_ensure_v2_writes_fresh_when_file_missing(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        r = _run("ensure-v2", "--scratchpad", str(sp))
        assert r.returncode == 0, r.stderr
        assert "ENSURE_V2: created" in r.stdout
        data = json.loads(sp.read_text())
        assert data["version"] == 2
        assert isinstance(data["tracks"], dict)

    def test_ensure_v2_exits_1_on_malformed_json(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text("not valid json {{{")
        r = _run("ensure-v2", "--scratchpad", str(sp))
        assert r.returncode == 1
        assert r.stderr.strip() != ""

    def test_ensure_v2_stdout_contains_marker(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V1_FIXTURE))
        r = _run("ensure-v2", "--scratchpad", str(sp))
        assert "ENSURE_V2:" in r.stdout


# ---------------------------------------------------------------------------
# Round-trip integration tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_reset_then_ensure_v2_is_idempotent(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        _run("reset", "--scratchpad", str(sp), "--active-spec", "specs/foo.spec.md")
        data_after_reset = json.loads(sp.read_text())
        r = _run("ensure-v2", "--scratchpad", str(sp))
        assert r.returncode == 0
        assert "ENSURE_V2: noop" in r.stdout
        data_after_ensure = json.loads(sp.read_text())
        assert data_after_reset == data_after_ensure

    def test_lock_flow_v1_to_v2_then_reset(self, tmp_path):
        sp = tmp_path / "scratchpad.json"
        sp.write_text(json.dumps(_V1_FIXTURE))
        # Step 1: ensure-v2 migrates
        r1 = _run("ensure-v2", "--scratchpad", str(sp))
        assert r1.returncode == 0
        assert "ENSURE_V2: migrated" in r1.stdout
        mid = json.loads(sp.read_text())
        assert mid["version"] == 2
        # Step 2: reset to new spec
        r2 = _run("reset", "--scratchpad", str(sp), "--active-spec", "specs/locked.spec.md")
        assert r2.returncode == 0
        final = json.loads(sp.read_text())
        assert final["version"] == 2
        assert final["active_mission"] == "specs/locked.spec.md"
        track = final["tracks"]["default"]
        assert track["step"] == 1
        assert track["paths_touched"] == []
        assert track["failed_hypotheses"] == []
        assert track["active_spec"] == "specs/locked.spec.md"
