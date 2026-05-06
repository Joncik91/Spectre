"""CLI tests for bin/track.py __main__ entrypoint (Phase 2D, issue #13).

Invokes the module via `python3 -m bin.track <subcommand>` as a subprocess.
The supervisor is spawned per-test (cwd=tmp_path/project).
"""
import json
import pathlib
import socket
import subprocess
import sys
import time

import pytest

_CMD = [sys.executable, "-m", "bin.track"]
_REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(*args, cwd=None):
    return subprocess.run(
        _CMD + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or _REPO,
    )


def _stop_supervisor(project: pathlib.Path) -> None:
    """Best-effort supervisor shutdown by socket-disconnect + pid-kill."""
    pid_path = project / "state" / "supervisor.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text())
            import os, signal
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
        except (ValueError, ProcessLookupError, PermissionError):
            pass


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "state").mkdir(parents=True)
    yield proj
    _stop_supervisor(proj)


class TestAcquireCli:
    def test_acquire_grants_unique_resource(self, project):
        r = _run(
            "acquire",
            "--project", str(project),
            "--track", "alpha",
            "--resources", "port:8001",
        )
        assert r.returncode == 0

    def test_acquire_prints_ACQUIRED(self, project):
        r = _run(
            "acquire",
            "--project", str(project),
            "--track", "alpha",
            "--resources", "port:8002",
        )
        assert "ACQUIRED: port:8002" in r.stdout

    def test_acquire_multiple_resources(self, project):
        r = _run(
            "acquire",
            "--project", str(project),
            "--track", "alpha",
            "--resources", "port:8003,port:8004",
        )
        assert "ACQUIRED: port:8003" in r.stdout and "ACQUIRED: port:8004" in r.stdout

    def test_acquire_queued_exits_one(self, project):
        # First acquisition by track alpha.
        _run(
            "acquire",
            "--project", str(project),
            "--track", "alpha",
            "--resources", "port:8005",
        )
        # Second acquisition by track beta on the same resource → queued.
        r = _run(
            "acquire",
            "--project", str(project),
            "--track", "beta",
            "--resources", "port:8005",
        )
        assert r.returncode == 1

    def test_acquire_queued_prints_QUEUED(self, project):
        _run(
            "acquire", "--project", str(project),
            "--track", "alpha", "--resources", "port:8006",
        )
        r = _run(
            "acquire", "--project", str(project),
            "--track", "beta", "--resources", "port:8006",
        )
        assert "QUEUED: port:8006" in r.stdout

    def test_acquire_empty_resources_exits_1(self, project):
        r = _run(
            "acquire",
            "--project", str(project),
            "--track", "alpha",
            "--resources", "",
        )
        assert r.returncode == 1


class TestReleaseCli:
    def test_release_after_acquire_exits_zero(self, project):
        _run(
            "acquire", "--project", str(project),
            "--track", "alpha", "--resources", "port:9001",
        )
        r = _run(
            "release", "--project", str(project),
            "--track", "alpha", "--resources", "port:9001",
        )
        assert r.returncode == 0

    def test_release_prints_RELEASED(self, project):
        _run(
            "acquire", "--project", str(project),
            "--track", "alpha", "--resources", "port:9002",
        )
        r = _run(
            "release", "--project", str(project),
            "--track", "alpha", "--resources", "port:9002",
        )
        assert "RELEASED: port:9002" in r.stdout

    def test_release_then_reacquire_succeeds(self, project):
        _run(
            "acquire", "--project", str(project),
            "--track", "alpha", "--resources", "port:9003",
        )
        _run(
            "release", "--project", str(project),
            "--track", "alpha", "--resources", "port:9003",
        )
        r = _run(
            "acquire", "--project", str(project),
            "--track", "beta", "--resources", "port:9003",
        )
        assert r.returncode == 0

    def test_release_idempotent(self, project):
        """Releasing an unowned resource is a no-op (supervisor returns no error)."""
        r = _run(
            "release", "--project", str(project),
            "--track", "alpha", "--resources", "port:9999",
        )
        # Supervisor not running → connection error path. Acquire first.
        _run(
            "acquire", "--project", str(project),
            "--track", "alpha", "--resources", "port:9888",
        )
        r2 = _run(
            "release", "--project", str(project),
            "--track", "alpha", "--resources", "port:9888",
        )
        # Second release of same resource — idempotent on supervisor.
        r3 = _run(
            "release", "--project", str(project),
            "--track", "alpha", "--resources", "port:9888",
        )
        assert r3.returncode == 0


class TestArgparse:
    def test_no_subcommand_exits_2(self):
        r = _run()
        assert r.returncode == 2

    def test_acquire_missing_track_exits_2(self, project):
        r = _run(
            "acquire", "--project", str(project),
            "--resources", "port:9100",
        )
        assert r.returncode == 2

    def test_acquire_missing_resources_exits_2(self, project):
        r = _run(
            "acquire", "--project", str(project),
            "--track", "alpha",
        )
        assert r.returncode == 2
