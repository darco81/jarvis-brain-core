"""MCP HTTP endpoint - JSON-RPC 2.0 dispatch for brain dev tools.

Supports methods:
  - initialize           -> handshake, returns capabilities
  - tools/list           -> list of the 5 brain tools
  - tools/call           -> execute named tool, return result envelope

Errors map to JSON-RPC error codes:
  -32001 Unauthorized (401)
  -32002 Forbidden (403)
  -32004 Not Found (404)
  -32600 Invalid request
  -32601 Method not found
  -32602 Invalid params (422)
  -32603 Internal error (500)
  -32700 Parse error
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from brain.api._stubs import DevTokenInfo, RateLimiter, TokenVerifier, log_query

# Production wiring writes the audit log via SQLAlchemy AsyncSession. The
# educational version stubs that out (see _stubs.log_query), so sqlalchemy is
# not a runtime dependency here. Imports are gated behind TYPE_CHECKING so
# the public install stays slim. Restore as a real dependency when wiring
# production auth (see pyproject.toml).
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
else:
    AsyncSession = Any

    class async_sessionmaker:  # noqa: N801  (matches sqlalchemy public name)
        def __class_getitem__(cls, _item: Any) -> Any:
            return Any
from brain.api.mcp_tools import (
    TOOL_DEFINITIONS,
    BrainExplainArgs,
    BrainFfcssArgs,
    BrainGraphArgs,
    BrainPathArgs,
    BrainQueryArgs,
)
from brain.core.logging import get_logger

logger = get_logger("api.mcp")

try:
    _SERVER_VERSION = importlib.metadata.version("jarvis-brain-core")
except importlib.metadata.PackageNotFoundError:  # running from a raw checkout
    _SERVER_VERSION = "0.0.0+unknown"

ToolExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_TOOLS: dict[str, type[BaseModel]] = {
    "brain_query": BrainQueryArgs,
    "brain_graph": BrainGraphArgs,
    "brain_path": BrainPathArgs,
    "brain_explain": BrainExplainArgs,
    "brain_ffcss": BrainFfcssArgs,
}

_HTTP_TO_RPC: dict[int, int] = {
    401: -32001,
    403: -32002,
    404: -32004,
    422: -32602,
}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _success(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _content_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap tool output as MCP content array (type=text with JSON stringified)."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, default=str)}]
    }


def _result_count(result: Any) -> int:
    """Best-effort count for audit log across the three tool response shapes."""
    if not isinstance(result, dict):
        return 0
    for key in ("results", "hits", "nodes", "path"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _describe_query(tool_name: str, args: dict[str, Any]) -> str:
    """Audit-log text for a tools/call invocation.

    brain_query uses the user's search string; brain_graph records the group
    (and repo, if scoped); brain_path records the from→to edge. Without this
    the audit row would be identical for every call to the same tool and
    effectively useless for graph/path.
    """
    if tool_name == "brain_query":
        return str(args.get("q", tool_name))
    if tool_name == "brain_graph":
        group = args.get("group")
        repo = args.get("repo")
        if group and repo:
            return f"{group}/{repo}"
        if group:
            return str(group)
        return tool_name
    if tool_name == "brain_path":
        return f"{args.get('from_node', '?')}->{args.get('to_node', '?')}"
    if tool_name == "brain_explain":
        return str(args.get("node_id", tool_name))
    if tool_name == "brain_ffcss":
        group = args.get("group")
        mode = args.get("mode", "tokens")
        return f"{group}:{mode}"
    return tool_name


# Prevent fire-and-forget audit tasks from being garbage-collected mid-flight:
# asyncio keeps only weak references to tasks without a strong handle, so we
# stash them in a module-level set and release them via a done callback.
_PENDING_AUDIT_TASKS: set[asyncio.Task[None]] = set()


def _spawn_audit_task(coro: Coroutine[Any, Any, None]) -> None:
    task: asyncio.Task[None] = asyncio.create_task(coro)
    _PENDING_AUDIT_TASKS.add(task)
    task.add_done_callback(_PENDING_AUDIT_TASKS.discard)


def build_mcp_router(
    *,
    query_executor: ToolExecutor,
    graph_executor: ToolExecutor,
    path_executor: ToolExecutor,
    explain_executor: ToolExecutor,
    ffcss_executor: ToolExecutor,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    rate_limiter: RateLimiter | None = None,
    auth_override: Callable[..., DevTokenInfo | None] | None = None,
) -> APIRouter:
    router = APIRouter()

    auth_dep: Callable[..., Any]
    if auth_override is not None:
        auth_dep = auth_override
    elif sessionmaker is not None:
        auth_dep = TokenVerifier(
            required_scope="query",
            sessionmaker=sessionmaker,
            rate_limiter=rate_limiter,
        )
    else:
        raise ValueError("Either sessionmaker or auth_override must be provided")

    executors: dict[str, ToolExecutor] = {
        "brain_query": query_executor,
        "brain_graph": graph_executor,
        "brain_path": path_executor,
        "brain_explain": explain_executor,
        "brain_ffcss": ffcss_executor,
    }

    @router.post("/mcp")
    async def mcp_handler(
        request: Request,
        info: DevTokenInfo | None = Depends(auth_dep),
    ) -> dict[str, Any]:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error(None, -32700, "parse error: invalid JSON")

        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if body.get("jsonrpc") != "2.0":
            return _error(req_id, -32600, "invalid request: jsonrpc must be '2.0'")

        if method == "initialize":
            return _success(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "jarvis-brain", "version": _SERVER_VERSION},
                },
            )

        if method == "tools/list":
            return _success(req_id, {"tools": TOOL_DEFINITIONS})

        if method == "tools/call":
            name = params.get("name")
            raw_args = params.get("arguments") or {}

            args_model = _TOOLS.get(name) if isinstance(name, str) else None
            if args_model is None or name not in executors:
                return _error(req_id, -32601, f"unknown tool: {name}")

            try:
                validated = args_model.model_validate(raw_args)
            except ValidationError as err:
                return _error(req_id, -32602, f"invalid params: {err}")

            start = time.perf_counter()
            try:
                result = await executors[name](validated.model_dump())
            except HTTPException as err:
                code = _HTTP_TO_RPC.get(err.status_code, -32603)
                return _error(req_id, code, str(err.detail))
            except Exception as err:
                logger.exception(
                    "mcp.tool.exec_failed", tool=name, error=str(err)
                )
                return _error(req_id, -32603, f"internal error: {err}")

            latency_ms = int((time.perf_counter() - start) * 1000)
            if sessionmaker is not None and info is not None:
                args_dict = validated.model_dump()
                scope = args_dict.get("scope")
                _spawn_audit_task(
                    log_query(
                        sessionmaker,
                        dev_token_name=info.name,
                        query_text=_describe_query(name, args_dict),
                        scope=scope if isinstance(scope, str) else None,
                        result_count=_result_count(result),
                        latency_ms=latency_ms,
                    )
                )

            return _success(req_id, _content_envelope(result))

        return _error(req_id, -32601, f"method not found: {method}")

    return router
