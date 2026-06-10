"""Test SuperIndexPublisher - cross-group FTS5 index builder.

Ported from the private jarvis-brain test suite (sanitized).
"""
import json
import sqlite3
from pathlib import Path

from brain.publishers.super_index import SuperIndexPublisher


def test_super_index_unions_groups(tmp_path: Path) -> None:
    """SuperIndexPublisher should union nodes/edges from multiple group masters."""
    group_a = tmp_path / "a" / "_master" / "graph.json"
    group_a.parent.mkdir(parents=True)
    group_a.write_text(json.dumps({
        "nodes": [{"id": "a/R:Foo", "name": "Foo", "metadata": {"_repo": "R"}}],
        "edges": [],
    }))

    group_b = tmp_path / "b" / "_master" / "graph.json"
    group_b.parent.mkdir(parents=True)
    group_b.write_text(json.dumps({
        "nodes": [{"id": "b/S:Bar", "name": "Bar", "metadata": {"_repo": "S"}}],
        "edges": [],
    }))

    out_dir = tmp_path / "_super"
    SuperIndexPublisher().publish_from_masters([group_a, group_b], out_dir)

    con = sqlite3.connect(out_dir / "index.sqlite")
    rows = con.execute("SELECT node_id FROM nodes_fts ORDER BY node_id").fetchall()
    con.close()
    assert [r[0] for r in rows] == ["a/R:Foo", "b/S:Bar"]


def test_super_index_match_finds_across_groups(tmp_path: Path) -> None:
    """FTS5 MATCH should find nodes by name across all groups."""
    ga = tmp_path / "a" / "_master" / "graph.json"
    ga.parent.mkdir(parents=True)
    ga.write_text(json.dumps({
        "nodes": [{"id": "a/R:useCart", "name": "useCart", "metadata": {"_repo": "R"}}],
        "edges": [],
    }))
    out_dir = tmp_path / "_super"
    SuperIndexPublisher().publish_from_masters([ga], out_dir)

    con = sqlite3.connect(out_dir / "index.sqlite")
    rows = con.execute(
        "SELECT node_id FROM nodes_fts WHERE nodes_fts MATCH ?", ("Cart",)
    ).fetchall()
    con.close()
    assert len(rows) == 1
    assert rows[0][0] == "a/R:useCart"


def test_super_index_skips_missing_paths(tmp_path: Path) -> None:
    """SuperIndexPublisher should skip missing master paths without raising."""
    missing = tmp_path / "no" / "_master" / "graph.json"
    present = tmp_path / "yes" / "_master" / "graph.json"
    present.parent.mkdir(parents=True)
    present.write_text(json.dumps({
        "nodes": [{"id": "yes/R:Ok", "name": "Ok", "metadata": {"_repo": "R"}}],
        "edges": [],
    }))
    out_dir = tmp_path / "_super"
    # Should not raise
    SuperIndexPublisher().publish_from_masters([missing, present], out_dir)
    con = sqlite3.connect(out_dir / "index.sqlite")
    rows = con.execute("SELECT node_id FROM nodes_fts").fetchall()
    con.close()
    assert len(rows) == 1


def test_scope_super_query_routes_to_super_index(tmp_path: Path) -> None:
    """End-to-end: scope='super' in _route_query hits the published super index.

    Before this publisher was ported, scope='super' (advertised in
    mcp_tools.py) could only 404.
    """
    from brain.api.query import _route_query
    from brain.core.paths import DataPaths

    ga = tmp_path / "graphs" / "g" / "_master" / "graph.json"
    ga.parent.mkdir(parents=True)
    ga.write_text(json.dumps({
        "nodes": [{"id": "g/R:useCart", "name": "useCart", "metadata": {"_repo": "R"}}],
        "edges": [],
    }))
    paths = DataPaths(root=tmp_path)
    SuperIndexPublisher().publish_from_masters([ga], paths.super_index())

    hits = _route_query(paths, "Cart", scope="super", limit=10)
    assert [h["node_id"] for h in hits] == ["g/R:useCart"]
