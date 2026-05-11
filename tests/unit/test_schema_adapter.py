"""Brain ↔ graphifyy schema adapter tests.

Our schema: brain.core.graph_schema.Graph (nodes with {id, kind, name, file, ...}
and edges with {source, target, relation, confidence}).

graphifyy schema: {id, label, file_type, source_file, source_location} nodes,
{source, target, relation, confidence, source_file, source_location} edges.
"""
from __future__ import annotations

from datetime import UTC, datetime

from brain.core.graph_schema import Graph, GraphEdge, GraphNode, NodeConfidence
from brain.viz.schema_adapter import (
    brain_id_for_graphifyy_node,
    from_graphifyy_extraction,
    to_graphifyy_extraction,
)


def _sample_graph() -> Graph:
    return Graph(
        group="example-group",
        repo="example-front-a",
        built_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        built_by="test",
        nodes=[
            GraphNode(
                id="example-group/example-front-a:LoginButton",
                kind="class",
                name="LoginButton",
                file="layers/example-front-a/components/product/LoginButton.vue",
                line=None,
                community=None,
                metadata={"framework": "vue"},
            ),
            GraphNode(
                id="example-group/example-front-a:useCurrentUser",
                kind="function",
                name="useCurrentUser",
                file="layers/example-front-a/composables/useCurrentUser.ts",
                line=None,
                community=None,
            ),
        ],
        edges=[
            GraphEdge(
                source="example-group/example-front-a:LoginButton",
                target="example-group/example-front-a:useCurrentUser",
                relation="uses_hook",
                confidence=NodeConfidence.EXTRACTED,
            ),
            GraphEdge(
                source="example-group/example-front-a:LoginButton",
                target="example-group/example-core:Button",
                relation="imports_from_parent_repo",
                confidence=NodeConfidence.EXTRACTED,
            ),
        ],
    )


def test_to_graphifyy_extraction_returns_nodes_and_edges() -> None:
    g = _sample_graph()
    result = to_graphifyy_extraction(g)
    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 2


def test_node_has_brain_id_metadata_for_reverse_lookup() -> None:
    g = _sample_graph()
    result = to_graphifyy_extraction(g)
    first = result["nodes"][0]
    assert first["metadata"]["_brain_id"] == "example-group/example-front-a:LoginButton"


def test_node_label_preserves_name() -> None:
    g = _sample_graph()
    result = to_graphifyy_extraction(g)
    labels = {n["label"] for n in result["nodes"]}
    assert labels == {"LoginButton", "useCurrentUser"}


def test_cross_repo_edge_flagged_in_metadata() -> None:
    g = _sample_graph()
    result = to_graphifyy_extraction(g)
    cross = [e for e in result["edges"] if e.get("metadata", {}).get("_cross_repo")]
    assert len(cross) == 1
    assert cross[0]["metadata"]["_brain_relation"] == "imports_from_parent_repo"


def test_custom_relations_passed_through() -> None:
    """renders, uses_hook, exports are brain-specific; graphifyy accepts strings."""
    g = _sample_graph()
    result = to_graphifyy_extraction(g)
    uses_hook_edges = [e for e in result["edges"] if e["relation"] == "uses_hook"]
    assert len(uses_hook_edges) == 1


def test_confidence_mapping() -> None:
    g = _sample_graph()
    result = to_graphifyy_extraction(g)
    assert all(e["confidence"] == "EXTRACTED" for e in result["edges"])


def test_brain_id_reverse_lookup() -> None:
    g = _sample_graph()
    extraction = to_graphifyy_extraction(g)
    first_gid = extraction["nodes"][0]["id"]
    recovered = brain_id_for_graphifyy_node(first_gid, extraction)
    assert recovered == "example-group/example-front-a:LoginButton"


def test_brain_id_reverse_lookup_missing_returns_none() -> None:
    extraction = {"nodes": [{"id": "stranger", "label": "x"}], "edges": []}
    assert brain_id_for_graphifyy_node("stranger", extraction) is None


def test_from_graphifyy_extraction_round_trip_preserves_ids_and_relations() -> None:
    original = _sample_graph()
    extraction = to_graphifyy_extraction(original)
    recovered = from_graphifyy_extraction(extraction, group="example-group")
    recovered_ids = {n.id for n in recovered.nodes}
    original_ids = {n.id for n in original.nodes}
    assert recovered_ids == original_ids
    recovered_relations = {e.relation for e in recovered.edges}
    original_relations = {e.relation for e in original.edges}
    assert recovered_relations == original_relations


def test_unknown_relation_preserved_via_metadata() -> None:
    """Adapter never drops edges; unknown relations mapped to 'calls' + flag."""
    g = Graph(
        group="example-group",
        repo="Test",
        built_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        built_by="test",
        nodes=[
            GraphNode(id="example-group/Test:A", kind="function", name="A", line=None, community=None),
            GraphNode(id="example-group/Test:B", kind="function", name="B", line=None, community=None),
        ],
        edges=[
            GraphEdge(
                source="example-group/Test:A",
                target="example-group/Test:B",
                relation="novel_relation_type",
                confidence=NodeConfidence.INFERRED,
            )
        ],
    )
    extraction = to_graphifyy_extraction(g)
    assert len(extraction["edges"]) == 1
    edge = extraction["edges"][0]
    assert edge["metadata"]["_brain_relation"] == "novel_relation_type"
