import pytest
from bin import graph


def test_node_types_are_exact_set():
    assert graph.NODE_TYPES == ("invariant", "interface", "implementation", "resource")


def test_edge_types_are_exact_set():
    assert graph.EDGE_TYPES == ("constrains", "satisfies", "blocks", "invalidates", "supersedes")


def test_statuses_are_exact_set():
    assert graph.STATUSES == ("active", "stale", "superseded")


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
        n.add_edge(target="y", edge_type="bogus_edge")


def test_edge_add_appends_to_list():
    n = graph.Node(id="x", type="invariant", title="t")
    n.add_edge(target="y", edge_type="constrains")
    assert n.edges == [{"target": "y", "type": "constrains"}]


def test_node_status_active():
    n = graph.Node(id="x", type="invariant", title="t", status="active")
    assert n.status == "active"


def test_node_status_stale():
    n = graph.Node(id="x", type="invariant", title="t", status="stale")
    assert n.status == "stale"


def test_node_status_superseded():
    n = graph.Node(id="x", type="invariant", title="t", status="superseded")
    assert n.status == "superseded"


def test_node_status_rejects_unknown():
    with pytest.raises(ValueError, match="unknown status"):
        graph.Node(id="x", type="invariant", title="t", status="weird")


def test_serialize_node_produces_frontmatter_block():
    n = graph.Node(id="auth-001", type="invariant", title="UserObject schema")
    n.add_edge(target="auth-002", edge_type="constrains")
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


def test_parse_manifest_empty_returns_empty_list():
    assert graph.parse_manifest("") == []


def test_parse_manifest_header_only_returns_empty():
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
    n1.add_edge(target="b", edge_type="constrains")
    n2 = graph.Node(id="b", type="implementation", title="B", status="stale")
    text = graph.serialize_node(n1) + graph.serialize_node(n2)
    parsed = graph.parse_manifest(text)
    assert len(parsed) == 2
    assert parsed[0].id == n1.id
    assert parsed[0].edges == n1.edges
    assert parsed[1].status == n2.status
