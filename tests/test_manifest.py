import json
from pathlib import Path


def test_manifest_is_valid_json():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    assert data["id"] == "sdl-vision-engine"


def test_post_tool_use_matcher_is_strictly_bash():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    post = data["hooks"]["PostToolUse"]
    assert len(post) == 1
    assert post[0]["matcher"] == {"tool_name": "Bash"}


def test_session_start_runs_hydrate():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    cmd = data["hooks"]["SessionStart"][0]["command"]
    assert "hydrate.py" in cmd


def test_skill_registered():
    path = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text())
    paths = [s["path"] for s in data["skills"]]
    assert "skills/vision.md" in paths
