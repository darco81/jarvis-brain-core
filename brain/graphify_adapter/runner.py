"""GraphifyRunner: orchestrates file collection, LLM extraction, atomic write.

Semantic-only extraction per repo - federation happens downstream in
FederationMerger. Ported from the private jarvis-brain repo (sanitized).
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import structlog

from brain.graphify_adapter.backends import (
    BackendUnavailable,
    ExtractionResult,
    LLMBackend,
)
from brain.graphify_adapter.router import Mode, ModelRouter

logger = structlog.get_logger(__name__)

EXCLUDED_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", ".next", ".nuxt", ".output",
    "coverage", "htmlcov", ".tox",
})


@dataclass(frozen=True)
class RunResult:
    nodes_count: int
    edges_count: int
    model_used: str
    input_tokens: int
    output_tokens: int
    skipped_count: int = 0  # files requested in incremental but not found on disk


class GraphifyRunner:
    """Orchestrates file collection + LLM extraction + atomic graph write.

    The ``ModelRouter`` picks a backend per request (``qwen-coder-local`` or
    ``openrouter``). When the router chooses Qwen and ``qwen_backend`` is
    configured, extraction is attempted there first. Any ``BackendUnavailable``
    is caught and the request is retried transparently on the default
    ``backend`` (OpenRouter). ``RunResult.model_used`` and the graph JSON's
    ``model`` field always reflect the backend that actually produced the
    data, not the router's initial pick.
    """

    def __init__(
        self,
        router: ModelRouter,
        backend: LLMBackend,
        qwen_backend: LLMBackend | None = None,
    ) -> None:
        self._router = router
        self._backend = backend
        self._qwen_backend = qwen_backend

    async def run(
        self,
        repo_path: Path,
        output: Path,
        mode: Mode,
        changed_files: list[str] | None,
    ) -> RunResult:
        files, skipped = self._collect_files(repo_path, mode, changed_files)
        if not files:
            # Incremental callers can legally end up here when every listed
            # file was deleted on disk. Writing an empty graph would wipe
            # the repo's previous contribution to the group-level merge, so
            # we instead leave the existing output untouched and report a
            # no-op.
            logger.warning(
                "runner.no_files_to_extract",
                mode=mode,
                skipped=skipped,
                output=str(output),
            )
            decision = self._router.select(mode=mode, changed_count=0)
            return RunResult(
                nodes_count=0,
                edges_count=0,
                model_used=decision.model,
                input_tokens=0,
                output_tokens=0,
                skipped_count=skipped,
            )
        decision = self._router.select(mode=mode, changed_count=len(files))
        extraction, model_used = await self._extract(files, decision.model)
        graph = {
            "version": 1,
            "mode": mode,
            "model": model_used,
            "nodes": extraction.nodes,
            "edges": extraction.edges,
        }
        self._atomic_write_json(output, graph)
        return RunResult(
            nodes_count=len(extraction.nodes),
            edges_count=len(extraction.edges),
            model_used=model_used,
            input_tokens=extraction.input_tokens,
            output_tokens=extraction.output_tokens,
            skipped_count=skipped,
        )

    async def _extract(
        self, files: list[Path], model: str
    ) -> tuple[ExtractionResult, str]:
        """Dispatch to qwen → openrouter fallback, or straight to default backend."""
        if model == "qwen-coder-local" and self._qwen_backend is not None:
            try:
                result = await self._qwen_backend.extract_semantic(files)
                return result, self._qwen_backend.model_name
            except BackendUnavailable as err:
                logger.warning(
                    "qwen.unavailable", error=str(err), fallback="openrouter"
                )
                # Fall through to default backend.
        result = await self._backend.extract_semantic(files)
        return result, self._backend.model_name

    def _collect_files(
        self, repo_path: Path, mode: Mode, changed: list[str] | None
    ) -> tuple[list[Path], int]:
        if mode == "incremental" and changed is not None:
            result: list[Path] = []
            skipped = 0
            for c in changed:
                p = repo_path / c
                if p.exists():
                    result.append(p)
                else:
                    skipped += 1
            return result, skipped

        allowed = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".md",
                   ".yml", ".yaml", ".json", ".css", ".scss"}
        out: list[Path] = []
        for p in repo_path.rglob("*"):
            if not p.is_file() or p.suffix not in allowed:
                continue
            # Skip if any ancestor directory is in the exclusion set
            if any(part in EXCLUDED_DIRS for part in p.relative_to(repo_path).parts):
                continue
            out.append(p)
        return out, 0

    def _atomic_write_json(self, output: Path, data: dict) -> None:  # type: ignore[type-arg]
        """Write JSON atomically via tempfile + fsync + rename."""
        output.parent.mkdir(parents=True, exist_ok=True)
        # Temp file placed in same directory as target to ensure os.replace is atomic
        # (same filesystem). Prefix `.` hides from ls; suffix identifies stale temps.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".graph-", suffix=".json.tmp", dir=str(output.parent)
        )
        try:
            with os.fdopen(fd, "w") as f:
                # Compact JSON: smaller files, faster IO
                # inspect via `jq .` or re-dump with indent=2
                json.dump(data, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, output)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
