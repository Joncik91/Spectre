"""Supervisor lock state carries operator_mode (v1.2.1 #7).

Each lock entry records `operator_mode: "interactive" | "auto"` so downstream
audit/evidence can distinguish operator-driven locks from /implement auto-mode
locks.
"""
import json
import pathlib

import pytest

from bin import supervisor


def test_122_acquire_defaults_to_interactive_mode(tmp_path: pathlib.Path):
    state = supervisor.LockState(tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    granted = state.acquire(
        "port:8080", track="auth", actor_pid=12345, actor_start_time=1000.0
    )
    assert granted is True
    payload = json.loads((tmp_path / ".locks.json").read_text())
    assert payload["locks"][0]["operator_mode"] == "interactive"


def test_123_acquire_records_auto_mode_when_passed(tmp_path: pathlib.Path):
    state = supervisor.LockState(tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    granted = state.acquire(
        "port:8080",
        track="auth",
        actor_pid=12345,
        actor_start_time=1000.0,
        operator_mode="auto",
    )
    assert granted is True
    payload = json.loads((tmp_path / ".locks.json").read_text())
    assert payload["locks"][0]["operator_mode"] == "auto"


def test_124_acquire_raises_on_unknown_operator_mode(tmp_path: pathlib.Path):
    state = supervisor.LockState(tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    with pytest.raises(ValueError, match="operator_mode"):
        state.acquire(
            "port:8080",
            track="auth",
            actor_pid=12345,
            actor_start_time=1000.0,
            operator_mode="unsupervised",
        )
