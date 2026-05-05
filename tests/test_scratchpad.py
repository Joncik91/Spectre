import json
from pathlib import Path

from bin import _scratchpad as sp


def test_load_returns_default_when_missing(plugin_root):
    data = sp.load(plugin_root / "state" / "scratchpad.json")
    assert data["step"] == 1
    assert data["failed_hypotheses"] == []
    assert data["last_command"] is None


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
    assert not (plugin_root / "state" / "scratchpad.json.tmp").exists()


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
