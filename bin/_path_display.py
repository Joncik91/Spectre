"""bin/_path_display.py — path normalization for user-visible output.

Public API:
    relative_to_project(p, project_root) -> str
    display(p, *, project_root=None) -> str

Rules:
    1. Strip ${CLAUDE_PLUGIN_ROOT} prefix (plugin internals must never appear).
    2. Resolve to project-relative path if p is under cwd / project_root.
    3. Replace $HOME / user home dir with ~.
    4. Never emit an absolute path in user-visible output.
"""
from __future__ import annotations

import os
import pathlib
import re


_PLUGIN_ROOT_ENV_RE = re.compile(r"^\$\{CLAUDE_PLUGIN_ROOT\}/?")
_HOME = pathlib.Path.home()


def _strip_plugin_root(p: str) -> str:
    """Remove leading ${CLAUDE_PLUGIN_ROOT}/ if present."""
    p = _PLUGIN_ROOT_ENV_RE.sub("", p)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root and p.startswith(plugin_root):
        p = p[len(plugin_root):].lstrip("/")
    return p


def relative_to_project(p: str | pathlib.Path, project_root: str | pathlib.Path) -> str:
    """Return p relative to project_root if it is a sub-path; otherwise return display(p).

    Parameters
    ----------
    p:
        The path to normalise.
    project_root:
        The root against which to compute a relative path.
    """
    p_str = str(p)
    p_str = _strip_plugin_root(p_str)

    try:
        resolved = pathlib.Path(p_str).resolve()
        root_resolved = pathlib.Path(project_root).resolve()
        rel = resolved.relative_to(root_resolved)
        return str(rel)
    except (ValueError, OSError):
        pass

    # Fall back to display() for home-relative or relative-already paths
    return display(p_str)


def display(p: str | pathlib.Path, *, project_root: str | pathlib.Path | None = None) -> str:
    """Normalise p for user-visible output.

    Order of operations:
    1. Strip ${CLAUDE_PLUGIN_ROOT}.
    2. If project_root given, try relative_to_project first.
    3. Resolve to cwd-relative if under cwd.
    4. Replace home dir prefix with ~.
    5. If still absolute and not under home, return as-is (best-effort).
    """
    p_str = _strip_plugin_root(str(p))

    if project_root is not None:
        try:
            resolved = pathlib.Path(p_str).resolve()
            root_resolved = pathlib.Path(project_root).resolve()
            rel = resolved.relative_to(root_resolved)
            return str(rel)
        except (ValueError, OSError):
            pass

    # Try cwd-relative
    try:
        cwd = pathlib.Path.cwd()
        resolved = pathlib.Path(p_str).resolve()
        rel = resolved.relative_to(cwd)
        return str(rel)
    except (ValueError, OSError):
        pass

    # Replace home with ~
    try:
        resolved = pathlib.Path(p_str).resolve()
        rel = resolved.relative_to(_HOME)
        return f"~/{rel}"
    except (ValueError, OSError):
        pass

    # Last resort: return as-is (could be already relative or non-existent path)
    return p_str
