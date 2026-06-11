"""/query/path - shortest path between nodes in merged master graph."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain.api.query_path import build_query_path_router


def _make_master_graph(
    path: Path, nodes: list[dict], edges: list[dict]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "v1",
        "group": "example-group",
        "repo": "_master",
        "built_at": datetime.now(UTC).isoformat(),
        "built_by": "federation-merger",
        "nodes": nodes,
        "edges": edges,
        "stats": {"nodes_count": len(nodes), "edges_count": len(edges)},
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _node(nid: str) -> dict:
    return {
        "id": nid,
        "kind": "class",
        "name": nid.rsplit(":", 1)[-1],
        "file": None,
        "line": None,
        "community": None,
        "metadata": {},
    }


def _edge(src: str, dst: str) -> dict:
    return {
        "source": src,
        "target": dst,
        "relation": "imports",
        "confidence": "extracted",
        "metadata": {},
    }


def _client(graphs_base: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_query_path_router(
            graphs_base=graphs_base, auth_override=lambda: None
        )
    )
    return TestClient(app)


def test_query_path_returns_shortest(tmp_path: Path) -> None:
    graphs_base = tmp_path / "graphs"
    master = graphs_base / "example-group" / "_master" / "graph.json"
    nodes = [_node(f"example-group/example-front-a:A{i}") for i in range(4)]
    edges = [
        _edge(f"example-group/example-front-a:A{i}", f"example-group/example-front-a:A{i + 1}")
        for i in range(3)
    ]
    _make_master_graph(master, nodes, edges)

    resp = _client(graphs_base).get(
        "/query/path",
        params={
            "from_node": "example-group/example-front-a:A0",
            "to_node": "example-group/example-front-a:A3",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == [
        "example-group/example-front-a:A0",
        "example-group/example-front-a:A1",
        "example-group/example-front-a:A2",
        "example-group/example-front-a:A3",
    ]
    assert body["hops"] == 3


def test_query_path_no_path_returns_404(tmp_path: Path) -> None:
    graphs_base = tmp_path / "graphs"
    master = graphs_base / "example-group" / "_master" / "graph.json"
    _make_master_graph(
        master,
        [_node("example-group/example-front-a:A"), _node("example-group/example-front-a:B")],
        [],
    )
    resp = _client(graphs_base).get(
        "/query/path",
        params={
            "from_node": "example-group/example-front-a:A",
            "to_node": "example-group/example-front-a:B",
        },
    )
    assert resp.status_code == 404
    assert "no path" in resp.json()["detail"].lower()


def test_query_path_node_not_found_returns_404(tmp_path: Path) -> None:
    graphs_base = tmp_path / "graphs"
    master = graphs_base / "example-group" / "_master" / "graph.json"
    _make_master_graph(master, [_node("example-group/example-front-a:A")], [])
    resp = _client(graphs_base).get(
        "/query/path",
        params={
            "from_node": "example-group/example-front-a:A",
            "to_node": "example-group/example-front-a:NOPE",
        },
    )
    assert resp.status_code == 404


def test_query_path_missing_master_returns_404(tmp_path: Path) -> None:
    resp = _client(tmp_path / "graphs").get(
        "/query/path",
        params={
            "from_node": "example-group/example-front-a:A",
            "to_node": "example-group/example-front-a:B",
        },
    )
    assert resp.status_code == 404


def test_query_path_unqualified_node_returns_422(tmp_path: Path) -> None:
    resp = _client(tmp_path / "graphs").get(
        "/query/path",
        params={"from_node": "example-front-a_only", "to_node": "example-group/example-front-a:B"},
    )
    assert resp.status_code == 422


def test_query_path_exceeds_max_hops_returns_404(tmp_path: Path) -> None:
    graphs_base = tmp_path / "graphs"
    master = graphs_base / "example-group" / "_master" / "graph.json"
    nodes = [_node(f"example-group/example-front-a:N{i}") for i in range(10)]
    edges = [
        _edge(f"example-group/example-front-a:N{i}", f"example-group/example-front-a:N{i + 1}")
        for i in range(9)
    ]
    _make_master_graph(master, nodes, edges)

    resp = _client(graphs_base).get(
        "/query/path",
        params={
            "from_node": "example-group/example-front-a:N0",
            "to_node": "example-group/example-front-a:N9",
            "max_hops": 3,
        },
    )
    assert resp.status_code == 404
    assert "max_hops" in resp.json()["detail"]


def test_shortest_path_rejects_cross_group_with_422() -> None:
    """from_node and to_node in different groups: only from_node's group
    graph is loaded, so the old behaviour was a confusing 404 'node not
    found'. It must be a clear 422 instead. The guard fires before any
    filesystem access, so the graphs_base path is irrelevant."""
    import pytest
    from fastapi import HTTPException

    from brain.api.query_path import shortest_path_payload

    with pytest.raises(HTTPException) as exc:
        shortest_path_payload(
            Path("/nonexistent"), "group-a/repo:Foo", "group-b/repo:Bar"
        )
    assert exc.value.status_code == 422
    assert "cross-group" in str(exc.value.detail).lower()
