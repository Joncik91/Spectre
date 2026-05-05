import json
from pathlib import Path

import pytest

from bin import _scratchpad as sp


def test_load_returns_default_when_missing(plugin_root):
    data = sp.load(plugin_root / "state" / "scratchpad.json")
    assert data["step"] == 1
    assert data["failed_hypotheses"] == []
    assert data["last_command"] is None


def test_default_includes_paths_touched_empty_list(plugin_root):
    data = sp.load(plugin_root / "state" / "scratchpad.json")
    assert data["paths_touched"] == []


def test_default_includes_last_drift_check_step_zero(plugin_root):
    data = sp.load(plugin_root / "state" / "scratchpad.json")
    assert data["last_drift_check_step"] == 0


def test_paths_touched_cap_constant_is_at_least_100():
    assert sp.PATHS_TOUCHED_CAP >= 100


def test_load_returns_existing(initial_scratchpad):
    data = sp.load(initial_scratchpad)
    assert data["step"] == 1


def test_atomic_write_creates_file(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    sp.atomic_write(target, {"step": 5})
    assert json.loads(target.read_text())["step"] == 5


def test_atomic_write_no_tmp_left_behind(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    sp.atomic_write(target, {"step": 5})
    leftovers = list((plugin_root / "state").glob("scratchpad.json*.tmp"))
    assert leftovers == []


def test_atomic_write_cleans_up_tmp_on_failure(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    # object() is not JSON-serializable -> json.dump raises TypeError -> cleanup branch fires
    with pytest.raises(TypeError):
        sp.atomic_write(target, {"bad": object()})
    leftovers = list((plugin_root / "state").glob("scratchpad.json*.tmp"))
    assert leftovers == []
    assert not target.exists()  # original target never created


def test_append_failed_hypothesis(initial_scratchpad):
    sp.append_failed_hypothesis(
        initial_scratchpad,
        step=2,
        command="pytest",
        error="ModuleNotFoundError: foo",
    )
    data = json.loads(initial_scratchpad.read_text())
    assert len(data["failed_hypotheses"]) == 1
    assert data["failed_hypotheses"][0]["error"] == "ModuleNotFoundError: foo"
    assert data["failed_hypotheses"][0]["step"] == 2
