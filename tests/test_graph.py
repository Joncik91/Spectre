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
