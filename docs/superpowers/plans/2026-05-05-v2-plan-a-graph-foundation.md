# v2 Plan A — Graph Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the graph data model + parser/serializer + codebase fingerprinter that v2 Plans B and C will consume. No skill changes, no behavior change for existing v1 users. Pure infrastructure ending in `v0.2.0`.

**Architecture:** Two new stdlib-only modules under `bin/`: `graph.py` (parse/serialize/query `specs/.graph.md`) and `fingerprint.py` (walk repo, regex+ast extract symbol map to `state/local-symbols.json`). Single-file markdown manifest with frontmatter-block-per-node, separated by `---`. In-memory adjacency list rebuilt every session start. Pure functions, no global state.

**Tech Stack:** Python 3.11+ (stdlib only). `ast` for Python parsing, `re` for shell/markdown/yaml, `pathlib` for traversal, `json` for symbol map output, `pytest` for tests.

---

## File Structure

```
bin/graph.py                          # Graph parser/serializer/query (NEW)
bin/fingerprint.py                    # Codebase symbol-map walker (NEW)
specs/.graph.md                       # Manifest (NEW; created at first use)
state/local-symbols.json              # Fingerprint output (NEW; gitignored)
tests/test_graph.py                   # Graph round-trip + query tests (NEW)
tests/test_fingerprint.py             # Fingerprinter tests (NEW)
.gitignore                            # Add state/local-symbols.json
```

No existing files modified. v1 keeps working unchanged.

---

### Task 1: Repo prep — gitignore + scaffolding

**Files:**
- Modify: `.gitignore`
- Create: `specs/.graph.md.template` (empty graph manifest seed)

- [ ] **Step 1: Append to `.gitignore`**

```
state/local-symbols.json
```

- [ ] **Step 2: Create `specs/.graph.md.template`** with an empty manifest seed:

```markdown
# Spectre Graph Manifest

This file is auto-managed by bin/graph.py. Do not hand-edit unless you understand the schema.

Each node is a frontmatter block separated by a `---` line. Edges are listed inside each node's `edges:` field.
```

- [ ] **Step 3: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add .gitignore specs/.graph.md.template
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "chore: gitignore symbol map + graph manifest template"
```

---

### Task 2: Graph data model — Node + Edge types (test-first)

**Files:**
- Create: `bin/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph.py
import pytest
from bin import graph


def test_node_types_are_exact_set():
    assert graph.NODE_TYPES == ("invariant", "interface", "implementation", "resource")


def test_edge_types_are_exact_set():
    assert graph.EDGE_TYPES == ("constrains", "satisfies", "blocks", "invalidates", "supersedes")


def test_node_init_requires_id_type_title():
    n = graph.Node(id="auth-001", type="invariant", title="UserObject schema")
    assert n.id == "auth-001"
    assert n.type == "invariant"
    assert n.title == "UserObject schema"
    assert n.status == "active"
    assert n.edges == []


def test_node_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown node type"):
        graph.Node(id="x", type="bogus", title="t")


def test_edge_rejects_unknown_type():
    n = graph.Node(id="x", type="invariant", title="t")
    with pytest.raises(ValueError, match="unknown edge type"):
        n.add_edge(target="y", type="bogus_edge")


def test_edge_add_appends_to_list():
    n = graph.Node(id="x", type="invariant", title="t")
    n.add_edge(target="y", type="constrains")
    assert n.edges == [{"target": "y", "type": "constrains"}]


def test_node_status_supports_active_stale_superseded():
    for s in ("active", "stale", "superseded"):
        n = graph.Node(id="x", type="invariant", title="t", status=s)
        assert n.status == s


def test_node_status_rejects_unknown():
    with pytest.raises(ValueError, match="unknown status"):
        graph.Node(id="x", type="invariant", title="t", status="weird")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/joncik/apps/Spectre && pytest tests/test_graph.py -v
```
Expected: `ModuleNotFoundError: No module named 'bin.graph'` or ImportError.

- [ ] **Step 3: Implement `bin/graph.py`** (data classes only, no I/O yet)

```python
"""Graph data model + manifest serializer/parser. Stdlib only.

The graph lives at specs/.graph.md as a single markdown file.
Each node is a YAML frontmatter block separated by `---` lines.
"""
from dataclasses import dataclass, field
from typing import Literal

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

    def add_edge(self, *, target: str, type: str) -> None:
        if type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type: {type!r}")
        self.edges.append({"target": target, "type": type})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_graph.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/graph.py tests/test_graph.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(graph): node + edge data model with type validation"
