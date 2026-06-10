"""LLM backend protocol + MockBackend + OpenRouterBackend + QwenLocalBackend.

Path A of the two ingestion paths: LLM extraction targeting the same graph
shapes the deterministic Path B emits. Ported from the private jarvis-brain
repo (sanitized). Requires the [llm] extra (httpx).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from brain.core.circuit import CircuitBreaker
from brain.llm.prompts import build_extraction_system_prompt

MAX_CHARS_PER_FILE = 8000


@dataclass
class ExtractionResult:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLMBackend(Protocol):
    """Structural interface for semantic extraction backends.

    model_name may be either a class attribute (MockBackend) or
    an instance attribute assigned in __init__ (OpenRouterBackend). Both
    satisfy structural subtyping per PEP 544.
    """

    model_name: str

    async def extract_semantic(self, files: list[Path]) -> ExtractionResult: ...


class MockBackend:
    """Deterministic backend for tests."""

    model_name = "mock"

    def __init__(self, fixture: dict[str, dict[str, Any]]) -> None:
        self._fixture = fixture

    async def extract_semantic(self, files: list[Path]) -> ExtractionResult:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for f in files:
            data = self._fixture.get(str(f), {})
            nodes.extend(data.get("nodes", []))
            edges.extend(data.get("edges", []))
        return ExtractionResult(nodes=nodes, edges=edges, model="mock")


def _common_parent(paths: list[Path]) -> Path:
    """Return the longest common parent directory of a list of absolute paths."""
    if not paths:
        return Path("/")
    parts_list = [p.parts for p in paths]
    common: tuple[str, ...] = parts_list[0]
    for other in parts_list[1:]:
        new_common: list[str] = []
        for a, b in zip(common, other, strict=False):
            if a == b:
                new_common.append(a)
            else:
                break
        common = tuple(new_common)
    return Path(*common) if common else Path("/")


class OpenRouterBackend:
    """Paid fallback when local Qwen is unavailable or for deep-mode jobs.

    Hits OpenRouter's OpenAI-compatible chat-completions endpoint. Defaults
    to anthropic/claude-haiku-4.5 (configurable per env). Transport-level
    failures and HTTP errors propagate; malformed JSON content raises
    ValueError so the runner surfaces a hard failure (this is the last
    backend in the chain - no further fallback).
    """

    _ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    _REQUEST_TIMEOUT_S = 120.0

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-haiku-4.5",
        batch_size: int = 20,
        system_prompt: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model_name = model
        self._batch = batch_size
        self._system_prompt = system_prompt or build_extraction_system_prompt(
            include_ffcss=False
        )
        self._transport = transport

    async def extract_semantic(self, files: list[Path]) -> ExtractionResult:
        result = ExtractionResult(model=self.model_name)
        repo_root = _common_parent(files) if files else Path.cwd()
        batches = [
            files[i : i + self._batch] for i in range(0, len(files), self._batch)
        ]
        async with httpx.AsyncClient(
            timeout=self._REQUEST_TIMEOUT_S, transport=self._transport
        ) as client:
            for batch in batches:
                user_prompt = self._build_user_prompt(batch, repo_root=repo_root)
                resp = await client.post(
                    self._ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model_name,
                        "messages": [
                            {"role": "system", "content": self._system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.0,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"OpenRouter returned non-JSON content: {exc}"
                    ) from exc
                result.nodes.extend(parsed.get("nodes", []))
                result.edges.extend(parsed.get("edges", []))
                usage = data.get("usage") or {}
                result.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
                result.output_tokens += int(usage.get("completion_tokens", 0) or 0)
        return result

    def _build_user_prompt(self, files: list[Path], repo_root: Path) -> str:
        parts: list[str] = []
        for f in files:
            try:
                body = f.read_text(errors="replace")[:MAX_CHARS_PER_FILE]
            except OSError:
                body = ""
            try:
                rel = f.relative_to(repo_root)
            except ValueError:
                rel = f
            parts.append(f"=== FILE: {rel} ===\n{body}")
        return "\n\n".join(parts)


# ----- Sprint 1 (Phase 2): Qwen local backend -----


class BackendUnavailable(RuntimeError):  # noqa: N818 - runner sentinel, not a user-facing error
    """Raised when a backend is temporarily not callable.

    The runner treats this as a signal to fall through to the next backend
    in the router chain (e.g., Qwen unavailable -> fall back to OpenRouter).
    """


_QWEN_EXTRACTION_SYSTEM_PROMPT = build_extraction_system_prompt(include_ffcss=False)


class QwenLocalBackend:
    """OpenAI-compatible Ollama client for incremental semantic extraction.

    Points at any OpenAI-compatible endpoint (a local Ollama by default).
    A simple circuit breaker skips the backend quickly when it is known to
    be unhealthy; a per-request timeout avoids hanging the runner on
    individual slow batches.

    Conforms to the ``LLMBackend`` protocol: takes ``list[Path]`` and
    returns ``ExtractionResult``. Raises ``BackendUnavailable`` when the
    runner should fall through to the next backend.
    """

    _MAX_CHARS_PER_FILE = MAX_CHARS_PER_FILE
    _MAX_CHUNK_CHARS = MAX_CHARS_PER_FILE * 3
    _CONSECUTIVE_FAILURE_THRESHOLD = 3

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        circuit_breaker: CircuitBreaker,
        request_timeout_s: float = 60.0,
        health_timeout_s: float = 0.5,
        circuit_open_s: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model
        self.circuit_breaker = circuit_breaker
        self.request_timeout_s = request_timeout_s
        self.health_timeout_s = health_timeout_s
        self.circuit_open_s = circuit_open_s
        self._transport = transport
        self._system_prompt = system_prompt or _QWEN_EXTRACTION_SYSTEM_PROMPT
        # Extraction-level failures (healthy server returning 500s, malformed
        # JSON, etc.) do not show up in the healthcheck, so we count them
        # here and trip the breaker after a small run of consecutive
        # failures. Reset on the first successful batch.
        self._consecutive_failures = 0

    async def _is_available(self) -> bool:
        """Check breaker + run a cheap /api/tags healthcheck.

        Opens the breaker on any transport failure or non-200 response.
        """
        if await self.circuit_breaker.is_open():
            return False
        try:
            async with httpx.AsyncClient(
                timeout=self.health_timeout_s, transport=self._transport
            ) as client:
                resp = await client.get(f"{self.endpoint}/api/tags")
        except (httpx.TimeoutException, httpx.TransportError):
            await self.circuit_breaker.open(ttl_s=self.circuit_open_s)
            return False
        if resp.status_code != 200:
            await self.circuit_breaker.open(ttl_s=self.circuit_open_s)
            return False
        return True

    async def extract_semantic(self, files: list[Path]) -> ExtractionResult:
        if not await self._is_available():
            raise BackendUnavailable("qwen circuit open or healthcheck failed")

        pairs = [(p, _safe_read(p)) for p in files]
        chunks = self._build_chunks(pairs)
        result = ExtractionResult(model=self.model_name)
        async with httpx.AsyncClient(
            timeout=self.request_timeout_s, transport=self._transport
        ) as client:
            for chunk in chunks:
                try:
                    resp = await client.post(
                        f"{self.endpoint}/v1/chat/completions",
                        json={
                            "model": self.model_name,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": self._system_prompt,
                                },
                                {"role": "user", "content": chunk},
                            ],
                            "response_format": {"type": "json_object"},
                            "temperature": 0.0,
                        },
                    )
                except (httpx.TimeoutException, httpx.TransportError) as err:
                    await self._record_failure()
                    raise BackendUnavailable(
                        f"qwen transport error: {err}"
                    ) from err
                if resp.status_code != 200:
                    await self._record_failure()
                    raise BackendUnavailable(
                        f"qwen returned {resp.status_code}"
                    )
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                except (KeyError, ValueError, json.JSONDecodeError) as err:
                    await self._record_failure()
                    raise BackendUnavailable(
                        f"qwen bad response: {err}"
                    ) from err
                result.nodes.extend(parsed.get("nodes", []))
                result.edges.extend(parsed.get("edges", []))
        self._consecutive_failures = 0
        return result

    async def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._CONSECUTIVE_FAILURE_THRESHOLD:
            await self.circuit_breaker.open(ttl_s=self.circuit_open_s)
            self._consecutive_failures = 0

    def _build_chunks(self, files: list[tuple[Path, str]]) -> list[str]:
        """Pack file blocks into prompt-sized chunks."""
        chunks: list[str] = []
        current: list[str] = []
        current_chars = 0
        for path, content in files:
            snippet = content[: self._MAX_CHARS_PER_FILE]
            block = f"### {path}\n```\n{snippet}\n```\n"
            if (
                current_chars + len(block) > self._MAX_CHUNK_CHARS
                and current
            ):
                chunks.append("\n".join(current))
                current = []
                current_chars = 0
            current.append(block)
            current_chars += len(block)
        if current:
            chunks.append("\n".join(current))
        return chunks


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""
