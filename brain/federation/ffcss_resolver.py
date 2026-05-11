"""Cross-repo FFCSS token resolution.

Runs AFTER FederationMerger.merge_group has namespaced IDs. Mutates token
node metadata in-place (canonical flag), returns new edges to append to
the master graph, and returns the set of `uses_token` edges whose target
was rewritten to the canonical token id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FFCSSResolveResult:
    new_edges: list[dict[str, Any]] = field(default_factory=list)
    rewritten_edges: list[dict[str, Any]] = field(default_factory=list)


def _tokens_by_name(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if not isinstance(n, dict) or n.get("kind") != "ffcss_token":
            continue
        name = n.get("name")
        if isinstance(name, str):
            out[name] = n
    return out


def _canonical_id(group: str, core_repo: str, token_name: str) -> str:
    return f"{group}/{core_repo}:ffcss:{token_name}"


def resolve_ffcss(
    *,
    group: str,
    repo_graphs: list[tuple[str, dict[str, Any]]],
    repo_roles: dict[str, str],
    dry_detection: bool,
) -> FFCSSResolveResult:
    """Apply canonical flag, emit overrides/duplicates edges, rewrite uses_token.

    Only single-core groups are supported (matches imports_detector rule).
    """
    result = FFCSSResolveResult()
    core_repos = sorted(r for r, role in repo_roles.items() if role == "core")
    if len(core_repos) > 1:
        raise ValueError(
            f"Multiple core repos in group: {core_repos!r}. "
            "Multi-core FFCSS federation is not supported."
        )
    core_repo = core_repos[0] if core_repos else None

    per_repo_tokens: dict[str, dict[str, dict[str, Any]]] = {}
    for repo, g in repo_graphs:
        per_repo_tokens[repo] = _tokens_by_name(g.get("nodes", []))

    if core_repo is not None:
        for _name, node in per_repo_tokens.get(core_repo, {}).items():
            meta = node.setdefault("metadata", {})
            meta["canonical"] = True

    for repo, tokens in per_repo_tokens.items():
        if repo == core_repo:
            continue
        for name, node in tokens.items():
            meta = node.setdefault("metadata", {})
            meta["canonical"] = False
            if core_repo is not None and name in per_repo_tokens.get(core_repo, {}):
                result.new_edges.append(
                    {
                        "source": node["id"],
                        "target": _canonical_id(group, core_repo, name),
                        "relation": "overrides_token",
                        "confidence": "inferred",
                    }
                )

    if dry_detection:
        non_core = sorted(r for r in per_repo_tokens if r != core_repo)
        core_names = set(per_repo_tokens.get(core_repo, {})) if core_repo else set()
        per_name: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for repo in non_core:
            for name, node in per_repo_tokens[repo].items():
                if name in core_names:
                    continue
                per_name.setdefault(name, []).append((repo, node))
        for _name, entries in per_name.items():
            entries = sorted(entries, key=lambda x: x[0])
            for i, (_repo_i, node_i) in enumerate(entries):
                for _repo_j, node_j in entries[i + 1:]:
                    val_i = node_i.get("metadata", {}).get("value")
                    val_j = node_j.get("metadata", {}).get("value")
                    if val_i is not None and val_i == val_j:
                        result.new_edges.append(
                            {
                                "source": node_j["id"],
                                "target": node_i["id"],
                                "relation": "duplicates_token",
                                "confidence": "inferred",
                            }
                        )

    if core_repo is not None:
        core_names = set(per_repo_tokens.get(core_repo, {}))
        for repo, g in repo_graphs:
            if repo == core_repo:
                continue
            own = set(per_repo_tokens.get(repo, {}))
            for e in g.get("edges", []):
                if not isinstance(e, dict) or e.get("relation") != "uses_token":
                    continue
                target = e.get("target")
                if not isinstance(target, str):
                    continue
                if ":ffcss:" not in target:
                    continue
                token_name = target.rsplit(":ffcss:", 1)[1]
                if token_name in own:
                    continue
                if token_name in core_names:
                    e["target"] = _canonical_id(group, core_repo, token_name)
                    result.rewritten_edges.append(e)

    return result
