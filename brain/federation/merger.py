"""Federation merger - P1: namespace union + optional cross-repo imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from brain.federation.ffcss_resolver import resolve_ffcss
from brain.federation.imports_detector import (
    detect_cross_repo_imports as _detect_cross_repo_imports,
)


@dataclass
class FederationMerger:
    detect_cross_repo_imports: bool = False
    detect_ffcss_tokens: bool = False
    dry_detection: bool = True
    detect_shared_components: bool = False  # P2 noop
    repo_roles: dict[str, str] = field(default_factory=dict)

    def merge_group(
        self, group: str, repo_graphs: list[tuple[str, dict[str, Any]]]
    ) -> dict[str, Any]:
        """Federated group master from per-repo graphs.

        Node IDs are namespaced as `{group}/{repo}:{original_id}`. The original_id
        may itself contain colons - downstream parsers must use
        `namespaced.partition(":")` (NOT `split(":")`) to avoid splitting on
        embedded colons.

        Given schema-valid per-repo graphs, the output validates against
        Graph v1: repo provenance lives in `metadata._repo`/`metadata._group`
        (GraphNode forbids extra top-level keys) and the envelope carries
        schema_version/repo/built_at/built_by with `repo="_master"`.
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for repo, g in repo_graphs:
            ns = f"{group}/{repo}:"
            for n in g.get("nodes", []):
                if not isinstance(n, dict) or "id" not in n:
                    continue
                new_node: dict[str, Any] = dict(n)
                new_node["id"] = f"{ns}{n['id']}"
                metadata = dict(n.get("metadata") or {})
                metadata["_repo"] = repo
                metadata["_group"] = group
                new_node["metadata"] = metadata
                nodes.append(new_node)
            for e in g.get("edges", []):
                if not isinstance(e, dict) or "source" not in e or "target" not in e:
                    continue
                new_e: dict[str, Any] = dict(e)
                new_e["source"] = f"{ns}{e['source']}"
                new_e["target"] = f"{ns}{e['target']}"
                edges.append(new_e)

        if self.detect_cross_repo_imports and self.repo_roles:
            for cross in _detect_cross_repo_imports(repo_graphs, self.repo_roles):
                cross = dict(cross)
                src_repo = str(cross.pop("source_repo"))
                tgt_repo = str(cross.pop("target_repo"))
                cross["source"] = f"{group}/{src_repo}:{cross['source']}"
                cross["target"] = f"{group}/{tgt_repo}:{cross['target']}"
                edges.append(cross)

        if self.detect_ffcss_tokens and self.repo_roles:
            # Build a namespaced view of repo_graphs with ns-prefixed ids
            ns_graphs: list[tuple[str, dict[str, Any]]] = []
            for repo, g in repo_graphs:
                ns = f"{group}/{repo}:"
                ns_nodes = [
                    {**n, "id": f"{ns}{n['id']}"}
                    for n in g.get("nodes", [])
                    if isinstance(n, dict) and "id" in n
                ]
                ns_edges = [
                    {
                        **e,
                        "source": f"{ns}{e['source']}",
                        "target": f"{ns}{e['target']}",
                    }
                    for e in g.get("edges", [])
                    if isinstance(e, dict) and "source" in e and "target" in e
                ]
                ns_graphs.append((repo, {"nodes": ns_nodes, "edges": ns_edges}))

            res = resolve_ffcss(
                group=group,
                repo_graphs=ns_graphs,
                repo_roles=self.repo_roles,
                dry_detection=self.dry_detection,
            )

            # Copy canonical flag from ns view back into master nodes
            ns_token_meta: dict[str, dict[str, Any]] = {}
            for _repo, g in ns_graphs:
                for n in g["nodes"]:
                    if n.get("kind") == "ffcss_token":
                        ns_token_meta[n["id"]] = n.get("metadata", {})
            for n in nodes:
                if n["id"] in ns_token_meta:
                    n.setdefault("metadata", {}).update(
                        {"canonical": ns_token_meta[n["id"]].get("canonical", False)}
                    )

            edges.extend(res.new_edges)
            for rw in res.rewritten_edges:
                # Extract token name from rewritten target
                # rewritten target is {group}/{repo}:ffcss:{token_name}
                rw_target = rw.get("target", "")
                if ":ffcss:" in str(rw_target):
                    # Match canonical or local ffcss:<name> edges by name
                    token_name = str(rw_target).rsplit(":ffcss:", 1)[-1]
                    for i, e in enumerate(edges):
                        if (
                            e.get("source") == rw["source"]
                            and e.get("relation") == "uses_token"
                            and ":ffcss:" in str(e.get("target", ""))
                            and str(e.get("target", "")).rsplit(":ffcss:", 1)[-1] == token_name
                        ):
                            edges[i] = rw
                            break

        for e in edges:
            c = e.get("confidence")
            if isinstance(c, str):
                e["confidence"] = c.lower()

        return {
            "schema_version": "v1",
            "group": group,
            "repo": "_master",
            "built_at": datetime.now(UTC).isoformat(),
            "built_by": "federation-merger",
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "repos": len(repo_graphs),
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

    def pass_through_super(self, group_masters: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        """P1: super-master graph.

        With 1 group: super-master = copy of group master (pass-through).
        With N>1 groups: naive union of nodes/edges (P4 adds cross-group semantic links).
        The `groups` key always contains the list of source group names.

        Note: the super-master is a P1 union artifact with its own envelope
        (`super`/`groups`), not a Graph v1 document - unlike `merge_group` output.
        """
        groups = [g for g, _ in group_masters]
        # Strip the Graph-v1 envelope so the super-master carries exactly one
        # envelope (version/super/groups) - leaving schema_version on the
        # copy would misclassify it as a per-repo Graph v1 document.
        graph_v1_envelope = {
            "group", "schema_version", "repo", "built_at", "built_by", "stats"
        }
        if len(group_masters) == 1:
            _, master = group_masters[0]
            copy = {
                k: v for k, v in master.items() if k not in graph_v1_envelope
            }
            copy["version"] = 1
            copy["super"] = True
            copy["groups"] = groups
            return copy
        merged: dict[str, Any] = {
            "version": 1, "super": True, "groups": groups, "nodes": [], "edges": []
        }
        for _, m in group_masters:
            merged["nodes"].extend(m.get("nodes", []))
            merged["edges"].extend(m.get("edges", []))
        return merged
