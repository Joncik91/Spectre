"""tests/test_prompt_level_emissions.py — PROMPT-level emission standardization (Axis D).

Covers:
1. walker peek-pending emits PROMPT walker.concern with id/round/prompt/options fields.
2. walker peek-pending omits options= when concern.prefab_options is empty.
3. walker peek-pending --json routes PROMPT to stderr (stdout stays pure JSON).
4. spectre _status emit subcommand emits a well-formed PROMPT line.
5. spectre _status emit exits 1 for an unknown level.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_WALKER_CMD = [sys.executable, "-m", "bin.walker"]
_STATUS_CMD = [sys.executable, "-m", "bin._status"]


def _run_walker(*args, env_extra=None):
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        _WALKER_CMD + list(args),
        capture_output=True,
        text=True,
        cwd=_REPO,
        env=env,
    )


def _run_status(*args, env_extra=None):
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        _STATUS_CMD + list(args),
        capture_output=True,
        text=True,
        cwd=_REPO,
        env=env,
    )


def _init_state(tmp_path: pathlib.Path) -> pathlib.Path:
    """Initialise a fresh walk state with default seed concerns. Returns state path."""
    state = tmp_path / ".walk.json"
    draft = tmp_path / "foo.spec.md.draft"
    draft.write_text("# draft\n", encoding="utf-8")
    r = _run_walker(
        "init-or-resume",
        "--intent", "build a BTC price fetcher",
        "--draft", str(draft),
        "--state-path", str(state),
    )
    assert r.returncode == 0, f"init-or-resume failed: {r.stderr}"
    return state


# ---------------------------------------------------------------------------
# 1. peek-pending emits PROMPT walker.concern (text mode)
# ---------------------------------------------------------------------------

class TestPeekPendingEmitsPrompt:
    def test_prompt_line_present_in_stdout(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--state-path", str(state))
        assert r.returncode == 0
        assert "PROMPT walker.concern" in r.stdout

    def test_prompt_line_contains_id_field(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--state-path", str(state))
        assert r.returncode == 0
        assert "id=" in r.stdout

    def test_prompt_line_contains_round_field(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--state-path", str(state))
        assert r.returncode == 0
        assert "round=" in r.stdout

    def test_prompt_line_contains_prompt_field(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--state-path", str(state))
        assert r.returncode == 0
        # prompt= field carries the concern summary
        assert "prompt=" in r.stdout


# ---------------------------------------------------------------------------
# 2. options= field omitted when prefab_options is empty
# ---------------------------------------------------------------------------

class TestPeekPendingOptionsField:
    def test_no_options_field_when_prefab_empty(self, tmp_path):
        """Seed concerns have empty prefab_options by default — options= must be absent."""
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--state-path", str(state))
        assert r.returncode == 0
        # Find the PROMPT line specifically
        prompt_lines = [l for l in r.stdout.splitlines() if l.startswith("PROMPT walker.concern")]
        assert prompt_lines, "No PROMPT walker.concern line found"
        assert "options=" not in prompt_lines[0]

    def test_options_field_present_when_prefab_non_empty(self, tmp_path):
        """Appending a concern with prefab_options causes options= to appear."""
        from bin import walker as w
        state_path = tmp_path / ".walk.json"
        draft = tmp_path / "foo.spec.md.draft"
        draft.write_text("# draft\n", encoding="utf-8")
        state = w.init_walk(spec_intent="test intent", spec_draft_path=draft)
        # Clear seed concerns and inject one with explicit prefab_options
        state.pending.clear()
        state.pending.append(w.Concern(
            id="test-prefab-1",
            kind="edge-case",
            receivers=["implement"],
            depends_on=[],
            summary="Should the daemon restart automatically?",
            prefab_options=["yes", "no", "ask-on-fail"],
        ))
        w.persist(state, state_path)
        r = _run_walker("peek-pending", "--state-path", str(state_path))
        assert r.returncode == 0
        prompt_lines = [l for l in r.stdout.splitlines() if l.startswith("PROMPT walker.concern")]
        assert prompt_lines, "No PROMPT walker.concern line found"
        assert "options=yes,no,ask-on-fail" in prompt_lines[0]


# ---------------------------------------------------------------------------
# 3. --json mode: stdout is pure JSON, PROMPT goes to stderr
# ---------------------------------------------------------------------------

class TestPeekPendingJsonModeRoutesPromptToStderr:
    def test_stdout_is_valid_json(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--json", "--state-path", str(state))
        assert r.returncode == 0
        # stdout must parse as JSON
        data = json.loads(r.stdout)
        assert data is not None

    def test_prompt_not_in_stdout_in_json_mode(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--json", "--state-path", str(state))
        assert r.returncode == 0
        assert "PROMPT walker.concern" not in r.stdout

    def test_prompt_in_stderr_in_json_mode(self, tmp_path):
        state = _init_state(tmp_path)
        r = _run_walker("peek-pending", "--json", "--state-path", str(state))
        assert r.returncode == 0
        assert "PROMPT walker.concern" in r.stderr


# ---------------------------------------------------------------------------
# 4. _status emit subcommand emits a well-formed PROMPT line
# ---------------------------------------------------------------------------

class TestStatusEmitSubcommand:
    def test_emit_prompt_exits_zero(self):
        r = _run_status(
            "emit", "prompt", "vision.lock_confirm",
            "--field", "draft=specs/foo.spec.md.draft",
            "--field", "options=yes,refine,cancel",
        )
        assert r.returncode == 0

    def test_emit_prompt_produces_prompt_line(self):
        r = _run_status(
            "emit", "prompt", "vision.lock_confirm",
            "--field", "draft=specs/foo.spec.md.draft",
            "--field", "options=yes,refine,cancel",
        )
        assert r.returncode == 0
        assert "PROMPT vision.lock_confirm" in r.stdout

    def test_emit_prompt_includes_all_fields(self):
        r = _run_status(
            "emit", "prompt", "vision.lock_confirm",
            "--field", "draft=specs/foo.spec.md.draft",
            "--field", "summary=5 steps",
            "--field", "options=yes,refine,cancel",
        )
        assert r.returncode == 0
        line = r.stdout.strip()
        assert "draft=specs/foo.spec.md.draft" in line
        assert "options=yes,refine,cancel" in line

    def test_emit_coverage_continue(self):
        r = _run_status(
            "emit", "prompt", "vision.coverage_continue",
            "--field", "missing=3",
            "--field", "options=yes,refine",
        )
        assert r.returncode == 0
        assert "PROMPT vision.coverage_continue" in r.stdout

    def test_emit_warn_proceed(self):
        r = _run_status(
            "emit", "prompt", "vision.warn_proceed",
            "--field", "warn_count=2",
            "--field", "options=yes,refine,cancel",
        )
        assert r.returncode == 0
        assert "PROMPT vision.warn_proceed" in r.stdout
        assert "warn_count=2" in r.stdout


# ---------------------------------------------------------------------------
# 5. unknown level exits 1
# ---------------------------------------------------------------------------

class TestStatusEmitUnknownLevel:
    def test_unknown_level_exits_nonzero(self):
        r = _run_status("emit", "badlevel", "vision.lock_confirm")
        assert r.returncode != 0
