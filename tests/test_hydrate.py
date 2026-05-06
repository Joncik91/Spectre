import pathlib
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


def test_hydrate_auto_migrates_v1_scratchpad(plugin_root):
    import json
    target = plugin_root / "state" / "scratchpad.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"step": 3, "active_spec": "specs/foo.spec.md"}))
    result = run_hydrate(plugin_root)
    data = json.loads(target.read_text())
    assert data["version"] == 2
    assert "MIGRATED:" in result.stdout


def test_hydrate_v2_scratchpad_no_migration_signal(plugin_root):
    import json
    target = plugin_root / "state" / "scratchpad.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"version": 2, "tracks": {}}))
    result = run_hydrate(plugin_root)
    assert "MIGRATED:" not in result.stdout


def test_hydrate_emits_pending_patches_signal_when_proposed_dir_has_files(tmp_path, monkeypatch, capsys):
    """v0.4.2: SessionStart hydrate surfaces pending template-patches."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    proposed = tmp_path / ".spectre" / "template-patches" / "proposed"
    proposed.mkdir(parents=True)
    (proposed / "patch-a.md").write_text("# a\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from bin import hydrate
    hydrate.surface_pending_template_patches()
    out = capsys.readouterr().out
    assert "PENDING_TEMPLATE_PATCHES: 1" in out


def test_hydrate_emits_zero_when_proposed_dir_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    proposed = tmp_path / ".spectre" / "template-patches" / "proposed"
    proposed.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    from bin import hydrate
    hydrate.surface_pending_template_patches()
    out = capsys.readouterr().out
    assert "PENDING_TEMPLATE_PATCHES: 0" in out


def test_hydrate_emits_zero_when_proposed_dir_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    from bin import hydrate
    hydrate.surface_pending_template_patches()
    out = capsys.readouterr().out
    assert "PENDING_TEMPLATE_PATCHES: 0" in out


def test_hydrate_proposes_new_patches_for_recurring_fingerprints(tmp_path, monkeypatch):
    """If recurrences have hit threshold and no patch exists yet, hydrate
    auto-proposes one."""
    from bin import observations, hydrate
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    # Three halts of the same fingerprint → recurrence
    for _ in range(3):
        observations.record_halt(
            kind="tier-gate", fingerprint="g"*64,
            project_path="/p", spec_slug="s", action="x",
            classifier_label="y",
        )
    hydrate.detect_and_propose_patches()
    proposed = tmp_path / ".spectre" / "template-patches" / "proposed"
    md_files = list(proposed.glob("*.md"))
    assert len(md_files) >= 1


def test_hydrate_does_not_reproprose_existing_patch(tmp_path, monkeypatch):
    """Idempotency: hydrate must not duplicate a patch on a 2nd run when no new
    halts have occurred. Locks the slug-parity contract between hydrate.detect_and_propose_patches
    and template_patcher.propose_patch (a future divergence in slug computation
    would silently break this and cause patch duplicates)."""
    from bin import observations, hydrate
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        observations.record_halt(
            kind="tier-gate", fingerprint="g" * 64,
            project_path="/p", spec_slug="s", action="x",
            classifier_label="y",
        )
    hydrate.detect_and_propose_patches()
    proposed_dir = tmp_path / ".spectre" / "template-patches" / "proposed"
    first_run_files = sorted(proposed_dir.glob("*.md"))

    # Second run with no new halts — must be idempotent.
    hydrate.detect_and_propose_patches()
    second_run_files = sorted(proposed_dir.glob("*.md"))

    assert first_run_files == second_run_files
