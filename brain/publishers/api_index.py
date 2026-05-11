"""Build SQLite FTS5 index for fast /query lookup."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from brain.utils.camelcase import split_camel


class APIIndexPublisher:
    def publish(self, master: dict[str, Any], out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        db_path = out_dir / "index.sqlite"
        if db_path.exists():
            db_path.unlink()
        con = sqlite3.connect(db_path)
        try:
            con.executescript(
                """
                CREATE VIRTUAL TABLE nodes_fts USING fts5(node_id, label, file, repo);
                CREATE TABLE node_meta(node_id TEXT PRIMARY KEY, json TEXT);
                CREATE TABLE neighbors(node_id TEXT, neighbor_id TEXT, relation TEXT);
                CREATE INDEX idx_neighbors_nid ON neighbors(node_id);
                """
            )

            # Guard: skip nodes missing required 'id' field
            raw_nodes = master.get("nodes", [])
            nodes = [n for n in raw_nodes if isinstance(n, dict) and "id" in n]
            by_id = {n["id"]: n for n in nodes}

            for n in nodes:
                name = str(n.get("name", ""))
                label = f"{name} {split_camel(name)}".strip() if name else ""
                # Federation master graphs expose `_repo` top-level; per-repo
                # extraction emits it under `metadata`. Prefer metadata, fall
                # back to top-level.
                metadata = n.get("metadata", {})
                meta_repo = (
                    metadata.get("_repo")
                    if isinstance(metadata, dict)
                    else None
                )
                repo = str(meta_repo or n.get("_repo") or "")
                con.execute(
                    "INSERT INTO nodes_fts(node_id,label,file,repo) VALUES(?,?,?,?)",
                    (n["id"], label, n.get("file", ""), repo),
                )
                con.execute(
                    "INSERT INTO node_meta(node_id,json) VALUES(?,?)",
                    (n["id"], json.dumps(n)),
                )

            for e in master.get("edges", []):
                # Guard: skip edges missing source/target or referencing unknown nodes
                if not isinstance(e, dict):
                    continue
                src = e.get("source")
                tgt = e.get("target")
                if not src or not tgt:
                    continue
                if src in by_id and tgt in by_id:
                    con.execute(
                        "INSERT INTO neighbors(node_id,neighbor_id,relation) VALUES(?,?,?)",
                        (src, tgt, e.get("relation", "related")),
                    )
                    con.execute(
                        "INSERT INTO neighbors(node_id,neighbor_id,relation) VALUES(?,?,?)",
                        (tgt, src, e.get("relation", "related")),
                    )

            con.commit()
        finally:
            con.close()
