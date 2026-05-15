"""Client API for tracks to talk to the local supervisor. Stdlib only."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# v1.1.1 Fix G: see bin/walker.py for the rationale on this sys.path shim.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bin import supervisor  # noqa: E402

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


def _supervisor_alive(sock_path: Path) -> bool:
    """Probe the UDS — supervisor is alive iff a socket connect succeeds."""
    if not sock_path.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(sock_path))
        return True
    except (ConnectionRefusedError, OSError):
        return False
    finally:
        s.close()


def ensure_supervisor_running(project_root: Path) -> int:
    """Spawn the supervisor if not running. Returns its PID.

    Probes the socket for a live listener before trusting an existing pid file —
    a SIGKILL'd supervisor leaves stale pid+sock on disk that would otherwise
    short-circuit the spawn.
    """
    project_root = Path(project_root)
    pid_path = _pid_path(project_root)
    sock_path = _socket_path(project_root)
    if pid_path.exists() and sock_path.exists() and _supervisor_alive(sock_path):
        try:
            return int(pid_path.read_text())
        except ValueError:
            pass
    # Stale pid/sock → clean up so a fresh bind succeeds
    sock_path.unlink(missing_ok=True)
    pid_path.unlink(missing_ok=True)
    # Spawn detached. Resolve project_root to absolute path because the
    # supervisor's cwd is the Spectre repo (so it can `import bin.supervisor`),
    # not the project. Without resolve, Path('.') would bind in the wrong dir.
    abs_project = project_root.resolve()
    proc = subprocess.Popen(
        [sys.executable, "-m", "bin.supervisor", str(abs_project)],
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


def acquire(
    project_root: Path,
    *,
    track_name: str,
    resource_id: str,
    operator_mode: str = "interactive",
) -> dict[str, Any]:
    pid, st = _self_actor()
    return _send(project_root, {
        "op": "acquire",
        "track": track_name,
        "resource_id": resource_id,
        "actor_pid": pid,
        "actor_start_time": st,
        "operator_mode": operator_mode,
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


# ── CLI entrypoint ────────────────────────────────────────────────────────────


def _split_resources(arg: str) -> list[str]:
    """Split a comma-separated --resources flag into a clean list."""
    return [r.strip() for r in arg.split(",") if r.strip()]


if __name__ == "__main__":
    import argparse
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="track",
        description="Track CLI — acquire / release Resource locks via supervisor.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_acq = sub.add_parser(
        "acquire",
        help=(
            "Ensure supervisor running, then acquire each --resources entry. "
            "Prints `ACQUIRED: <rid>` per granted lock or "
            "`QUEUED: <rid> (position N)` for the first queued lock and exits "
            "1 (queue is a halt-worthy state for the skill)."
        ),
    )
    p_acq.add_argument(
        "--project",
        default=".",
        help="Project root (default: '.', the cwd).",
    )
    p_acq.add_argument("--track", required=True, help="Track name.")
    p_acq.add_argument(
        "--resources",
        required=True,
        help="Comma-separated list of resource ids (e.g. 'port:8080,db:postgres').",
    )

    p_rel = sub.add_parser(
        "release",
        help="Release each --resources entry (idempotent; supervisor no-ops on unknown).",
    )
    p_rel.add_argument(
        "--project",
        default=".",
        help="Project root (default: '.', the cwd).",
    )
    p_rel.add_argument("--track", required=True, help="Track name.")
    p_rel.add_argument(
        "--resources",
        required=True,
        help="Comma-separated list of resource ids.",
    )

    args = parser.parse_args()

    project = Path(args.project)
    rids = _split_resources(args.resources)
    if not rids:
        _status.emit("error", "track.bad_resources", dest="stderr",
                     reason="--resources is empty",
                     remediation="pass a comma-separated list of resource IDs to --resources")
        sys.exit(1)

    if args.cmd == "acquire":
        try:
            ensure_supervisor_running(project)
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "track.supervisor_spawn", dest="stderr", reason=str(exc),
                         remediation="retry /implement; if it recurs open an issue with the full halt output")
            sys.exit(1)
        for rid in rids:
            try:
                resp = acquire(project, track_name=args.track, resource_id=rid)
            except Exception as exc:  # noqa: BLE001
                _status.emit("error", "track.acquire", dest="stderr",
                             resource=rid, reason=str(exc),
                             remediation="retry /implement; if it recurs open an issue with the full halt output")
                sys.exit(1)
            if not resp.get("granted"):
                pos = resp.get("queued_position", "?")
                _status.emit("halt", "track.queue", resource=rid, position=pos,
                         remediation="wait for the holding track to release or pass --skip-queue to bypass")
                sys.exit(1)
            _status.emit("ok", "track.acquire", resource=rid)

    elif args.cmd == "release":
        for rid in rids:
            try:
                release(project, track_name=args.track, resource_id=rid)
            except Exception as exc:  # noqa: BLE001
                _status.emit("error", "track.release", dest="stderr",
                             resource=rid, reason=str(exc),
                             remediation="retry /implement; if it recurs open an issue at https://github.com/Joncik91/Spectre/issues with this halt's full output")
                sys.exit(1)
            _status.emit("ok", "track.release", resource=rid)
