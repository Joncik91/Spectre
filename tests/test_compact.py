import json
import subprocess
import sys
from pathlib import Path


def run_compact(cwd: Path, event: dict) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parent.parent / "bin" / "compact.py"
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        input=json.dumps(event),
        capture_output=True,
        text=True,
    )


def make_event(command: str, exit_code: int = 0, stdout: str = "", stderr: str = "") -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": stdout, "stderr": stderr, "exit_code": exit_code},
    }


def test_emits_additional_context_json(plugin_root):
    result = run_compact(plugin_root, make_event("ls"))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "additionalContext" in payload
    ctx = payload["additionalContext"]
    assert "COMMAND_RESULT: 0" in ctx
    assert "ANCHOR:" in ctx


def test_delta_for_mkdir(plugin_root):
    result = run_compact(plugin_root, make_event("mkdir -p foo/bar"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "mkdir" in ctx.lower() or "foo/bar" in ctx


def test_delta_for_unknown_command(plugin_root):
    result = run_compact(plugin_root, make_event("some_weird_binary --flag"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "unknown" in ctx.lower()


def test_anchor_uses_active_spec(plugin_root):
    (plugin_root / "specs" / ".active").write_text("specs/x.spec.md")
    result = run_compact(plugin_root, make_event("ls"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "specs/x.spec.md" in ctx


def test_anchor_when_no_active_spec(plugin_root):
    result = run_compact(plugin_root, make_event("ls"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "no active spec" in ctx.lower()
