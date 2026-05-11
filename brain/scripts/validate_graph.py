"""CLI: validate graph.json against schema v1.

Exit codes: 0 valid, 1 invalid, 2 IO error / argparse usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from brain.core.graph_schema import Graph


def validate_file(path: Path) -> int:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        graph = Graph.model_validate(data)
    except ValidationError as exc:
        print(f"ERROR: schema validation failed:\n{exc}", file=sys.stderr)
        return 1

    print(
        f"OK Schema v1 valid\n"
        f"  group: {graph.group}, repo: {graph.repo}\n"
        f"  built_by: {graph.built_by}\n"
        f"  nodes: {len(graph.nodes)}, edges: {len(graph.edges)}"
    )

    bad_relations = graph.validate_edge_relations()
    if bad_relations:
        print(f"  warnings: {len(bad_relations)} edges with non-whitelist relation:")
        for line in bad_relations[:5]:
            print(f"    - {line}")

    dangling = graph.validate_edge_node_refs()
    if dangling:
        print(f"  info: {len(dangling)} edges reference nodes not in this graph "
              "(cross-repo refs, expected)")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate graph.json against schema v1")
    parser.add_argument("path", type=Path, help="Path to graph.json")
    args = parser.parse_args()
    return validate_file(args.path)


if __name__ == "__main__":
    sys.exit(main())
