"""Distribute leg — reusable template artifacts. Stdlib only.

~/.spectre/templates/{specs,skills}/ holds reusable spec drafts and skill
markdown files that can be imported into a new project. Local-only in
v0.4.2 — no remote sync (deferred to v0.5+).

Design: docs/superpowers/specs/2026-05-06-spectre-v0.4-cdlc-closure.md §6.6.

Public API:
    TEMPLATES_VERSION
    templates_dir_default() -> pathlib.Path
    list_templates() -> list[dict]
    import_template(*, source_name, target_name, kind=None) -> None
    export_template(*, source_path, target_name, kind=None) -> None
"""
from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

TEMPLATES_VERSION = "0.4.2"


def templates_dir_default() -> pathlib.Path:
    return pathlib.Path.home() / ".spectre" / "templates"


def list_templates() -> list[dict]:
    """Return list of template descriptors: [{name, kind, path}, ...].

    kind is "spec" (under specs/) or "skill" (under skills/). Empty list
    if the templates dir doesn't exist.
    """
    base = templates_dir_default()
    if not base.is_dir():
        return []
    out: list[dict] = []
    for kind, subdir in (("spec", "specs"), ("skill", "skills")):
        sub = base / subdir
        if not sub.is_dir():
            continue
        for entry in sorted(sub.iterdir()):
            if entry.is_file() and entry.suffix == ".md":
                # name is the stem with .spec stripped if present
                name = entry.stem
                if name.endswith(".spec"):
                    name = name[:-len(".spec")]
                out.append({"name": name, "kind": kind, "path": str(entry)})
    return out
