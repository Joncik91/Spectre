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

    def test_output_starts_with_WALK(self, tmp_path):
        state = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        r = _run(
            "init-or-resume",
            "--intent", "build a thing",
            "--draft", str(draft),
            "--state-path", str(state),
        )
        assert r.stdout.strip().startswith("WALK:")

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
        assert "0 rounds" in r.stdout

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
        assert "5 pending" in r.stdout

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
        assert "7 rounds" in r.stdout

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
        assert "YIELD: skipped" in r.stdout

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
        assert "YIELD: skipped (draft missing)" in r.stdout

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
        assert "YIELD: skipped (round_count=0)" in r.stdout

    def test_missing_draft_flag_exits_2(self):
        r = _run("yield-check", "--state-path", "state/.walk.json")
        assert r.returncode == 2
