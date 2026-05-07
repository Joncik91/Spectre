"""test_managed_venv.py — tests for bin/managed_venv.py (v0.5.2 Gap E).

Covers:
  - ensure_venv creates dir with mode 0700
  - ensure_venv is idempotent (second call is no-op, no subprocess)
  - normalize_action rewrites bare python3 -c "..."
  - normalize_action preserves heredoc python invocations
  - normalize_action preserves already-absolute python paths
  - normalize_action rewrites pip install -e . to <venv>/bin/python -m pip install -e .
  - normalize_action rewrites bare python (no suffix)
  - normalize_action rewrites pip3
  - normalize_action leaves non-python commands untouched
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
from unittest import mock

import pytest

from bin.managed_venv import (
    ensure_venv,
    normalize_action,
    pip_install_editable,
    persist_venv_python,
    load_venv_python,
)


# ── ensure_venv ───────────────────────────────────────────────────────────────


def test_ensure_venv_creates_directory_mode_0700(tmp_path):
    """ensure_venv must create state/.venv/ with mode 0700."""
    venv_python = ensure_venv(tmp_path)
    venv_dir = tmp_path / "state" / ".venv"
    assert venv_dir.exists(), "state/.venv/ was not created"
    mode = stat.S_IMODE(venv_dir.stat().st_mode)
    assert mode == 0o700, f"expected 0700 got {oct(mode)}"
    assert venv_python.exists(), "returned interpreter path must exist"
    # The returned path is the symlink inside the venv (not resolved), e.g. .venv/bin/python
    assert "python" in venv_python.name, f"unexpected interpreter name: {venv_python.name}"


def test_ensure_venv_returns_interpreter_inside_state_venv(tmp_path):
    """The returned path must be inside state/.venv/bin/ (as a symlink, not resolved)."""
    venv_python = ensure_venv(tmp_path)
    venv_bin = tmp_path / "state" / ".venv" / "bin"
    assert venv_python.parent == venv_bin, (
        f"interpreter must be inside state/.venv/bin/, got {venv_python.parent}"
    )


def test_ensure_venv_second_call_is_noop(tmp_path):
    """Second call must not launch venv creation (interpreter already exists)."""
    # First call creates the venv.
    first = ensure_venv(tmp_path)

    # Patch subprocess.run to detect if it's called again.
    with mock.patch("bin.managed_venv.subprocess.run") as mock_run:
        second = ensure_venv(tmp_path)

    mock_run.assert_not_called()
    assert first == second


def test_ensure_venv_raises_on_venv_failure(tmp_path):
    """If python3 -m venv exits non-zero, ensure_venv must raise RuntimeError."""
    with mock.patch("bin.managed_venv.subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(
            returncode=1,
            stderr="No space left on device",
        )
        with pytest.raises(RuntimeError, match="HALT"):
            ensure_venv(tmp_path)


def test_ensure_venv_raises_on_missing_venv_module(tmp_path):
    """If the venv module isn't available, ensure_venv raises RuntimeError."""
    with mock.patch("bin.managed_venv.subprocess.run", side_effect=FileNotFoundError("python3")):
        with pytest.raises(RuntimeError, match="HALT"):
            ensure_venv(tmp_path)


# ── normalize_action — python3 rewriting ─────────────────────────────────────


@pytest.fixture
def fake_venv_python(tmp_path):
    p = tmp_path / "bin" / "python"
    p.parent.mkdir(parents=True)
    p.touch()
    return p


def test_normalize_action_rewrites_python3_dash_c(fake_venv_python):
    """bare python3 -c '...' must be rewritten to <venv>/bin/python -c '...'"""
    action = "python3 -c \"print('hello')\""
    result = normalize_action(action, fake_venv_python)
    assert result.startswith(str(fake_venv_python))
    assert "-c" in result
    assert "print" in result


