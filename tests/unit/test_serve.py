"""Integration tests for brain.scripts.serve - all 5 tools over JSON-RPC.

Uses the demo_ingest synthetic graph as the data root, so this doubles as
a regression test for the documented 3-command quick start
(demo_ingest -> serve -> claude mcp add).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from brain.publishers.api_index import APIIndexPublisher
from brain.scripts.demo_ingest import _build_synthetic_graph
from brain.scripts.serve import build_app

GROUP = "example-group"


@pytest.fixture()
def demo_app(tmp_path: Path) -> FastAPI:
    graph = _build_synthetic_graph()
    master_path = tmp_path / "graphs" / GROUP / "_master" / "graph.json"
    master_path.parent.mkdir(parents=True)
    master_path.write_text(json.dumps(graph))
    APIIndexPublisher().publish(graph, tmp_path / "vaults" / GROUP / "index")
    return build_app(tmp_path)


async def _call(app: FastAPI, method: str, params: dict[str, Any]) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _tool(app: FastAPI, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    body = await _call(app, "tools/call", {"name": name, "arguments": arguments})
    assert "error" not in body, body
    payload: dict[str, Any] = json.loads(body["result"]["content"][0]["text"])
    return payload


@pytest.mark.asyncio
async def test_initialize_and_tools_list(demo_app: FastAPI) -> None:
    init = await _call(demo_app, "initialize", {})
    assert init["result"]["protocolVersion"]
    listed = await _call(demo_app, "tools/list", {})
    names = sorted(t["name"] for t in listed["result"]["tools"])
    assert names == ["brain_explain", "brain_ffcss", "brain_graph", "brain_path", "brain_query"]


@pytest.mark.asyncio
async def test_brain_query_camelcase_trick(demo_app: FastAPI) -> None:
    payload = await _tool(demo_app, "brain_query", {"q": "user", "scope": GROUP})
    ids = [h["node_id"] for h in payload["hits"]]
    assert f"{GROUP}/app-core:useUserSession" in ids


@pytest.mark.asyncio
async def test_brain_graph_without_node_returns_summary_not_dump(
    demo_app: FastAPI,
) -> None:
    out = await _tool(demo_app, "brain_graph", {"group": GROUP})
    assert "nodes" not in out, "no node_id must mean summary, not a full dump"
    assert out["summary"]["total_nodes"] == 5
    assert out["summary"]["nodes_by_kind"] == {"function": 3, "component": 2}
    assert set(out["summary"]["nodes_by_repo"]) == {"app-core", "app-front-a"}


@pytest.mark.asyncio
async def test_brain_graph_ego_radius_1_vs_2(demo_app: FastAPI) -> None:
    center = f"{GROUP}/app-front-a:CheckoutPage"
    r1 = await _tool(demo_app, "brain_graph", {"group": GROUP, "node_id": center, "radius": 1})
    r2 = await _tool(demo_app, "brain_graph", {"group": GROUP, "node_id": center, "radius": 2})
    ids1 = {n["id"] for n in r1["nodes"]}
    ids2 = {n["id"] for n in r2["nodes"]}
    # radius 1: center + direct neighbors (LoginButton, useCheckoutFlow)
    assert ids1 == {
        center,
        f"{GROUP}/app-front-a:LoginButton",
        f"{GROUP}/app-core:useCheckoutFlow",
    }
    # radius 2 adds LoginButton's core imports
    assert ids1 < ids2
    assert f"{GROUP}/app-core:useUserSession" in ids2


@pytest.mark.asyncio
async def test_brain_graph_concise_vs_detailed(demo_app: FastAPI) -> None:
    center = f"{GROUP}/app-front-a:LoginButton"
    concise = await _tool(demo_app, "brain_graph", {"group": GROUP, "node_id": center})
    node = concise["nodes"][0]
    assert set(node) == {"id", "name", "kind"}
    detailed = await _tool(
        demo_app,
        "brain_graph",
        {"group": GROUP, "node_id": center, "response_format": "detailed"},
    )
    dnode = next(n for n in detailed["nodes"] if n["id"] == center)
    assert "file" in dnode and "metadata" in dnode


@pytest.mark.asyncio
async def test_brain_graph_unknown_node_returns_not_found(demo_app: FastAPI) -> None:
    body = await _call(
        demo_app,
        "tools/call",
        {
            "name": "brain_graph",
            "arguments": {"group": GROUP, "node_id": f"{GROUP}/app-core:Nope"},
        },
    )
    assert body["error"]["code"] == -32004


@pytest.mark.asyncio
async def test_brain_path_walks_demo_graph(demo_app: FastAPI) -> None:
    payload = await _tool(
        demo_app,
        "brain_path",
        {
            "from_node": f"{GROUP}/app-front-a:CheckoutPage",
            "to_node": f"{GROUP}/app-core:useUserSession",
        },
    )
    assert payload["hops"] == 2


@pytest.mark.asyncio
async def test_brain_explain_returns_neighbors(demo_app: FastAPI) -> None:
    payload = await _tool(
        demo_app, "brain_explain", {"node_id": f"{GROUP}/app-front-a:LoginButton"}
    )
    assert payload["kind"] == "component"
    out_ids = {n["id"] for n in payload["neighbors_out"]}
    assert f"{GROUP}/app-core:useUserSession" in out_ids


@pytest.mark.asyncio
async def test_brain_ffcss_responds(demo_app: FastAPI) -> None:
    payload = await _tool(demo_app, "brain_ffcss", {"group": GROUP, "mode": "tokens"})
    assert payload["mode"] == "tokens"
    assert payload["tokens"] == []  # demo graph has no design tokens


@pytest.mark.asyncio
async def test_unknown_group_maps_to_rpc_not_found(demo_app: FastAPI) -> None:
    body = await _call(
        demo_app,
        "tools/call",
        {"name": "brain_graph", "arguments": {"group": "nope"}},
    )
    assert body["error"]["code"] == -32004
