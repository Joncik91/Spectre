import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest_is_valid_json():
    data = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert data["name"] == "sdl-vision-engine"
    assert data["license"] == "MIT"
    # hooks/skills must NOT be in plugin.json — they live elsewhere
    assert "hooks" not in data
    assert "skills" not in data


def test_marketplace_manifest_is_valid_json():
    data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert data["name"] == "spectre-marketplace"
    assert any(p["name"] == "sdl-vision-engine" for p in data["plugins"])


def test_hooks_json_post_tool_use_matcher_is_strictly_bash():
    data = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    post = data["hooks"]["PostToolUse"]
    assert len(post) == 1
    assert post[0]["matcher"] == "Bash"


def test_hooks_json_session_start_runs_hydrate():
    data = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "hydrate.py" in cmd
    assert "${CLAUDE_PLUGIN_ROOT}" in cmd


def test_vision_skill_has_skill_md_with_name_frontmatter():
    path = ROOT / "skills" / "vision" / "SKILL.md"
    text = path.read_text()
    assert text.startswith("---\n")
    assert "name: vision" in text.split("---", 2)[1]


def test_implement_skill_has_skill_md_with_name_frontmatter():
    path = ROOT / "skills" / "implement" / "SKILL.md"
    text = path.read_text()
    assert text.startswith("---\n")
    assert "name: implement" in text.split("---", 2)[1]
