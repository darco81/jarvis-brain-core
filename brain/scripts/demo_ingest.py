"""Demo flow: write a synthetic master graph, build the FTS5 index, query it.

Run from the repo root:
    python -m brain.scripts.demo_ingest

Pass --data-root to persist the graph + index where `brain.scripts.serve`
can pick them up (default: a throwaway tmp dir):
    python -m brain.scripts.demo_ingest --data-root ~/.jarvis-brain-demo

What it does, in order:
    1. Writes `example-group/_master/graph.json` with a handful of synthetic
       nodes and edges under a tmp data root (the path is printed).
    2. Calls `APIIndexPublisher` to build the FTS5 SQLite index from that graph.
    3. Runs three illustrative queries against the index, demonstrating the
       camelCase preprocessing trick (search `user` -> hits `useUserSession`).
    4. Walks a shortest path through the graph with networkx (same logic
       brain_path uses).

The goal is to give a reader a runnable example without needing a real codebase
indexed. The synthetic graph follows the exact same schema as the federated
master graph that the production deployment serves.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import networkx as nx

from brain.publishers.api_index import APIIndexPublisher

GROUP = "example-group"
CORE = "app-core"
FRONT_A = "app-front-a"


def _build_synthetic_graph() -> dict[str, Any]:
    """Return a small master graph with cross-repo imports + design tokens."""

    def _node(
        repo: str,
        name: str,
        kind: str = "function",
        file: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": f"{GROUP}/{repo}:{name}",
            "kind": kind,
            "name": name,
            "file": file or f"layers/{repo}/{name.lower()}.ts",
            "line": 1,
            "metadata": {"_repo": repo},
        }

    def _edge(
        src_repo: str,
        src_name: str,
        tgt_repo: str,
        tgt_name: str,
        relation: str,
    ) -> dict[str, Any]:
        return {
            "source": f"{GROUP}/{src_repo}:{src_name}",
            "target": f"{GROUP}/{tgt_repo}:{tgt_name}",
            "relation": relation,
            "confidence": "extracted",
        }

    front_login_vue = f"layers/{FRONT_A}/components/LoginButton.vue"
    front_checkout_vue = f"layers/{FRONT_A}/pages/CheckoutPage.vue"
    nodes = [
        _node(CORE, "useUserSession", "function"),
        _node(CORE, "useCurrentUser", "function"),
        _node(CORE, "useCheckoutFlow", "function"),
        _node(FRONT_A, "LoginButton", "component", file=front_login_vue),
        _node(FRONT_A, "CheckoutPage", "component", file=front_checkout_vue),
    ]
    imports = "imports_from_parent_repo"
    edges = [
        _edge(FRONT_A, "LoginButton", CORE, "useUserSession", imports),
        _edge(FRONT_A, "LoginButton", CORE, "useCurrentUser", imports),
        _edge(FRONT_A, "CheckoutPage", CORE, "useCheckoutFlow", imports),
        _edge(FRONT_A, "CheckoutPage", FRONT_A, "LoginButton", "renders"),
    ]
    return {
        "schema_version": "v1",
        "group": GROUP,
        "repo": "_master",
        "built_by": "demo_ingest",
        "built_at": "2026-05-12T00:00:00Z",
        "nodes": nodes,
        "edges": edges,
    }


def _run_query(db_path: Path, q: str, limit: int = 5) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            "SELECT node_id, label, file, repo FROM nodes_fts WHERE nodes_fts MATCH ? LIMIT ?",
            (q, limit),
        ).fetchall()
    finally:
        con.close()


def _shortest_path(graph: dict[str, Any], from_node: str, to_node: str) -> list[str]:
    g: nx.DiGraph = nx.DiGraph()
    for n in graph["nodes"]:
        g.add_node(n["id"])
    for e in graph["edges"]:
        g.add_edge(e["source"], e["target"], relation=e["relation"])
    return list(nx.shortest_path(g, from_node, to_node))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brain.scripts.demo_ingest",
        description="Build a synthetic master graph + FTS5 index and query it.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Persist graph + index here (default: throwaway tmp dir). "
        "Use the same path with brain.scripts.serve.",
    )
    args = parser.parse_args(argv)

    root = args.data_root or Path(tempfile.mkdtemp(prefix="jarvis-brain-demo-"))
    root.mkdir(parents=True, exist_ok=True)
    print(f"[demo] data root: {root}")

    # 1. write the master graph
    graph = _build_synthetic_graph()
    master_path = root / "graphs" / GROUP / "_master" / "graph.json"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text(json.dumps(graph, indent=2))
    print(
        f"[demo] wrote master graph: {master_path} "
        f"({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)"
    )

    # 2. build the FTS5 index
    index_dir = root / "vaults" / GROUP / "index"
    APIIndexPublisher().publish(graph, index_dir)
    db_path = index_dir / "index.sqlite"
    print(f"[demo] built FTS5 index: {db_path}")

    # 3. run queries - the third one demonstrates camelCase preprocessing
    print("\n[demo] queries:")
    for q in ["LoginButton", "checkout", "user"]:
        hits = _run_query(db_path, q)
        print(f"  q={q!r:20} -> {len(hits)} hit(s):")
        for node_id, _label, file, _repo in hits:
            print(f"    {node_id}  ({file})")

    # 4. shortest path from a front to a core composable
    from_node = f"{GROUP}/{FRONT_A}:CheckoutPage"
    to_node = f"{GROUP}/{CORE}:useUserSession"
    print(f"\n[demo] shortest path:\n  from: {from_node}\n  to:   {to_node}")
    try:
        path = _shortest_path(graph, from_node, to_node)
        print(f"  path: {' -> '.join(path)}  ({len(path) - 1} hops)")
    except nx.NetworkXNoPath:
        print("  no path")

    print("\n[demo] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
