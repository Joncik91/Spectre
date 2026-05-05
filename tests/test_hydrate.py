import subprocess
import sys
from pathlib import Path


def run_hydrate(cwd: Path) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parent.parent / "bin" / "hydrate.py"
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_no_active_emits_signal_and_lists_specs(plugin_root):
    (plugin_root / "specs" / "foo.spec.md").write_text("# foo")
    result = run_hydrate(plugin_root)
    assert result.returncode == 0
    assert "SIGNAL: No active spec" in result.stdout
    assert "foo.spec.md" in result.stdout


def test_stale_pointer_emits_error_and_lists_specs(plugin_root):
    (plugin_root / "specs" / ".active").write_text("specs/missing.spec.md\n")
    (plugin_root / "specs" / "other.spec.md").write_text("# other")
    result = run_hydrate(plugin_root)
    assert result.returncode == 0
    assert "ERROR: stale .active pointer" in result.stdout
    assert "other.spec.md" in result.stdout


def test_valid_active_emits_full_body(plugin_root):
    spec = plugin_root / "specs" / "primary.spec.md"
    spec.write_text("# Primary\n\nbody line\n")
    (plugin_root / "specs" / ".active").write_text("specs/primary.spec.md\n")
    result = run_hydrate(plugin_root)
    assert result.returncode == 0
    assert "--- ACTIVE SPEC: specs/primary.spec.md ---" in result.stdout
    assert "body line" in result.stdout
    assert "--- END ACTIVE SPEC ---" in result.stdout


def test_valid_active_appends_state_line(plugin_root):
    import json
    (plugin_root / "specs" / "p.spec.md").write_text("# P")
    (plugin_root / "specs" / ".active").write_text("specs/p.spec.md")
    (plugin_root / "state" / "scratchpad.json").write_text(json.dumps({
        "step": 4, "exit_code": 0, "last_command": "ls",
        "active_spec": "specs/p.spec.md", "failed_hypotheses": [],
    }))
    result = run_hydrate(plugin_root)
    assert "STATE: step=4" in result.stdout
    assert "exit_code=0" in result.stdout
