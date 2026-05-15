"""Relative-path authoring + workspace-boundary guard for spec_ast (v1.2.1 #3).

`_action_authored_path` now recognizes relative paths (when a project root is
supplied) and the `touch` authoring verb. Paths that resolve outside the
project root — `../etc/passwd`, absolute paths to system locations, symlink
escapes — are not considered authored, so `self-cycle-produces` keeps firing
for them.
"""
import pathlib

import pytest

from bin import spec_ast


@pytest.fixture
def project_root(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path


# ── Relative-path authoring (was rejected pre-v1.2.1) ────────────────────────

def test_99_tee_relative_path_is_authored(project_root: pathlib.Path):
    paths = spec_ast._action_authored_path(
        "tee schemas/x.json", project_root=project_root
    )
    assert "schemas/x.json" in paths


def test_100_touch_relative_path_is_authored(project_root: pathlib.Path):
    paths = spec_ast._action_authored_path(
        "touch state/cookie.json", project_root=project_root
    )
    assert "state/cookie.json" in paths


def test_101_redirect_relative_path_is_authored(project_root: pathlib.Path):
    paths = spec_ast._action_authored_path(
        "echo hello > state/log.txt", project_root=project_root
    )
    assert "state/log.txt" in paths


# ── Boundary guard: out-of-root paths must NOT be cleared ───────────────────

def test_102_dotdot_escape_not_authored(project_root: pathlib.Path):
    paths = spec_ast._action_authored_path(
        "touch ../etc/passwd", project_root=project_root
    )
    assert paths == []


def test_103_absolute_outside_root_not_authored(project_root: pathlib.Path):
    paths = spec_ast._action_authored_path(
        "tee /etc/spectre.conf", project_root=project_root
    )
    assert paths == []


def test_104_absolute_inside_root_authored(project_root: pathlib.Path):
    target = project_root / "schemas" / "y.json"
    paths = spec_ast._action_authored_path(
        f"tee {target}", project_root=project_root
    )
    assert str(target) in paths


# ── Backward compatibility: None project_root keeps today's behavior ────────

def test_105_no_project_root_only_abs_paths_authored():
    paths = spec_ast._action_authored_path("tee schemas/x.json")
    assert paths == []  # relative path unrecognized without a root


def test_106_no_project_root_abs_path_authored():
    paths = spec_ast._action_authored_path("tee /tmp/x.json")
    assert "/tmp/x.json" in paths


# ── Touch with multiple paths ───────────────────────────────────────────────

def test_107_touch_multi_path_all_authored(project_root: pathlib.Path):
    paths = spec_ast._action_authored_path(
        "touch state/a.json state/b.json", project_root=project_root
    )
    assert "state/a.json" in paths
    assert "state/b.json" in paths


# ── classify() integration: relative authoring clears self-cycle finding ────

def test_108_classify_with_project_root_clears_self_cycle(
    project_root: pathlib.Path, tmp_path: pathlib.Path
):
    # A two-step spec where step 1's action authors a relative path via
    # `tee` and step 2 references that path. Without the project_root,
    # step 1's authoring goes unrecognized and `self-cycle-produces` may
    # fire when step 1's produces: file matches its own action.
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# Test Spec\n"
        "**Slug:** test-spec\n"
        "## 1. Hard Problem\nfoo\n"
        "## 2. First Principles\n- foo\n"
        "## 3. Algorithm Audit\n- Delete: none\n- Simplify: none\n- Accelerate: none\n"
        "## 4. Speed-of-Light Limit\nfoo\n"
        "## 5. Physics Guardrails\n- foo\n"
        "## 6. Steps\n\n"
        "```yaml\n"
        "- step: 1\n"
        "  why: seed config\n"
        "  action: tee schemas/x.json\n"
        "  verification: test -f schemas/x.json\n"
        "  produces: [file:schemas/x.json]\n"
        "  requires: []\n"
        "```\n\n"
        "## 7. Success Criteria\n- [ ] done\n\n"
        "## 8. Receiver Calibration\n\n"
        "### 8.1 Hard contract\n\n"
        "- mutates: schemas/x.json\n"
        "- never-touches: /etc\n"
        "- decision-budget: none\n"
        "- reboot-survival: none\n",
        encoding="utf-8",
    )
    findings = spec_ast.classify(spec, project_root=project_root)
    self_cycles = [f for f in findings if f.kind == "self-cycle-produces"]
    assert self_cycles == []
