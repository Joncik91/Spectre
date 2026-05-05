"""Client API for tracks to talk to the local supervisor. Stdlib only."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from bin import supervisor

_SPAWN_WAIT_SECONDS = 5
_RECV_BUFFER = 65536


def _socket_path(project_root: Path) -> Path:
    return Path(project_root) / "state" / supervisor.SOCKET_NAME


def _pid_path(project_root: Path) -> Path:
    return Path(project_root) / "state" / supervisor.PID_FILE_NAME


def _send(project_root: Path, req: dict[str, Any]) -> dict[str, Any]:
    sock_path = _socket_path(project_root)
    if not sock_path.exists():
        raise RuntimeError(f"supervisor socket missing: {sock_path}")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            s.connect(str(sock_path))
        except ConnectionRefusedError:
            # Stale socket from a SIGKILL'd or crashed supervisor.
            # Clean it up so the next ensure_supervisor_running re-spawns.
            sock_path.unlink(missing_ok=True)
            pid_file = _pid_path(project_root)
            pid_file.unlink(missing_ok=True)
            raise RuntimeError(f"supervisor socket stale (connection refused): {sock_path}")
        s.sendall(json.dumps(req).encode("utf-8"))
        buf = s.recv(_RECV_BUFFER).decode("utf-8")
    finally:
        s.close()
    return json.loads(buf.strip())


def ensure_supervisor_running(project_root: Path) -> int:
    """Spawn the supervisor if not running. Returns its PID."""
    project_root = Path(project_root)
    pid_path = _pid_path(project_root)
    sock_path = _socket_path(project_root)
    if pid_path.exists() and sock_path.exists():
        try:
            return int(pid_path.read_text())
        except ValueError:
            pass
    # Spawn detached
    proc = subprocess.Popen(
        [sys.executable, "-m", "bin.supervisor", str(project_root)],
        cwd=Path(__file__).parent.parent,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + _SPAWN_WAIT_SECONDS
    while time.time() < deadline and not sock_path.exists():
        time.sleep(0.1)
    if not sock_path.exists():
        raise RuntimeError(f"supervisor failed to bind socket within {_SPAWN_WAIT_SECONDS}s")
    return proc.pid


def _self_actor() -> tuple[int, float]:
    pid = os.getpid()
    stat = Path(f"/proc/{pid}/stat").read_text()
    rparen = stat.rfind(")")
    after = stat[rparen + 2:].split()
    return pid, float(after[19])


def acquire(project_root: Path, *, track_name: str, resource_id: str) -> dict[str, Any]:
    pid, st = _self_actor()
    return _send(project_root, {
        "op": "acquire",
        "track": track_name,
        "resource_id": resource_id,
        "actor_pid": pid,
        "actor_start_time": st,
    })


def release(project_root: Path, *, track_name: str, resource_id: str) -> dict[str, Any]:
    return _send(project_root, {
        "op": "release",
        "track": track_name,
        "resource_id": resource_id,
    })


def status(project_root: Path) -> dict[str, Any]:
    return _send(project_root, {"op": "status"})


def heartbeat(project_root: Path, *, track_name: str) -> dict[str, Any]:
    return _send(project_root, {"op": "heartbeat", "track": track_name})
