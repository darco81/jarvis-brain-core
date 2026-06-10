"""Circuit breaker - minimal open/closed with TTL expiry.

There is no explicit half-open state: the first request after TTL simply
runs normally and either confirms recovery (stays closed) or re-opens the
breaker on failure.

The production deployment backs this with Redis so the breaker state is
shared across worker processes. The educational version ships an in-memory
implementation with the same async API - single-process, which is all the
local pipeline needs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


class CircuitBreaker(Protocol):
    """Async open/closed breaker contract shared by both implementations."""

    async def is_open(self) -> bool: ...

    async def open(self, ttl_s: int = 300) -> None: ...

    async def close(self) -> None: ...


@dataclass
class InMemoryCircuitBreaker:
    name: str
    _open_until: float = field(default=0.0, init=False)

    async def is_open(self) -> bool:
        """Return True if the circuit is currently open."""
        return time.monotonic() < self._open_until

    async def open(self, ttl_s: int = 300) -> None:
        """Open the circuit for ``ttl_s`` seconds."""
        if ttl_s <= 0:
            raise ValueError(f"ttl_s must be >= 1, got {ttl_s}")
        self._open_until = time.monotonic() + ttl_s

    async def close(self) -> None:
        """Force-close the circuit (manual recovery)."""
        self._open_until = 0.0
