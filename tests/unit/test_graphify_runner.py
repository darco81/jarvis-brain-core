"""GraphifyRunner with MockBackend - the Path A demo without any network.

Proves the README claim end-to-end: the LLM path emits the same node/edge
shapes Path B does, and the runner's output feeds the merger unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from brain.federation.merger import FederationMerger
from brain.graphify_adapter.backends import MockBackend
from brain.graphify_adapter.router import ModelRouter
from brain.graphify_adapter.runner import GraphifyRunner


def _fixture_for(f: Path) -> dict[str, dict[str, Any]]:
    return {
        str(f): {
            "nodes": [
                {
                    "id": "useCart",
                    "kind": "function",
                    "name": "useCart",
                    "file": "composables/useCart.ts",
                    "line": 1,
                    "metadata": {},
                }
            ],
            "edges": [],
        }
    }


@pytest.mark.asyncio
async def test_runner_writes_graph_and_reports_counts(tmp_path: Path) -> None:
    src = tmp_path / "repo" / "composables" / "useCart.ts"
    src.parent.mkdir(parents=True)
    src.write_text("export function useCart() {}")

    runner = GraphifyRunner(
        router=ModelRouter(qwen_available=False),
        backend=MockBackend(fixture=_fixture_for(src)),
    )
    out = tmp_path / "graphs" / "repo" / "graph.json"
    result = await runner.run(
        repo_path=tmp_path / "repo",
        output=out,
        mode="full",
        changed_files=None,
    )

    assert result.nodes_count == 1
    assert result.model_used == "mock"
    graph = json.loads(out.read_text())
    assert graph["nodes"][0]["name"] == "useCart"


@pytest.mark.asyncio
async def test_runner_output_feeds_merger(tmp_path: Path) -> None:
    src = tmp_path / "repo" / "useCart.ts"
    src.parent.mkdir(parents=True)
    src.write_text("export function useCart() {}")

    runner = GraphifyRunner(
        router=ModelRouter(qwen_available=False),
        backend=MockBackend(fixture=_fixture_for(src)),
    )
    out = tmp_path / "graph.json"
    await runner.run(
        repo_path=tmp_path / "repo", output=out, mode="full", changed_files=None
    )

    graph = json.loads(out.read_text())
    master = FederationMerger().merge_group(
        group="example-group", repo_graphs=[("app-core", graph)]
    )
    node = next(n for n in master["nodes"] if n["name"] == "useCart")
    assert node["id"] == "example-group/app-core:useCart"
    assert node["metadata"]["_repo"] == "app-core"


@pytest.mark.asyncio
async def test_runner_incremental_skips_missing_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "kept.py").write_text("x = 1")

    runner = GraphifyRunner(
        router=ModelRouter(qwen_available=False),
        backend=MockBackend(fixture={}),
    )
    out = tmp_path / "graph.json"
    result = await runner.run(
        repo_path=repo,
        output=out,
        mode="incremental",
        changed_files=["kept.py", "deleted.py"],
    )
    assert result.skipped_count == 1
