"""Runnable MCP server - wires all 5 brain tools over HTTP JSON-RPC.

The educational counterpart of the production app.py: same router, same
executors, auth stubbed out (see brain/api/_stubs.py). Bind to localhost
only - this server has no real authentication and must never be exposed
publicly.

Quick start (3 commands, no real codebase needed):

    python -m brain.scripts.demo_ingest --data-root ~/.jarvis-brain-demo
    python -m brain.scripts.serve --data-root ~/.jarvis-brain-demo
    claude mcp add --transport http brain http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from brain.api._stubs import DevTokenInfo
from brain.api.executors import _build_explain_executor, _build_ffcss_executor
from brain.api.mcp import build_mcp_router
from brain.api.query import _route_query
from brain.api.query_path import shortest_path_payload
from brain.core.paths import DataPaths


def _repo_of(n: dict[str, Any]) -> str | None:
    m = n.get("metadata") or {}
    r = m.get("_repo")
    if not isinstance(r, str):
        r = n.get("_repo")
    return r if isinstance(r, str) else None


# Hard cap on ego-graph size - a raw master graph is a context bomb for an
# agent; past this many nodes the caller should narrow the radius instead.
_EGO_MAX_NODES = 200


def _graph_summary(
    group: str,
    repo: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_repo: dict[str, int] = {}
    for n in nodes:
        kind = str(n.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        r = _repo_of(n) or "unknown"
        by_repo[r] = by_repo.get(r, 0) + 1
    return {
        "group": group,
        "repo": repo,
        "summary": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "nodes_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
            "nodes_by_repo": dict(sorted(by_repo.items(), key=lambda kv: -kv[1])),
        },
        "hint": (
            "Pass node_id (e.g. from brain_query) to get the ego-graph "
            "around a specific node."
        ),
    }


def _ego_graph(
    *,
    group: str,
    repo: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    center: str,
    radius: int,
    detailed: bool,
) -> dict[str, Any]:
    by_id = {n["id"]: n for n in nodes}
    if center not in by_id:
        raise HTTPException(
            status_code=404,
            detail=f"brain_graph: node not found: {center}",
        )
    # Undirected BFS over edge endpoints
    adjacency: dict[str, set[str]] = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if isinstance(s, str) and isinstance(t, str):
            adjacency.setdefault(s, set()).add(t)
            adjacency.setdefault(t, set()).add(s)
    visited = {center}
    frontier = {center}
    for _hop in range(radius):
        frontier = {
            nb
            for node in frontier
            for nb in adjacency.get(node, set())
            if nb in by_id
        } - visited
        if not frontier:
            break
        visited |= frontier

    truncated = len(visited) > _EGO_MAX_NODES
    if truncated:
        # Keep the center unconditionally - a deterministic slice of the
        # neighborhood must never evict the node the caller asked about.
        kept_ids = {center} | set(
            sorted(visited - {center})[: _EGO_MAX_NODES - 1]
        )
    else:
        kept_ids = visited

    def _shape(n: dict[str, Any]) -> dict[str, Any]:
        if detailed:
            return {
                "id": n["id"],
                "name": n.get("name"),
                "kind": n.get("kind"),
                "file": n.get("file"),
                "line": n.get("line"),
                "metadata": n.get("metadata", {}),
            }
        return {"id": n["id"], "name": n.get("name"), "kind": n.get("kind")}

    out_nodes = [_shape(by_id[i]) for i in sorted(kept_ids)]
    out_edges = [
        e for e in edges
        if e.get("source") in kept_ids and e.get("target") in kept_ids
    ]
    result: dict[str, Any] = {
        "group": group,
        "repo": repo,
        "center": center,
        "radius": radius,
        "nodes": out_nodes,
        "edges": out_edges,
    }
    if truncated:
        result["truncated"] = True
        result["hint"] = (
            f"Ego-graph exceeded {_EGO_MAX_NODES} nodes and was cut. "
            "Lower `radius` or filter with `repo` to narrow it."
        )
    return result


def build_app(data_root: Path) -> FastAPI:
    """FastAPI app exposing /mcp with all 5 brain tools wired to data_root."""
    paths = DataPaths(root=data_root)
    graphs_base = data_root / "graphs"

    async def query_executor(args: dict[str, Any]) -> dict[str, Any]:
        hits = _route_query(paths, args["q"], args.get("scope"), args.get("limit", 10))
        return {"hits": hits}

    async def graph_executor(args: dict[str, Any]) -> dict[str, Any]:
        group = args["group"]
        master_path = paths.group_master_graph(group)
        if not master_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"brain_graph: no master graph for group {group}",
            )
        data = json.loads(master_path.read_text())
        repo = args.get("repo")
        nodes = [n for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n]
        edges = data.get("edges", [])
        if repo:
            nodes = [n for n in nodes if _repo_of(n) == repo]
            kept = {n["id"] for n in nodes}
            edges = [
                e for e in edges
                if e.get("source") in kept and e.get("target") in kept
            ]
        node_id = args.get("node_id")
        if node_id is None:
            return _graph_summary(group, repo, nodes, edges)
        return _ego_graph(
            group=group,
            repo=repo,
            nodes=nodes,
            edges=edges,
            center=node_id,
            radius=args.get("radius", 2),
            detailed=args.get("response_format", "concise") == "detailed",
        )

    async def path_executor(args: dict[str, Any]) -> dict[str, Any]:
        return shortest_path_payload(
            graphs_base,
            args["from_node"],
            args["to_node"],
            args.get("max_hops", 6),
        )

    app = FastAPI(title="jarvis-brain-core")
    app.include_router(
        build_mcp_router(
            query_executor=query_executor,
            graph_executor=graph_executor,
            path_executor=path_executor,
            explain_executor=_build_explain_executor(paths),
            ffcss_executor=_build_ffcss_executor(paths),
            auth_override=lambda: DevTokenInfo(),
        )
    )
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brain.scripts.serve",
        description="Serve the 5 brain MCP tools over HTTP JSON-RPC.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("BRAIN_DATA_ROOT", "data")),
        help="Directory with graphs/ and vaults/ (default: $BRAIN_DATA_ROOT or ./data)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (keep it local)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if not (args.data_root / "graphs").exists():
        print(
            f"[serve] no graphs/ under {args.data_root} - run "
            "`python -m brain.scripts.demo_ingest --data-root "
            f"{args.data_root}` first",
            file=sys.stderr,
        )
        return 1

    try:
        import uvicorn
    except ImportError:
        print(
            "[serve] uvicorn not installed - run `uv pip install -e \".[server]\"`",
            file=sys.stderr,
        )
        return 1

    print(f"[serve] data root: {args.data_root}")
    print(f"[serve] MCP endpoint: http://{args.host}:{args.port}/mcp")
    print(
        "[serve] connect Claude Code: claude mcp add --transport http "
        f"brain http://{args.host}:{args.port}/mcp"
    )
    uvicorn.run(build_app(args.data_root), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
