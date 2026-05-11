from __future__ import annotations

from pathlib import Path

from brain.extractors.ffcss import (
    FFCSSUsage,
    extract_from_source,
)

SCSS_SOURCE = """\
:root {
  --dt-color-primary: #1a2b3c;
  --dt-spacing-md: 1rem;
  --unprefixed: red;
}

$dt-font-base: 'Inter', sans-serif;
$other: 12px;

.btn {
  color: var(--dt-color-primary);
  padding: var(--dt-spacing-md);
  background: $dt-font-base;
  border: var(--unprefixed);
}
"""

VUE_SOURCE = """\
<template>
  <div class="hero">Hero</div>
</template>

<style lang="scss">
.hero {
  font-family: $dt-font-base;
  color: var(--dt-color-primary);
  padding: var(--dt-spacing-md);
}
</style>
"""


def test_extracts_css_variable_definitions_with_prefix() -> None:
    cands = extract_from_source(
        path=Path("assets/scss/_tokens.scss"),
        source=SCSS_SOURCE,
        prefix="dt-",
    )
    defs = {c.token_name: c for c in cands if c.definitions}
    assert "color-primary" in defs
    assert "spacing-md" in defs
    assert "font-base" in defs
    assert "unprefixed" not in defs
    assert "other" not in defs


def test_css_variable_definition_records_value_and_line() -> None:
    cands = extract_from_source(
        path=Path("assets/scss/_tokens.scss"),
        source=SCSS_SOURCE,
        prefix="dt-",
    )
    primary = next(c for c in cands if c.token_name == "color-primary")
    assert len(primary.definitions) == 1
    d = primary.definitions[0]
    assert d.value == "#1a2b3c"
    assert d.syntax == "css-variable"
    assert d.line == 2
    assert str(d.file).endswith("_tokens.scss")


def test_scss_and_css_are_bridged_when_same_token_name() -> None:
    bridge_source = (
        ":root { --dt-color-primary: #000; }\n"
        "$dt-color-primary: #000;\n"
    )
    cands = extract_from_source(
        path=Path("_bridge.scss"),
        source=bridge_source,
        prefix="dt-",
    )
    primary = next(c for c in cands if c.token_name == "color-primary")
    assert primary.token_type == "scss-css-bridge"
    kinds = sorted(d.syntax for d in primary.definitions)
    assert kinds == ["css-variable", "scss-variable"]


def test_extracts_usages_in_vue_style_block() -> None:
    cands = extract_from_source(
        path=Path("components/Hero.vue"),
        source=VUE_SOURCE,
        prefix="dt-",
    )
    usages_by_name = {c.token_name: c.usages for c in cands}
    assert "color-primary" in usages_by_name
    assert "spacing-md" in usages_by_name
    assert "font-base" in usages_by_name
    u = usages_by_name["color-primary"][0]
    assert isinstance(u, FFCSSUsage)
    assert u.line >= 8
    assert str(u.file).endswith("Hero.vue")


def test_empty_prefix_accepts_all_tokens() -> None:
    cands = extract_from_source(
        path=Path("_t.scss"),
        source=SCSS_SOURCE,
        prefix="",
    )
    names = {c.token_name for c in cands}
    assert "color-primary" in names
    assert "unprefixed" in names
    assert "other" in names


def test_prefix_with_hyphen_or_underscore_in_name_not_truncated() -> None:
    src = ":root { --dt-my-long-name-token: 1px; }\n"
    cands = extract_from_source(
        path=Path("_t.scss"),
        source=src,
        prefix="dt-",
    )
    assert any(c.token_name == "my-long-name-token" for c in cands)


def test_syntax_error_in_scss_does_not_raise() -> None:
    src = ":root { --dt-color-primary: #000; "
    cands = extract_from_source(
        path=Path("_broken.scss"),
        source=src,
        prefix="dt-",
    )
    assert any(c.token_name == "color-primary" for c in cands)
