"""Schema v1 contract tests - anchors format produced by GraphifyRunner
and CC local bootstrap (/brain-extract)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from brain.core.graph_schema import Graph, GraphEdge, GraphNode, NodeConfidence


def _valid_minimal_graph() -> dict:
    return {
        "schema_version": "v1",
        "group": "example-group",
        "repo": "example-front-a",
        "built_at": datetime.now(UTC).isoformat(),
        "built_by": "cc-local",
        "nodes": [
            {
                "id": "example-group/example-front-a:Button",
                "kind": "class",
                "name": "Button",
                "file": "src/components/Button.tsx",
                "line": 10,
                "community": None,
                "metadata": {},
            }
        ],
        "edges": [],
        "stats": {"nodes_count": 1, "edges_count": 0},
    }


def test_minimal_valid_graph_parses() -> None:
    g = Graph.model_validate(_valid_minimal_graph())
    assert g.group == "example-group"
    assert g.repo == "example-front-a"
    assert len(g.nodes) == 1
    assert g.nodes[0].kind == "class"
    assert isinstance(g.nodes[0], GraphNode)


def test_missing_required_field_raises() -> None:
    data = _valid_minimal_graph()
    del data["group"]
    with pytest.raises(ValidationError) as exc_info:
        Graph.model_validate(data)
    assert "group" in str(exc_info.value)


def test_extra_field_forbidden() -> None:
    data = _valid_minimal_graph()
    data["unknown_field"] = "oops"
    with pytest.raises(ValidationError) as exc_info:
        Graph.model_validate(data)
    assert "unknown_field" in str(exc_info.value)


def test_bad_schema_version_rejected() -> None:
    data = _valid_minimal_graph()
    data["schema_version"] = "v999"
    with pytest.raises(ValidationError):
        Graph.model_validate(data)


def test_edge_relation_whitelist_soft_check() -> None:
    data = _valid_minimal_graph()
    data["nodes"].append({
        "id": "example-group/example-front-a:Form",
        "kind": "class", "name": "Form",
        "file": None, "line": None, "community": None, "metadata": {},
    })
    data["edges"].append({
        "source": "example-group/example-front-a:Button",
        "target": "example-group/example-front-a:Form",
        "relation": "mystery_relation",
        "confidence": "inferred",
        "metadata": {},
    })
    g = Graph.model_validate(data)
    assert isinstance(g.edges[0], GraphEdge)
    assert g.edges[0].confidence == NodeConfidence.INFERRED
    bad = g.validate_edge_relations()
    assert len(bad) == 1
    assert "mystery_relation" in bad[0]


def test_edge_dangling_node_ref_soft_check() -> None:
    data = _valid_minimal_graph()
    data["edges"].append({
        "source": "example-group/example-front-a:Button",
        "target": "example-group/example-front-a:NotInNodes",
        "relation": "imports",
        "confidence": "extracted",
        "metadata": {},
    })
    g = Graph.model_validate(data)
    dangling = g.validate_edge_node_refs()
    assert len(dangling) == 1
    assert "NotInNodes" in dangling[0]


def test_schema_file_documents_ffcss_additions() -> None:
    repo_root = Path(__file__).parent.parent.parent
    schema = json.loads((repo_root / "schemas" / "graph_v1.json").read_text())
    node = schema["$defs"]["GraphNode"]
    edge = schema["$defs"]["GraphEdge"]
    assert "ffcss_token" in node["properties"]["kind"].get("examples", [])
    rel_examples = edge["properties"]["relation"].get("examples", [])
    for rel in (
        "defines_token",
        "uses_token",
        "overrides_token",
        "duplicates_token",
    ):
        assert rel in rel_examples
