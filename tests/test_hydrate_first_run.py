"""tests/test_hydrate_first_run.py — pin first-run detection logic (Axis C, v0.9.0)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


def _run_hydrate(cwd: Path) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO)
    return subprocess.run(
        [sys.executable, "-m", "bin.hydrate"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _first_run(cwd: Path) -> bool:
    """Import and call _is_first_run() with cwd set to *cwd*."""
    import importlib
    import os

    old_cwd = os.getcwd()
    try:
        os.chdir(cwd)
        # Force reimport so Path(".") resolves against new cwd.
        import bin.hydrate as _h
        importlib.reload(_h)
        return _h._is_first_run()
    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Unit tests for _is_first_run()
# ---------------------------------------------------------------------------

def test_fresh_project_is_first_run(tmp_path):
    """Empty directory with no state/ or specs/ — must be first-run."""
    assert _first_run(tmp_path) is True


def test_state_dir_exists_no_walk_files_still_first_run(tmp_path):
    """state/ dir present but empty (no .walk.json / .eval-result.json) — still first-run."""
    (tmp_path / "state").mkdir()
    assert _first_run(tmp_path) is True


def test_scratchpad_present_not_first_run(tmp_path):
    """state/scratchpad.json exists — not first-run."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "scratchpad.json").write_text("{}", encoding="utf-8")
    assert _first_run(tmp_path) is False


def test_active_spec_present_not_first_run(tmp_path):
    """specs/.active exists — not first-run."""
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / ".active").write_text("specs/foo.spec.md\n", encoding="utf-8")
    assert _first_run(tmp_path) is False


def test_walk_file_present_not_first_run(tmp_path):
    """state/.walk.json present — not first-run."""
    state = tmp_path / "state"
    state.mkdir()
    (state / ".walk.json").write_text("{}", encoding="utf-8")
    assert _first_run(tmp_path) is False


def test_eval_result_file_present_not_first_run(tmp_path):
    """state/*.eval-result.json present — not first-run."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "foo.eval-result.json").write_text("{}", encoding="utf-8")
    assert _first_run(tmp_path) is False


def test_welcomed_marker_suppresses_first_run(tmp_path):
    """state/.spectre-welcomed marker makes is_first_run=False even with no other markers."""
    state = tmp_path / "state"
    state.mkdir()
    (state / ".spectre-welcomed").touch()
    assert _first_run(tmp_path) is False


# ---------------------------------------------------------------------------
# End-to-end: hydrate emit includes is_first_run field
# ---------------------------------------------------------------------------

def test_hydrate_emit_includes_is_first_run_true(tmp_path):
    """Fresh project: hydrate.signal line includes is_first_run=True."""
    result = _run_hydrate(tmp_path)
    assert result.returncode == 0
    assert "hydrate.signal" in result.stdout
    assert "is_first_run=True" in result.stdout


def test_hydrate_emit_includes_is_first_run_false_on_scratchpad(tmp_path):
    """Project with scratchpad: hydrate.signal includes is_first_run=False."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "scratchpad.json").write_text("{}", encoding="utf-8")
    result = _run_hydrate(tmp_path)
    assert result.returncode == 0
    assert "hydrate.signal" in result.stdout
    assert "is_first_run=False" in result.stdout


def test_hydrate_emit_includes_is_first_run_false_on_welcomed(tmp_path):
    """Project with .spectre-welcomed marker: is_first_run=False."""
    state = tmp_path / "state"
    state.mkdir()
    (state / ".spectre-welcomed").touch()
    result = _run_hydrate(tmp_path)
    assert result.returncode == 0
    assert "is_first_run=False" in result.stdout
