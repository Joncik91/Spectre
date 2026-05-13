"""managed_venv.py — executor-owned Python environment.

Spectre owns the venv; specs must not declare PEP 668 strategy.

Public API
----------
    ensure_venv(project_path) -> pathlib.Path
    pip_install_editable(project_path, target=None) -> None
    normalize_action(action, venv_python) -> str

Stdlib only. Python 3.11+.
"""
from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import sys

__all__ = ["ensure_venv", "pip_install_editable", "normalize_action"]

_VENV_DIR_NAME = ".venv"


# ── Public API ────────────────────────────────────────────────────────────────


def ensure_venv(project_path: pathlib.Path) -> pathlib.Path:
    """Return path to the venv's python interpreter, creating the venv if needed.

    The venv is created at ``<project_path>/state/.venv/``.  Directory mode is
    set to 0700 on creation.  Idempotent: if the interpreter already exists the
    call is a no-op (no subprocess launched).

    Raises RuntimeError on any failure — caller must HALT, not fall back to
    system Python.
    """
    project_path = pathlib.Path(project_path).resolve()
    venv_dir = project_path / "state" / _VENV_DIR_NAME
    python_path = venv_dir / "bin" / "python"

    if python_path.exists():
        # W2: detect stale venv (system Python referenced in pyvenv.cfg was removed/upgraded).
        pyvenv_cfg = venv_dir / "pyvenv.cfg"
        if pyvenv_cfg.exists():
            for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("executable"):
                    _, _, exe = line.partition("=")
                    exe_path = pathlib.Path(exe.strip())
                    if not exe_path.exists():
                        raise RuntimeError(
                            f"HALT: venv stale — executable {exe_path} referenced in "
                            f"{pyvenv_cfg} no longer exists. "
                            "Delete state/.venv to re-create the venv."
                        )
                    break
        return python_path

    # Create venv
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"HALT: python3 -m venv unavailable — {exc}. "
            "Install the 'python3-venv' package and retry."
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"HALT: venv creation failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr.strip()}"
        )

    if not python_path.exists():
        raise RuntimeError(
            f"HALT: venv created but interpreter not found at {python_path}."
        )

    # Mode 0700 on the venv dir
    os.chmod(venv_dir, stat.S_IRWXU)

    return python_path


def pip_install_editable(
    project_path: pathlib.Path,
    target: pathlib.Path | None = None,
) -> None:
    """Run ``<venv-python> -m pip install -e <target>`` with stderr captured.

    ``target`` defaults to ``project_path`` when None.  Caller should pass the
    directory that contains ``pyproject.toml`` — often the project root, not
    ``state/``.

    Raises RuntimeError on non-zero exit.
    """
    project_path = pathlib.Path(project_path).resolve()
    install_target = pathlib.Path(target).resolve() if target is not None else project_path
    venv_python = ensure_venv(project_path)

    result = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-e", str(install_target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"HALT: pip install -e failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr.strip()}"
        )


# Regex for rewriting python/pip at the head of each shell-operator-delimited
# command-list element.  Group 1: the leading prefix (start-of-string or a shell
# operator followed by optional whitespace).  Group 2: optional env-var prefix(es)
# of the form WORD=VALUE followed by whitespace.  Group 3: the bare python/pip token.
#
# Shell operators matched: &&, ||, ;, |, &  (order: longest first to avoid
# partial matches, e.g. || before |).
#
# Heredoc limitation (§6.0): if a heredoc body contains "python" at the start of
# a shell-operator-delimited segment, the regex will rewrite it.  This is
# accepted as a known limitation — specs must not embed Python inside heredocs
# in action/verification strings.
_REWRITE_RE = re.compile(
    r"(^|(?:&&|\|\||;|\||&)\s*)"   # group 1: start or shell operator + optional space
    r"((?:\w+=\S+\s+)*)"           # group 2: zero-or-more env-var assignments
    r"(python3?|pip3?)\b"          # group 3: the bare python/pip token (word-boundary)
)

# Detect heredocs by structural pattern: << optionally followed by - and an
# optional quote, then a word (the delimiter tag).
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")


