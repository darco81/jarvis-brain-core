"""CLI contract: `python -m brain.scripts.validate_graph <path>`.

Exit codes:
  0 - schema-valid (possibly with soft warnings)
  1 - schema-invalid (structural errors)
  2 - file not found / unreadable
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _valid_graph_dict() -> dict:
    return {
        "schema_version": "v1",
        "group": "example-group",
        "repo": "example-front-a",
        "built_at": datetime.now(UTC).isoformat(),
        "built_by": "cc-local",
        "nodes": [{
            "id": "example-group/example-front-a:Button",
            "kind": "class", "name": "Button",
            "file": "src/Button.tsx", "line": 1,
            "community": None, "metadata": {},
        }],
        "edges": [],
        "stats": {"nodes_count": 1, "edges_count": 0},
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_valid_graph_exits_zero(tmp_path: Path) -> None:
    f = tmp_path / "graph.json"
    _write_json(f, _valid_graph_dict())
    result = subprocess.run(
        [sys.executable, "-m", "brain.scripts.validate_graph", str(f)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "valid" in result.stdout.lower()


def test_missing_file_exits_2(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "brain.scripts.validate_graph",
         str(tmp_path / "does-not-exist.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 2


def test_bad_json_exits_1(tmp_path: Path) -> None:
    f = tmp_path / "broken.json"
    f.write_text("{not valid json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "brain.scripts.validate_graph", str(f)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "JSON" in result.stderr


def test_schema_violation_exits_1(tmp_path: Path) -> None:
    data = _valid_graph_dict()
    del data["group"]
    f = tmp_path / "bad.json"
    _write_json(f, data)
    result = subprocess.run(
        [sys.executable, "-m", "brain.scripts.validate_graph", str(f)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "validation failed" in result.stderr.lower()


def test_soft_warnings_still_exit_zero(tmp_path: Path) -> None:
    data = _valid_graph_dict()
    data["edges"].append({
        "source": "example-group/example-front-a:Button",
        "target": "example-group/example-front-a:Missing",
        "relation": "imports",
        "confidence": "extracted", "metadata": {},
    })
    f = tmp_path / "soft.json"
    _write_json(f, data)
    result = subprocess.run(
        [sys.executable, "-m", "brain.scripts.validate_graph", str(f)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "cross-repo refs" in result.stdout
