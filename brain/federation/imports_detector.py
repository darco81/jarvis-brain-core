"""Deterministic cross-repo import detection.

For every edge in a frontend/admin repo whose target id is not present in the
repo's own nodes but IS present in the core repo of the same group, emit a
cross-repo edge `imports_from_parent_repo`. Pure set membership + role inspection.
"""
from __future__ import annotations

from typing import Any


def detect_cross_repo_imports(
    repo_graphs: list[tuple[str, dict[str, Any]]],
    repo_roles: dict[str, str],
) -> list[dict[str, Any]]:
    node_index: dict[str, set[str]] = {
        repo: {n["id"] for n in g.get("nodes", []) if isinstance(n, dict) and "id" in n}
        for repo, g in repo_graphs
    }
    core_repos = [r for r, role in repo_roles.items() if role == "core"]
    if not core_repos:
        return []
    if len(core_repos) > 1:
        raise ValueError(
            f"Multiple core repos in group: {core_repos!r}. "
            "Multi-core federation is not supported until P3."
        )
    core = core_repos[0]
    core_nodes = node_index.get(core, set())
    out: list[dict[str, Any]] = []
    for repo, g in repo_graphs:
        if repo == core:
            continue
        own = node_index.get(repo, set())
        for e in g.get("edges", []):
            if not isinstance(e, dict):
                continue
            target = e.get("target")
            source = e.get("source")
            if (
                target
                and isinstance(target, str)
                and isinstance(source, str)
                and target not in own
                and target in core_nodes
                and source in own
            ):
                out.append(
                    {
                        "source": source,
                        "target": target,
                        "source_repo": repo,
                        "target_repo": core,
                        "relation": "imports_from_parent_repo",
                        "confidence": "extracted",
                    }
                )
    return out
