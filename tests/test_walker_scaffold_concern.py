"""Tests for the walker scaffold-precondition seed concern (§46).

Covers:
- generate_scaffold_precondition_concern fires for each action-verb heuristic
- no-fire when the scaffold step already exists (path in produces)
- no-fire when Step 1 has a no-op / non-matching action
- idempotency (seed-scaffold already in state)
- concern has correct kind, receiver, id
"""
import pathlib
import tempfile

import pytest

from bin import walker


# ── Helpers ────────────────────────────────────────────────────────────────────


def _state() -> walker.WalkState:
    """Minimal blank walk state."""
    return walker.WalkState(
        spec_intent="test",
        spec_draft_path=pathlib.Path("/tmp/test.spec.md.draft"),
    )


def _step(n: int, action: str, produces: list[str] | None = None) -> dict:
    return {
        "step": n,
        "why": "test",
        "action": action,
        "produces": produces or [],
        "requires": [],
        "negative_paths": [],
    }


def _scaffold_concerns(steps: list[dict]) -> list[walker.Concern]:
    return walker.generate_scaffold_precondition_concern(_state(), steps)


def _one_concern(steps: list[dict]) -> walker.Concern:
    cs = _scaffold_concerns(steps)
    assert len(cs) == 1, f"expected 1 concern, got {cs}"
    return cs[0]


# ── Concern shape ──────────────────────────────────────────────────────────────


def test_concern_kind_is_scaffold_precondition():
    steps = [_step(1, "pip install -e .")]
    c = _one_concern(steps)
    assert c.kind == "scaffold-precondition"


def test_concern_id_is_seed_scaffold():
    steps = [_step(1, "pip install -e .")]
    c = _one_concern(steps)
    assert c.id == "seed-scaffold"


def test_concern_receiver_is_human():
    steps = [_step(1, "pip install -e .")]
    c = _one_concern(steps)
    assert c.receivers == ["human"]


def test_concern_depends_on_is_empty():
    steps = [_step(1, "pip install -e .")]
    c = _one_concern(steps)
    assert c.depends_on == []


def test_concern_summary_mentions_action():
    action = "pip install -e ."
    steps = [_step(1, action)]
    c = _one_concern(steps)
    assert action in c.summary


# ── pip install -e . heuristic ─────────────────────────────────────────────────


def test_pip_install_editable_fires_when_no_producer():
    steps = [_step(1, "pip install -e .")]
    assert len(_scaffold_concerns(steps)) == 1


def test_pip_install_dot_fires_when_no_producer():
    steps = [_step(1, "pip install . && vidence --version")]
    assert len(_scaffold_concerns(steps)) == 1


def test_pip_install_editable_no_fire_when_pyproject_in_produces():
    steps = [
        _step(0, "write pyproject.toml", produces=["file:pyproject.toml"]),
        _step(1, "pip install -e ."),
    ]
    assert _scaffold_concerns(steps) == []


def test_pip_install_editable_no_fire_when_setup_py_in_produces():
    steps = [
        _step(0, "write setup.py", produces=["file:setup.py"]),
        _step(1, "pip install -e ."),
    ]
    assert _scaffold_concerns(steps) == []


# ── pip install -r <file> heuristic ───────────────────────────────────────────


def test_pip_install_requirements_fires_when_no_producer():
    steps = [_step(1, "pip install -r requirements.txt")]
    assert len(_scaffold_concerns(steps)) == 1


def test_pip_install_requirements_summary_names_file():
    steps = [_step(1, "pip install -r requirements-dev.txt")]
    c = _one_concern(steps)
    assert "requirements-dev.txt" in c.summary


def test_pip_install_requirements_no_fire_when_file_produced():
    steps = [
        _step(0, "write reqs", produces=["file:requirements.txt"]),
        _step(1, "pip install -r requirements.txt"),
    ]
    assert _scaffold_concerns(steps) == []


# ── cargo heuristic ────────────────────────────────────────────────────────────


def test_cargo_build_fires_when_no_cargo_toml():
    steps = [_step(1, "cargo build --release")]
    assert len(_scaffold_concerns(steps)) == 1


def test_cargo_test_fires_when_no_cargo_toml():
    steps = [_step(1, "cargo test")]
    assert len(_scaffold_concerns(steps)) == 1


def test_cargo_build_no_fire_when_cargo_toml_produced():
    steps = [
        _step(0, "scaffold crate", produces=["file:Cargo.toml"]),
        _step(1, "cargo build"),
    ]
    assert _scaffold_concerns(steps) == []


# ── npm heuristic ──────────────────────────────────────────────────────────────


def test_npm_install_fires_when_no_package_json():
    steps = [_step(1, "npm install")]
    assert len(_scaffold_concerns(steps)) == 1


def test_npm_ci_fires_when_no_package_json():
    steps = [_step(1, "npm ci")]
    assert len(_scaffold_concerns(steps)) == 1


def test_npm_run_fires_when_no_package_json():
    steps = [_step(1, "npm run build")]
    assert len(_scaffold_concerns(steps)) == 1


def test_npm_install_no_fire_when_package_json_produced():
    steps = [
        _step(0, "scaffold node", produces=["file:package.json"]),
        _step(1, "npm install"),
    ]
    assert _scaffold_concerns(steps) == []


# ── yarn / pnpm heuristic ─────────────────────────────────────────────────────


def test_yarn_fires_when_no_package_json():
    steps = [_step(1, "yarn")]
    assert len(_scaffold_concerns(steps)) == 1


