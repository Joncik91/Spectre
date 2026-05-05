import json
import os
import socket
import subprocess
import time
from pathlib import Path
import pytest
from bin import track, supervisor


@pytest.fixture
def running_supervisor(tmp_path):
    proc = subprocess.Popen(
        ["python3", "-m", "bin.supervisor", str(tmp_path)],
        cwd=Path(__file__).parent.parent,
    )
    sock_path = tmp_path / "state" / supervisor.SOCKET_NAME
    deadline = time.time() + 5
    while time.time() < deadline and not sock_path.exists():
        time.sleep(0.1)
    assert sock_path.exists()
    yield tmp_path
    try:
        track._send(tmp_path, {"op": "shutdown"})
    except Exception:
        pass
    proc.terminate()
    proc.wait(timeout=5)


def test_acquire_grants_first(running_supervisor):
    resp = track.acquire(running_supervisor, track_name="auth", resource_id="port:8080")
    assert resp["granted"] is True


def test_release_after_acquire(running_supervisor):
    track.acquire(running_supervisor, track_name="auth", resource_id="port:8080")
    resp = track.release(running_supervisor, track_name="auth", resource_id="port:8080")
    assert resp["ok"] is True


def test_status_returns_locks_dict(running_supervisor):
    track.acquire(running_supervisor, track_name="auth", resource_id="port:8080")
    s = track.status(running_supervisor)
    assert "port:8080" in s["locks"]


def test_ensure_supervisor_running_spawns_when_absent(tmp_path):
    pid = track.ensure_supervisor_running(tmp_path)
    sock_path = tmp_path / "state" / supervisor.SOCKET_NAME
    deadline = time.time() + 5
    while time.time() < deadline and not sock_path.exists():
        time.sleep(0.1)
    assert sock_path.exists()
    track._send(tmp_path, {"op": "shutdown"})
    # Wait a moment for cleanup
    time.sleep(0.5)


def test_ensure_supervisor_idempotent_when_running(running_supervisor):
    pid_first = track.ensure_supervisor_running(running_supervisor)
    pid_second = track.ensure_supervisor_running(running_supervisor)
    assert pid_first == pid_second


def test_send_stale_socket_raises_runtime_error(tmp_path):
    """If sock file exists but no supervisor listens, _send must raise RuntimeError + clean up."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    sock_path = state_dir / supervisor.SOCKET_NAME
    pid_path = state_dir / supervisor.PID_FILE_NAME
    # Create a sock file with no listener — connect will refuse
    sock_path.touch()
    pid_path.write_text("99999")
    with pytest.raises(RuntimeError, match="stale"):
        track._send(tmp_path, {"op": "status"})


def test_send_stale_socket_cleans_up_files(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    sock_path = state_dir / supervisor.SOCKET_NAME
    pid_path = state_dir / supervisor.PID_FILE_NAME
    sock_path.touch()
    pid_path.write_text("99999")
    with pytest.raises(RuntimeError):
        track._send(tmp_path, {"op": "status"})
    assert not sock_path.exists()
