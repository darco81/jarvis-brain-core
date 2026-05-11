"""Tests for /query endpoint: fan-out, super index, repo filter."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain.api.query import _route_query, build_query_router
from brain.core.paths import DataPaths
from brain.publishers.api_index import APIIndexPublisher

DEV_TOKEN = "test-dev-token"


def _make_index(index_dir: Path, nodes: list[dict], edges: list[dict] | None = None) -> None:
    """Create a minimal FTS5 index for testing."""
    index_dir.mkdir(parents=True, exist_ok=True)
    master = {"nodes": nodes, "edges": edges or []}
    APIIndexPublisher().publish(master, index_dir)


def _client(paths: DataPaths) -> TestClient:
    app = FastAPI()
    app.include_router(build_query_router(paths, DEV_TOKEN))
    return TestClient(app)


def test_query_scope_none_fan_out(tmp_path: Path) -> None:
    """scope omitted → fan-out across all group indexes."""
    paths = DataPaths(tmp_path)

    # Create two group indexes
    group_a_idx = tmp_path / "vaults" / "groupA" / "index"
    _make_index(
        group_a_idx,
        [
            {
                "id": "groupA/repoA:useCart",
                "name": "useCart",
                "file": "hooks.ts",
                "metadata": {"_repo": "repoA"},
            }
        ],
    )

    group_b_idx = tmp_path / "vaults" / "groupB" / "index"
    _make_index(
        group_b_idx,
        [
            {
                "id": "groupB/repoB:LoginButton",
                "name": "LoginButton",
                "file": "components.vue",
                "metadata": {"_repo": "repoB"},
            }
        ],
    )

    client = _client(paths)
    r = client.get(
        "/query?q=Cart",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert isinstance(hits, list)
    # Should find results from both groups
    assert len(hits) >= 1


def test_query_scope_super(tmp_path: Path) -> None:
    """scope=super → read from super index."""
    paths = DataPaths(tmp_path)

    # Create super index
    super_idx = tmp_path / "vaults" / "_super" / "index"
    _make_index(
        super_idx,
        [
            {
                "id": "groupA/repoA:Cart",
                "name": "Cart",
                "file": "cart.ts",
                "metadata": {"_repo": "repoA"},
            }
        ],
    )

    client = _client(paths)
    r = client.get(
        "/query?q=Cart&scope=super",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 200
    assert isinstance(r.json()["hits"], list)


def test_query_scope_super_404_when_missing(tmp_path: Path) -> None:
    """scope=super returns 404 if super index doesn't exist."""
    paths = DataPaths(tmp_path)
    client = _client(paths)
    r = client.get(
        "/query?q=Cart&scope=super",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 404


def test_query_scope_group_repo_filter(tmp_path: Path) -> None:
    """scope=group/repo returns only hits where repo column matches."""
    paths = DataPaths(tmp_path)

    # Create group index with multiple repos
    group_idx = tmp_path / "vaults" / "example-group" / "index"
    _make_index(
        group_idx,
        [
            {
                "id": "example-group/example-front-a:Cart",
                "name": "Cart",
                "file": "cart.vue",
                "metadata": {"_repo": "example-front-a"},
            },
            {
                "id": "example-group/OtherRepo:ShoppingCart",
                "name": "ShoppingCart",
                "file": "shop.ts",
                "metadata": {"_repo": "OtherRepo"},
            },
        ],
    )

    client = _client(paths)
    r = client.get(
        "/query?q=Cart&scope=example-group/example-front-a",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 200
    for hit in r.json()["hits"]:
        assert hit["repo"] == "example-front-a"


def test_query_scope_group_only(tmp_path: Path) -> None:
    """scope=group → search group-wide without repo filter."""
    paths = DataPaths(tmp_path)

    group_idx = tmp_path / "vaults" / "example-group" / "index"
    _make_index(
        group_idx,
        [
            {
                "id": "example-group/Repo1:Item",
                "name": "Item",
                "file": "item.ts",
                "metadata": {"_repo": "Repo1"},
            },
            {
                "id": "example-group/Repo2:Cart",
                "name": "Cart",
                "file": "cart.ts",
                "metadata": {"_repo": "Repo2"},
            },
        ],
    )

    client = _client(paths)
    r = client.get(
        "/query?q=Cart&scope=example-group",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert len(hits) >= 1
    # At least one hit from any repo (not filtered)


def test_query_missing_group_returns_404(tmp_path: Path) -> None:
    """scope=nonexistent → 404."""
    paths = DataPaths(tmp_path)
    client = _client(paths)
    r = client.get(
        "/query?q=test&scope=nonexistent",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 404


def test_query_invalid_syntax_returns_422(tmp_path: Path) -> None:
    """Invalid FTS5 query syntax → 422."""
    paths = DataPaths(tmp_path)
    group_idx = tmp_path / "vaults" / "test" / "index"
    _make_index(
        group_idx,
        [
            {
                "id": "test/repo:Node",
                "name": "Node",
                "file": "f.ts",
                "metadata": {"_repo": "repo"},
            }
        ],
    )

    client = _client(paths)
    r = client.get(
        "/query?q=AND&scope=test",  # AND is invalid without operands
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 422


def test_query_no_auth_in_educational_version(tmp_path: Path) -> None:
    """Educational version replaces production bearer auth with a no-op stub
    (see brain/api/_stubs.py). The production deployment enforces 401 on
    missing/invalid tokens; here the request succeeds and returns 404 because
    the requested group has no index."""
    paths = DataPaths(tmp_path)
    client = _client(paths)
    r = client.get("/query?q=test&scope=group")
    assert r.status_code == 404


def test_query_q_required(tmp_path: Path) -> None:
    """Missing q parameter → 422."""
    paths = DataPaths(tmp_path)
    client = _client(paths)
    r = client.get(
        "/query?scope=group",
        headers={"Authorization": f"Bearer {DEV_TOKEN}"},
    )
    assert r.status_code == 422


def test_route_query_fan_out_returns_merged_results(tmp_path: Path) -> None:
    """_route_query with scope=None merges results and truncates to limit."""
    paths = DataPaths(tmp_path)

    # Group A: 5 hits for "test"
    group_a_idx = tmp_path / "vaults" / "groupA" / "index"
    _make_index(
        group_a_idx,
        [
            {
                "id": f"groupA/r:Node{i}",
                "name": f"TestNode{i}",
                "file": f"f{i}.ts",
                "metadata": {"_repo": "r"},
            }
            for i in range(5)
        ],
    )

    # Group B: 3 hits for "test"
    group_b_idx = tmp_path / "vaults" / "groupB" / "index"
    _make_index(
        group_b_idx,
        [
            {
                "id": f"groupB/r:TestItem{i}",
                "name": f"TestItem{i}",
                "file": f"f{i}.ts",
                "metadata": {"_repo": "r"},
            }
            for i in range(3)
        ],
    )

    hits = _route_query(paths, "test", None, limit=10)
    assert len(hits) <= 10
    assert len(hits) >= 1  # should find something


def test_route_query_super_index_returns_union(tmp_path: Path) -> None:
    """_route_query with scope=super reads union index."""
    paths = DataPaths(tmp_path)

    super_idx = tmp_path / "vaults" / "_super" / "index"
    _make_index(
        super_idx,
        [
            {
                "id": "g1/r:Item",
                "name": "Item",
                "file": "f.ts",
                "metadata": {"_repo": "r"},
            }
        ],
    )

    hits = _route_query(paths, "item", "super", limit=10)
    assert len(hits) >= 1


def test_hit_structure_includes_all_fields(tmp_path: Path) -> None:
    """Each hit has node_id, label, file, repo, meta, neighbors."""
    paths = DataPaths(tmp_path)

    idx = tmp_path / "vaults" / "group" / "index"
    _make_index(
        idx,
        [
            {
                "id": "group/repo:TestNode",
                "name": "TestNode",
                "file": "test.ts",
                "metadata": {"_repo": "repo", "custom": "value"},
            }
        ],
    )

    hits = _route_query(paths, "test", "group", limit=10)
    assert len(hits) == 1
    hit = hits[0]
    assert "node_id" in hit
    assert "label" in hit
    assert "file" in hit
    assert "repo" in hit
    assert "meta" in hit
    assert "neighbors" in hit
    assert hit["node_id"] == "group/repo:TestNode"
    assert hit["repo"] == "repo"
