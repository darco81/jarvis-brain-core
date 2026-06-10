"""InMemoryCircuitBreaker - TTL open/close semantics."""

from __future__ import annotations

import pytest

from brain.core.circuit import InMemoryCircuitBreaker


@pytest.mark.asyncio
async def test_breaker_starts_closed() -> None:
    cb = InMemoryCircuitBreaker(name="t")
    assert await cb.is_open() is False


@pytest.mark.asyncio
async def test_open_then_close(monkeypatch: pytest.MonkeyPatch) -> None:
    cb = InMemoryCircuitBreaker(name="t")
    await cb.open(ttl_s=300)
    assert await cb.is_open() is True
    await cb.close()
    assert await cb.is_open() is False


@pytest.mark.asyncio
async def test_open_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = {"t": 1000.0}
    monkeypatch.setattr("brain.core.circuit.time.monotonic", lambda: now["t"])
    cb = InMemoryCircuitBreaker(name="t")
    await cb.open(ttl_s=60)
    assert await cb.is_open() is True
    now["t"] += 61
    assert await cb.is_open() is False


@pytest.mark.asyncio
async def test_open_rejects_non_positive_ttl() -> None:
    cb = InMemoryCircuitBreaker(name="t")
    with pytest.raises(ValueError, match="ttl_s"):
        await cb.open(ttl_s=0)
