"""Unit tests for brain_explain MCP args schema."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_brain_explain_args_accepts_valid_node_id() -> None:
    from brain.api.mcp_tools import BrainExplainArgs

    args = BrainExplainArgs(node_id="example-group/example-front-a:LoginButton")
    assert args.node_id == "example-group/example-front-a:LoginButton"


def test_brain_explain_args_rejects_empty_node_id() -> None:
    from pydantic import ValidationError

    from brain.api.mcp_tools import BrainExplainArgs

    with pytest.raises(ValidationError):
        BrainExplainArgs(node_id="")


def test_brain_explain_args_rejects_overlong_node_id() -> None:
    from pydantic import ValidationError

    from brain.api.mcp_tools import BrainExplainArgs

    with pytest.raises(ValidationError):
        BrainExplainArgs(node_id="x" * 513)


def test_brain_explain_in_tool_definitions() -> None:
    from brain.api.mcp_tools import TOOL_DEFINITIONS

    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "brain_explain" in names


@pytest.mark.asyncio
async def test_brain_explain_surfaces_provenance_from_last_commit(tmp_path: Path) -> None:
    from brain.api.executors import _build_explain_executor
    from brain.core.paths import DataPaths

    master = {
        "nodes": [{
            "id": "example-group/example-front-a:useCart",
            "name": "useCart",
            "kind": "function",
            "file": "composables/useCart.ts",
            "line": 42,
            "metadata": {
                "community": 7,
                "last_commit": {
                    "sha": "a1b2c3d4",
                    "date": "2026-03-01T10:00:00Z",
                    "author": "Dariusz",
                },
            },
        }],
        "edges": [],
    }
    mp = tmp_path / "graphs" / "example-group" / "_master" / "graph.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps(master))
    paths = DataPaths(root=tmp_path)
    exec_fn = _build_explain_executor(paths)
    out = await exec_fn({"node_id": "example-group/example-front-a:useCart"})
    assert out["provenance"] == {
        "sha": "a1b2c3d4",
        "date": "2026-03-01T10:00:00Z",
        "author": "Dariusz",
    }


@pytest.mark.asyncio
async def test_brain_explain_provenance_is_none_when_missing(tmp_path: Path) -> None:
    from brain.api.executors import _build_explain_executor
    from brain.core.paths import DataPaths

    master = {
        "nodes": [{
            "id": "example-group/example-front-a:useCart",
            "name": "useCart",
            "kind": "function",
            "file": "f",
            "metadata": {},
        }],
        "edges": [],
    }
    mp = tmp_path / "graphs" / "example-group" / "_master" / "graph.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps(master))
    exec_fn = _build_explain_executor(DataPaths(root=tmp_path))
    out = await exec_fn({"node_id": "example-group/example-front-a:useCart"})
    assert out["provenance"] is None


@pytest.mark.asyncio
async def test_brain_explain_tolerates_edge_without_relation(tmp_path: Path) -> None:
    """An edge lacking 'relation' (merger only requires source+target) must
    not raise KeyError -> -32603; it should surface with a blank relation."""
    from brain.api.executors import _build_explain_executor
    from brain.core.paths import DataPaths

    master = {
        "nodes": [
            {"id": "g/r:A", "name": "A", "kind": "function"},
            {"id": "g/r:B", "name": "B", "kind": "function"},
        ],
        "edges": [
            {"source": "g/r:A", "target": "g/r:B"},  # no 'relation', no 'confidence'
        ],
    }
    mp = tmp_path / "graphs" / "g" / "_master" / "graph.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps(master))
    out = await _build_explain_executor(DataPaths(root=tmp_path))({"node_id": "g/r:A"})
    assert out["neighbors_out"] == [{"id": "g/r:B", "relation": "", "confidence": ""}]
