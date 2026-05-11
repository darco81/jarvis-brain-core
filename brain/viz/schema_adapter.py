"""Brain ↔ graphifyy schema adapter.

Brain graph schema (brain.core.graph_schema): nodes with stable ids of the form
``<group>/<repo>:<symbol>``, kinds ``class|function|module|doc``, and edges with a
small whitelisted relation vocabulary (``imports``, ``imports_from_parent_repo``,
``renders``, ``uses_hook``, etc.).

graphifyy expects nodes with ``{id, label, file_type, source_file,
source_location}`` and edges with free-form ``relation`` strings. graphifyy's
AST extractor uses sanitized filesystem paths as node ids.

Mapping strategy:
- Node id: hash-stable transform of the brain id (safe chars only). Original
  preserved in ``metadata._brain_id`` for reverse lookup.
- Cross-repo edges (``imports_from_parent_repo``): stored as
  ``relation="imports_from"`` with ``metadata._cross_repo=True`` plus the
  original relation in ``metadata._brain_relation``.
- Unknown relations: mapped to ``calls`` (graphifyy-native) with
  ``metadata._brain_relation`` capturing the original. Never dropped.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from brain.core.graph_schema import Graph, GraphEdge, GraphNode, NodeConfidence

_RELATION_MAP: dict[str, str] = {
    "imports": "imports_from",
    "imports_from_parent_repo": "imports_from",
}

_KIND_TO_FILE_TYPE: dict[str, str] = {
    "class": "code",
    "function": "code",
    "module": "code",
    "doc": "document",
}


def _sanitize_id(brain_id: str) -> str:
    """Make graphifyy-safe id from brain's group/repo:symbol shape."""
    return re.sub(r"[^A-Za-z0-9_]+", "_", brain_id).strip("_")


def to_graphifyy_id(brain_id: str) -> str:
    """Convert a brain node id into its graphifyy-safe counterpart.

    Public symmetric pair of `from_graphifyy_id`. Reuses the internal
    `_sanitize_id` so all sanitisation logic lives in one place.
    """
    return _sanitize_id(brain_id)


def from_graphifyy_id(gid: str, extraction: dict[str, Any]) -> str | None:
    """Resolve a graphifyy-sanitized id back to the brain id via the
    `metadata._brain_id` side-channel carried in the extraction.

    Returns None if the id is not present in the extraction OR if the
    matching node lacks `_brain_id` (i.e. the extraction was not produced
    by our adapter). Callers should log a warning + fall back to the
    sanitized id as the display label.
    """
    for n in extraction.get("nodes", []):
        if n.get("id") == gid:
            result = n.get("metadata", {}).get("_brain_id")
            return str(result) if result is not None else None
    return None


def to_graphifyy_extraction(g: Graph) -> dict[str, Any]:
    """Convert brain Graph → graphifyy extraction dict."""
    nodes_out: list[dict[str, Any]] = []
    for n in g.nodes:
        gid = _sanitize_id(n.id)
        node_dict: dict[str, Any] = {
            "id": gid,
            "label": n.name,
            "file_type": _KIND_TO_FILE_TYPE.get(n.kind, "code"),
            "source_file": n.file or "",
            "source_location": f"L{n.line}" if n.line is not None else None,
            "metadata": {
                "_brain_id": n.id,
                "_brain_kind": n.kind,
                **n.metadata,
            },
        }
        nodes_out.append(node_dict)

    edges_out: list[dict[str, Any]] = []
    for e in g.edges:
        original_rel = e.relation
        new_rel = _RELATION_MAP.get(original_rel, original_rel)
        is_cross_repo = original_rel == "imports_from_parent_repo"
        edge_dict: dict[str, Any] = {
            "source": _sanitize_id(e.source),
            "target": _sanitize_id(e.target),
            "relation": new_rel,
            "confidence": e.confidence.value.upper(),
            "source_file": "",
            "source_location": None,
            "weight": 1.0,
            "metadata": {
                "_brain_relation": original_rel,
                "_brain_source": e.source,
                "_brain_target": e.target,
                **({"_cross_repo": True} if is_cross_repo else {}),
                **e.metadata,
            },
        }
        edges_out.append(edge_dict)

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def from_graphifyy_extraction(extraction: dict[str, Any], group: str) -> Graph:
    """Reverse conversion - best-effort reconstruction of a brain Graph.

    Used when graphifyy is the extractor (not our current path); also used by
    round-trip tests. Requires ``metadata._brain_id`` on each node - fails
    cleanly if the extraction wasn't produced by our adapter.
    """
    nodes: list[GraphNode] = []
    seen_repos: set[str] = set()
    for n in extraction.get("nodes", []):
        brain_id = n.get("metadata", {}).get("_brain_id")
        if not brain_id:
            continue
        kind = n.get("metadata", {}).get("_brain_kind", "module")
        if ":" in brain_id:
            repo_part = brain_id.split(":", 1)[0].split("/", 1)[-1]
            seen_repos.add(repo_part)
        filtered_meta = {
            k: v
            for k, v in n.get("metadata", {}).items()
            if not k.startswith("_brain")
        }
        nodes.append(
            GraphNode(
                id=brain_id,
                kind=kind,
                name=n.get("label", brain_id.rsplit(":", 1)[-1]),
                file=n.get("source_file") or None,
                line=None,
                community=None,
                metadata=filtered_meta,
            )
        )

    edges: list[GraphEdge] = []
    id_by_sanitized = {
        _sanitize_id(n_out.id): n_out.id for n_out in nodes
    }
    for e in extraction.get("edges", []):
        emeta = e.get("metadata", {})
        src_brain = emeta.get("_brain_source") or id_by_sanitized.get(e["source"])
        tgt_brain = emeta.get("_brain_target") or id_by_sanitized.get(e["target"])
        if src_brain is None or tgt_brain is None:
            continue
        original_rel = emeta.get("_brain_relation", e.get("relation", "calls"))
        conf_str = str(e.get("confidence", "EXTRACTED")).lower()
        confidence = (
            NodeConfidence.EXTRACTED
            if conf_str == "extracted"
            else NodeConfidence.INFERRED
        )
        edges.append(
            GraphEdge(
                source=src_brain,
                target=tgt_brain,
                relation=original_rel,
                confidence=confidence,
                metadata={
                    k: v for k, v in e.get("metadata", {}).items()
                    if not k.startswith("_brain") and k != "_cross_repo"
                },
            )
        )

    first_repo = next(iter(seen_repos)) if seen_repos else "unknown"
    return Graph(
        group=group,
        repo=first_repo,
        built_at=datetime.now(UTC),
        built_by="graphifyy-roundtrip",
        nodes=nodes,
        edges=edges,
    )


def brain_id_for_graphifyy_node(gid: str, extraction: dict[str, Any]) -> str | None:
    """Deprecated alias - prefer `from_graphifyy_id`."""
    return from_graphifyy_id(gid, extraction)