def test_pnpm_install_fires_when_no_package_json():
    steps = [_step(1, "pnpm install")]
    assert len(_scaffold_concerns(steps)) == 1


# ── make heuristic ─────────────────────────────────────────────────────────────


def test_make_fires_when_no_makefile():
    steps = [_step(1, "make")]
    assert len(_scaffold_concerns(steps)) == 1


def test_make_target_fires_when_no_makefile():
    steps = [_step(1, "make install")]
    assert len(_scaffold_concerns(steps)) == 1


def test_make_no_fire_when_makefile_produced():
    steps = [
        _step(0, "write Makefile", produces=["file:Makefile"]),
        _step(1, "make"),
    ]
    assert _scaffold_concerns(steps) == []


# ── go heuristic ───────────────────────────────────────────────────────────────


def test_go_build_fires_when_no_go_mod():
    steps = [_step(1, "go build ./...")]
    assert len(_scaffold_concerns(steps)) == 1


def test_go_test_fires_when_no_go_mod():
    steps = [_step(1, "go test ./...")]
    assert len(_scaffold_concerns(steps)) == 1


def test_go_build_no_fire_when_go_mod_produced():
    steps = [
        _step(0, "go mod init", produces=["file:go.mod"]),
        _step(1, "go build ./..."),
    ]
    assert _scaffold_concerns(steps) == []


# ── python -m heuristic ────────────────────────────────────────────────────────


def test_python_m_non_stdlib_fires():
    steps = [_step(1, "python -m myapp.server")]
    assert len(_scaffold_concerns(steps)) == 1


def test_python3_m_non_stdlib_fires():
    steps = [_step(1, "python3 -m myapp")]
    assert len(_scaffold_concerns(steps)) == 1


def test_python3_m_stdlib_http_server_no_fire():
    # http.server is stdlib — should not fire
    steps = [_step(1, "python3 -m http.server 8080")]
    assert _scaffold_concerns(steps) == []


def test_python3_m_venv_no_fire():
    steps = [_step(1, "python3 -m venv .venv")]
    assert _scaffold_concerns(steps) == []


def test_python3_m_pip_no_fire():
    steps = [_step(1, "python3 -m pip install requests")]
    assert _scaffold_concerns(steps) == []


def test_python_m_non_stdlib_no_fire_when_package_produced():
    steps = [
        _step(0, "scaffold package", produces=["package:myapp"]),
        _step(1, "python3 -m myapp"),
    ]
    assert _scaffold_concerns(steps) == []


# ── systemctl heuristic ────────────────────────────────────────────────────────


def test_systemctl_start_fires_when_no_unit_file():
    steps = [_step(1, "systemctl start myservice")]
    assert len(_scaffold_concerns(steps)) == 1


def test_systemctl_enable_fires_when_no_unit_file():
    steps = [_step(1, "systemctl enable myservice")]
    assert len(_scaffold_concerns(steps)) == 1


def test_systemctl_start_no_fire_when_unit_produced():
    steps = [
        _step(0, "write unit", produces=["file:/etc/systemd/system/myservice.service"]),
        _step(1, "systemctl start myservice"),
    ]
    assert _scaffold_concerns(steps) == []


# ── docker compose heuristic ──────────────────────────────────────────────────


def test_docker_compose_up_fires_when_no_compose_file():
    steps = [_step(1, "docker compose up -d")]
    assert len(_scaffold_concerns(steps)) == 1


def test_docker_compose_hyphen_up_fires():
    steps = [_step(1, "docker-compose up")]
    assert len(_scaffold_concerns(steps)) == 1


def test_docker_compose_no_fire_when_compose_yaml_produced():
    steps = [
        _step(0, "write compose", produces=["file:docker-compose.yml"]),
        _step(1, "docker compose up -d"),
    ]
    assert _scaffold_concerns(steps) == []


# ── No-fire cases ──────────────────────────────────────────────────────────────


def test_no_fire_when_no_steps():
    assert _scaffold_concerns([]) == []


def test_no_fire_when_no_step_1():
    steps = [_step(2, "pip install -e .")]
    assert _scaffold_concerns(steps) == []


def test_no_fire_for_plain_echo_action():
    steps = [_step(1, "echo hello")]
    assert _scaffold_concerns(steps) == []


def test_no_fire_for_mkdir_action():
    steps = [_step(1, "mkdir -p /tmp/out")]
    assert _scaffold_concerns(steps) == []


# ── Idempotency ────────────────────────────────────────────────────────────────


def test_no_fire_when_seed_scaffold_already_in_asked():
    state = _state()
    existing = walker.Concern(
        id="seed-scaffold",
        kind="scaffold-precondition",
        receivers=["human"],
        depends_on=[],
        summary="already asked",
    )
    state.asked.append(existing)
    steps = [_step(1, "pip install -e .")]
    result = walker.generate_scaffold_precondition_concern(state, steps)
    assert result == []


def test_no_fire_when_seed_scaffold_already_in_pending():
    state = _state()
    existing = walker.Concern(
        id="seed-scaffold",
        kind="scaffold-precondition",
        receivers=["human"],
        depends_on=[],
        summary="already pending",
    )
    state.pending.append(existing)
    steps = [_step(1, "pip install -e .")]
    result = walker.generate_scaffold_precondition_concern(state, steps)
    assert result == []


def test_no_fire_when_seed_scaffold_already_answered():
    state = _state()
    state.answered["seed-scaffold"] = "yes, there is a scaffold step"
    steps = [_step(1, "pip install -e .")]
    result = walker.generate_scaffold_precondition_concern(state, steps)
    assert result == []
