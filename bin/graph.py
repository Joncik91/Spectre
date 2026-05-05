"""Graph data model + manifest serializer/parser. Stdlib only.

The graph lives at specs/.graph.md as a single markdown file.
Each node is a YAML frontmatter block separated by `---` lines.
"""
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

NODE_TYPES = ("invariant", "interface", "implementation", "resource")
EDGE_TYPES = ("constrains", "satisfies", "blocks", "invalidates", "supersedes")
STATUSES = ("active", "stale", "superseded")


@dataclass
class Node:
    id: str
    type: str
    title: str
    status: str = "active"
    edges: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.type not in NODE_TYPES:
            raise ValueError(f"unknown node type: {self.type!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status: {self.status!r}")

    def add_edge(self, *, target: str, edge_type: str) -> None:
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type: {edge_type!r}")
        self.edges.append({"target": target, "type": edge_type})


def parse_manifest(text: str) -> list[Node]:
    """Parse a graph manifest markdown into a list of Node objects.

    Format: zero or more frontmatter blocks separated by `---` lines.
    Anything outside frontmatter blocks (e.g. a leading `# Header`) is ignored.
    """
    nodes: list[Node] = []
    in_block = False
    block_lines: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            if in_block:
                nodes.append(_parse_block(block_lines))
                block_lines = []
                in_block = False
            else:
                in_block = True
        elif in_block:
            block_lines.append(line)
    return nodes


def _parse_block(lines: list[str]) -> Node:
    fields: dict[str, object] = {}
    edges: list[dict] = []
    in_edges = False
    current_edge: dict[str, str] = {}
    for line in lines:
        if line.startswith("edges:"):
            rest = line[len("edges:"):].strip()
            if rest == "[]":
                in_edges = False
            else:
                in_edges = True
            continue
        if in_edges:
            stripped = line.lstrip()
            if stripped.startswith("- target:"):
                if current_edge:
                    if "type" not in current_edge:
                        raise ValueError(
                            f"manifest block has edge with target but no type: {current_edge!r}"
                        )
                    edges.append(current_edge)
                current_edge = {"target": stripped[len("- target:"):].strip()}
            elif stripped.startswith("type:"):
                current_edge["type"] = stripped[len("type:"):].strip()
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    if current_edge:
        if "type" not in current_edge:
            raise ValueError(
                f"manifest block has edge with target but no type: {current_edge!r}"
            )
        edges.append(current_edge)
    for required in ("id", "type", "title"):
        if required not in fields:
            raise ValueError(
                f"manifest block missing required field {required!r}: {fields!r}"
            )
    n = Node(
        id=str(fields["id"]),
        type=str(fields["type"]),
        title=str(fields["title"]),
        status=str(fields.get("status", "active")),
    )
    n.edges = edges
    return n


MANIFEST_HEADER = "# Spectre Graph Manifest\n\n"


def load_graph(path: Path) -> list[Node]:
    path = Path(path)
    if not path.exists():
        return []
    return parse_manifest(path.read_text(encoding="utf-8"))


def save_graph(path: Path, nodes: list[Node]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = MANIFEST_HEADER + "".join(serialize_node(n) for n in nodes)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def serialize_node(n: Node) -> str:
    lines = ["---"]
    lines.append(f"id: {n.id}")
    lines.append(f"type: {n.type}")
    lines.append(f"title: {n.title}")
    lines.append(f"status: {n.status}")
    if not n.edges:
        lines.append("edges: []")
    else:
        lines.append("edges:")
        for e in n.edges:
            lines.append(f"  - target: {e['target']}")
            lines.append(f"    type: {e['type']}")
    lines.append("---")
    return "\n".join(lines) + "\n"
