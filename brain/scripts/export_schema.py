"""Export Pydantic Graph model -> JSON Schema file.

Usage:
  python -m brain.scripts.export_schema > schemas/graph_v1.json
"""

from __future__ import annotations

import json
import sys

from brain.core.graph_schema import Graph


def main() -> int:
    schema = Graph.model_json_schema()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
