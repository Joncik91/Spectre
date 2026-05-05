"""ADR writer and supersedes-edge tests."""
import json
from pathlib import Path

import pytest

from bin import adr, graph


def test_next_id_returns_0001_when_directory_empty(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    assert adr.next_id(d) == "0001"


def test_next_id_returns_0002_when_one_adr_exists(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "0001-foo.md").write_text("---\nid: 0001\n---\n")
    assert adr.next_id(d) == "0002"


def test_next_id_handles_gaps(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "0001-a.md").write_text("---\n")
    (d / "0005-b.md").write_text("---\n")
    assert adr.next_id(d) == "0006"


def test_next_id_ignores_non_adr_files(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / ".gitkeep").write_text("")
    (d / "README.md").write_text("# Decisions")
    assert adr.next_id(d) == "0001"


def test_slugify_basic():
    assert adr.slugify("Use Postgres 16 for primary store") == "use-postgres-16-for-primary-store"


def test_slugify_strips_non_alphanumerics():
    assert adr.slugify("foo: bar/baz!") == "foo-bar-baz"


def test_slugify_collapses_repeats():
    assert adr.slugify("a   b") == "a-b"


def test_slugify_strips_leading_trailing_dashes():
    assert adr.slugify("---hello---") == "hello"


def test_write_adr_creates_file(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    p = adr.write_adr(d, title="Pick Postgres", date="2026-05-05", body="Body text.")
    assert p.exists()
    assert p.name == "0001-pick-postgres.md"


def test_write_adr_frontmatter_shape(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    p = adr.write_adr(d, title="Pick Postgres", date="2026-05-05", body="Body text.")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "id: 0001\n" in text
    assert 'title: "Pick Postgres"\n' in text
    assert "date: 2026-05-05\n" in text
    assert "status: accepted\n" in text
    assert "supersedes: null\n" in text
    assert "\n---\n\nBody text.\n" in text


def test_write_adr_with_supersedes(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    adr.write_adr(d, title="First", date="2026-05-04", body="A.")
    p = adr.write_adr(
        d, title="Second", date="2026-05-05", body="B.", supersedes="0001"
    )
    text = p.read_text(encoding="utf-8")
    assert "supersedes: 0001\n" in text


def test_write_adr_marks_superseded_status_on_old(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    p1 = adr.write_adr(d, title="First", date="2026-05-04", body="A.")
    adr.write_adr(d, title="Second", date="2026-05-05", body="B.", supersedes="0001")
    text = p1.read_text(encoding="utf-8")
    assert "status: superseded\n" in text


def test_write_adr_atomic(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    adr.write_adr(d, title="Foo", date="2026-05-05", body="Body.")
    leftovers = list(d.glob("*.tmp"))
    assert leftovers == []


def test_update_graph_for_supersedes_appends_edge(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    g.parent.mkdir()
    nodes = [
        graph.Node(id="adr-0001", type="invariant", title="Old"),
        graph.Node(id="adr-0002", type="invariant", title="New"),
    ]
    graph.save_graph(g, nodes)
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0002", old_adr_id="adr-0001")
    reloaded = graph.load_graph(g)
    new_node = graph.get_node(reloaded, "adr-0002")
    assert new_node is not None
    assert {"target": "adr-0001", "type": "supersedes"} in new_node.edges


def test_update_graph_for_supersedes_marks_old_superseded(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    g.parent.mkdir()
    nodes = [
        graph.Node(id="adr-0001", type="invariant", title="Old"),
        graph.Node(id="adr-0002", type="invariant", title="New"),
    ]
    graph.save_graph(g, nodes)
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0002", old_adr_id="adr-0001")
    reloaded = graph.load_graph(g)
    old = graph.get_node(reloaded, "adr-0001")
    assert old is not None
    assert old.status == "superseded"


def test_update_graph_for_supersedes_noop_when_graph_missing(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0002", old_adr_id="adr-0001")
    assert not g.exists()


def test_update_graph_for_supersedes_noop_when_node_missing(tmp_path):
    g = tmp_path / "specs" / ".graph.md"
    g.parent.mkdir()
    nodes = [graph.Node(id="adr-0001", type="invariant", title="Old")]
    graph.save_graph(g, nodes)
    adr.update_graph_for_supersedes(g, new_adr_id="adr-0099", old_adr_id="adr-0001")
    reloaded = graph.load_graph(g)
    old = graph.get_node(reloaded, "adr-0001")
    assert old is not None
    assert old.status == "active"
