"""Tests for brain.viz.insights_wrapper - thin facade over graphifyy."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from brain.core.graph_schema import Graph, GraphEdge, GraphNode, NodeConfidence
from brain.viz.insights_wrapper import (
    InsightsOutput,
    render_master,
    render_repo,
)

_GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden"


@pytest.fixture
def sample_graph() -> Graph:
    data = json.loads((_GOLDEN_DIR / "sample_graph.json").read_text())
    # Fixture from jarvis-brain-job-graphs may not have all required fields;
    # stamp defaults so pydantic validation passes.
    data.setdefault("built_at", "2026-04-17T18:40:00+00:00")
    data.setdefault("built_by", "cc-local")
    return Graph(**data)


def test_render_master_writes_expected_files(sample_graph: Graph, tmp_path: Path) -> None:
    out: InsightsOutput = render_master(sample_graph, tmp_path)
    assert out["graph_html_path"].exists()
    assert out["graph_html_path"].stat().st_size > 0
    assert out["insights_json_path"].exists()
    payload = json.loads(out["insights_json_path"].read_text())
    assert "communities" in payload
    assert "god_nodes" in payload
    assert "stats" in payload
    assert payload["stats"]["nodes"] == len(sample_graph.nodes)


def test_render_master_threshold_falls_back_to_placeholder(tmp_path: Path) -> None:
    large = _synthetic_graph(node_count=7500)
    out = render_master(large, tmp_path, max_nodes_viz=6000)
    html = out["graph_html_path"].read_text()
    assert "too large" in html.lower()
    assert "per-repo" in html.lower()
    payload = json.loads(out["insights_json_path"].read_text())
    assert payload["stats"]["nodes"] == 7500


def test_render_repo_for_single_repo_graph(sample_graph: Graph, tmp_path: Path) -> None:
    out = render_repo(sample_graph, tmp_path)
    assert out["graph_html_path"].exists()


def _synthetic_graph(node_count: int) -> Graph:
    nodes = [
        GraphNode(
            id=f"example-group/Synth:node_{i}",
            kind="function",
            name=f"node_{i}",
            line=None,
            community=None,
        )
        for i in range(node_count)
    ]
    edges = [
        GraphEdge(
            source=f"example-group/Synth:node_{i}",
            target=f"example-group/Synth:node_{(i + 1) % node_count}",
            relation="calls",
            confidence=NodeConfidence.EXTRACTED,
        )
        for i in range(node_count)
    ]
    return Graph(
        group="example-group",
        repo="Synth",
        built_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        built_by="test",
        nodes=nodes,
        edges=edges,
    )
