"""APIIndexPublisher tests - FTS5 build, camelCase label, repo fallback.

Ported from the private jarvis-brain test suite (sanitized: repo/group
names replaced with the example-group fixtures used across this repo).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from brain.publishers.api_index import APIIndexPublisher


def _sample_master() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "example-group/app-front-a:Checkout",
                "name": "Checkout",
                "file": "src/pages/Checkout.vue",
                "metadata": {"_repo": "app-front-a", "_group": "example-group"},
            },
            {
                "id": "example-group/app-core:Button",
                "name": "Button",
                "file": "src/Button.vue",
                "metadata": {"_repo": "app-core", "_group": "example-group"},
            },
        ],
        "edges": [
            {
                "source": "example-group/app-front-a:Checkout",
                "target": "example-group/app-core:Button",
                "relation": "imports_from_parent_repo",
            }
        ],
    }


def test_publisher_builds_fts5_index(tmp_path: Path) -> None:
    APIIndexPublisher().publish(_sample_master(), out_dir=tmp_path)
    db_path = tmp_path / "index.sqlite"
    assert db_path.exists()
    con = sqlite3.connect(db_path)
    rows = list(
        con.execute("SELECT node_id, label FROM nodes_fts WHERE nodes_fts MATCH 'checkout'")
    )
    con.close()
    assert any("Checkout" in label for _, label in rows)


def test_publisher_records_bidirectional_neighbors(tmp_path: Path) -> None:
    APIIndexPublisher().publish(_sample_master(), out_dir=tmp_path)
    con = sqlite3.connect(tmp_path / "index.sqlite")
    rows = con.execute(
        "SELECT node_id, neighbor_id FROM neighbors ORDER BY node_id"
    ).fetchall()
    con.close()
    assert ("example-group/app-core:Button", "example-group/app-front-a:Checkout") in rows
    assert ("example-group/app-front-a:Checkout", "example-group/app-core:Button") in rows


def test_publisher_skips_malformed_inputs(tmp_path: Path) -> None:
    master = {
        "nodes": [
            {"id": "A", "name": "NodeA", "metadata": {"_repo": "test"}},
            {"name": "skipped"},
            "not a dict",
        ],
        "edges": [
            {"source": "A"},
            "not a dict",
        ],
    }
    APIIndexPublisher().publish(master, out_dir=tmp_path)
    con = sqlite3.connect(tmp_path / "index.sqlite")
    count = con.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()[0]
    con.close()
    assert count == 1  # only NodeA indexed


def test_publish_populates_camelcase_label_and_repo(tmp_path: Path) -> None:
    master = {
        "nodes": [
            {
                "id": "example-group/app-core:useBaseUser",
                "name": "useBaseUser",
                "kind": "function",
                "file": "layers/app-core/composables/useBaseUser.ts",
                "metadata": {"_repo": "app-core", "_group": "example-group"},
            },
        ],
        "edges": [],
    }
    APIIndexPublisher().publish(master, tmp_path)

    con = sqlite3.connect(tmp_path / "index.sqlite")
    node_id, label, file, repo = con.execute(
        "SELECT node_id, label, file, repo FROM nodes_fts"
    ).fetchone()
    con.close()

    assert "useBaseUser" in label
    assert "use Base User" in label
    assert repo == "app-core"
    assert "useBaseUser.ts" in file


def test_publish_fts_match_on_camel_part(tmp_path: Path) -> None:
    master = {
        "nodes": [
            {
                "id": "example-group/app-core:useBaseUser",
                "name": "useBaseUser",
                "file": "composables/useBaseUser.ts",
                "metadata": {"_repo": "app-core"},
            }
        ],
        "edges": [],
    }
    APIIndexPublisher().publish(master, tmp_path)

    con = sqlite3.connect(tmp_path / "index.sqlite")
    rows = con.execute(
        "SELECT node_id FROM nodes_fts WHERE nodes_fts MATCH ?", ("Base",)
    ).fetchall()
    con.close()

    assert rows == [("example-group/app-core:useBaseUser",)]


def test_publish_uses_top_level_repo_fallback(tmp_path: Path) -> None:
    """Masters written by the v0.1.0 merger carried `_repo` top-level."""
    master = {
        "nodes": [
            {
                "id": "example-group/app-core:X",
                "name": "X",
                "_repo": "app-core",
                "metadata": {"framework": "vue"},
            }
        ],
        "edges": [],
    }
    APIIndexPublisher().publish(master, tmp_path)
    con = sqlite3.connect(tmp_path / "index.sqlite")
    rows = con.execute("SELECT node_id, repo FROM nodes_fts").fetchall()
    con.close()
    assert rows == [("example-group/app-core:X", "app-core")]
