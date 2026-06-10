"""Dev query endpoint: FTS5 over pre-computed index."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from brain.api._stubs import bearer_dependency
from brain.core.paths import DataPaths


def build_query_router(paths: DataPaths, dev_token: str) -> APIRouter:
    router = APIRouter()
    auth = bearer_dependency(dev_token)

    @router.get("/query", dependencies=[Depends(auth)])
    async def query_endpoint(
        q: str = Query(..., min_length=1, max_length=200),
        scope: str | None = Query(None),
        limit: int = Query(10, ge=1, le=100),
    ) -> dict[str, Any]:
        """Search the FTS5 index.

        The `q` parameter is interpreted as an FTS5 MATCH expression.
        Power-user operators are supported: `term1 OR term2`, `term*` (prefix),
        `"exact phrase"`, `NEAR(a, b)`. Invalid syntax returns 422.

        scope options:
        - None (default): fan-out across all group indexes
        - "super": cross-group merged index
        - "group": search group-wide index
        - "group/repo": search group index filtered by repo column
        """
        hits = _route_query(paths, q, scope, limit)
        return {"hits": hits}

    return router


def _route_query(
    paths: DataPaths, q: str, scope: str | None, limit: int
) -> list[dict[str, Any]]:
    """Route query to appropriate index (super, all groups, or specific group)."""
    if scope == "super":
        idx = paths.super_index() / "index.sqlite"
        if not idx.exists():
            raise HTTPException(
                status_code=404,
                detail="super index not built - publish it first (see super_index publisher)",
            )
        return _search(idx, q, limit, repo_filter=None)

    if scope is None:
        # Fan-out: search every group index we can find, then fuse the
        # per-group rankings with reciprocal rank fusion (k=60). Plain
        # concatenation would let directory order beat relevance.
        groups_root = paths.root / "vaults"
        ranked_lists: list[list[dict[str, Any]]] = []
        if groups_root.exists():
            for group_dir in sorted(groups_root.iterdir()):
                if group_dir.name.startswith("_"):
                    continue
                idx = group_dir / "index" / "index.sqlite"
                if idx.exists():
                    try:
                        ranked_lists.append(_search(idx, q, limit, repo_filter=None))
                    except sqlite3.OperationalError:
                        continue  # skip corrupt index
        return _rrf_fuse(ranked_lists, limit)

    # scope = "group" or "group/repo"
    parts = scope.split("/", 1)
    group = parts[0]
    repo = parts[1] if len(parts) > 1 else None
    idx = paths.vault_index(group) / "index.sqlite"
    if not idx.exists():
        raise HTTPException(status_code=404, detail=f"Index missing for {group}")
    return _search(idx, q, limit, repo_filter=repo)


def _rrf_fuse(
    ranked_lists: list[list[dict[str, Any]]], limit: int
) -> list[dict[str, Any]]:
    """Fuse independently-ranked hit lists via reciprocal rank fusion.

    score(hit) = sum over lists of 1 / (k + rank), k=60 (the standard
    constant from the original RRF paper). Node ids are namespaced per
    group, so this interleaves rather than deduplicates. Equal RRF scores
    (e.g. every list's rank-0) are tie-broken by the raw bm25 score the
    hits carry - lower bm25 is more relevant in SQLite.
    """
    k = 60
    scored: dict[str, tuple[float, dict[str, Any]]] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits):
            node_id = hit["node_id"]
            score = 1.0 / (k + rank)
            prev = scored.get(node_id)
            scored[node_id] = (score + (prev[0] if prev else 0.0), hit)
    fused = sorted(
        scored.values(),
        key=lambda sv: (-sv[0], sv[1].get("score", 0.0)),
    )
    return [hit for _score, hit in fused[:limit]]


# bm25() column weights, in nodes_fts declaration order
# (node_id, label, file, repo): an identifier-name match should beat a
# file-path match, which should beat incidental id/repo matches.
_BM25_WEIGHTS = "0.5, 10.0, 3.0, 0.5"


def _search(
    db_path: Path, q: str, limit: int, repo_filter: str | None
) -> list[dict[str, Any]]:
    """Search FTS5 index, BM25-ranked with label-heavy column weights."""
    con = sqlite3.connect(db_path)
    try:
        # q is passed raw: it IS the FTS5 MATCH expression (the docstring
        # advertises "exact phrase" / OR / NEAR). Doubling quotes here would
        # silently turn phrase queries into bag-of-words matches; invalid
        # syntax is already surfaced as 422 below.
        try:
            if repo_filter:
                rows = con.execute(
                    "SELECT node_id, label, file, repo, "
                    f"bm25(nodes_fts, {_BM25_WEIGHTS}) AS score FROM nodes_fts "
                    "WHERE nodes_fts MATCH ? AND repo = ? "
                    "ORDER BY score LIMIT ?",
                    (q, repo_filter, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT node_id, label, file, repo, "
                    f"bm25(nodes_fts, {_BM25_WEIGHTS}) AS score FROM nodes_fts "
                    "WHERE nodes_fts MATCH ? "
                    "ORDER BY score LIMIT ?",
                    (q, limit),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid query syntax: {exc}",
            ) from exc
        hits: list[dict[str, Any]] = []
        for node_id, label, file, repo, score in rows:
            meta_row = con.execute(
                "SELECT json FROM node_meta WHERE node_id=?", (node_id,)
            ).fetchone()
            meta = json.loads(meta_row[0]) if meta_row else {}
            neighbors = [
                {"id": nid, "relation": rel}
                for nid, rel in con.execute(
                    "SELECT neighbor_id, relation FROM neighbors WHERE node_id=? LIMIT 20",
                    (node_id,),
                ).fetchall()
            ]
            hits.append({
                "node_id": node_id,
                "label": label,
                "file": file,
                "repo": repo,
                "score": score,
                "meta": meta,
                "neighbors": neighbors,
            })
        return hits
    finally:
        con.close()
