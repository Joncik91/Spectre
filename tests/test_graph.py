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


def test_load_graph_returns_empty_when_missing(tmp_path):
    nodes = graph.load_graph(tmp_path / "nope.md")
    assert nodes == []


def test_save_graph_then_load_round_trip(tmp_path):
    path = tmp_path / "g.md"
    n = graph.Node(id="a", type="invariant", title="A")
    n.add_edge(target="b", edge_type="constrains")
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


def test_save_graph_cleans_up_tmp_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "g.md"
    n = graph.Node(id="x", type="resource", title="t")

    def boom(*args, **kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(graph.os, "replace", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        graph.save_graph(path, [n])

    leftovers = list(tmp_path.glob("g.md*.tmp"))
    assert leftovers == []
    assert not path.exists()


def test_parse_manifest_incomplete_edge_raises_valueerror():
    text = (
        "---\n"
        "id: a\n"
        "type: invariant\n"
        "title: A\n"
        "status: active\n"
        "edges:\n"
        "  - target: b\n"
        "---\n"
    )
    with pytest.raises(ValueError, match="edge with target but no type"):
        graph.parse_manifest(text)


def test_parse_manifest_missing_id_raises_valueerror():
    text = (
        "---\n"
        "type: invariant\n"
        "title: Anonymous\n"
        "edges: []\n"
        "---\n"
    )
    with pytest.raises(ValueError, match="missing required field 'id'"):
        graph.parse_manifest(text)


def test_parse_manifest_missing_title_raises_valueerror():
    text = (
        "---\n"
        "id: a\n"
        "type: invariant\n"
        "edges: []\n"
        "---\n"
    )
    with pytest.raises(ValueError, match="missing required field 'title'"):
        graph.parse_manifest(text)


def _build_sample_graph():
    inv = graph.Node(id="inv-1", type="invariant", title="UserObject schema")
    inv.add_edge(target="impl-1", edge_type="constrains")
    inv.add_edge(target="impl-2", edge_type="constrains")
    impl1 = graph.Node(id="impl-1", type="implementation", title="signup endpoint")
    impl1.add_edge(target="iface-1", edge_type="satisfies")
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
