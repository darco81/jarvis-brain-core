"""Deterministic model routing - which backend handles which job size.

Ported from the private jarvis-brain repo (sanitized).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["incremental", "full", "deep"]


@dataclass
class RoutingDecision:
    model: str
    reason: str


class ModelRouter:
    def __init__(self, qwen_available: bool = False) -> None:
        self._qwen_available = qwen_available

    def select(self, mode: Mode, changed_count: int) -> RoutingDecision:
        if mode == "deep":
            return RoutingDecision("openrouter", "deep_mode")
        if mode == "incremental" and changed_count < 20:
            if self._qwen_available:
                return RoutingDecision("qwen-coder-local", "small_incremental")
            return RoutingDecision("openrouter", "qwen_unavailable,small_incremental")
        return RoutingDecision("openrouter", "default")
