"""Tests for BrainFfcssArgs and brain_ffcss tool definition."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_brain_ffcss_args_accepts_tokens_mode_minimal() -> None:
    from brain.api.mcp_tools import BrainFfcssArgs
    a = BrainFfcssArgs(group="example-group", mode="tokens")
    assert a.group == "example-group"
    assert a.mode == "tokens"
    assert a.repo is None


def test_brain_ffcss_args_accepts_usage_with_repo() -> None:
    from brain.api.mcp_tools import BrainFfcssArgs
    a = BrainFfcssArgs(group="example-group", repo="example-front-a", mode="usage")
    assert a.repo == "example-front-a"
    assert a.mode == "usage"


def test_brain_ffcss_args_rejects_invalid_mode() -> None:
    from brain.api.mcp_tools import BrainFfcssArgs
    with pytest.raises(ValidationError):
        BrainFfcssArgs(group="g", mode="invalid")


def test_brain_ffcss_args_rejects_empty_group() -> None:
    from brain.api.mcp_tools import BrainFfcssArgs
    with pytest.raises(ValidationError):
        BrainFfcssArgs(group="", mode="tokens")


def test_brain_ffcss_in_tool_definitions() -> None:
    from brain.api.mcp_tools import TOOL_DEFINITIONS
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert "brain_ffcss" in names
    ff = next(t for t in TOOL_DEFINITIONS if t["name"] == "brain_ffcss")
    schema = ff["inputSchema"]
    props = schema.get("properties") or {}
    defs = schema.get("$defs", {}).get("BrainFfcssArgs", {}).get("properties", {})
    assert "group" in props or "group" in defs
