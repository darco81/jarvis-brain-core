"""End-to-end pipeline test: extract -> merge -> index -> all 5 tool surfaces.

This is the test that protects the educational core idea: both ingestion
paths emit the same schema, the merger federates them into a schema-valid
master, and every MCP tool surface answers against that master. The
merger<->executor `_repo` placement bug and the schema-envelope mismatch
both shipped in v0.1.0 precisely because no test ran this chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from brain.api.executors import _build_explain_executor, _build_ffcss_executor
from brain.api.query import _route_query
from brain.api.query_path import shortest_path_payload
from brain.core.graph_schema import Graph
from brain.core.paths import DataPaths
from brain.extractors.ffcss import extract_from_source
from brain.federation.merger import FederationMerger
from brain.publishers.api_index import APIIndexPublisher

GROUP = "example-group"
CORE = "app-core"
FRONT = "app-front-a"

CORE_SCSS = """
:root {
  --dt-color-primary: #1a2b3c;
  --dt-spacing-md: 16px;
}
"""

FRONT_SCSS = """
:root {
  --dt-color-primary: #ff0000;
}
.checkout-button {
  color: var(--dt-color-primary);
  margin: var(--dt-spacing-md);
}
"""


def _tokens_to_graph(repo: str, scss_path: str, source: str) -> dict[str, Any]:
    """Convert extractor candidates into a schema-v1 per-repo graph.

    This is the documented Path B shape: one module node for the stylesheet,
    one ffcss_token node per candidate, defines_token/uses_token edges.
    """
    candidates = extract_from_source(path=Path(scss_path), source=source, prefix="dt-")
    nodes: list[dict[str, Any]] = [
        {"id": scss_path, "kind": "module", "name": scss_path, "file": scss_path},
    ]
    edges: list[dict[str, Any]] = []
    for c in candidates:
        token_id = f"ffcss:{c.token_name}"
        if c.definitions:
            nodes.append({
                "id": token_id,
                "kind": "ffcss_token",
                "name": c.token_name,
                "file": scss_path,
                "metadata": {
                    "token_type": c.token_type,
                    "value": c.value,
                    "definitions": [
                        {
                            "file": str(d.file),
                            "line": d.line,
                            "syntax": d.syntax,
                            "value": d.value,
                        }
                        for d in c.definitions
                    ],
                },
            })
            edges.append({
                "source": scss_path,
                "target": token_id,
                "relation": "defines_token",
                "confidence": "extracted",
            })
        if c.usages:
            edges.append({
                "source": scss_path,
                "target": token_id,
                "relation": "uses_token",
                "confidence": "extracted",
            })
    return {"nodes": nodes, "edges": edges}


@pytest.fixture()
def pipeline(tmp_path: Path) -> tuple[DataPaths, dict[str, Any]]:
    """Run the full chain once: extract -> merge -> validate -> publish."""
    core_graph = _tokens_to_graph(CORE, "assets/_tokens.scss", CORE_SCSS)
    front_graph = _tokens_to_graph(FRONT, "assets/checkout.scss", FRONT_SCSS)

    merger = FederationMerger(
        detect_ffcss_tokens=True,
        dry_detection=True,
        repo_roles={CORE: "core", FRONT: "frontend"},
    )
    master = merger.merge_group(
        group=GROUP, repo_graphs=[(CORE, core_graph), (FRONT, front_graph)]
    )

    master_path = tmp_path / "graphs" / GROUP / "_master" / "graph.json"
    master_path.parent.mkdir(parents=True)
    master_path.write_text(json.dumps(master))
    APIIndexPublisher().publish(master, tmp_path / "vaults" / GROUP / "index")
    return DataPaths(root=tmp_path), master


def test_master_validates_against_graph_v1(pipeline: tuple[DataPaths, dict[str, Any]]) -> None:
    _, master = pipeline
    graph = Graph.model_validate(master)
    assert graph.repo == "_master"
    assert not graph.validate_edge_relations()


def test_ffcss_resolver_marks_core_token_canonical(
    pipeline: tuple[DataPaths, dict[str, Any]],
) -> None:
    _, master = pipeline
    canonical = [
        n for n in master["nodes"]
        if n.get("kind") == "ffcss_token" and n["metadata"].get("canonical")
    ]
    assert {n["name"] for n in canonical} == {"color-primary", "spacing-md"}
    assert all(n["metadata"]["_repo"] == CORE for n in canonical)
    relations = {e["relation"] for e in master["edges"]}
    assert "overrides_token" in relations


def test_query_surface_finds_extracted_token(
    pipeline: tuple[DataPaths, dict[str, Any]],
) -> None:
    paths, _ = pipeline
    hits = _route_query(paths, "primary", scope=GROUP, limit=10)
    names = {h["meta"].get("name") for h in hits}
    assert "color-primary" in names


def test_path_surface_walks_defines_edge(
    pipeline: tuple[DataPaths, dict[str, Any]],
) -> None:
    paths, _ = pipeline
    payload = shortest_path_payload(
        paths.root / "graphs",
        f"{GROUP}/{CORE}:assets/_tokens.scss",
        f"{GROUP}/{CORE}:ffcss:color-primary",
    )
    assert payload["hops"] == 1


async def test_explain_surface_shows_token_neighbors(
    pipeline: tuple[DataPaths, dict[str, Any]],
) -> None:
    paths, _ = pipeline
    explain = _build_explain_executor(paths)
    out = await explain({"node_id": f"{GROUP}/{CORE}:ffcss:color-primary"})
    assert out["kind"] == "ffcss_token"
    in_relations = {n["relation"] for n in out["neighbors_in"]}
    assert "defines_token" in in_relations


async def test_ffcss_surface_repo_filter_and_usage(
    pipeline: tuple[DataPaths, dict[str, Any]],
) -> None:
    paths, _ = pipeline
    ffcss = _build_ffcss_executor(paths)

    tokens = await ffcss({"group": GROUP, "mode": "tokens", "repo": FRONT})
    assert [t["name"] for t in tokens["tokens"]] == ["color-primary"]
    assert tokens["tokens"][0]["repo"] == FRONT

    usage = await ffcss({"group": GROUP, "mode": "usage"})
    used = {u["token"] for u in usage["usage"]}
    assert {"color-primary", "spacing-md"} <= used
