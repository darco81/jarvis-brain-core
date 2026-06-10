"""Ranking tests: BM25 ordering with column weights + RRF fan-out fusion.

v0.1.0 returned FTS5 hits in insertion order (no ORDER BY) and merged
fan-out results by truncation - first group wins regardless of relevance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from brain.api.query import _route_query, _search
from brain.core.paths import DataPaths
from brain.publishers.api_index import APIIndexPublisher


def _publish(tmp_path: Path, group: str, nodes: list[dict[str, Any]]) -> Path:
    master = {"nodes": nodes, "edges": []}
    index_dir = tmp_path / "vaults" / group / "index"
    APIIndexPublisher().publish(master, index_dir)
    return index_dir / "index.sqlite"


def _node(group: str, repo: str, name: str, file: str = "") -> dict[str, Any]:
    return {
        "id": f"{group}/{repo}:{name}",
        "name": name,
        "file": file or f"src/{name}.ts",
        "metadata": {"_repo": repo},
    }


def test_label_match_outranks_file_only_match(tmp_path: Path) -> None:
    """A hit in the label column must rank above a hit only in the file path."""
    db = _publish(
        tmp_path,
        "g",
        [
            # 'cart' appears only in the file path
            _node("g", "r", "useCheckout", file="src/cart/useCheckout.ts"),
            # 'cart' appears in the (camelCase-split) label
            _node("g", "r", "useCart"),
        ],
    )
    hits = _search(db, "cart", limit=10, repo_filter=None)
    assert hits[0]["node_id"] == "g/r:useCart"


def test_search_results_are_rank_ordered_not_insertion_ordered(tmp_path: Path) -> None:
    """More query-term occurrences in the label => earlier in the results."""
    db = _publish(
        tmp_path,
        "g",
        [
            # Inserted first, weaker match (one 'session' occurrence)
            _node("g", "r", "sessionUtils"),
            # Inserted second, stronger match ('session' twice in split label)
            _node("g", "r", "useSessionSession"),
        ],
    )
    hits = _search(db, "session", limit=10, repo_filter=None)
    assert hits[0]["node_id"] == "g/r:useSessionSession"


def test_fanout_interleaves_groups_by_rank(tmp_path: Path) -> None:
    """scope=None fan-out must fuse per-group rankings (RRF), not truncate
    group-by-group in directory order."""
    # Group 'aaa' sorts first; fill it with weak file-path-only matches.
    _publish(
        tmp_path,
        "aaa",
        [
            _node("aaa", "r", f"helper{i}", file=f"src/cart/helper{i}.ts")
            for i in range(3)
        ],
    )
    # Group 'zzz' sorts last but holds the best (label) match.
    _publish(tmp_path, "zzz", [_node("zzz", "r", "useCart")])

    paths = DataPaths(root=tmp_path)
    hits = _route_query(paths, "cart", scope=None, limit=3)

    ids = [h["node_id"] for h in hits]
    assert "zzz/r:useCart" in ids, "best cross-group match must survive the limit"
    assert ids[0] == "zzz/r:useCart", "best cross-group match must rank first"


def test_fanout_respects_limit(tmp_path: Path) -> None:
    _publish(tmp_path, "a", [_node("a", "r", f"useCart{i}") for i in range(5)])
    _publish(tmp_path, "b", [_node("b", "r", f"useCart{i}") for i in range(5)])
    paths = DataPaths(root=tmp_path)
    hits = _route_query(paths, "cart", scope=None, limit=4)
    assert len(hits) == 4


def test_quoted_phrase_query_keeps_phrase_semantics(tmp_path: Path) -> None:
    """'"exact phrase"' must match the phrase, not the reversed bag of words.

    v0.1.0 doubled quotes before MATCH, silently degrading the documented
    phrase syntax into an AND of terms.
    """
    db = _publish(
        tmp_path,
        "g",
        [
            _node("g", "r", "exactPhrase"),     # label: 'exactPhrase exact Phrase'
            _node("g", "r", "phraseExact"),     # reversed order
        ],
    )
    hits = _search(db, '"exact phrase"', limit=10, repo_filter=None)
    assert [h["node_id"] for h in hits] == ["g/r:exactPhrase"]
