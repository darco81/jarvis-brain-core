"""MockBackend tests. Ported from the private jarvis-brain suite."""
from pathlib import Path

import pytest

from brain.graphify_adapter.backends import ExtractionResult, MockBackend


@pytest.mark.asyncio
async def test_mock_backend_returns_deterministic_result(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    return 1\n")
    b = MockBackend(fixture={str(f): {"nodes": [{"id": "a.foo"}], "edges": []}})
    result: ExtractionResult = await b.extract_semantic([f])
    assert result.nodes[0]["id"] == "a.foo"
    assert result.input_tokens == 0
    assert result.output_tokens == 0
