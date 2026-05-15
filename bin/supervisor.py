"""Per-project Resource lock supervisor. UDS daemon, stdlib only."""
import json
import os
import select
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOCKET_NAME = ".supervisor.sock"
PID_FILE_NAME = ".supervisor.pid"
LOCKS_FILE_NAME = ".locks.json"
LOCK_FILE_VERSION = 1
IDLE_SHUTDOWN_SECONDS = 1800
GRANT_TIMEOUT_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 60
RECV_BUFFER = 65536


def _actor_alive(pid: int, start_time: float) -> bool:
    """Check /proc/<pid>/stat field 22 against expected start_time."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return False
    # Field 22 is starttime (jiffies since boot).
    # Field 2 is the command name in parens — may contain spaces/parens itself,
    # so we find the LAST ')' to safely split past it.
    rparen = stat.rfind(")")
    after = stat[rparen + 2:].split()
    if len(after) < 20:
        return False
    try:
        actual_start = float(after[19])
    except ValueError:
        return False
    return abs(actual_start - start_time) < 1.0


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


_VALID_OPERATOR_MODES = ("interactive", "auto")


class LockState:
    """In-memory + JSON-persisted lock state for one project."""

    def __init__(self, locks_path: Path):
        self.locks_path = Path(locks_path)
        self.resources: dict[str, int] = {}  # resource_id -> capacity
        # Internal 5-tuple storage: (track, pid, start_time, granted_at_iso, operator_mode)
        # operator_mode (v1.2.1 #7) records whether the lock was acquired by
        # an interactive /vision/walker session or an auto-mode /implement run.
        # Downstream consumers (audit, evidence trail) can distinguish the two.
        self._holders: dict[str, list[tuple[str, int, float, str, str]]] = {}
        self.queues: dict[str, list[tuple[str, int, float, str, str]]] = {}

    def register_resource(self, resource_id: str, capacity: int) -> None:
        self.resources[resource_id] = capacity
        self._holders.setdefault(resource_id, [])
        self.queues.setdefault(resource_id, [])

    def acquire(
        self,
        resource_id: str,
        *,
        track: str,
        actor_pid: int,
        actor_start_time: float,
        operator_mode: str = "interactive",
    ) -> bool:
        if resource_id not in self.resources:
            raise KeyError(f"unknown resource: {resource_id}")
        if operator_mode not in _VALID_OPERATOR_MODES:
            raise ValueError(
                f"operator_mode must be one of {_VALID_OPERATOR_MODES}, got {operator_mode!r}"
            )
        granted_at = datetime.now(timezone.utc).isoformat()
        entry = (track, actor_pid, actor_start_time, granted_at, operator_mode)
        if len(self._holders[resource_id]) < self.resources[resource_id]:
            self._holders[resource_id].append(entry)
            self._persist()
            return True
        self.queues[resource_id].append(entry)
        self._persist()
        return False

    def release(self, resource_id: str, *, track: str) -> list[tuple[str, int]]:
        if resource_id not in self.resources:
            return []
        before = len(self._holders[resource_id])
        self._holders[resource_id] = [h for h in self._holders[resource_id] if h[0] != track]
        if len(self._holders[resource_id]) == before:
            return []
        promoted: list[tuple[str, int]] = []
        while self.queues[resource_id] and len(self._holders[resource_id]) < self.resources[resource_id]:
            next_holder = self.queues[resource_id].pop(0)
            self._holders[resource_id].append(next_holder)
            promoted.append((next_holder[0], next_holder[1]))
        self._persist()
        return promoted

    def queue(self, resource_id: str) -> list[tuple[str, int]]:
        """Return 2-tuple view of the queue: [(track, pid), ...]."""
        return [(h[0], h[1]) for h in self.queues.get(resource_id, [])]

    def holders_view(self, resource_id: str) -> list[tuple[str, int]]:
        """Return 2-tuple view of current holders: [(track, pid), ...]."""
        return [(h[0], h[1]) for h in self._holders.get(resource_id, [])]

    def holders(self, resource_id: str) -> list[tuple[str, int]]:
        """Return 2-tuple view of current holders (backward-compat alias)."""
        return self.holders_view(resource_id)

    def reconcile(self) -> None:
        """Read locks.json, probe each actor, re-grant live actors, reap dead ones.

        Idempotent: clears in-memory holders for each known resource before
        repopulating from the persisted file.
        """
        if not self.locks_path.exists():
            return
        try:
            data = json.loads(self.locks_path.read_text())
        except json.JSONDecodeError:
            return
        for rid in self.resources:
            self._holders[rid] = []
        for entry in data.get("locks", []):
            rid = entry["resource"]
            if rid not in self.resources:
                continue
            pid = entry["actor_pid"]
            st = entry["actor_start_time"]
            if _actor_alive(pid, st):
                granted_at = entry.get("granted_at", datetime.now(timezone.utc).isoformat())
                # v1.2.1 #7: default to interactive for pre-1.2.1 lock files
                # that don't carry the field.
                operator_mode = entry.get("operator_mode", "interactive")
                self._holders[rid].append(
                    (entry["track"], pid, st, granted_at, operator_mode)
                )
        self._persist()

    def _persist(self) -> None:
        all_locks = []
        for rid, holders in self._holders.items():
            for track, pid, st, granted_at, operator_mode in holders:
                all_locks.append({
                    "resource": rid,
                    "track": track,
                    "actor_pid": pid,
                    "actor_start_time": st,
                    "granted_at": granted_at,
                    "operator_mode": operator_mode,
                })
        _atomic_write_json(self.locks_path, {
            "version": LOCK_FILE_VERSION,
            "locks": all_locks,
        })


def handle_request(state: LockState, req: dict[str, Any]) -> dict[str, Any]:
    op = req.get("op")
    try:
        if op == "acquire":
            for k in ("track", "resource_id", "actor_pid", "actor_start_time"):
                if k not in req:
                    return {"ok": False, "error": f"missing field: {k}"}
            # v1.2.1 #7: operator_mode defaults to "interactive" so pre-1.2.1
            # callers (and tests) keep working unchanged.
            granted = state.acquire(
                req["resource_id"],
                track=req["track"],
                actor_pid=req["actor_pid"],
                actor_start_time=req["actor_start_time"],
                operator_mode=req.get("operator_mode", "interactive"),
            )
            resp: dict[str, Any] = {"ok": True, "granted": granted}
            if not granted:
                resp["queued_position"] = len(state.queue(req["resource_id"]))
            return resp
        if op == "release":
            for k in ("track", "resource_id"):
                if k not in req:
                    return {"ok": False, "error": f"missing field: {k}"}
            promoted = state.release(req["resource_id"], track=req["track"])
            return {"ok": True, "promoted": promoted}
        if op == "heartbeat":
            return {"ok": True}
        if op == "status":
            return {
                "ok": True,
                "locks": {rid: state.holders_view(rid) for rid in state.resources},
                "queues": {rid: state.queue(rid) for rid in state.resources},
            }
        if op == "shutdown":
            return {"ok": True, "_shutdown": True}
        return {"ok": False, "error": f"unknown op: {op}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


CLIENT_RECV_TIMEOUT_SECONDS = 2.0


def serve(project_root: Path) -> None:
    """Main daemon loop. Binds UDS, runs select() until idle or shutdown.

    Bind is performed BEFORE writing the pid file, so a second-spawn racer
    that loses on bind exits without disturbing the winner's pid file.
    """
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    sock_path = state_dir / SOCKET_NAME
    pid_path = state_dir / PID_FILE_NAME
    locks_path = state_dir / LOCKS_FILE_NAME

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(sock_path))
    except OSError:
        # Another supervisor won the race. Close the spare socket and exit cleanly.
        server.close()
        sys.exit(0)

    pid_path.write_text(str(os.getpid()))
    os.chmod(sock_path, 0o600)
    server.listen(8)
    server.setblocking(False)

    state = LockState(locks_path=locks_path)
    state.reconcile()

    last_activity = time.time()
    try:
        while True:
            r, _, _ = select.select([server], [], [], 60)
            now = time.time()
            if not r:
                if now - last_activity > IDLE_SHUTDOWN_SECONDS:
                    break
                continue
            conn, _ = server.accept()
            last_activity = now
            conn.settimeout(CLIENT_RECV_TIMEOUT_SECONDS)
            should_break = False
            with conn:
                try:
                    buf = conn.recv(RECV_BUFFER)
                except socket.timeout:
                    continue
                if not buf:
                    continue
                try:
                    req = json.loads(buf.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    conn.sendall(b'{"ok": false, "error": "invalid json"}\n')
                    continue
                if req.get("op") == "acquire" and req.get("resource_id"):
                    rid = req["resource_id"]
                    if rid not in state.resources:
                        state.register_resource(rid, capacity=1)
                resp = handle_request(state, req)
                should_break = resp.pop("_shutdown", False)
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            if should_break:
                break
    finally:
        server.close()
        if sock_path.exists():
            sock_path.unlink()
        if pid_path.exists():
            pid_path.unlink()


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    serve(project)
