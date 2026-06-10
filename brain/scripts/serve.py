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
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        if repo:
            nodes = [n for n in nodes if _repo_of(n) == repo]
            kept = {n["id"] for n in nodes if "id" in n}
            edges = [
                e for e in edges
                if e.get("source") in kept and e.get("target") in kept
            ]
        return {"group": group, "repo": repo, "nodes": nodes, "edges": edges}

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
