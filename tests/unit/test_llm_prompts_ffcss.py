"""Tests for LLM extraction prompts with FFCSS section."""
from __future__ import annotations

from brain.llm.prompts import (
    FFCSS_RULES_SECTION,
    build_extraction_system_prompt,
)


def test_base_prompt_has_schema_and_relations() -> None:
    prompt = build_extraction_system_prompt(include_ffcss=False)
    assert '"nodes"' in prompt
    assert '"edges"' in prompt
    assert "imports" in prompt
    assert "semantically_similar_to" in prompt
    assert "ffcss_token" not in prompt
    assert "defines_token" not in prompt


def test_ffcss_prompt_includes_rules_and_relations() -> None:
    prompt = build_extraction_system_prompt(include_ffcss=True, prefix="dt-")
    assert "ffcss_token" in prompt
    for rel in (
        "defines_token",
        "uses_token",
        "overrides_token",
        "duplicates_token",
    ):
        assert rel in prompt
    assert "dt-" in prompt
    assert "scss-css-bridge" in prompt


def test_ffcss_prompt_with_custom_prefix() -> None:
    prompt = build_extraction_system_prompt(include_ffcss=True, prefix="mylib-")
    assert "mylib-" in prompt
    assert "dt-" not in prompt


def test_ffcss_prompt_with_empty_prefix_documents_all_tokens_policy() -> None:
    prompt = build_extraction_system_prompt(include_ffcss=True, prefix="")
    assert "empty" in prompt.lower()


def test_ffcss_rules_section_is_exported() -> None:
    assert isinstance(FFCSS_RULES_SECTION, str)
    assert "ffcss_token" in FFCSS_RULES_SECTION