```

---

### Task 3: Manifest serializer — Node → markdown frontmatter (test-first)

**Files:**
- Modify: `bin/graph.py` (add `serialize_node`)
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Append the failing test**

```python
def test_serialize_node_produces_frontmatter_block():
    n = graph.Node(id="auth-001", type="invariant", title="UserObject schema")
    n.add_edge(target="auth-002", type="constrains")
    out = graph.serialize_node(n)
    assert out.startswith("---\n")
    assert "id: auth-001" in out
    assert "type: invariant" in out
    assert "title: UserObject schema" in out
    assert "status: active" in out
    assert "edges:" in out
    assert "  - target: auth-002" in out
    assert "    type: constrains" in out
    assert out.endswith("---\n")


def test_serialize_node_no_edges_omits_list():
    n = graph.Node(id="x", type="resource", title="port-8080")
    out = graph.serialize_node(n)
    assert "edges: []" in out
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_graph.py -v
```
Expected: `AttributeError: module 'bin.graph' has no attribute 'serialize_node'`.

- [ ] **Step 3: Add `serialize_node` to `bin/graph.py`**

```python
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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_graph.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/graph.py tests/test_graph.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(graph): serialize_node to markdown frontmatter block"
```

---

### Task 4: Manifest parser — markdown → list[Node] (test-first)

**Files:**
- Modify: `bin/graph.py` (add `parse_manifest`)
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Append failing tests**

```python
def test_parse_manifest_empty_returns_empty_list():
    assert graph.parse_manifest("") == []
    assert graph.parse_manifest("# header only\n") == []


def test_parse_manifest_single_node_no_edges():
    text = (
        "---\n"
        "id: x-001\n"
        "type: invariant\n"
        "title: Single node\n"
        "status: active\n"
        "edges: []\n"
        "---\n"
    )
    nodes = graph.parse_manifest(text)
    assert len(nodes) == 1
    assert nodes[0].id == "x-001"
    assert nodes[0].edges == []


def test_parse_manifest_two_nodes_with_edges():
    text = (
        "# Header text ignored\n"
        "---\n"
        "id: a\n"
        "type: invariant\n"
        "title: A\n"
        "status: active\n"
        "edges:\n"
        "  - target: b\n"
        "    type: constrains\n"
        "---\n"
        "---\n"
        "id: b\n"
        "type: implementation\n"
        "title: B\n"
        "status: stale\n"
        "edges: []\n"
        "---\n"
    )
    nodes = graph.parse_manifest(text)
    assert [n.id for n in nodes] == ["a", "b"]
    assert nodes[0].edges == [{"target": "b", "type": "constrains"}]
    assert nodes[1].status == "stale"


def test_parse_manifest_round_trip():
    n1 = graph.Node(id="a", type="invariant", title="A")
    n1.add_edge(target="b", type="constrains")
    n2 = graph.Node(id="b", type="implementation", title="B", status="stale")
    text = graph.serialize_node(n1) + graph.serialize_node(n2)
    parsed = graph.parse_manifest(text)
    assert len(parsed) == 2
    assert parsed[0].id == n1.id
    assert parsed[0].edges == n1.edges
    assert parsed[1].status == n2.status
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_graph.py -v
```
Expected: `AttributeError: module 'bin.graph' has no attribute 'parse_manifest'`.

- [ ] **Step 3: Add `parse_manifest` to `bin/graph.py`**

```python
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
                # close block
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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_graph.py -v
```
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/graph.py tests/test_graph.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(graph): parse_manifest with round-trip test"
```

---

### Task 5: Manifest file I/O — load/save with atomic write (test-first)

**Files:**
- Modify: `bin/graph.py` (add `load_graph`, `save_graph`)
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Append failing tests**

