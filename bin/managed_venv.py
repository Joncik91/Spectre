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
import shlex
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


def normalize_action(action: str, venv_python: pathlib.Path) -> str:
    """Rewrite bare python/pip invocations to use the venv interpreter.

    Rules
    -----
    - Rewrites top-level shell tokens only (via ``shlex``).
    - Bare ``python3``, ``python``, ``pip3``, ``pip`` → ``<venv_python>`` (or
      ``<venv_python> -m pip``).
    - Preserves invocations that already start with an absolute path.
    - Preserves heredoc blocks (``<<'PY'`` … ``PY`` / ``<<PY`` … ``PY``).
    - Preserves invocations nested inside quoted strings (shlex separates them).

    Returns the rewritten string, or the original if no change is needed.
    """
    venv_python = pathlib.Path(venv_python)

    # Skip heredoc blocks — shlex cannot tokenize them safely and the spec
    # prose invariant is "no heredoc-Python in actions/verifications".
    if "<<" in action and ("PY" in action or "'PY'" in action):
        return action

    try:
        tokens = shlex.split(action)
    except ValueError:
        # Untokenisable (mismatched quotes etc.) — return unchanged.
        return action

    if not tokens:
        return action

    head = tokens[0]

    # Already absolute — leave alone.
    if head.startswith("/"):
        return action

    # pip / pip3 → <venv_python> -m pip
    if head in ("pip", "pip3"):
        rest = tokens[1:]
        new_tokens = [str(venv_python), "-m", "pip"] + rest
        return shlex.join(new_tokens)

    # python / python3 → <venv_python>
    if head in ("python", "python3"):
        rest = tokens[1:]
        new_tokens = [str(venv_python)] + rest
        return shlex.join(new_tokens)

    return action


# ── Scratchpad persistence helpers ────────────────────────────────────────────


def load_venv_python(scratchpad_path: pathlib.Path) -> pathlib.Path | None:
    """Read ``venv_python`` from top-level of scratchpad JSON, or None."""
    import json

    scratchpad_path = pathlib.Path(scratchpad_path)
    if not scratchpad_path.exists():
        return None
    try:
        data = json.loads(scratchpad_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    val = data.get("venv_python")
    if val:
        p = pathlib.Path(val)
        if p.exists():
            return p
    return None


def persist_venv_python(
    scratchpad_path: pathlib.Path, venv_python: pathlib.Path
) -> None:
    """Write ``venv_python`` (absolute string) to top-level of scratchpad JSON.

    Uses ``_scratchpad.atomic_write`` — safe under interrupt.
    """
    # Import here so managed_venv has no circular dependency at module level.
    from bin import _scratchpad as sp  # noqa: PLC0415

    data = sp.load(scratchpad_path)
    data["venv_python"] = str(venv_python.absolute())
    sp.atomic_write(scratchpad_path, data)


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

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
            print(exc, file=sys.stderr)
            sys.exit(1)
        print(f"VENV_PYTHON: {venv_py}")

    elif args.cmd == "pip-install-editable":
        try:
            pip_install_editable(
                pathlib.Path(args.project_path),
                pathlib.Path(args.target) if args.target else None,
            )
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            sys.exit(1)
        print("PIP_INSTALL_EDITABLE: ok")

    elif args.cmd == "normalize":
        result = normalize_action(args.action, pathlib.Path(args.venv_python))
        print(result)
