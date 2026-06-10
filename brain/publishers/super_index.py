"""Build a union FTS5 index across all group master graphs.

Ported from the private jarvis-brain repo (sanitized). This is the missing
rung of the federation ladder: per-repo graphs -> group master -> super
index, the index `brain_query` scope="super" searches.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain.publishers.api_index import APIIndexPublisher


class SuperIndexPublisher:
    """Union all group master graphs into one cross-group FTS5 index."""

    def publish_from_masters(
        self, master_paths: list[Path], out_dir: Path
    ) -> None:
        """Load all master graphs, union nodes/edges, publish single FTS5 index.

        Args:
            master_paths: Paths to group master graph.json files.
            out_dir: Output directory for index.sqlite.
        """
        union_nodes: list[dict[str, Any]] = []
        union_edges: list[dict[str, Any]] = []

        for mp in master_paths:
            if not mp.exists():
                continue
            data = json.loads(mp.read_text(encoding="utf-8"))
            union_nodes.extend(data.get("nodes", []))
            union_edges.extend(data.get("edges", []))

        merged = {"nodes": union_nodes, "edges": union_edges}
        APIIndexPublisher().publish(merged, out_dir)
