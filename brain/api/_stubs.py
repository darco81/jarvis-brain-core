"""Educational-version stubs for production-only API concerns.

The production deployment of jarvis-brain wires auth (per-dev tokens with
scopes), rate limiting, and query audit logging on every MCP endpoint. Those
concerns are intentionally omitted from this educational destylat - the focus
is the method (graph extraction, federation, FTS5 query, MCP shape), not
multi-tenant production hardening.

These stubs keep the same call shapes the production code uses, so the
router-construction code can stay identical to the private repo and a reader
can clearly see where auth/rate-limit/audit would attach in a real deployment.

For a production-ready multi-tenant deployment, see https://sdet.it/services.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DevTokenInfo:
    """Identity envelope returned by `TokenVerifier` in production."""

    name: str = "local-dev"
    scopes: tuple[str, ...] = ("query",)


class RateLimiter:
    """No-op stand-in for the production token-bucket rate limiter."""

    async def check(self, *_: Any, **__: Any) -> None:  # noqa: D401
        return None


class TokenVerifier:
    """No-op stand-in for the production bearer-token verifier.

    Production version verifies a bearer token against the dev_tokens table,
    enforces scope, and applies per-token rate limiting. The educational
    version accepts every call and returns a constant identity.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._info = DevTokenInfo()

    async def __call__(self, *_: Any, **__: Any) -> DevTokenInfo:
        return self._info


def bearer_dependency(_dev_token: str) -> Callable[..., Awaitable[None]]:
    """No-op stand-in for the production single-token bearer dependency."""

    async def _noop() -> None:
        return None

    return _noop


async def log_query(*_: Any, **__: Any) -> None:
    """No-op stand-in for the production query audit log writer."""
    return
