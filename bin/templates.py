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


def _resolve_source(source_name: str, kind: str | None) -> tuple[pathlib.Path, str]:
    """Locate a template by name, optionally constrained by kind.
    Returns (path, kind). Raises FileNotFoundError if not found."""
    base = templates_dir_default()
    candidates: list[tuple[pathlib.Path, str]] = []
    if kind in (None, "spec"):
        spec_path = base / "specs" / f"{source_name}.spec.md"
        if spec_path.is_file():
            candidates.append((spec_path, "spec"))
    if kind in (None, "skill"):
        skill_path = base / "skills" / f"{source_name}.md"
        if skill_path.is_file():
            candidates.append((skill_path, "skill"))
    if not candidates:
        raise FileNotFoundError(f"template not found: {source_name!r}")
    # If kind not specified and both exist, prefer spec (specs are the v0.4.2 default).
    return candidates[0]


def import_template(
    *,
    source_name: str,
    target_name: str,
    kind: str | None = None,
) -> None:
    """Copy a template from ~/.spectre/templates/ into the active project.

    Specs land at ./specs/<target_name>.spec.md.draft (the .draft suffix
    means /vision Step 6 confirmation drives the lock — keeps the
    interrogation flow consistent).

    Skills land at ./skills/<target_name>.md.
    """
    source_path, resolved_kind = _resolve_source(source_name, kind)
    body = source_path.read_text(encoding="utf-8")
    cwd = pathlib.Path.cwd()
    if resolved_kind == "spec":
        target_dir = cwd / "specs"
        target = target_dir / f"{target_name}.spec.md.draft"
    else:
        target_dir = cwd / "skills"
        target = target_dir / f"{target_name}.md"
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def export_template(
    *,
    source_path: pathlib.Path,
    target_name: str,
    kind: str | None = None,
) -> None:
    """Copy a project file into ~/.spectre/templates/ for reuse.

    kind defaults to "spec" if source_path ends in .spec.md, "skill"
    otherwise. Target is mode 0600.
    """
    source_path = pathlib.Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"source spec not found: {source_path}")
    if kind is None:
        kind = "spec" if source_path.name.endswith(".spec.md") else "skill"
    base = templates_dir_default()
    if kind == "spec":
        target_dir = base / "specs"
        target = target_dir / f"{target_name}.spec.md"
    else:
        target_dir = base / "skills"
        target = target_dir / f"{target_name}.md"
    target_dir.mkdir(parents=True, exist_ok=True)
    body = source_path.read_text(encoding="utf-8")
    fd, tmp = tempfile.mkstemp(
        dir=str(target_dir), prefix=target.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── CLI entrypoint ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="templates",
        description="Templates CLI — list spec/skill templates under ~/.spectre/templates/.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser(
        "list",
        help=(
            "List available templates under ~/.spectre/templates/. Default "
            "output: `TEMPLATES_AVAILABLE: N` followed by up to --limit "
            "`  <kind>: <name>` lines."
        ),
    )
    p_list.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max entries to print after the header (default: 10).",
    )
    p_list.add_argument(
        "--json",
        action="store_true",
        help="Emit the full descriptors as JSON (ignores --limit).",
    )

    args = parser.parse_args()

    if args.cmd == "list":
        try:
            ts = list_templates()
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "templates.list", dest="stderr", reason=str(exc))
            sys.exit(1)
        if args.json:
            print(json.dumps(ts, indent=2))
        else:
            items = ",".join(f"{t['kind']}:{t['name']}" for t in ts[: max(0, args.limit)])
            _status.emit("result", "templates.list",
                         count=len(ts),
                         items=items or "none")