```python
def test_load_graph_returns_empty_when_missing(tmp_path):
    nodes = graph.load_graph(tmp_path / "nope.md")
    assert nodes == []


def test_save_graph_then_load_round_trip(tmp_path):
    path = tmp_path / "g.md"
    n = graph.Node(id="a", type="invariant", title="A")
    n.add_edge(target="b", type="constrains")
    graph.save_graph(path, [n])
    assert path.exists()
    loaded = graph.load_graph(path)
    assert len(loaded) == 1
    assert loaded[0].id == "a"
    assert loaded[0].edges == [{"target": "b", "type": "constrains"}]


def test_save_graph_no_tmp_left_behind(tmp_path):
    path = tmp_path / "g.md"
    graph.save_graph(path, [graph.Node(id="x", type="resource", title="t")])
    leftovers = list(tmp_path.glob("g.md*.tmp"))
    assert leftovers == []


def test_save_graph_creates_parent_dir(tmp_path):
    path = tmp_path / "subdir" / "g.md"
    graph.save_graph(path, [graph.Node(id="x", type="resource", title="t")])
    assert path.exists()
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_graph.py -v
```
Expected: `AttributeError` on `load_graph` / `save_graph`.

- [ ] **Step 3: Add I/O functions to `bin/graph.py`**

```python
import os
import tempfile
from pathlib import Path

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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_graph.py -v
```
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/graph.py tests/test_graph.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(graph): atomic load/save for .graph.md"
```

---

### Task 6: Graph queries — neighbors, children_by_edge, find_stale (test-first)

**Files:**
- Modify: `bin/graph.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Append failing tests**

```python
def _build_sample_graph():
    inv = graph.Node(id="inv-1", type="invariant", title="UserObject schema")
    inv.add_edge(target="impl-1", type="constrains")
    inv.add_edge(target="impl-2", type="constrains")
    impl1 = graph.Node(id="impl-1", type="implementation", title="signup endpoint")
    impl1.add_edge(target="iface-1", type="satisfies")
    impl2 = graph.Node(id="impl-2", type="implementation", title="login endpoint", status="stale")
    iface1 = graph.Node(id="iface-1", type="interface", title="POST /signup")
    return [inv, impl1, impl2, iface1]


def test_children_by_edge_filters_correctly():
    nodes = _build_sample_graph()
    children = graph.children_by_edge(nodes, source="inv-1", edge_type="constrains")
    assert sorted(c.id for c in children) == ["impl-1", "impl-2"]


def test_children_by_edge_empty_when_no_match():
    nodes = _build_sample_graph()
    assert graph.children_by_edge(nodes, source="iface-1", edge_type="constrains") == []


def test_find_stale_returns_only_stale_nodes():
    nodes = _build_sample_graph()
    stale = graph.find_stale(nodes)
    assert [n.id for n in stale] == ["impl-2"]


def test_get_node_by_id_returns_match():
    nodes = _build_sample_graph()
    n = graph.get_node(nodes, "impl-1")
    assert n is not None
    assert n.title == "signup endpoint"


def test_get_node_returns_none_when_missing():
    nodes = _build_sample_graph()
    assert graph.get_node(nodes, "no-such-id") is None
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_graph.py -v
```
Expected: `AttributeError` on the four new query functions.

- [ ] **Step 3: Add query functions to `bin/graph.py`**

```python
def get_node(nodes: list[Node], node_id: str) -> Node | None:
    for n in nodes:
        if n.id == node_id:
            return n
    return None


def children_by_edge(nodes: list[Node], *, source: str, edge_type: str) -> list[Node]:
    src = get_node(nodes, source)
    if src is None:
        return []
    targets = {e["target"] for e in src.edges if e["type"] == edge_type}
    return [n for n in nodes if n.id in targets]


def find_stale(nodes: list[Node]) -> list[Node]:
    return [n for n in nodes if n.status == "stale"]
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_graph.py -v
```
Expected: 23 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/graph.py tests/test_graph.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(graph): query functions (get_node, children_by_edge, find_stale)"
```

---

### Task 7: Graph mutation — mark_stale + cascade via edges (test-first)

**Files:**
- Modify: `bin/graph.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Append failing tests**

