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
