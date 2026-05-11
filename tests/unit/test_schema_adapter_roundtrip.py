"""Round-trip invariant for brain ↔ graphifyy id mapping.

Required because `insights.json` (god_nodes, surprising_connections) stores
graphifyy-flavoured sanitized IDs. `brain_explain` resolves those back to
brain IDs via `from_graphifyy_id(gid, extraction)`; without symmetry the
explain endpoint gets orphaned god-node references."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from brain.core.graph_schema import Graph, GraphNode
from brain.viz.schema_adapter import (
    from_graphifyy_id,
    to_graphifyy_extraction,
    to_graphifyy_id,
)


def _sample_graph() -> Graph:
    return Graph(
        group="example-group",
        repo="example-front-a",
        built_at=datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        built_by="test",
        nodes=[
            GraphNode(
                id="example-group/example-front-a:LoginButton",
                kind="class",
                name="LoginButton",
                file="a.vue",
                line=None,
                community=None,
            ),
            GraphNode(
                id="example-group/example-front-a:useCurrentUser",
                kind="function",
                name="useCurrentUser",
                file="b.ts",
                line=None,
                community=None,
            ),
        ],
        edges=[],
    )


def test_to_graphifyy_id_is_pure_function() -> None:
    assert to_graphifyy_id("example-group/example-core:X") == to_graphifyy_id(
        "example-group/example-core:X"
    )


def test_to_graphifyy_id_produces_sanitized_chars_only() -> None:
    # to_graphifyy_id replaces every non-[A-Za-z0-9_] run with a single
    # underscore - hyphens included. Brain ids like "example-group/example-core:X"
    # become "example_group_example_core_X".
    gid = to_graphifyy_id("example-group/example-core:LoginButton")
    assert gid == "example_group_example_core_LoginButton"


@pytest.mark.parametrize("brain_id", [
    "example-group/example-core:LoginButton",
    "example-group/example-front-a:useCurrentUser",
    "a/b:c",
    "group.with.dots/repo-dashed:Symbol",
])
def test_roundtrip_from_to_graphifyy_id(brain_id: str) -> None:
    """Core invariant: `from_graphifyy_id(to_graphifyy_id(x), extraction) == x`
    when the extraction carries the `_brain_id` metadata (which it always does
    because we produced it)."""
    g = Graph(
        group="example-group", repo="example-front-a",
        built_at=datetime(2026, 4, 20, tzinfo=UTC), built_by="test",
        nodes=[GraphNode(id=brain_id, kind="module", name="x",
                         file=None, line=None, community=None)],
        edges=[],
    )
    extraction = to_graphifyy_extraction(g)
    gid = to_graphifyy_id(brain_id)
    recovered = from_graphifyy_id(gid, extraction)
    assert recovered == brain_id


def test_from_graphifyy_id_returns_none_for_unknown() -> None:
    extraction = to_graphifyy_extraction(_sample_graph())
    assert from_graphifyy_id("not_a_real_gid", extraction) is None


def test_from_graphifyy_id_fallback_when_missing_brain_id() -> None:
    """Defensive: if extraction was NOT produced by us and lacks `_brain_id`,
    return None with no crash. Callers handle None by displaying the sanitized
    id as-is + logging a warning."""
    extraction = {
        "nodes": [
            {"id": "mystery_gid", "label": "X", "metadata": {}},
        ],
        "edges": [],
    }
    assert from_graphifyy_id("mystery_gid", extraction) is None
