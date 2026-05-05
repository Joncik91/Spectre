import json
import subprocess
import sys
from pathlib import Path


def test_full_cycle(plugin_root):
    """Hydrate (no spec) -> create spec + .active -> hydrate (active) -> compact (success) -> compact (failure)."""
    bin_dir = Path(__file__).resolve().parent.parent / "bin"

    # 1. Hydrate before any spec exists.
    r = subprocess.run([sys.executable, str(bin_dir / "hydrate.py")],
                       cwd=plugin_root, capture_output=True, text=True)
    assert "SIGNAL: No active spec" in r.stdout

    # 2. Create a spec and flip .active (simulating /vision).
    (plugin_root / "specs" / "demo.spec.md").write_text("# Demo\n\nbody\n")
    (plugin_root / "specs" / ".active").write_text("specs/demo.spec.md\n")
    (plugin_root / "state" / "scratchpad.json").write_text(json.dumps({
        "active_spec": "specs/demo.spec.md", "step": 1,
        "last_command": None, "exit_code": None, "delta": None,
        "timestamp": None, "failed_hypotheses": [],
    }))

    # 3. Hydrate with active spec.
    r = subprocess.run([sys.executable, str(bin_dir / "hydrate.py")],
                       cwd=plugin_root, capture_output=True, text=True)
    assert "--- ACTIVE SPEC: specs/demo.spec.md ---" in r.stdout
    assert "body" in r.stdout

    # 4. Compact a successful command.
    event = {"tool_name": "Bash",
             "tool_input": {"command": "ls"},
             "tool_response": {"stdout": "", "stderr": "", "exit_code": 0}}
    r = subprocess.run([sys.executable, str(bin_dir / "compact.py")],
                       cwd=plugin_root, input=json.dumps(event),
                       capture_output=True, text=True)
    payload = json.loads(r.stdout)
    assert "COMMAND_RESULT: 0" in payload["additionalContext"]
    assert "specs/demo.spec.md" in payload["additionalContext"]

    # 5. Compact a failing command.
    event["tool_input"]["command"] = "pytest"
    event["tool_response"] = {"stdout": "", "stderr": "ModuleNotFoundError: x\n", "exit_code": 1}
    subprocess.run([sys.executable, str(bin_dir / "compact.py")],
                   cwd=plugin_root, input=json.dumps(event),
                   capture_output=True, text=True)
    data = json.loads((plugin_root / "state" / "scratchpad.json").read_text())
    assert data["exit_code"] == 1
    assert len(data["failed_hypotheses"]) == 1
    assert "ModuleNotFoundError" in data["failed_hypotheses"][0]["error"]
