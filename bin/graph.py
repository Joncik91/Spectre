"""Graph data model + manifest serializer/parser. Stdlib only.

The graph lives at specs/.graph.md as a single markdown file.
Each node is a YAML frontmatter block separated by `---` lines.
"""
from dataclasses import dataclass, field

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
        edges.append(current_edge)
    n = Node(
        id=str(fields["id"]),
        type=str(fields["type"]),
        title=str(fields["title"]),
        status=str(fields.get("status", "active")),
    )
    n.edges = edges
    return n


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