def test_normalize_action_rewrites_bare_python3(fake_venv_python):
    """python3 script.py → <venv>/bin/python script.py"""
    action = "python3 script.py"
    result = normalize_action(action, fake_venv_python)
    assert result == f"{fake_venv_python} script.py"


def test_normalize_action_rewrites_bare_python(fake_venv_python):
    """python script.py → <venv>/bin/python script.py"""
    action = "python script.py"
    result = normalize_action(action, fake_venv_python)
    assert result == f"{fake_venv_python} script.py"


def test_normalize_action_rewrites_pip_install_editable(fake_venv_python):
    """pip install -e . → <venv>/bin/python -m pip install -e ."""
    action = "pip install -e ."
    result = normalize_action(action, fake_venv_python)
    assert result == f"{fake_venv_python} -m pip install -e ."


def test_normalize_action_rewrites_pip3(fake_venv_python):
    """pip3 install requests → <venv>/bin/python -m pip install requests"""
    action = "pip3 install requests"
    result = normalize_action(action, fake_venv_python)
    assert result == f"{fake_venv_python} -m pip install requests"


def test_normalize_action_rewrites_pip_no_args(fake_venv_python):
    """bare pip → <venv>/bin/python -m pip"""
    action = "pip"
    result = normalize_action(action, fake_venv_python)
    assert result == f"{fake_venv_python} -m pip"


# ── normalize_action — preservation rules ────────────────────────────────────


def test_normalize_action_preserves_absolute_python_path(fake_venv_python):
    """An action that already uses an absolute path must be left untouched."""
    action = "/usr/bin/python3 script.py"
    result = normalize_action(action, fake_venv_python)
    assert result == action


def test_normalize_action_preserves_heredoc_python(fake_venv_python):
    """Heredoc python blocks (python3 - <<'PY' ... PY) must be preserved."""
    action = "python3 - <<'PY'\nprint('x')\nPY"
    result = normalize_action(action, fake_venv_python)
    assert result == action


def test_normalize_action_preserves_heredoc_variant_no_quotes(fake_venv_python):
    """python3 - <<PY must also be preserved."""
    action = "python3 - <<PY\nprint('x')\nPY"
    result = normalize_action(action, fake_venv_python)
    assert result == action


def test_normalize_action_preserves_non_python_command(fake_venv_python):
    """Commands that don't start with python/pip must be returned unchanged."""
    action = "pytest tests/ -v"
    result = normalize_action(action, fake_venv_python)
    assert result == action


def test_normalize_action_preserves_absolute_pip_path(fake_venv_python):
    """If someone writes /usr/bin/pip, leave it alone."""
    action = "/usr/bin/pip install foo"
    result = normalize_action(action, fake_venv_python)
    assert result == action


def test_normalize_action_empty_string(fake_venv_python):
    """Empty action must be returned unchanged."""
    assert normalize_action("", fake_venv_python) == ""


# ── scratchpad persistence ────────────────────────────────────────────────────


def test_persist_and_load_venv_python(tmp_path, fake_venv_python):
    """persist_venv_python writes venv_python; load_venv_python reads it back."""
    (tmp_path / "state").mkdir()
    sp_path = tmp_path / "state" / "scratchpad.json"
    sp_path.write_text(json.dumps({"step": 1}))

    persist_venv_python(sp_path, fake_venv_python)
    loaded = load_venv_python(sp_path)

    assert loaded is not None
    assert loaded.resolve() == fake_venv_python.resolve()


def test_load_venv_python_returns_none_when_missing(tmp_path):
    """load_venv_python returns None when scratchpad doesn't exist."""
    result = load_venv_python(tmp_path / "state" / "scratchpad.json")
    assert result is None


def test_load_venv_python_returns_none_for_nonexistent_path(tmp_path):
    """load_venv_python returns None when stored path no longer exists."""
    sp_path = tmp_path / "scratchpad.json"
    sp_path.write_text(json.dumps({"venv_python": "/nonexistent/bin/python"}))
    result = load_venv_python(sp_path)
    assert result is None
