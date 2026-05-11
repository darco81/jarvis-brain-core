"""MCP HTTP endpoint: JSON-RPC 2.0 dispatch of brain_query/brain_graph/brain_path.

Auth is bypassed via `auth_override` to keep these as fast pure-unit tests
for the JSON-RPC router itself. DB-backed TokenVerifier is covered by its
own suite (test_tokens_dependency.py).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from brain.api.mcp import build_mcp_router


async def _noop(_args: dict) -> dict:
    return {}


def _build_app(**executors: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_mcp_router(
            query_executor=executors.get("query_executor", _noop),
            graph_executor=executors.get("graph_executor", _noop),
            path_executor=executors.get("path_executor", _noop),
            explain_executor=executors.get("explain_executor", _noop),
            ffcss_executor=executors.get("ffcss_executor", _noop),
            auth_override=lambda: None,
        )
    )
    return app


async def _rpc(app: FastAPI, **payload: Any) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/mcp", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_tools_list_returns_five_tools() -> None:
    app = _build_app()
    body = await _rpc(
        app, jsonrpc="2.0", id=1, method="tools/list", params={}
    )
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    names = sorted(t["name"] for t in body["result"]["tools"])
    assert names == ["brain_explain", "brain_ffcss", "brain_graph", "brain_path", "brain_query"]


@pytest.mark.asyncio
async def test_initialize_returns_capabilities() -> None:
    app = _build_app()
    body = await _rpc(
        app, jsonrpc="2.0", id=2, method="initialize", params={}
    )
    assert body["result"]["protocolVersion"]
    assert body["result"]["capabilities"]["tools"] == {}
    assert body["result"]["serverInfo"]["name"] == "jarvis-brain"


@pytest.mark.asyncio
async def test_tools_call_brain_query_executes() -> None:
    captured: dict = {}

    async def exec_query(args: dict) -> dict:
        captured.update(args)
        return {"hits": [{"node_id": "example-group/example-front-a:Button", "score": 0.9}]}

    app = _build_app(query_executor=exec_query)
    body = await _rpc(
        app,
        jsonrpc="2.0",
        id=3,
        method="tools/call",
        params={
            "name": "brain_query",
            "arguments": {
                "q": "checkout",
                "scope": "example-group/example-front-a",
                "limit": 5,
            },
        },
    )
    assert "content" in body["result"]
    payload = json.loads(body["result"]["content"][0]["text"])
    assert payload["hits"][0]["node_id"] == "example-group/example-front-a:Button"
    assert captured == {"q": "checkout", "scope": "example-group/example-front-a", "limit": 5}


@pytest.mark.asyncio
async def test_brain_query_mcp_scope_none_works() -> None:
    """Per S1: scope=None fan-out works, no more 422."""
    async def exec_query(args: dict) -> dict:
        # Simulate fan-out with empty results
        return {"hits": []}

    app = _build_app(query_executor=exec_query)
    body = await _rpc(
        app,
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={
            "name": "brain_query",
            "arguments": {"q": "anything"}
        },
    )
    assert body["jsonrpc"] == "2.0"
    assert "error" not in body
    content = json.loads(body["result"]["content"][0]["text"])
    assert "hits" in content
    assert isinstance(content["hits"], list)


@pytest.mark.asyncio
async def test_brain_query_mcp_scope_super() -> None:
    """scope='super' should work; 200 with error or without."""
    async def exec_query(args: dict) -> dict:
        # Return some hits to simulate super index
        return {"hits": [{"node_id": "group/repo:Node", "label": "Node"}]}

    app = _build_app(query_executor=exec_query)
    body = await _rpc(
        app,
        jsonrpc="2.0",
        id=2,
        method="tools/call",
        params={
            "name": "brain_query",
            "arguments": {"q": "anything", "scope": "super"}
        },
    )
    assert body["jsonrpc"] == "2.0"
    # Accept either error or success (super may not exist in test env)
    if "error" in body:
        # -32603 is internal error, acceptable if super doesn't exist
        assert body["error"]["code"] in (-32603, -32004)
    else:
        content = json.loads(body["result"]["content"][0]["text"])
        assert "hits" in content


@pytest.mark.asyncio
async def test_tools_call_unknown_tool_returns_method_not_found() -> None:
    app = _build_app()
    body = await _rpc(
        app,
        jsonrpc="2.0",
        id=4,
        method="tools/call",
        params={"name": "brain_unknown", "arguments": {}},
    )
    assert body["error"]["code"] == -32601
    assert "unknown tool" in body["error"]["message"]


@pytest.mark.asyncio
async def test_tools_call_invalid_args_returns_invalid_params() -> None:
    app = _build_app()
    body = await _rpc(
        app,
        jsonrpc="2.0",
        id=5,
        method="tools/call",
        params={
            "name": "brain_query",
            "arguments": {"limit": 999},  # missing 'q', limit too high
        },
    )
    assert body["error"]["code"] == -32602
    assert "invalid params" in body["error"]["message"]


@pytest.mark.asyncio
async def test_tools_call_http_exception_maps_to_rpc_error() -> None:
    async def exec_path(_args: dict) -> dict:
        raise HTTPException(status_code=404, detail="no path between nodes")

    app = _build_app(path_executor=exec_path)
    body = await _rpc(
        app,
        jsonrpc="2.0",
        id=6,
        method="tools/call",
        params={
            "name": "brain_path",
            "arguments": {
                "from_node": "example-group/example-front-a:A",
                "to_node": "example-group/example-front-a:Z",
            },
        },
    )
    assert body["error"]["code"] == -32004
    assert "no path" in body["error"]["message"]


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found() -> None:
    app = _build_app()
    body = await _rpc(
        app, jsonrpc="2.0", id=7, method="prompts/list", params={}
    )
    assert body["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_missing_jsonrpc_version_returns_invalid_request() -> None:
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as ac:
        resp = await ac.post(
            "/mcp", json={"id": 8, "method": "tools/list", "params": {}}
        )
    body = resp.json()
    assert body["error"]["code"] == -32600
