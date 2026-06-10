"""OpenRouterBackend - paid fallback when local Qwen is unavailable.

httpx.MockTransport simulates OpenRouter's POST /api/v1/chat/completions
without a real network call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from brain.graphify_adapter.backends import OpenRouterBackend


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _make_backend(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    model: str = "anthropic/claude-haiku-4.5",
    batch_size: int = 20,
) -> OpenRouterBackend:
    return OpenRouterBackend(
        api_key="sk-or-v1-test",
        model=model,
        batch_size=batch_size,
        transport=_transport(handler),
    )


@pytest.mark.asyncio
async def test_extract_happy_path_returns_nodes_edges_and_tokens(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-or-v1-test"
        body = json.loads(request.content)
        assert body["model"] == "anthropic/claude-haiku-4.5"
        assert body["response_format"] == {"type": "json_object"}
        content = json.dumps(
            {
                "nodes": [
                    {
                        "id": "example-group/app-front-a:A",
                        "kind": "class",
                        "name": "A",
                        "file": "src/A.ts",
                        "line": 1,
                        "metadata": {},
                    }
                ],
                "edges": [],
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            },
        )

    src = tmp_path / "A.ts"
    src.write_text("class A {}")

    backend = _make_backend(handler)
    result = await backend.extract_semantic([src])

    assert len(result.nodes) == 1
    assert result.nodes[0]["id"] == "example-group/app-front-a:A"
    assert result.edges == []
    assert result.model == "anthropic/claude-haiku-4.5"
    assert result.input_tokens == 100
    assert result.output_tokens == 30


@pytest.mark.asyncio
async def test_extract_raises_value_error_on_non_json_content(
    tmp_path: Path,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "I cannot do that."}}]},
        )

    src = tmp_path / "a.py"
    src.write_text("x = 1")

    backend = _make_backend(handler)
    with pytest.raises(ValueError, match="non-JSON"):
        await backend.extract_semantic([src])


@pytest.mark.asyncio
async def test_extract_raises_on_http_5xx(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "openrouter down"})

    src = tmp_path / "a.py"
    src.write_text("pass")

    backend = _make_backend(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await backend.extract_semantic([src])


@pytest.mark.asyncio
async def test_extract_batches_files_and_accumulates_tokens(
    tmp_path: Path,
) -> None:
    """With batch_size=2 and 5 files, expect 3 POST calls and tokens summed."""

    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        content = json.dumps(
            {
                "nodes": [{"id": f"n{calls['n']}", "kind": "x"}],
                "edges": [],
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    files = []
    for i in range(5):
        f = tmp_path / f"f{i}.py"
        f.write_text(f"x = {i}")
        files.append(f)

    backend = _make_backend(handler, batch_size=2)
    result = await backend.extract_semantic(files)

    assert calls["n"] == 3  # 2 + 2 + 1
    assert len(result.nodes) == 3  # 1 per batch
    assert result.input_tokens == 30  # 10 * 3
    assert result.output_tokens == 15  # 5 * 3


@pytest.mark.asyncio
async def test_extract_includes_file_bodies_in_prompt(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["user_content"] = body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"nodes": [], "edges": []})}}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    src1 = tmp_path / "hello.py"
    src1.write_text("HELLO_MARKER = 42")
    src2 = tmp_path / "world.py"
    src2.write_text("WORLD_MARKER = 1")

    backend = _make_backend(handler)
    await backend.extract_semantic([src1, src2])

    assert "HELLO_MARKER = 42" in captured["user_content"]
    assert "hello.py" in captured["user_content"]
    assert "world.py" in captured["user_content"]


def test_openrouter_backend_has_model_name_attribute() -> None:
    """Required by LLMBackend protocol."""
    backend = OpenRouterBackend(api_key="x", model="anthropic/claude-haiku-4.5")
    assert backend.model_name == "anthropic/claude-haiku-4.5"
