"""ModelRouter tests. Ported from the private jarvis-brain suite."""
import pytest

from brain.graphify_adapter.router import ModelRouter, RoutingDecision


@pytest.mark.parametrize(
    "mode,changed,expected",
    [
        ("deep", 1, "openrouter"),
        ("deep", 9999, "openrouter"),
        ("incremental", 5, "qwen-coder-local"),
        ("incremental", 19, "qwen-coder-local"),
        ("incremental", 20, "openrouter"),
        ("incremental", 100, "openrouter"),
        ("full", 1, "openrouter"),
        ("full", 9999, "openrouter"),
    ],
)
def test_model_routing_decisions(mode: str, changed: int, expected: str) -> None:
    router = ModelRouter(qwen_available=True)
    d: RoutingDecision = router.select(mode=mode, changed_count=changed)  # type: ignore[arg-type]
    assert d.model == expected


def test_when_qwen_unavailable_fallback_to_openrouter() -> None:
    router = ModelRouter(qwen_available=False)
    d = router.select(mode="incremental", changed_count=5)  # type: ignore[arg-type]
    assert d.model == "openrouter"
    assert "qwen_unavailable" in d.reason
