"""MCP tool schemas and metadata (name, description, input schema)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BrainQueryArgs(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    scope: str | None = Field(
        None,
        description=(
            "'example-group' (group-wide) | 'example-group/example-front' (repo-filtered) "
            "| 'super' (cross-group merged index) | None (fan-out all groups)"
        ),
    )
    limit: int = Field(10, ge=1, le=50)


class BrainGraphArgs(BaseModel):
    group: str = Field(..., min_length=1, max_length=64)
    repo: str | None = Field(
        None,
        description="Optional repo filter, e.g. 'example-front'.",
    )
    node_id: str | None = Field(
        None,
        max_length=512,
        description=(
            "Center of an ego-graph, e.g. "
            "'example-group/example-front:LoginButton'. Returns only nodes "
            "within `radius` hops. Omit for a whole-graph summary "
            "(counts per kind/repo) instead of a full dump."
        ),
    )
    radius: int = Field(
        2,
        ge=1,
        le=4,
        description="Ego-graph hop radius around node_id (default 2).",
    )
    response_format: Literal["concise", "detailed"] = Field(
        "concise",
        description=(
            "'concise' = id/name/kind per node (about 3x fewer tokens); "
            "'detailed' adds file, line and metadata."
        ),
    )


class BrainPathArgs(BaseModel):
    from_node: str = Field(..., min_length=1, max_length=256)
    to_node: str = Field(..., min_length=1, max_length=256)
    max_hops: int = Field(6, ge=1, le=10)


class BrainExplainArgs(BaseModel):
    node_id: str = Field(..., min_length=1, max_length=512)


class BrainFfcssArgs(BaseModel):
    group: str = Field(..., min_length=1, max_length=64)
    repo: str | None = Field(
        None,
        description="Optional repo filter. None = group-wide aggregates.",
        max_length=64,
    )
    mode: Literal["tokens", "usage", "violations"] = Field(
        "tokens",
        description=(
            "'tokens' = list tokens with canonical flag + values; "
            "'usage' = count uses per token + per repo; "
            "'violations' = DRY violations (duplicates_token edges)."
        ),
    )


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "brain_query",
        "description": (
            "Free-text search across the knowledge graph. Returns ranked hits "
            "from FTS5 index with 2-hop neighbors and cross-repo hints."
        ),
        "inputSchema": BrainQueryArgs.model_json_schema(),
    },
    {
        "name": "brain_graph",
        "description": (
            "Structure around a node, or a graph overview. With node_id: an "
            "ego-graph of everything within `radius` hops (default 2) - use "
            "this to see a component's neighborhood, e.g. node_id="
            "'example-group/example-front:LoginButton'. Without node_id: a "
            "summary (node counts per kind and repo), never a full dump. "
            "Start concise; switch response_format='detailed' only when you "
            "need file/line/metadata."
        ),
        "inputSchema": BrainGraphArgs.model_json_schema(),
    },
    {
        "name": "brain_path",
        "description": (
            "Shortest path between two nodes in the merged master graph. "
            "Useful for tracing how an app-core primitive reaches a specific "
            "frontend feature."
        ),
        "inputSchema": BrainPathArgs.model_json_schema(),
    },
    {
        "name": "brain_explain",
        "description": (
            "Returns a structured explanation of a single graph node: its "
            "metadata (kind, file, community) and direct neighbors (inbound + "
            "outbound relations). Uses existing graph.json metadata - no external "
            "LLM call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                    "description": "Exact node id, e.g. 'example-group/example-front:LoginButton'",
                },
            },
            "required": ["node_id"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "name": {"type": "string"},
                "kind": {"type": "string"},
                "file": {"type": "string"},
                "line": {"type": ["integer", "null"]},
                "community": {"type": ["integer", "null"]},
                "provenance": {
                    "type": ["object", "null"],
                    "description": (
                        "Commit metadata from the node's last update: "
                        "sha (commit hash), date (ISO 8601), author. "
                        "Null if no commit data available."
                    ),
                    "properties": {
                        "sha": {"type": "string"},
                        "date": {"type": "string"},
                        "author": {"type": "string"},
                    },
                },
                "neighbors_out": {"type": "array"},
                "neighbors_in": {"type": "array"},
                "truncated": {"type": "boolean"},
            },
            "required": [
                "node_id",
                "provenance",
                "neighbors_out",
                "neighbors_in",
                "truncated",
            ],
        },
    },
    {
        "name": "brain_ffcss",
        "description": (
            "Query FFCSS design-token convention across a group. Modes: "
            "tokens (list tokens), usage (per-repo usage stats), violations "
            "(DRY violations). Uses master graph.json, no LLM call."
        ),
        "inputSchema": BrainFfcssArgs.model_json_schema(),
    },
]
