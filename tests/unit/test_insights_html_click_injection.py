"""graph.html post-process: inject a click handler that navigates to
`/vault/<group>/_master/node/<slug>/` when a node is clicked.

The handler reads a `_brain_id` attribute from the node data (carried by
graphifyy because our schema_adapter embeds `_brain_id` in every node's
metadata), computes the slug via the in-page `nodeIdToSlug()` function
(ported from `brain/publishers/common.py`), then sets `window.location`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from brain.core.graph_schema import Graph, GraphEdge, GraphNode, NodeConfidence
from brain.viz.insights_wrapper import render_master


def _tiny_graph() -> Graph:
    return Graph(
        group="example-group", repo="_master",
        built_at=datetime.now(UTC), built_by="test",
        nodes=[
            GraphNode(id="example-group/R:A", kind="function", name="A",
                      file=None, line=None, community=None),
            GraphNode(id="example-group/R:B", kind="function", name="B",
                      file=None, line=None, community=None),
        ],
        edges=[
            GraphEdge(source="example-group/R:A", target="example-group/R:B",
                      relation="calls", confidence=NodeConfidence.EXTRACTED),
        ],
    )


def test_generated_html_contains_node_id_to_slug_js(tmp_path: Path) -> None:
    out = render_master(_tiny_graph(), tmp_path)
    html = out["graph_html_path"].read_text()
    assert "function nodeIdToSlug" in html, \
        "click handler JS must be injected into graph.html"


def test_generated_html_contains_click_handler(tmp_path: Path) -> None:
    out = render_master(_tiny_graph(), tmp_path)
    html = out["graph_html_path"].read_text()
    # Handler reads `_brain_id` from node data and navigates to wiki
    assert "_brain_id" in html
    assert "/vault/" in html or "node/" in html


def test_injected_script_is_before_closing_body(tmp_path: Path) -> None:
    out = render_master(_tiny_graph(), tmp_path)
    html = out["graph_html_path"].read_text()
    # Find last </body>; our script must appear before it
    script_pos = html.rfind("function nodeIdToSlug")
    body_pos = html.rfind("</body>")
    assert script_pos != -1
    assert body_pos != -1
    assert script_pos < body_pos


def test_injection_skipped_for_placeholder_html(tmp_path: Path) -> None:
    """If the graph was too large and we emitted the placeholder instead of
    graphifyy-generated HTML, there's nothing clickable - skip injection."""
    big_nodes = [
        GraphNode(id=f"example-group/R:N{i}", kind="function", name=f"N{i}",
                  file=None, line=None, community=None)
        for i in range(10)
    ]
    g = Graph(
        group="example-group", repo="_master",
        built_at=datetime.now(UTC), built_by="test",
        nodes=big_nodes, edges=[],
    )
    out = render_master(g, tmp_path, max_nodes_viz=5)
    html = out["graph_html_path"].read_text()
    # Placeholder has no nodes, no click handler should be injected
    assert "function nodeIdToSlug" not in html
    assert "graph too large for vis-network" in html or "graph too large" in html
