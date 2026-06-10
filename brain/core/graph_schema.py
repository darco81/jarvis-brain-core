"""Graph schema v1 - serialized form of a per-repo knowledge graph.

The contract both ingestion paths target (LLM extraction and the CC-local
regex skill) and every downstream consumer reads (merger, publishers, viz).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class NodeConfidence(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"


class NodeKind(StrEnum):
    """Canonical kinds emitted by extractors. Soft contract - free-form kinds allowed."""
    CLASS = "class"
    FUNCTION = "function"
    MODULE = "module"
    DOC = "doc"
    COMPONENT = "component"
    FFCSS_TOKEN = "ffcss_token"


class EdgeRelation(StrEnum):
    IMPORTS = "imports"
    EXPORTS = "exports"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    CALLS = "calls"
    RENDERS = "renders"
    USES_HOOK = "uses_hook"
    DOCUMENTS = "documents"
    IMPORTS_FROM_PARENT_REPO = "imports_from_parent_repo"
    SEMANTICALLY_SIMILAR_TO = "semantically_similar_to"
    DEFINES_TOKEN = "defines_token"
    USES_TOKEN = "uses_token"
    OVERRIDES_TOKEN = "overrides_token"
    DUPLICATES_TOKEN = "duplicates_token"


_ALLOWED_RELATIONS: frozenset[str] = frozenset({
    "imports",
    "exports",
    "extends",
    "implements",
    "calls",
    "renders",
    "uses_hook",
    "documents",
    "imports_from_parent_repo",
    "semantically_similar_to",
    # FFCSS federation (Sprint 3 Slice 4)
    "defines_token",      # module/component -> token
    "uses_token",         # component -> token (may cross-repo)
    "overrides_token",    # child_repo token -> canonical token
    "duplicates_token",   # non-canonical token A -> non-canonical token B (DRY violation)
})


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    kind: str = Field(
        ...,
        min_length=1,
        json_schema_extra={"examples": [k.value for k in NodeKind]},
    )
    name: str = Field(..., min_length=1)
    file: str | None = None
    line: int | None = Field(None, ge=0)
    community: int | None = Field(None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    relation: str = Field(
        ...,
        json_schema_extra={"examples": list[Any](sorted(_ALLOWED_RELATIONS))},
    )
    confidence: NodeConfidence
    metadata: dict[str, Any] = Field(default_factory=dict)


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["v1"] = "v1"
    group: str = Field(..., min_length=1)
    repo: str = Field(..., min_length=1)
    built_at: AwareDatetime
    built_by: str = Field(..., min_length=1)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)

    def validate_edge_relations(self) -> list[str]:
        """Return edges with non-whitelist relations (soft check)."""
        return [
            f"{e.source} -> {e.target} ({e.relation})"
            for e in self.edges
            if e.relation not in _ALLOWED_RELATIONS
        ]

    def validate_edge_node_refs(self) -> list[str]:
        """Return edges with dangling source/target (soft check)."""
        node_ids = {n.id for n in self.nodes}
        dangling: list[str] = []
        for e in self.edges:
            if e.source not in node_ids:
                dangling.append(f"source missing: {e.source} -> {e.target}")
            if e.target not in node_ids:
                dangling.append(f"target missing: {e.source} -> {e.target}")
        return dangling
