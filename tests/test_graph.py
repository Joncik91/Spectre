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