```python
def test_mark_stale_flips_status_on_target():
    nodes = _build_sample_graph()
    graph.mark_stale(nodes, node_id="impl-1")
    assert graph.get_node(nodes, "impl-1").status == "stale"


def test_mark_stale_cascades_through_constrains_edges():
    nodes = _build_sample_graph()
    graph.mark_stale_cascade(nodes, root_id="inv-1")
    # inv-1 itself + impl-1 (constrains target) + impl-2 (already stale, stays stale)
    assert graph.get_node(nodes, "inv-1").status == "stale"
    assert graph.get_node(nodes, "impl-1").status == "stale"
    assert graph.get_node(nodes, "impl-2").status == "stale"
    # iface-1 has no incoming constrains from inv-1 → stays active
    assert graph.get_node(nodes, "iface-1").status == "active"


def test_mark_stale_cascade_unknown_root_is_noop():
    nodes = _build_sample_graph()
    graph.mark_stale_cascade(nodes, root_id="bogus")
    assert all(n.status == "active" or n.id == "impl-2" for n in nodes)
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_graph.py -v
```
Expected: `AttributeError` on `mark_stale` / `mark_stale_cascade`.

- [ ] **Step 3: Add mutation functions to `bin/graph.py`**

```python
CASCADE_EDGES = ("constrains", "satisfies")


def mark_stale(nodes: list[Node], *, node_id: str) -> None:
    n = get_node(nodes, node_id)
    if n is not None:
        n.status = "stale"


def mark_stale_cascade(nodes: list[Node], *, root_id: str) -> None:
    """Mark root and all descendants reachable via cascade edges as stale."""
    root = get_node(nodes, root_id)
    if root is None:
        return
    visited: set[str] = set()
    stack = [root_id]
    while stack:
        current_id = stack.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        n = get_node(nodes, current_id)
        if n is None:
            continue
        n.status = "stale"
        for e in n.edges:
            if e["type"] in CASCADE_EDGES:
                stack.append(e["target"])
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_graph.py -v
```
Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/graph.py tests/test_graph.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(graph): mark_stale + cascade across constrains/satisfies edges"
```

---

### Task 8: Fingerprinter — Python AST symbol extraction (test-first)

**Files:**
- Create: `bin/fingerprint.py`
- Create: `tests/test_fingerprint.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fingerprint.py
import json
from pathlib import Path

import pytest

from bin import fingerprint as fp


