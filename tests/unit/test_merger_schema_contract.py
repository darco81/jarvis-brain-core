"""Contract tests: merger output must be a valid Graph v1 document.

Regression guard for the v0.1.0 gap where FederationMerger emitted an
envelope (`version`/top-level `_repo`) that failed Graph.model_validate,
silently breaking the brain_ffcss repo filter on real master graphs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from brain.core.graph_schema import Graph
from brain.federation.merger import FederationMerger


def _valid_repo_graph(component: str, imported: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": component, "kind": "component", "name": component},
        ],
        "edges": [
            {
                "source": component,
                "target": imported,
                "relation": "imports",
                "confidence": "EXTRACTED",
            },
        ],
    }


def _ffcss_master(group: str) -> dict[str, Any]:
    """Master built by the real merger from schema-valid token graphs."""
    g_core = {
        "nodes": [
            {
                "id": "ffcss:color-primary",
                "kind": "ffcss_token",
                "name": "color-primary",
                "metadata": {"token_type": "css-variable", "value": "#000"},
            },
        ],
        "edges": [],
    }
    g_front = {
        "nodes": [
            {
                "id": "ffcss:color-accent",
                "kind": "ffcss_token",
                "name": "color-accent",
                "metadata": {"token_type": "css-variable", "value": "#111"},
            },
        ],
        "edges": [],
    }
    merger = FederationMerger()
    return merger.merge_group(
        group=group,
        repo_graphs=[("app-core", g_core), ("app-front-a", g_front)],
    )


def test_merge_group_output_validates_against_graph_v1() -> None:
    g_core = {
        "nodes": [{"id": "Button", "kind": "component", "name": "Button"}],
        "edges": [],
    }
    g_front = _valid_repo_graph("Checkout", "Button")
    merger = FederationMerger(
        detect_cross_repo_imports=True,
        repo_roles={"app-core": "core", "app-front-a": "frontend"},
    )
    master = merger.merge_group(
        group="example-group",
        repo_graphs=[("app-core", g_core), ("app-front-a", g_front)],
    )

    graph = Graph.model_validate(master)

    assert graph.schema_version == "v1"
    assert graph.group == "example-group"
    assert graph.repo == "_master"
    node = next(n for n in graph.nodes if n.name == "Checkout")
    assert node.metadata["_repo"] == "app-front-a"
    assert node.metadata["_group"] == "example-group"
    assert all(e.confidence == "extracted" for e in graph.edges)
    cross = [e for e in graph.edges if e.relation == "imports_from_parent_repo"]
    assert len(cross) == 1


def test_merge_group_does_not_mutate_input_graphs() -> None:
    g_core = {
        "nodes": [{"id": "Button", "kind": "component", "name": "Button"}],
        "edges": [],
    }
    merger = FederationMerger()
    merger.merge_group(group="g", repo_graphs=[("r", g_core)])
    assert g_core["nodes"][0] == {"id": "Button", "kind": "component", "name": "Button"}


@pytest.mark.asyncio
async def test_ffcss_repo_filter_works_on_real_merger_output(tmp_path: Path) -> None:
    from brain.api.executors import _build_ffcss_executor
    from brain.core.paths import DataPaths

    master = _ffcss_master("example-group")
    mp = tmp_path / "graphs" / "example-group" / "_master" / "graph.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps(master))

    exec_fn = _build_ffcss_executor(DataPaths(root=tmp_path))
    out = await exec_fn({"group": "example-group", "mode": "tokens", "repo": "app-front-a"})

    assert [t["name"] for t in out["tokens"]] == ["color-accent"]
    assert out["tokens"][0]["repo"] == "app-front-a"


@pytest.mark.asyncio
async def test_ffcss_repo_falls_back_to_top_level_for_legacy_masters(tmp_path: Path) -> None:
    """Masters written by the v0.1.0 merger carry `_repo` top-level on nodes."""
    from brain.api.executors import _build_ffcss_executor
    from brain.core.paths import DataPaths

    legacy = {
        "nodes": [
            {
                "id": "example-group/app-core:ffcss:color-primary",
                "kind": "ffcss_token",
                "name": "color-primary",
                "_repo": "app-core",
                "_group": "example-group",
                "metadata": {"value": "#000"},
            },
        ],
        "edges": [],
    }
    mp = tmp_path / "graphs" / "example-group" / "_master" / "graph.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps(legacy))

    exec_fn = _build_ffcss_executor(DataPaths(root=tmp_path))
    out = await exec_fn({"group": "example-group", "mode": "tokens", "repo": "app-core"})

    assert [t["name"] for t in out["tokens"]] == ["color-primary"]
    assert out["tokens"][0]["repo"] == "app-core"
