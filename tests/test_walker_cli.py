"""CLI tests for bin/walker.py __main__ entrypoint.

Invokes the module via `python3 -m bin.walker <subcommand>` as a subprocess.

Pragma guard: one assertion per test; no _rejects_/_raises_ without
pytest.raises; no mocked exit.
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


# ── init-or-resume ────────────────────────────────────────────────────────────

class TestInitOrResumeCli:
    def test_happy_path_exits_zero(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.returncode == 0

    def test_creates_state_file(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert state.exists()

    def test_output_starts_with_OK_walker_init(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.stdout.strip().startswith("OK walker.init")

    def test_output_shows_zero_rounds_on_fresh_init(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert "rounds=0" in r.stdout

    def test_output_shows_5_pending_on_fresh_init(self, tmp_path):
        """init_walk seeds 5 concerns by design."""
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert "pending=5" in r.stdout

    def test_output_shows_stop_none_initially(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert "stop=none" in r.stdout

    def test_stderr_empty_on_success(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.stderr == ""

    def test_resume_existing_state_exits_zero(self, tmp_path):
        """Second call with the same state path resumes without reinitialising."""
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        r = _run(
            "init-or-resume",
            "--intent", "ignored-on-resume",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.returncode == 0

    def test_resume_reads_persisted_round_count(self, tmp_path):
        """State round_count from disk is reflected in the resumed output."""
        from bin import walker
        state_path = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        # Initialise and manually advance round_count
        state = walker.init_walk(spec_intent="test", spec_draft_path=draft)
        state.round_count = 7
        walker.persist(state, state_path)
        r = _run(
            "init-or-resume",
            "--intent", "ignored",
            "--draft", str(draft),
            "--state-path", str(state_path),
        )
        assert "rounds=7" in r.stdout

    def test_missing_intent_flag_exits_2(self):
        r = _run("init-or-resume", "--draft", "specs/foo.spec.md.draft")
        assert r.returncode == 2

    def test_missing_draft_flag_exits_2(self):
        r = _run("init-or-resume", "--intent", "build a thing")
        assert r.returncode == 2

    def test_corrupted_state_file_exits_1(self, tmp_path):
        state = tmp_path / ".walk.json"
        state.write_text('{"walker_version": "99.0.0", "spec_intent": "x"}', encoding="utf-8")
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.returncode == 1

    def test_corrupted_state_stderr_nonempty(self, tmp_path):
        state = tmp_path / ".walk.json"
        state.write_text('{"walker_version": "99.0.0", "spec_intent": "x"}', encoding="utf-8")
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.stderr != ""


# ── init-or-resume --json (issue #23) ────────────────────────────────────────


class TestInitOrResumeJsonMode:
    def _init(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
            "--json",
        )
        return r, state, draft

    def test_init_or_resume_json_mode_emits_full_state(self, tmp_path):
        r, _, _ = self._init(tmp_path)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        expected_keys = {
            "walker_version", "spec_intent", "spec_draft_path",
            "asked", "answered", "pending", "stale",
            "stop_reason", "round_count", "yield_history",
        }
        assert expected_keys.issubset(data.keys())

    def test_init_or_resume_json_mode_keys_match_dataclass_fields(self, tmp_path):
        from bin.walker import WalkState
        r, _, _ = self._init(tmp_path)
        data = json.loads(r.stdout)
        dataclass_fields = set(WalkState.__dataclass_fields__.keys())
        # JSON payload is a superset (includes walker_version extra key)
        assert dataclass_fields.issubset(data.keys())

    def test_init_or_resume_json_mode_no_summary_line(self, tmp_path):
        """--json replaces the status line with JSON; no OK walker.init prefix expected."""
        r, _, _ = self._init(tmp_path)
        assert not r.stdout.startswith("OK walker.init")

    def test_init_or_resume_no_json_flag_emits_status_line(self, tmp_path):
        """Without --json the one-line status is emitted."""
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.stdout.strip().startswith("OK walker.init")


# ── peek-pending (issue #23) ──────────────────────────────────────────────────


class TestPeekPendingCli:
    def _setup_state(self, tmp_path):
        from bin import walker
        state_path = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        state = walker.init_walk(spec_intent="test intent", spec_draft_path=draft)
        walker.persist(state, state_path)
        return state_path, draft

    def test_peek_pending_returns_first_concern_body(self, tmp_path):
        state_path, _ = self._setup_state(tmp_path)
        r = _run("peek-pending", "--state-path", str(state_path))
        assert r.returncode == 0
        assert "id=seed-1" in r.stdout
        assert "kind=assumption-surface" in r.stdout
        assert "receiver=human" in r.stdout
        assert "summary=" in r.stdout

    def test_peek_pending_json_mode_returns_concern_dict(self, tmp_path):
        state_path, _ = self._setup_state(tmp_path)
        r = _run("peek-pending", "--state-path", str(state_path), "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["id"] == "seed-1"
        assert data["kind"] == "assumption-surface"
        assert "receivers" in data
        assert "depends_on" in data
        assert "summary" in data

    def test_peek_pending_returns_empty_when_no_pending(self, tmp_path):
        from bin import walker
        state_path = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        # Build state with empty pending
        state = walker.init_walk(spec_intent="test", spec_draft_path=draft)
        # Drain all pending by moving them to asked
        for c in list(state.pending):
            state.asked.append(c)
            state.answered[c.id] = "answer"
        state.pending.clear()
        walker.persist(state, state_path)
        r = _run("peek-pending", "--state-path", str(state_path))
        assert r.returncode == 0
        assert "walker.empty" in r.stdout

    def test_peek_pending_missing_state_file_exits_1(self, tmp_path):
        r = _run("peek-pending", "--state-path", str(tmp_path / "nonexistent.json"))
        assert r.returncode == 1

    def test_peek_pending_json_mode_empty_exits_0(self, tmp_path):
        from bin import walker
        state_path = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        state = walker.init_walk(spec_intent="test", spec_draft_path=draft)
        for c in list(state.pending):
            state.asked.append(c)
            state.answered[c.id] = "answer"
        state.pending.clear()
        walker.persist(state, state_path)
        r = _run("peek-pending", "--state-path", str(state_path), "--json")
        assert r.returncode == 0
        # --json emits "null" on empty (callers expect valid JSON, not a status line)
        assert r.stdout.strip() == "null"


# ── yield-check (Phase 2D) ────────────────────────────────────────────────────


class TestYieldCheckCli:
    def test_no_state_skipped(self, tmp_path):
        draft = tmp_path / "x.spec.md.draft"
        draft.write_text("# x\n")
        r = _run(
            "yield-check",
            "--draft", str(draft),
            "--state-path", str(tmp_path / ".walk.json"),
        )
        assert "walker.yield_skipped" in r.stdout

    def test_no_draft_skipped(self, tmp_path):
        from bin import walker
        sp = tmp_path / ".walk.json"
        state = walker.init_walk(spec_intent="x", spec_draft_path=tmp_path / "missing.draft")
        state.round_count = 2
        walker.persist(state, sp)
        r = _run(
            "yield-check",
            "--draft", str(tmp_path / "missing.draft"),
            "--state-path", str(sp),
        )
        assert "walker.yield_skipped" in r.stdout
        assert "draft-missing" in r.stdout

    def test_zero_round_skipped(self, tmp_path):
        from bin import walker
        sp = tmp_path / ".walk.json"
        draft = tmp_path / "x.spec.md.draft"
        draft.write_text("# x\n")
        state = walker.init_walk(spec_intent="x", spec_draft_path=draft)
        # round_count default 0
        walker.persist(state, sp)
        r = _run(
            "yield-check",
            "--draft", str(draft),
            "--state-path", str(sp),
        )
        assert "walker.yield_skipped" in r.stdout
        assert "round_count=0" in r.stdout

    def test_missing_draft_flag_exits_2(self):
        r = _run("yield-check", "--state-path", "state/.walk.json")
        assert r.returncode == 2
