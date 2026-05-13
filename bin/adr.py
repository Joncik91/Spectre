"""ADR file writer + graph supersedes-edge updater. Stdlib only.

ADRs live at decisions/<NNNN>-<slug>.md with frontmatter:
  id, title, date, status (accepted | superseded), supersedes (null or NNNN).

Atomic writes via tempfile.mkstemp + os.replace.
"""
import json
import os
import re
import tempfile
from pathlib import Path

from bin import graph

_ADR_FILENAME_RE = re.compile(r"^(\d{4})-[\w-]+\.md$")


def _yaml_string(s: str) -> str:
    """Return a YAML-safe JSON-encoded string scalar.

    Raises ValueError for strings containing newline or carriage-return
    characters, which cannot be safely represented as a single-line YAML scalar.
    """
    if "\n" in s or "\r" in s:
        raise ValueError(f"Title must not contain newline characters: {s!r}")
    return json.dumps(s, ensure_ascii=False)


def slugify(title: str) -> str:
    """Lowercase, replace non-alphanumerics with `-`, collapse repeats, strip ends."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def next_id(decisions_dir: Path) -> str:
    """Return the next 4-digit ADR id."""
    decisions_dir = Path(decisions_dir)
    max_id = 0
    if decisions_dir.exists():
        for entry in decisions_dir.iterdir():
            if not entry.is_file():
                continue
            m = _ADR_FILENAME_RE.match(entry.name)
            if not m:
                continue
            n = int(m.group(1))
            if n > max_id:
                max_id = n
    return f"{max_id + 1:04d}"


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _mark_superseded(decisions_dir: Path, old_id: str) -> None:
    """Flip the old ADR's status: from accepted to superseded."""
    for entry in Path(decisions_dir).iterdir():
        m = _ADR_FILENAME_RE.match(entry.name)
        if not m or m.group(1) != old_id:
            continue
        text = entry.read_text(encoding="utf-8")
        new_text = re.sub(
            r"^status:\s*accepted\s*$",
            "status: superseded",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        _atomic_write_text(entry, new_text)
        return


def write_adr(
    decisions_dir: Path,
    *,
    title: str,
    date: str,
    body: str,
    supersedes: str | None = None,
) -> Path:
    """Write an ADR file. Return the new path.

    If supersedes is set, also flips the old ADR's status to "superseded".
    """
    decisions_dir = Path(decisions_dir)
    decisions_dir.mkdir(parents=True, exist_ok=True)
    new_id = next_id(decisions_dir)
    slug = slugify(title)
    filename = f"{new_id}-{slug}.md"
    path = decisions_dir / filename
    supersedes_value = supersedes if supersedes is not None else "null"
    text = (
        "---\n"
        f"id: {new_id}\n"
        f"title: {_yaml_string(title)}\n"
        f"date: {date}\n"
        "status: accepted\n"
        f"supersedes: {supersedes_value}\n"
        "---\n"
        f"\n{body}\n"
    )
    _atomic_write_text(path, text)
    if supersedes is not None:
        _mark_superseded(decisions_dir, supersedes)
    return path


def update_graph_for_supersedes(
    graph_path: Path,
    *,
    new_adr_id: str,
    old_adr_id: str,
) -> None:
    """Append a supersedes edge from new ADR node to old ADR node and mark old as superseded.

    No-op if the graph manifest does not exist OR either node id is absent.
    """
    graph_path = Path(graph_path)
    if not graph_path.exists():
        return
    nodes = graph.load_graph(graph_path)
    new_node = graph.get_node(nodes, new_adr_id)
    old_node = graph.get_node(nodes, old_adr_id)
    if new_node is None or old_node is None:
        return
    edge = {"target": old_adr_id, "type": "supersedes"}
    if edge not in new_node.edges:
        new_node.add_edge(target=old_adr_id, edge_type="supersedes")
    old_node.status = "superseded"
    graph.save_graph(graph_path, nodes)


# ── CLI entrypoint ────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse
    import sys
    from datetime import date as _date
    from bin import _status

    parser = argparse.ArgumentParser(
        prog="adr",
        description="ADR CLI — write a new ADR, update graph supersedes edges.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_w = sub.add_parser(
        "write",
        help=(
            "Write a new ADR file at <decisions-dir>/<NNNN>-<slug>.md. Prints "
            "`ADR: <path>` on success. If --supersedes is given, the named ADR "
            "id has its status flipped to 'superseded'."
        ),
    )
    p_w.add_argument(
        "--dir",
        default="decisions",
        help="Decisions directory (default: 'decisions').",
    )
    p_w.add_argument("--title", required=True, help="ADR title (one line).")
    p_w.add_argument(
        "--date",
        default=None,
        help="ISO date (default: today).",
    )
    p_w.add_argument("--body", required=True, help="ADR body (one paragraph).")
    p_w.add_argument(
        "--supersedes",
        default=None,
        help='Existing ADR id to mark superseded (e.g. "0007"). Omit for none.',
    )

    p_g = sub.add_parser(
        "update-graph",
        help=(
            "Append a supersedes edge from --new ADR to --old ADR in the "
            "graph manifest, and mark old as superseded. No-op if either node "
            "is missing or the manifest does not exist."
        ),
    )
    p_g.add_argument(
        "--graph",
        default="specs/.graph.md",
        help="Path to graph manifest (default: specs/.graph.md).",
    )
    p_g.add_argument("--new", dest="new_id", required=True, help="New ADR node id.")
    p_g.add_argument("--old", dest="old_id", required=True, help="Old ADR node id.")

    args = parser.parse_args()

    if args.cmd == "write":
        date_str = args.date or _date.today().isoformat()
        try:
            path = write_adr(
                Path(args.dir),
                title=args.title,
                date=date_str,
                body=args.body,
                supersedes=args.supersedes,
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "adr.write", dest="stderr", reason=str(exc))
            sys.exit(1)
        from bin import _path_display
        _status.emit("ok", "adr.write", path=_path_display.display(path))

    elif args.cmd == "update-graph":
        try:
            update_graph_for_supersedes(
                Path(args.graph),
                new_adr_id=args.new_id,
                old_adr_id=args.old_id,
            )
        except Exception as exc:  # noqa: BLE001
            _status.emit("error", "adr.graph_update", dest="stderr", reason=str(exc))
            sys.exit(1)
        _status.emit("ok", "adr.graph_updated", new=args.new_id, old=args.old_id)
