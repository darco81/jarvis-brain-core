"""MCP tool executors - the logic behind brain_explain and brain_ffcss.

These functions read a federated master graph (`graphs/<group>/_master/graph.json`)
and produce the response payload that the MCP dispatch in `brain/api/mcp.py`
wraps as a `content` envelope. They are pure: no DB, no network, no auth.

The other three MCP tools (`brain_query`, `brain_graph`, `brain_path`) are
exposed as HTTP routers in `brain/api/query.py` and `brain/api/query_path.py`;
their executor wrappers live in the production app.py (out of scope here)
and are 5-line shims around the routers.

Why split this out: extraction logic against the graph is the educational
core. The router wiring + executor adapter layer that ties this into a
running FastAPI app is part of the production deployment story.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from brain.core.paths import DataPaths


def _build_explain_executor(
    paths: DataPaths,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Build the executor for brain_explain.

    Returns a coroutine that takes a {"node_id": "..."} payload and emits a
    structured explanation: metadata (kind, file, line, community), provenance
    (commit sha/date/author from metadata.last_commit), and 1-hop neighbors
    in both directions. No LLM call.
    """

    async def _exec(args: dict[str, Any]) -> dict[str, Any]:
        node_id = args["node_id"]
        if "/" not in node_id:
            raise HTTPException(
                status_code=404,
                detail="brain_explain: node_id missing group prefix",
            )
        group = node_id.split("/", 1)[0]
        master_path = paths.group_master_graph(group)
        if not master_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"brain_explain: no master graph for group {group}",
            )
        data = json.loads(master_path.read_text())
        nodes_by_id = {n["id"]: n for n in data.get("nodes", [])}
        if node_id not in nodes_by_id:
            raise HTTPException(
                status_code=404,
                detail=f"brain_explain: node not found: {node_id}",
            )
        n = nodes_by_id[node_id]
        out: list[dict[str, Any]] = []
        inn: list[dict[str, Any]] = []
        for e in data.get("edges", []):
            # Edges are guaranteed source+target by the merger, but relation
            # is optional - read defensively so a relation-less edge yields a
            # blank relation instead of a -32603 KeyError.
            src = e.get("source")
            tgt = e.get("target")
            rel = e.get("relation", "")
            conf = e.get("confidence", "")
            if src == node_id:
                out.append({"id": tgt, "relation": rel, "confidence": conf})
            elif tgt == node_id:
                inn.append({"id": src, "relation": rel, "confidence": conf})
        last_commit = n.get("metadata", {}).get("last_commit")
        provenance = None
        if isinstance(last_commit, dict):
            provenance = {
                "sha": last_commit.get("sha"),
                "date": last_commit.get("date"),
                "author": last_commit.get("author"),
            }
        return {
            "node_id": node_id,
            "name": n.get("name"),
            "kind": n.get("kind"),
            "file": n.get("file"),
            "line": n.get("line"),
            "community": n.get("metadata", {}).get("community"),
            "provenance": provenance,
            "neighbors_out": out[:50],
            "neighbors_in": inn[:50],
            "truncated": len(out) > 50 or len(inn) > 50,
        }

    return _exec


def _build_ffcss_executor(
    paths: DataPaths,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """Build the executor for brain_ffcss.

    Three modes against the federated master graph:
      - tokens: every node of kind "ffcss_token", optionally filtered to repo.
      - usage: per-token usage counts (sum of uses_token edges).
      - violations: tokens with duplicates_token edges (DRY violations).
    """

    async def _exec(args: dict[str, Any]) -> dict[str, Any]:
        group = args["group"]
        repo = args.get("repo")
        mode = args.get("mode", "tokens")
        master_path = paths.group_master_graph(group)
        if not master_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"brain_ffcss: no master graph for group {group}",
            )
        data = json.loads(master_path.read_text())
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        def _repo_of(n: dict[str, Any]) -> str | None:
            # Prefer metadata._repo; masters written by the v0.1.0 merger
            # carried _repo top-level on nodes.
            m = n.get("metadata") or {}
            r = m.get("_repo")
            if not isinstance(r, str):
                r = n.get("_repo")
            return r if isinstance(r, str) else None

        if mode == "tokens":
            out: list[dict[str, Any]] = []
            for n in nodes:
                if n.get("kind") != "ffcss_token":
                    continue
                r = _repo_of(n)
                if repo and r != repo:
                    continue
                m = n.get("metadata") or {}
                out.append({
                    "id": n["id"],
                    "name": n.get("name"),
                    "canonical": m.get("canonical", False),
                    "value": m.get("value"),
                    "repo": r,
                    "token_type": m.get("token_type"),
                })
            return {"mode": "tokens", "tokens": out}

        if mode == "usage":
            node_by_id = {n["id"]: n for n in nodes if "id" in n}
            counter: dict[str, int] = {}
            for e in edges:
                if e.get("relation") != "uses_token":
                    continue
                src = e.get("source", "")
                if repo:
                    if not (isinstance(src, str) and "/" in src and ":" in src):
                        continue
                    src_repo = src.split("/", 1)[1].split(":", 1)[0]
                    if src_repo != repo:
                        continue
                tgt = node_by_id.get(e.get("target"))
                if tgt is None:
                    continue
                name = tgt.get("name")
                if isinstance(name, str):
                    counter[name] = counter.get(name, 0) + 1
            usage_list: list[dict[str, Any]] = [
                {"token": k, "count": v} for k, v in counter.items()
            ]
            usage = sorted(usage_list, key=lambda r: (-r["count"], r["token"]))
            return {"mode": "usage", "repo": repo, "usage": usage}

        if mode == "violations":
            node_by_id = {n["id"]: n for n in nodes if "id" in n}
            by_token: dict[str, dict[str, Any]] = {}
            for e in edges:
                if e.get("relation") != "duplicates_token":
                    continue
                src = node_by_id.get(e.get("source"))
                tgt = node_by_id.get(e.get("target"))
                if src is None or tgt is None:
                    continue
                name = src.get("name")
                if not isinstance(name, str):
                    continue
                entry = by_token.setdefault(
                    name,
                    {
                        "token": name,
                        "repos": [],
                        "value": (src.get("metadata") or {}).get("value"),
                    },
                )
                for n in (src, tgt):
                    r = _repo_of(n)
                    if r and r not in entry["repos"]:
                        entry["repos"].append(r)
            out_v = list(by_token.values())
            if repo:
                out_v = [v for v in out_v if repo in v["repos"]]
            return {"mode": "violations", "violations": out_v}

        raise HTTPException(status_code=422, detail=f"unknown mode: {mode}")

    return _exec
