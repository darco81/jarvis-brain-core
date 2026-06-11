"""Compute the `ffcss` section of insights.json from a master graph.

Pure function - no I/O. Ported from the private jarvis-brain repo
(sanitized); production invokes it from the insights worker after the
master render and merges the result into the group insights.json.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _token_repo(node: dict[str, Any]) -> str | None:
    meta = node.get("metadata") or {}
    repo = meta.get("_repo")
    if isinstance(repo, str) and repo:
        return repo
    nid_raw = node.get("id", "")
    nid = nid_raw if isinstance(nid_raw, str) else ""
    # id is 'group/repo:original_id'; original_id may itself contain colons,
    # so forward-parse: repo is between the first '/' and the first ':'.
    if "/" in nid and ":" in nid:
        repo = nid.split("/", 1)[1].split(":", 1)[0]
        return repo or None
    return None


def build_ffcss_section(
    master: dict[str, Any],
    *,
    top_n: int = 20,
) -> dict[str, Any]:
    nodes = master.get("nodes", [])
    edges = master.get("edges", [])

    tokens = [
        n for n in nodes
        if isinstance(n, dict) and n.get("kind") == "ffcss_token"
    ]
    canonical = [
        n for n in tokens
        if (n.get("metadata") or {}).get("canonical") is True
    ]
    local = [
        n for n in tokens
        if (n.get("metadata") or {}).get("canonical") is False
    ]

    overrides_per_repo: dict[str, int] = defaultdict(int)
    for e in edges:
        if not isinstance(e, dict) or e.get("relation") != "overrides_token":
            continue
        src = e.get("source", "")
        if isinstance(src, str) and "/" in src and ":" in src:
            repo = src.split("/", 1)[1].split(":", 1)[0]
            overrides_per_repo[repo] += 1

    dry_by_token: dict[str, dict[str, Any]] = {}
    node_by_id = {n["id"]: n for n in tokens if "id" in n}
    for e in edges:
        if not isinstance(e, dict) or e.get("relation") != "duplicates_token":
            continue
        src_node = node_by_id.get(e.get("source"))
        tgt_node = node_by_id.get(e.get("target"))
        if src_node is None or tgt_node is None:
            continue
        name = src_node.get("name")
        if not isinstance(name, str):
            continue
        entry = dry_by_token.setdefault(
            name,
            {
                "token": name,
                "repos": [],
                "value": (src_node.get("metadata") or {}).get("value"),
            },
        )
        for n in (src_node, tgt_node):
            tok_repo = _token_repo(n)
            if tok_repo and tok_repo not in entry["repos"]:
                entry["repos"].append(tok_repo)

    canonical_ids = {n["id"] for n in canonical if "id" in n}
    uses_by_repo: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if not isinstance(e, dict) or e.get("relation") != "uses_token":
            continue
        target = e.get("target")
        if not isinstance(target, str) or target not in canonical_ids:
            continue
        src = e.get("source", "")
        if isinstance(src, str) and "/" in src and ":" in src:
            repo = src.split("/", 1)[1].split(":", 1)[0]
            uses_by_repo[repo].add(target)
    coverage_per_repo: dict[str, float] = {}
    total_canonical = len(canonical_ids)
    if total_canonical > 0:
        for repo, used in uses_by_repo.items():
            coverage_per_repo[repo] = round(len(used) / total_canonical, 4)

    usage_counter: Counter[str] = Counter()
    for e in edges:
        if not isinstance(e, dict) or e.get("relation") != "uses_token":
            continue
        tgt = node_by_id.get(e.get("target"))
        if tgt is None:
            continue
        name = tgt.get("name")
        if isinstance(name, str):
            usage_counter[name] += 1
    most_used = [
        {"token": name, "count": count}
        for name, count in usage_counter.most_common(top_n)
    ]

    return {
        "total_tokens_canonical": len(canonical),
        "total_tokens_local": len(local),
        "overrides_per_repo": dict(overrides_per_repo),
        "dry_violations": list(dry_by_token.values()),
        "coverage_per_repo": coverage_per_repo,
        "most_used_tokens": most_used,
    }
