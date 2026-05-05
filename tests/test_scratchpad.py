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


def test_default_includes_last_audit_kinds_empty_list():
    assert sp.DEFAULT["last_audit_kinds"] == []


def test_default_includes_last_audit_passed_none():
    assert sp.DEFAULT["last_audit_passed"] is None


def test_default_includes_last_audit_failures_empty_list():
    assert sp.DEFAULT["last_audit_failures"] == []


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


def test_default_v2_top_level_keys():
    keys = set(sp.DEFAULT_V2.keys())
    assert keys == {"version", "active_mission", "tracks", "decisions_index", "graph_snapshot"}


def test_default_v2_version_is_2():
    assert sp.DEFAULT_V2["version"] == 2


def test_default_v2_tracks_is_empty_dict():
    assert sp.DEFAULT_V2["tracks"] == {}


def test_track_default_has_v1_fields():
    td = sp.track_default()
    assert td["step"] == 1
    assert td["paths_touched"] == []
    assert td["last_audit_kinds"] == []
    assert td["failed_hypotheses"] == []


def test_track_default_includes_active_spec_none():
    assert sp.track_default()["active_spec"] is None


def test_load_track_returns_default_for_unknown(plugin_root):
    sp.atomic_write(plugin_root / "state" / "scratchpad.json", dict(sp.DEFAULT_V2))
    td = sp.load_track(plugin_root / "state" / "scratchpad.json", "newtrack")
    assert td["step"] == 1


def test_save_track_writes_under_tracks_key(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    sp.atomic_write(target, dict(sp.DEFAULT_V2))
    sp.save_track(target, "auth", {"step": 5, "active_spec": "specs/auth.spec.md"})
    import json
    data = json.loads(target.read_text())
    assert data["tracks"]["auth"]["step"] == 5


def test_save_track_does_not_clobber_other_tracks(plugin_root):
    target = plugin_root / "state" / "scratchpad.json"
    base = dict(sp.DEFAULT_V2)
    base["tracks"] = {"payments": {"step": 12}}
    sp.atomic_write(target, base)
    sp.save_track(target, "auth", {"step": 1})
    import json
    data = json.loads(target.read_text())
    assert data["tracks"]["payments"]["step"] == 12
    assert data["tracks"]["auth"]["step"] == 1
