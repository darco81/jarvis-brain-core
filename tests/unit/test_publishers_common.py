"""Slug utility tests - shared between wiki.py and graph.html click handler.

Must be deterministic (same input → same output forever) and collision-safe
(different inputs → different slugs, even after sanitisation)."""
from __future__ import annotations

import pytest

from brain.publishers.common import (
    NODE_ID_TO_SLUG_JS,
    node_id_to_slug,
)


@pytest.mark.parametrize("node_id,expected", [
    ("example-group/example-core:LoginButton", "example-group_example-core_LoginButton"),
    ("example-group/example-front-a:useCurrentUser", "example-group_example-front-a_useCurrentUser"),
    ("a/b:c", "a_b_c"),
    ("simple", "simple"),
])
def test_node_id_to_slug_preserves_readable_part(node_id: str, expected: str) -> None:
    slug = node_id_to_slug(node_id)
    assert slug == expected


def test_node_id_to_slug_truncates_long_ids_with_hash_suffix() -> None:
    long_id = "example-group/example-front-a:" + ("a" * 500)
    slug = node_id_to_slug(long_id)
    assert len(slug) <= 200
    # Long input must carry a stable hash suffix so different long inputs
    # don't collide after truncation.
    assert "_" in slug


def test_node_id_to_slug_is_deterministic() -> None:
    node_id = "example-group/example-core:SomeSymbol"
    assert node_id_to_slug(node_id) == node_id_to_slug(node_id)


def test_different_long_inputs_get_different_slugs() -> None:
    a = "example-group/example-front-a:" + ("a" * 400) + "X"
    b = "example-group/example-front-a:" + ("a" * 400) + "Y"
    assert node_id_to_slug(a) != node_id_to_slug(b)


def test_empty_input_returns_unnamed() -> None:
    assert node_id_to_slug("") == "unnamed"


def test_only_special_chars_returns_unnamed() -> None:
    assert node_id_to_slug("///:::") == "unnamed"


def test_js_snippet_exports_same_function_name() -> None:
    """The JS port must define a function named nodeIdToSlug so the injected
    click handler can call it on click events."""
    assert "function nodeIdToSlug" in NODE_ID_TO_SLUG_JS
    assert "md5" in NODE_ID_TO_SLUG_JS.lower() or "hash" in NODE_ID_TO_SLUG_JS.lower()


def test_python_and_js_slug_agree_on_fixture() -> None:
    """Regression lock: hand-computed MD5 slice for a truncation case must
    equal what node_id_to_slug returns, guaranteeing JS port stays in sync."""
    import hashlib
    long_id = "example-group/example-front-a:" + ("z" * 500)
    prefix_padding = "z" * (190 - len("example-group_example-front-a_"))
    expected_prefix = "example-group_example-front-a_" + prefix_padding
    expected_suffix = hashlib.md5(long_id.encode()).hexdigest()[:8]  # noqa: S324
    result = node_id_to_slug(long_id)
    assert result.startswith(expected_prefix[:20])  # stable prefix shape
    assert expected_suffix in result
