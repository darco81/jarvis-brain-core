"""GET /query/path - shortest path between two nodes on the merged master graph.

Master graph loaded lazily per group, cached by (path, mtime_ns).
Networkx DiGraph - directed edges as written in graph.json.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

# Production wiring uses SQLAlchemy AsyncSession; the educational version
# stubs auth/audit out, so sqlalchemy is gated behind TYPE_CHECKING and is
# not a runtime dependency. Restore as a real dependency to wire prod auth.
from typing import TYPE_CHECKING, Any

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Query

from brain.api._stubs import DevTokenInfo, RateLimiter, TokenVerifier
from brain.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
else:
    AsyncSession = Any

    class async_sessionmaker:  # noqa: N801  (matches sqlalchemy public name)
        def __class_getitem__(cls, _item: Any) -> Any:
            return Any

logger = get_logger("api.query_path")


def _master_graph_path(graphs_base: Path, group: str) -> Path:
    return graphs_base / group / "_master" / "graph.json"


@lru_cache(maxsize=4)
def _load_master_graph_cached(
    graph_path_str: str, mtime_ns: int
) -> nx.DiGraph:
    """Load a master graph from disk. Cache key = (path, mtime_ns)."""
    # mtime_ns is only part of the cache key; the value is read from disk below.
    del mtime_ns
    path = Path(graph_path_str)
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    g: nx.DiGraph = nx.DiGraph()
    for n in data.get("nodes", []):
        attrs = {k: v for k, v in n.items() if k != "id"}
        g.add_node(n["id"], **attrs)
    for e in data.get("edges", []):
        g.add_edge(e["source"], e["target"], relation=e.get("relation"))
    return g


def _load_master_graph(graphs_base: Path, group: str) -> nx.DiGraph:
    path = _master_graph_path(graphs_base, group)
    if not path.exists():
        raise HTTPException(404, f"no master graph for group '{group}'")
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError as err:
        raise HTTPException(500, f"cannot stat master graph: {err}") from err
    return _load_master_graph_cached(str(path), mtime_ns)


def shortest_path_payload(
    graphs_base: Path, from_node: str, to_node: str, max_hops: int = 6
) -> dict[str, Any]:
    """Shortest path between two fully-qualified nodes on the master graph.

    Shared by the GET /query/path endpoint and the brain_path MCP executor.
    Raises HTTPException (422/404) on bad input, missing nodes, or no path.
    """
    if "/" not in from_node:
        raise HTTPException(
            422,
            "from_node must be fully qualified (<group>/<repo>:<id>): "
            f"{from_node}",
        )
    group = from_node.split("/", 1)[0]
    g = _load_master_graph(graphs_base, group)

    try:
        path = nx.shortest_path(g, from_node, to_node)
    except nx.NodeNotFound as err:
        raise HTTPException(404, f"node not found: {err}") from err
    except nx.NetworkXNoPath as err:
        raise HTTPException(404, "no path between nodes") from err

    hops = len(path) - 1
    if hops > max_hops:
        raise HTTPException(404, f"path exceeds max_hops={max_hops}")

    return {"path": list(path), "hops": hops}


def build_query_path_router(
    *,
    graphs_base: Path,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    rate_limiter: RateLimiter | None = None,
    auth_override: Callable[..., DevTokenInfo | None] | None = None,
) -> APIRouter:
    """Build /query/path router.

    Either `sessionmaker` (production) or `auth_override` (tests) must be set.
    """
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

    @router.get("/query/path")
    async def query_path(
        from_node: str = Query(..., min_length=1, max_length=256),
        to_node: str = Query(..., min_length=1, max_length=256),
        max_hops: int = Query(6, ge=1, le=10),
        _auth: DevTokenInfo | None = Depends(auth_dep),
    ) -> dict[str, Any]:
        return shortest_path_payload(graphs_base, from_node, to_node, max_hops)

    return router
