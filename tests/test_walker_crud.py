"""CLI tests for the walker CRUD subcommands:
  get-state, append-concern, answer-concern, stop.

Subprocess hygiene: cwd=worktree root, sys.executable, capture_output=True,
text=True, tmp_path for state files.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_CMD = [sys.executable, "-m", "bin.walker"]
_REPO = pathlib.Path(__file__).parent.parent


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


def _init(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a fresh walk state and return the state path."""
    state = tmp_path / ".walk.json"
    draft = tmp_path / "foo.spec.md.draft"
    draft.write_text("# draft\n", encoding="utf-8")
    r = _run(
        "init-or-resume",
        "--intent", "test intent",
        "--draft", str(draft),
        "--state-path", str(state),
    )
    assert r.returncode == 0, r.stderr
    return state


# ── get-state ─────────────────────────────────────────────────────────────────


class TestGetState:
    def test_get_state_human_format(self, tmp_path):
        state = _init(tmp_path)
        r = _run("get-state", "--state-path", str(state))
        assert r.returncode == 0
        # Fresh init: 0 rounds, 0 answered, 5 pending, stop=none
        assert "rounds=0" in r.stdout
        assert "answered=0" in r.stdout
        assert "pending=5" in r.stdout
        assert "stop=none" in r.stdout

    def test_get_state_json_mode(self, tmp_path):
        state = _init(tmp_path)
        r = _run("get-state", "--state-path", str(state), "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        for key in ("walker_version", "spec_intent", "spec_draft_path",
                    "asked", "answered", "pending", "stale",
                    "stop_reason", "round_count", "yield_history"):
            assert key in data, f"missing key {key!r}"

    def test_get_state_missing_file_exits_nonzero(self, tmp_path):
        r = _run("get-state", "--state-path", str(tmp_path / "nonexistent.json"))
        assert r.returncode == 1

    def test_get_state_missing_file_prints_error(self, tmp_path):
        r = _run("get-state", "--state-path", str(tmp_path / "nonexistent.json"))
        assert "ERROR" in r.stderr


# ── append-concern ────────────────────────────────────────────────────────────


class TestAppendConcern:
    def test_append_concern_happy_path(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "append-concern",
            "--id", "my-concern-1",
            "--kind", "edge-case",
            "--receiver", "human",
            "--summary", "What happens at midnight?",
            "--state-path", str(state),
        )
        assert r.returncode == 0
        # Verify pending increased from 5 to 6
        r2 = _run("get-state", "--state-path", str(state))
        assert "pending=6" in r2.stdout

    def test_append_concern_unknown_kind_exits_nonzero(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "append-concern",
            "--id", "bad-kind",
            "--kind", "not-a-real-kind",
            "--receiver", "human",
            "--summary", "irrelevant",
            "--state-path", str(state),
        )
        # argparse exits 2 for invalid choice; production path exits 1
        assert r.returncode != 0

    def test_append_concern_unknown_kind_stderr_nonempty(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "append-concern",
            "--id", "bad-kind",
            "--kind", "not-a-real-kind",
            "--receiver", "human",
            "--summary", "irrelevant",
            "--state-path", str(state),
        )
        assert r.stderr != ""

    def test_append_concern_duplicate_id_in_pending_exits_1(self, tmp_path):
        state = _init(tmp_path)
        # seed-1 is already in pending from init_walk
        r = _run(
            "append-concern",
            "--id", "seed-1",
            "--kind", "edge-case",
            "--receiver", "human",
            "--summary", "duplicate",
            "--state-path", str(state),
        )
        assert r.returncode == 1

    def test_append_concern_duplicate_id_in_pending_prints_error(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "append-concern",
            "--id", "seed-1",
            "--kind", "edge-case",
            "--receiver", "human",
            "--summary", "duplicate",
            "--state-path", str(state),
        )
        assert "ERROR" in r.stderr

    def test_append_concern_duplicate_id_after_answer_exits_1(self, tmp_path):
        state = _init(tmp_path)
        # Answer seed-1, then try to append a new concern with the same id
        _run(
            "answer-concern",
            "--id", "seed-1",
            "--answer", "some answer",
            "--state-path", str(state),
        )
        r = _run(
            "append-concern",
            "--id", "seed-1",
            "--kind", "edge-case",
            "--receiver", "human",
            "--summary", "duplicate after answer",
            "--state-path", str(state),
        )
        assert r.returncode == 1

    def test_append_concern_missing_id_exits_2(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "append-concern",
            "--kind", "edge-case",
            "--receiver", "human",
            "--summary", "no id",
            "--state-path", str(state),
        )
        assert r.returncode == 2

    def test_append_concern_missing_summary_exits_2(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "append-concern",
            "--id", "c-x",
            "--kind", "edge-case",
            "--receiver", "human",
            "--state-path", str(state),
        )
        assert r.returncode == 2


# ── answer-concern ────────────────────────────────────────────────────────────


class TestAnswerConcern:
    def test_answer_concern_moves_pending_to_answered(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "answer-concern",
            "--id", "seed-1",
            "--answer", "No hidden assumptions.",
            "--state-path", str(state),
        )
        assert r.returncode == 0
        r2 = _run("get-state", "--state-path", str(state))
        # After answering seed-1 (1 of 5 initial seeds), _refresh_pending fires
        # and adds seed-semantic-criteria → net pending = 4+1 = 5
        assert "pending=5" in r2.stdout
        assert "answered=1" in r2.stdout
        assert "rounds=1" in r2.stdout

    def test_answer_concern_increments_round_count(self, tmp_path):
        state = _init(tmp_path)
        _run(
            "answer-concern",
            "--id", "seed-1",
            "--answer", "first",
            "--state-path", str(state),
        )
        _run(
            "answer-concern",
            "--id", "seed-mutates",
            "--answer", "second",
            "--state-path", str(state),
        )
        r = _run("get-state", "--state-path", str(state))
        assert "rounds=2" in r.stdout

    def test_answer_concern_missing_id_exits_1(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "answer-concern",
            "--id", "does-not-exist",
            "--answer", "nope",
            "--state-path", str(state),
        )
        assert r.returncode == 1

    def test_answer_concern_missing_id_prints_error(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "answer-concern",
            "--id", "does-not-exist",
            "--answer", "nope",
            "--state-path", str(state),
        )
        assert "ERROR" in r.stderr


# ── stop ──────────────────────────────────────────────────────────────────────


class TestStop:
    def test_stop_sets_reason(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "stop",
            "--reason", "author-arbitrated",
            "--state-path", str(state),
        )
        assert r.returncode == 0
        r2 = _run("get-state", "--state-path", str(state))
        assert "stop=author-arbitrated" in r2.stdout

    def test_stop_accepts_arbitrary_reason(self, tmp_path):
        state = _init(tmp_path)
        r = _run(
            "stop",
            "--reason", "custom-halt",
            "--state-path", str(state),
        )
        assert r.returncode == 0
        data = json.loads(
            _run("get-state", "--state-path", str(state), "--json").stdout
        )
        assert data["stop_reason"] == "custom-halt"

    def test_stop_missing_reason_exits_2(self, tmp_path):
        state = _init(tmp_path)
        r = _run("stop", "--state-path", str(state))
        assert r.returncode == 2

    def test_stop_missing_state_exits_1(self, tmp_path):
        r = _run(
            "stop",
            "--reason", "author-arbitrated",
            "--state-path", str(tmp_path / "nonexistent.json"),
        )
        assert r.returncode == 1
