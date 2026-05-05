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


def test_failure_appended_to_failed_hypotheses(plugin_root):
    event = make_event(
        "pytest",
        exit_code=1,
        stderr="ModuleNotFoundError: No module named 'foo'\n",
    )
    run_compact(plugin_root, event)
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert len(data["failed_hypotheses"]) == 1
    assert "ModuleNotFoundError" in data["failed_hypotheses"][0]["error"]


def test_success_does_not_append_failed_hypothesis(plugin_root):
    run_compact(plugin_root, make_event("ls", exit_code=0))
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["failed_hypotheses"] == []


def test_failure_with_traceback_captures_first_error_line(plugin_root):
    stderr = "Traceback (most recent call last):\n  File \"x\"\nValueError: bad\n"
    run_compact(plugin_root, make_event("python x.py", exit_code=1, stderr=stderr))
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["failed_hypotheses"][0]["error"].startswith("Traceback")


def test_scratchpad_records_command_and_exit_code(plugin_root):
    run_compact(plugin_root, make_event("echo hi", exit_code=0))
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["last_command"] == "echo hi"
    assert data["exit_code"] == 0


def test_invalid_stdin_emits_error_payload(plugin_root):
    script = Path(__file__).resolve().parent.parent / "bin" / "compact.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=plugin_root,
        input="not json{",
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert "COMPACT_ERROR" in payload["additionalContext"]


def test_delta_for_mkdir_multi_arg(plugin_root):
    result = run_compact(plugin_root, make_event("mkdir foo bar baz"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "foo bar baz" in ctx


def test_delta_for_rm_multiple_flags(plugin_root):
    result = run_compact(plugin_root, make_event("rm -rf -v target.txt"))
    ctx = json.loads(result.stdout)["additionalContext"]
    assert "target.txt" in ctx
    # Should NOT report a flag like "-v" as the file
    assert "rm -v" not in ctx
