import json
from pathlib import Path
from bin import migrate_scratchpad_v1_to_v2 as mig


def test_migrate_v1_moves_fields_under_tracks_default(tmp_path):
    p = tmp_path / "scratchpad.json"
    p.write_text(json.dumps({
        "active_spec": "specs/foo.spec.md",
        "step": 5,
        "paths_touched": ["foo.txt"],
        "failed_hypotheses": [],
        "last_command": "ls",
        "exit_code": 0,
    }))
    result = mig.migrate(p)
    assert result == "migrated"
    data = json.loads(p.read_text())
    assert data["version"] == 2
    assert data["tracks"]["default"]["step"] == 5
    assert data["tracks"]["default"]["paths_touched"] == ["foo.txt"]
    assert data["tracks"]["default"]["active_spec"] == "specs/foo.spec.md"


def test_migrate_v2_is_noop(tmp_path):
    p = tmp_path / "scratchpad.json"
    p.write_text(json.dumps({
        "version": 2,
        "tracks": {"auth": {"step": 3}},
    }))
    result = mig.migrate(p)
    assert result == "noop"
    data = json.loads(p.read_text())
    assert data["tracks"]["auth"]["step"] == 3


def test_migrate_missing_file_creates_v2(tmp_path):
    p = tmp_path / "scratchpad.json"
    result = mig.migrate(p)
    assert result == "created"
    data = json.loads(p.read_text())
    assert data["version"] == 2
    assert data["tracks"] == {}


def test_migrate_preserves_active_spec_at_top_level(tmp_path):
    p = tmp_path / "scratchpad.json"
    p.write_text(json.dumps({
        "active_spec": "specs/foo.spec.md",
        "step": 1,
    }))
    mig.migrate(p)
    data = json.loads(p.read_text())
    assert data["active_mission"] == "specs/foo.spec.md"


def test_migrate_atomic_no_tmp_left_behind(tmp_path):
    p = tmp_path / "scratchpad.json"
    p.write_text(json.dumps({"step": 1}))
    mig.migrate(p)
    leftovers = list(tmp_path.glob("scratchpad.json*.tmp"))
    assert leftovers == []


def test_migrate_corrupt_v1_raises(tmp_path):
    p = tmp_path / "scratchpad.json"
    p.write_text("not json{")
    import pytest
    with pytest.raises(ValueError, match="cannot parse"):
        mig.migrate(p)