def normalize_action(action: str, venv_python: pathlib.Path) -> str:
    """Rewrite bare python/pip invocations to use the venv interpreter.

    Rules
    -----
    - Rewrites the head command token of every shell-operator-delimited segment
      (``&&``, ``||``, ``;``, ``|``, ``&``) via regex — does **not** use
      ``shlex.split``/``shlex.join``, so shell operators such as ``&&``, ``>``,
      and ``2>&1`` are left byte-identical.
    - Handles leading env-var prefixes (e.g. ``PYTHONPATH=src python3 -m foo``).
    - Bare ``python3``/``python`` → ``<venv_python>``.
    - Bare ``pip3``/``pip`` → ``<venv_python> -m pip``.
    - Absolute paths (``/usr/bin/python3``) are not matched by the regex.
    - Heredoc blocks (structurally detected via ``<<[delimiter]``) bypass
      rewriting entirely.

    Returns the rewritten string, or the original if no change is needed.
    """
    venv_python = pathlib.Path(venv_python)

    # Skip heredoc blocks — structural detection to avoid false positives.
    if _HEREDOC_RE.search(action):
        return action

    venv_bin = venv_python.parent

    def _sub(m: re.Match) -> str:
        prefix = m.group(1)
        env_vars = m.group(2)
        cmd = m.group(3)
        if cmd.startswith("python"):
            replacement = str(venv_python)
        else:
            # pip / pip3
            replacement = f"{venv_python} -m pip"
        return f"{prefix}{env_vars}{replacement}"

    return _REWRITE_RE.sub(_sub, action)


# ── Scratchpad persistence helpers ────────────────────────────────────────────


def load_venv_python(
    scratchpad_path: pathlib.Path, track: str = "default"
) -> pathlib.Path | None:
    """Read ``venv_python`` for *track* from the scratchpad JSON, or None.

    Lookup order (schema-version-aware):
    1. v2: ``data["tracks"][<track>]["venv_python"]``
    2. v1 fallback: ``data["venv_python"]`` (top-level, legacy placement)

    Returns None when the stored path no longer exists on disk.
    """
    import json

    scratchpad_path = pathlib.Path(scratchpad_path)
    if not scratchpad_path.exists():
        return None
    try:
        data = json.loads(scratchpad_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # v2 per-track location (preferred)
    tracks = data.get("tracks")
    val: str | None = None
    if isinstance(tracks, dict):
        track_data = tracks.get(track) or {}
        val = track_data.get("venv_python")
    # v1 top-level fallback
    if not val:
        val = data.get("venv_python")

    if val:
        p = pathlib.Path(val)
        if p.exists():
            return p
    return None


def persist_venv_python(
    scratchpad_path: pathlib.Path,
    venv_python: pathlib.Path,
    track: str = "default",
) -> None:
    """Write ``venv_python`` (absolute string) to ``tracks.<track>`` in scratchpad JSON.

    Auto-promotes v1 → v2 if needed.  Uses ``_scratchpad.atomic_write`` — safe under interrupt.
    """
    # Import here so managed_venv has no circular dependency at module level.
    from bin import _scratchpad as sp  # noqa: PLC0415

    data = sp.load(scratchpad_path)
    if data.get("version") != 2:
        data = sp.expand_v1_to_v2(data)
    if not isinstance(data.get("tracks"), dict):
        data["tracks"] = {}
    track_data = data["tracks"].get(track) or sp.track_default()
    track_data["venv_python"] = str(venv_python.absolute())
    data["tracks"][track] = track_data
    sp.atomic_write(scratchpad_path, data)


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="managed_venv",
        description="Spectre executor-owned Python venv helpers.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ensure = sub.add_parser(
        "ensure",
        help="Ensure the venv exists; print the interpreter path.",
    )
    p_ensure.add_argument(
        "--project-path",
        default=".",
        help="Project root (default: cwd).",
    )
    p_ensure.add_argument(
        "--scratchpad",
        default="state/scratchpad.json",
        help="Path to scratchpad.json for venv_python persistence.",
    )

    p_install = sub.add_parser(
        "pip-install-editable",
        help="Run <venv-python> -m pip install -e <target>.",
    )
    p_install.add_argument("--project-path", default=".")
    p_install.add_argument(
        "--target",
        default=None,
        help="Directory with pyproject.toml (defaults to --project-path).",
    )

    p_norm = sub.add_parser(
        "normalize",
        help="Print the normalized action string.",
    )
    p_norm.add_argument("--action", required=True)
    p_norm.add_argument("--venv-python", required=True)

    args = parser.parse_args()

    if args.cmd == "ensure":
        try:
            venv_py = ensure_venv(pathlib.Path(args.project_path))
            persist_venv_python(pathlib.Path(args.scratchpad), venv_py)
        except RuntimeError as exc:
            _status.emit("error", "venv.ensure", dest="stderr", reason=str(exc))
            sys.exit(1)
        _status.emit("ok", "venv.ensure", python="state/.venv/bin/python")

    elif args.cmd == "pip-install-editable":
        try:
            pip_install_editable(
                pathlib.Path(args.project_path),
                pathlib.Path(args.target) if args.target else None,
            )
        except RuntimeError as exc:
            _status.emit("error", "venv.pip_install", dest="stderr", reason=str(exc))
            sys.exit(1)
        _status.emit("info", "venv.pip_install", status="ok")

    elif args.cmd == "normalize":
        result = normalize_action(args.action, pathlib.Path(args.venv_python))
        print(result)