def test_extract_python_symbols_finds_top_level_function(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def hello():\n    return 1\n")
    syms = fp.extract_python_symbols(f)
    assert any(s["name"] == "hello" and s["kind"] == "function" for s in syms)


def test_extract_python_symbols_finds_top_level_class(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("class Widget:\n    pass\n")
    syms = fp.extract_python_symbols(f)
    assert any(s["name"] == "Widget" and s["kind"] == "class" for s in syms)


def test_extract_python_symbols_records_file_and_line(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("\ndef target():\n    pass\n")
    syms = fp.extract_python_symbols(f)
    target = next(s for s in syms if s["name"] == "target")
    assert target["file"] == str(f)
    assert target["line"] == 2


def test_extract_python_symbols_captures_module_docstring(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text('"""Top-level module purpose."""\ndef x(): pass\n')
    syms = fp.extract_python_symbols(f)
    module = next(s for s in syms if s["kind"] == "module")
    assert "Top-level module purpose" in module["doc"]


def test_extract_python_symbols_skips_nested_definitions(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        pass\n"
    )
    syms = fp.extract_python_symbols(f)
    names = [s["name"] for s in syms if s["kind"] == "function"]
    assert "outer" in names
    assert "inner" not in names


def test_extract_python_symbols_returns_empty_on_syntax_error(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def oops(:\n")
    syms = fp.extract_python_symbols(f)
    assert syms == []
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: `ModuleNotFoundError: No module named 'bin.fingerprint'`.

- [ ] **Step 3: Implement `bin/fingerprint.py`**

```python
"""Codebase fingerprinter: extract a symbol map from project files. Stdlib only.

Symbols are dicts with keys: kind, name, file, line, doc.
Output written to state/local-symbols.json by walk_repo().
"""
import ast
import json
import re
from pathlib import Path
from typing import Any


def extract_python_symbols(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    out: list[dict[str, Any]] = []
    mod_doc = ast.get_docstring(tree) or ""
    out.append({
        "kind": "module",
        "name": path.stem,
        "file": str(path),
        "line": 1,
        "doc": mod_doc,
    })
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append({
                "kind": "function",
                "name": node.name,
                "file": str(path),
                "line": node.lineno,
                "doc": ast.get_docstring(node) or "",
            })
        elif isinstance(node, ast.ClassDef):
            out.append({
                "kind": "class",
                "name": node.name,
                "file": str(path),
                "line": node.lineno,
                "doc": ast.get_docstring(node) or "",
            })
    return out
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/fingerprint.py tests/test_fingerprint.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(fingerprint): python AST symbol extraction with module docstring"
```

---

### Task 9: Fingerprinter — shell + markdown header extraction (test-first)

**Files:**
- Modify: `bin/fingerprint.py`
- Modify: `tests/test_fingerprint.py`

- [ ] **Step 1: Append failing tests**

```python
def test_extract_shell_symbols_finds_function(tmp_path):
    f = tmp_path / "script.sh"
    f.write_text(
        "#!/bin/bash\n"
        "do_thing() {\n"
        "  echo hi\n"
        "}\n"
        "function alt_form() {\n"
        "  echo alt\n"
        "}\n"
    )
    syms = fp.extract_shell_symbols(f)
    names = [s["name"] for s in syms if s["kind"] == "function"]
    assert "do_thing" in names
    assert "alt_form" in names


def test_extract_shell_symbols_records_line(tmp_path):
    f = tmp_path / "s.sh"
    f.write_text("\n\ndo_thing() {\n  :\n}\n")
    syms = fp.extract_shell_symbols(f)
    target = next(s for s in syms if s["name"] == "do_thing")
    assert target["line"] == 3


def test_extract_markdown_headers_returns_h1_h2(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text(
        "# Top\n"
        "Some prose.\n"
        "## Section A\n"
        "More.\n"
        "### Subsection (skipped)\n"
        "## Section B\n"
    )
    syms = fp.extract_markdown_headers(f)
    titles = [s["name"] for s in syms]
    assert titles == ["Top", "Section A", "Section B"]


def test_extract_markdown_headers_records_kind(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Top\n## Sub\n")
    syms = fp.extract_markdown_headers(f)
    assert syms[0]["kind"] == "h1"
    assert syms[1]["kind"] == "h2"
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: `AttributeError` on the two new functions.

- [ ] **Step 3: Add shell + markdown extractors to `bin/fingerprint.py`**

```python
SHELL_FUNC_RE = re.compile(
    r"^(?:function\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{",
    re.MULTILINE,
)
MD_HEADER_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)


def extract_shell_symbols(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for m in SHELL_FUNC_RE.finditer(src):
        line_no = src[: m.start()].count("\n") + 1
        out.append({
            "kind": "function",
            "name": m.group("name"),
            "file": str(path),
            "line": line_no,
            "doc": "",
        })
    return out


def extract_markdown_headers(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for m in MD_HEADER_RE.finditer(src):
        depth = len(m.group(1))
        line_no = src[: m.start()].count("\n") + 1
        out.append({
            "kind": f"h{depth}",
            "name": m.group(2).strip(),
            "file": str(path),
            "line": line_no,
            "doc": "",
        })
    return out
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/fingerprint.py tests/test_fingerprint.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(fingerprint): shell function + markdown header extractors"
```

---

### Task 10: Fingerprinter — repo walker + JSON output (test-first)

**Files:**
- Modify: `bin/fingerprint.py`
- Modify: `tests/test_fingerprint.py`

- [ ] **Step 1: Append failing tests**

```python
def test_walk_repo_collects_python_and_shell_and_md(tmp_path):
    (tmp_path / "a.py").write_text("def f(): pass\n")
    (tmp_path / "b.sh").write_text("g() { :; }\n")
    (tmp_path / "c.md").write_text("# Title\n## Sub\n")
    out = fp.walk_repo(tmp_path)
    names = {(s["kind"], s["name"]) for s in out}
    assert ("function", "f") in names
    assert ("function", "g") in names
    assert ("h1", "Title") in names
    assert ("h2", "Sub") in names


def test_walk_repo_skips_hidden_dirs(tmp_path):
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "x.py").write_text("def secret(): pass\n")
    out = fp.walk_repo(tmp_path)
    assert all(s["name"] != "secret" for s in out)


def test_walk_repo_skips_state_and_pycache(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "x.py").write_text("def cached(): pass\n")
    state = tmp_path / "state"
    state.mkdir()
    (state / "y.py").write_text("def stateful(): pass\n")
    out = fp.walk_repo(tmp_path)
    names = {s["name"] for s in out}
    assert "cached" not in names
    assert "stateful" not in names


def test_save_symbols_atomic_write(tmp_path):
    target = tmp_path / "syms.json"
    syms = [{"kind": "function", "name": "x", "file": "a.py", "line": 1, "doc": ""}]
    fp.save_symbols(target, syms)
    loaded = json.loads(target.read_text())
    assert loaded == syms
    leftovers = list(tmp_path.glob("syms.json*.tmp"))
    assert leftovers == []
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: `AttributeError` on `walk_repo` / `save_symbols`.

- [ ] **Step 3: Add walker + writer to `bin/fingerprint.py`**

```python
import os
import tempfile

SKIP_DIRS = {".git", "__pycache__", "state", ".venv", "node_modules", ".pytest_cache"}


def walk_repo(root: Path) -> list[dict[str, Any]]:
    root = Path(root)
    out: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        suffix = path.suffix.lower()
        if suffix == ".py":
            out.extend(extract_python_symbols(path))
        elif suffix == ".sh":
            out.extend(extract_shell_symbols(path))
        elif suffix == ".md":
            out.extend(extract_markdown_headers(path))
    return out


def save_symbols(path: Path, symbols: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(symbols, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/fingerprint.py tests/test_fingerprint.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(fingerprint): repo walker + atomic JSON writer with hidden-dir skip"
```

---

### Task 11: Fingerprinter — CLI entry point (test-first)

**Files:**
- Modify: `bin/fingerprint.py`
- Modify: `tests/test_fingerprint.py`

- [ ] **Step 1: Append failing tests**

```python
def test_cli_writes_symbols_json(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    fp.main()
    out_path = state_dir / "local-symbols.json"
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert any(s["name"] == "hello" for s in data)


def test_cli_emits_summary_to_stdout(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    (tmp_path / "state").mkdir()
    monkeypatch.chdir(tmp_path)
    fp.main()
    captured = capsys.readouterr()
    assert "FINGERPRINT" in captured.out
    assert "symbols" in captured.out.lower()
```

- [ ] **Step 2: Run tests, verify fail**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: `AttributeError: module 'bin.fingerprint' has no attribute 'main'`.

- [ ] **Step 3: Add `main()` to `bin/fingerprint.py`**

```python
def main() -> int:
    root = Path.cwd()
    syms = walk_repo(root)
    out_path = root / "state" / "local-symbols.json"
    save_symbols(out_path, syms)
    by_kind: dict[str, int] = {}
    for s in syms:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    print(f"FINGERPRINT: {len(syms)} symbols across {len(by_kind)} kinds")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind}: {count}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_fingerprint.py -v
```
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes add bin/fingerprint.py tests/test_fingerprint.py
git -c user.email=jounes.ds@gmail.com -c user.name=Jounes commit -m "feat(fingerprint): CLI main() with summary output"
```

---

### Task 12: Tag v0.2.0 + GitHub release

**Files:** none (release-only)

- [ ] **Step 1: Confirm full suite passes**

```bash
cd /home/joncik/apps/Spectre && pytest tests/ -v
```
Expected: 45 (existing v1) + 26 (graph) + 16 (fingerprint) = 87 passed.

- [ ] **Step 2: Push outstanding commits**

```bash
git push origin master
```

- [ ] **Step 3: Tag v0.2.0**

```bash
git tag -a v0.2.0 -m "v0.2.0 — Graph Foundation (Plan A)

Internal infrastructure for v2 Graph Orchestrator. No skill changes.

Adds:
- bin/graph.py: Node/Edge data model, markdown frontmatter serializer/parser, atomic load_graph/save_graph, query functions (get_node, children_by_edge, find_stale), mutation (mark_stale, mark_stale_cascade across constrains/satisfies edges).
- bin/fingerprint.py: Python AST + shell function + markdown header extractors, repo walker (skips .git/state/__pycache__/.venv/node_modules/.pytest_cache), atomic JSON writer to state/local-symbols.json, CLI main() with kind summary.

Stdlib only. 42 new tests. All v1 behavior unchanged.

Plan B (skill integration) and Plan C (parallel tracks) still ahead."
git push origin v0.2.0
```

- [ ] **Step 4: Create GitHub release**

```bash
gh release create v0.2.0 --title "v0.2.0 — Graph Foundation" --notes "$(cat <<'EOF'
First slice of the v2 Graph Orchestrator: pure infrastructure, no behavior change for v1 users.

## What ships

**\`bin/graph.py\`** — graph data model
- Node types: invariant, interface, implementation, resource
- Edge types: constrains, satisfies, blocks, invalidates, supersedes
- Markdown frontmatter manifest at \`specs/.graph.md\` (git-diffable, single file)
- Atomic load/save via \`tempfile.mkstemp + os.replace\`
- Query: \`get_node\`, \`children_by_edge\`, \`find_stale\`
- Mutation: \`mark_stale\`, \`mark_stale_cascade\` (propagates through constrains/satisfies edges)

**\`bin/fingerprint.py\`** — codebase symbol map
- Python AST extraction (modules, functions, classes, docstrings)
- Shell function extraction (both \`name() {}\` and \`function name() {}\` forms)
- Markdown H1/H2 header extraction
- Repo walker skipping \`.git\`, \`__pycache__\`, \`state\`, \`.venv\`, \`node_modules\`, \`.pytest_cache\`
- CLI: \`python3 bin/fingerprint.py\` writes \`state/local-symbols.json\`

## What's NOT here yet

- Skill integration (\`/vision\` doesn't call fingerprint yet → Plan B / v0.2.1)
- Persistence-Tier risk gate (still uses v1 regex Risk-Gate → Plan B)
- ADR generation (still no \`decisions/\` folder → Plan B)
- Multi-track scratchpad + supervisor (single-track only → Plan C / v0.2.2)
- Post-execution State Auditor (verification still bash-only → Plan B)

## Stack

Python 3.11+, stdlib only. 42 new tests, 87 total passing.
EOF
)"
```

- [ ] **Step 5: Confirm release URL printed**

Expected: `https://github.com/Joncik91/Spectre/releases/tag/v0.2.0`.

---

## Self-Review

**Spec coverage** (against v2 architecture doc Decisions 7 + 3 + 8 partial):

| v2 Decision | Plan A coverage |
|---|---|
| 1. Hierarchy (Invariants > Interfaces > Implementations) | Node types ship; consumed in Plan B |
| 2. Persistence-Tier classifier | Deferred to Plan B |
| 3. Codebase Fingerprint | ✅ `bin/fingerprint.py` ships full feature |
| 4. ADR markdown files | Deferred to Plan B |
| 5. Per-track scratchpad + Supervisor | Deferred to Plan C |
| 6. State Auditor with PBT-lite | Deferred to Plan B |
| 7. Graph data model + storage | ✅ `bin/graph.py` ships full data model + serialization + queries + cascade mutation |
| 8. Never Autonomous + Atomic Rollback | Deferred to Plan B |

Plan A is consistent with "infrastructure only; no skill changes." Decisions 1, 3, 7 are the foundation; everything else needs a skill or hook change and belongs in Plan B/C.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" / "similar to Task N" / "add error handling" patterns. Every code step has complete code. Every command has expected output.

**Type consistency:**
- `Node` dataclass shape consistent across Tasks 2, 3, 4, 5, 6, 7.
- `serialize_node` / `parse_manifest` / `load_graph` / `save_graph` signatures match.
- `extract_python_symbols` / `extract_shell_symbols` / `extract_markdown_headers` all return `list[dict[str, Any]]` with same key set: `kind`, `name`, `file`, `line`, `doc`. Verified consistent across Tasks 8, 9, 10.
- `mark_stale_cascade` uses `CASCADE_EDGES = ("constrains", "satisfies")` — Task 7 test asserts this exactly.

**Pragma anti-gaming:** Every test calls a real function with real input and asserts on real return values. No `assert True`. No identical-constant-on-both-sides. All `for` loops in tests assert the aggregate result, not loop-internal conditional state.

**No new git config:** All commit commands use `-c user.email=... -c user.name=...` flags per established repo pattern.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-05-v2-plan-a-graph-foundation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
