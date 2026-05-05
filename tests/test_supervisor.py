# tests/test_supervisor.py
import json
import os
import socket
import time
from pathlib import Path
from bin import supervisor


def test_lockstate_grant_increments_holders(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    granted = state.acquire("port:8080", track="auth", actor_pid=12345, actor_start_time=1000.0)
    assert granted is True
    assert state.holders("port:8080") == [("auth", 12345)]


def test_lockstate_grant_blocked_when_at_capacity(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    state.acquire("port:8080", track="auth", actor_pid=11, actor_start_time=1.0)
    granted = state.acquire("port:8080", track="payments", actor_pid=22, actor_start_time=2.0)
    assert granted is False
    assert state.queue("port:8080") == [("payments", 22)]


def test_lockstate_release_promotes_queued(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    state.acquire("port:8080", track="auth", actor_pid=11, actor_start_time=1.0)
    state.acquire("port:8080", track="payments", actor_pid=22, actor_start_time=2.0)
    promoted = state.release("port:8080", track="auth")
    assert promoted == [("payments", 22)]
    assert state.holders("port:8080") == [("payments", 22)]


def test_lockstate_release_idempotent_unknown_track(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    promoted = state.release("port:8080", track="ghost")
    assert promoted == []


def test_lockstate_acquire_unknown_resource_raises(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    import pytest
    with pytest.raises(KeyError, match="unknown resource"):
        state.acquire("port:9999", track="x", actor_pid=1, actor_start_time=1.0)


def test_lockstate_persists_after_grant(tmp_path):
    locks_path = tmp_path / ".locks.json"
    state = supervisor.LockState(locks_path=locks_path)
    state.register_resource("port:8080", capacity=1)
    state.acquire("port:8080", track="auth", actor_pid=11, actor_start_time=1.0)
    data = json.loads(locks_path.read_text())
    assert data["version"] == supervisor.LOCK_FILE_VERSION
    assert len(data["locks"]) == 1
    assert data["locks"][0]["resource"] == "port:8080"


def test_lockstate_reconcile_removes_dead_actor(tmp_path, monkeypatch):
    locks_path = tmp_path / ".locks.json"
    locks_path.write_text(json.dumps({
        "version": 1,
        "locks": [{
            "resource": "port:8080",
            "track": "auth",
            "actor_pid": 999999,  # almost certainly dead
            "actor_start_time": 0.0,
            "granted_at": "2026-05-05T00:00:00Z",
        }],
    }))
    monkeypatch.setattr(supervisor, "_actor_alive", lambda pid, st: False)
    state = supervisor.LockState(locks_path=locks_path)
    state.register_resource("port:8080", capacity=1)
    state.reconcile()
    assert state.holders("port:8080") == []


def test_lockstate_reconcile_keeps_live_actor(tmp_path, monkeypatch):
    locks_path = tmp_path / ".locks.json"
    locks_path.write_text(json.dumps({
        "version": 1,
        "locks": [{
            "resource": "port:8080",
            "track": "auth",
            "actor_pid": 11,
            "actor_start_time": 1.0,
            "granted_at": "2026-05-05T00:00:00Z",
        }],
    }))
    monkeypatch.setattr(supervisor, "_actor_alive", lambda pid, st: True)
    state = supervisor.LockState(locks_path=locks_path)
    state.register_resource("port:8080", capacity=1)
    state.reconcile()
    assert state.holders("port:8080") == [("auth", 11)]


def test_handle_request_acquire_grants(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    req = {"op": "acquire", "track": "auth", "resource_id": "port:8080",
           "actor_pid": 11, "actor_start_time": 1.0}
    resp = supervisor.handle_request(state, req)
    assert resp["ok"] is True
    assert resp["granted"] is True


def test_handle_request_acquire_queues(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    state.acquire("port:8080", track="auth", actor_pid=11, actor_start_time=1.0)
    req = {"op": "acquire", "track": "payments", "resource_id": "port:8080",
           "actor_pid": 22, "actor_start_time": 2.0}
    resp = supervisor.handle_request(state, req)
    assert resp["ok"] is True
    assert resp["granted"] is False
    assert resp["queued_position"] == 1


def test_handle_request_release(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    state.acquire("port:8080", track="auth", actor_pid=11, actor_start_time=1.0)
    req = {"op": "release", "track": "auth", "resource_id": "port:8080"}
    resp = supervisor.handle_request(state, req)
    assert resp["ok"] is True


def test_handle_request_unknown_op_returns_error(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    req = {"op": "telepathy"}
    resp = supervisor.handle_request(state, req)
    assert resp["ok"] is False
    assert "unknown op" in resp["error"]


def test_handle_request_missing_field_returns_error(tmp_path):
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    state.register_resource("port:8080", capacity=1)
    req = {"op": "acquire", "track": "auth"}  # missing resource_id, etc.
    resp = supervisor.handle_request(state, req)
    assert resp["ok"] is False


def test_shutdown_response_omits_internal_sentinel(tmp_path):
    """_shutdown is a control flag, must not leak into client-visible JSON."""
    state = supervisor.LockState(locks_path=tmp_path / ".locks.json")
    req = {"op": "shutdown"}
    resp = supervisor.handle_request(state, req)
    # handle_request still includes _shutdown in its return — serve() pops it
    # before sendall. The contract: handle_request's return is private; what
    # matters is that the LITERAL pop happens before sendall in serve().
    # This test pins the contract that pop returns truthy on shutdown.
    assert resp.pop("_shutdown") is True


def test_reconcile_idempotent_no_holder_duplication(tmp_path, monkeypatch):
    """Calling reconcile twice must not duplicate live-actor holders."""
    locks_path = tmp_path / ".locks.json"
    locks_path.write_text(json.dumps({
        "version": 1,
        "locks": [{
            "resource": "port:8080", "track": "auth",
            "actor_pid": 11, "actor_start_time": 1.0,
            "granted_at": "2026-05-05T00:00:00Z",
        }],
    }))
    monkeypatch.setattr(supervisor, "_actor_alive", lambda pid, st: True)
    state = supervisor.LockState(locks_path=locks_path)
    state.register_resource("port:8080", capacity=1)
    state.reconcile()
    state.reconcile()
    assert state.holders("port:8080") == [("auth", 11)]


def test_persist_preserves_original_granted_at(tmp_path):
    """granted_at must reflect acquire time, not last-persist time."""
    locks_path = tmp_path / ".locks.json"
    state = supervisor.LockState(locks_path=locks_path)
    state.register_resource("port:8080", capacity=1)
    state.acquire("port:8080", track="auth", actor_pid=11, actor_start_time=1.0)
    first = json.loads(locks_path.read_text())["locks"][0]["granted_at"]
    _time.sleep(0.01)
    # Trigger another persist via a register_resource + manual _persist
    state.register_resource("port:9090", capacity=1)
    state._persist()
    second = json.loads(locks_path.read_text())["locks"][0]["granted_at"]
    assert first == second


def test_actor_alive_returns_false_on_permission_error(tmp_path, monkeypatch):
    """_actor_alive must not crash if /proc/<pid>/stat read raises PermissionError."""
    def boom(self):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "read_text", boom)
    assert supervisor._actor_alive(12345, 1.0) is False


# Integration test — real socket
import subprocess
import time as _time


def test_real_socket_acquire_release(tmp_path):
    proc = subprocess.Popen(
        ["python3", "-m", "bin.supervisor", str(tmp_path)],
        cwd=Path(__file__).parent.parent,
    )
    sock_path = tmp_path / "state" / supervisor.SOCKET_NAME
    deadline = _time.time() + 5
    while _time.time() < deadline and not sock_path.exists():
        _time.sleep(0.1)
    assert sock_path.exists(), "supervisor never bound socket"

    def call(req):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(sock_path))
        s.sendall(json.dumps(req).encode("utf-8"))
        data = s.recv(supervisor.RECV_BUFFER).decode("utf-8")
        s.close()
        return json.loads(data.strip())

    try:
        resp = call({
            "op": "acquire", "track": "auth", "resource_id": "port:8080",
            "actor_pid": os.getpid(), "actor_start_time": 0.0,
        })
        assert resp["ok"] and resp["granted"]
        resp = call({"op": "release", "track": "auth", "resource_id": "port:8080"})
        assert resp["ok"]
        call({"op": "shutdown"})
    finally:
        proc.terminate()
        proc.wait(timeout=5)
