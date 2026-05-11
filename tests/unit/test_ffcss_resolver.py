from __future__ import annotations

import pytest

from brain.federation.ffcss_resolver import resolve_ffcss


def _token(repo: str, name: str, value: str, canonical: bool = False) -> dict:
    return {
        "id": f"example-group/{repo}:ffcss:{name}",
        "kind": "ffcss_token",
        "name": name,
        "file": f"{repo}/tokens.scss",
        "metadata": {
            "token_type": "css-variable",
            "value": value,
            "canonical": canonical,
            "definitions": [
                {
                    "file": f"{repo}/tokens.scss",
                    "line": 1,
                    "syntax": "css-variable",
                    "value": value,
                }
            ],
        },
    }


def test_canonical_flag_set_for_core_repo() -> None:
    repo_graphs = [
        ("example-core", {"nodes": [_token("example-core", "color-primary", "#000")], "edges": []}),
        ("example-front-a",      {"nodes": [_token("example-front-a",      "color-primary", "#111")], "edges": []}),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend"}
    resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    ff_token = next(
        n for n in repo_graphs[0][1]["nodes"] if n["kind"] == "ffcss_token"
    )
    frontend_a_token = next(
        n for n in repo_graphs[1][1]["nodes"] if n["kind"] == "ffcss_token"
    )
    assert ff_token["metadata"]["canonical"] is True
    assert frontend_a_token["metadata"]["canonical"] is False


def test_overrides_edge_emitted_child_to_canonical() -> None:
    repo_graphs = [
        ("example-core", {"nodes": [_token("example-core", "color-primary", "#000")], "edges": []}),
        ("example-front-a",      {"nodes": [_token("example-front-a",      "color-primary", "#111")], "edges": []}),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    overrides = [e for e in result.new_edges if e["relation"] == "overrides_token"]
    assert len(overrides) == 1
    assert overrides[0]["source"] == "example-group/example-front-a:ffcss:color-primary"
    assert overrides[0]["target"] == "example-group/example-core:ffcss:color-primary"
    assert overrides[0]["confidence"] == "inferred"


def test_duplicates_edge_emitted_only_when_both_non_canonical_and_values_identical() -> None:
    repo_graphs = [
        ("example-core", {"nodes": [], "edges": []}),  # no canonical token
        ("example-front-a",      {"nodes": [_token("example-front-a",   "radius-md", "8px")], "edges": []}),
        ("example-front-b",     {"nodes": [_token("example-front-b",  "radius-md", "8px")], "edges": []}),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend", "example-front-b": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    dups = [e for e in result.new_edges if e["relation"] == "duplicates_token"]
    assert len(dups) == 1
    # Alphabetical sort of ["example-front-a","example-front-b"]
    # Later (example-front-b) -> earlier (example-front-a)
    assert dups[0]["source"] == "example-group/example-front-b:ffcss:radius-md"
    assert dups[0]["target"] == "example-group/example-front-a:ffcss:radius-md"


def test_no_duplicates_when_values_differ() -> None:
    repo_graphs = [
        ("example-core", {"nodes": [], "edges": []}),
        ("example-front-a",   {"nodes": [_token("example-front-a",   "radius-md", "8px")],  "edges": []}),
        ("example-front-b",  {"nodes": [_token("example-front-b",  "radius-md", "12px")], "edges": []}),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend", "example-front-b": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    assert [e for e in result.new_edges if e["relation"] == "duplicates_token"] == []


def test_duplicates_skipped_when_one_side_is_canonical() -> None:
    repo_graphs = [
        ("example-core", {"nodes": [_token("example-core", "color-primary", "#000")], "edges": []}),
        ("example-front-a",      {"nodes": [_token("example-front-a",      "color-primary", "#000")], "edges": []}),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    assert any(e["relation"] == "overrides_token" for e in result.new_edges)
    assert not any(e["relation"] == "duplicates_token" for e in result.new_edges)


def test_dry_detection_disabled_suppresses_duplicates() -> None:
    repo_graphs = [
        ("example-core", {"nodes": [], "edges": []}),
        ("example-front-a",   {"nodes": [_token("example-front-a",   "radius-md", "8px")], "edges": []}),
        ("example-front-b",  {"nodes": [_token("example-front-b",  "radius-md", "8px")], "edges": []}),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend", "example-front-b": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=False,
    )
    assert not any(e["relation"] == "duplicates_token" for e in result.new_edges)


def test_no_canonical_repo_returns_empty_overrides() -> None:
    repo_graphs = [
        ("example-front-a",   {"nodes": [_token("example-front-a",   "color-primary", "#111")], "edges": []}),
        ("example-front-b",  {"nodes": [_token("example-front-b",  "color-primary", "#222")], "edges": []}),
    ]
    roles = {"example-front-a": "frontend", "example-front-b": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    assert not any(e["relation"] == "overrides_token" for e in result.new_edges)


def test_uses_token_edge_rewrites_to_canonical_when_child_lacks_local() -> None:
    forge_token = _token("example-core", "color-primary", "#000", canonical=True)
    frontend_a_component = {
        "id": "example-group/example-front-a:components/Hero.vue",
        "kind": "component",
        "name": "Hero.vue",
    }
    repo_graphs = [
        ("example-core", {"nodes": [forge_token], "edges": []}),
        (
            "example-front-a",
            {
                "nodes": [frontend_a_component],
                "edges": [
                    {
                        "source": "example-group/example-front-a:components/Hero.vue",
                        "target": "example-group/example-front-a:ffcss:color-primary",
                        "relation": "uses_token",
                        "confidence": "extracted",
                    }
                ],
            },
        ),
    ]
    roles = {"example-core": "core", "example-front-a": "frontend"}
    result = resolve_ffcss(
        group="example-group",
        repo_graphs=repo_graphs,
        repo_roles=roles,
        dry_detection=True,
    )
    uses = [e for e in result.rewritten_edges if e["relation"] == "uses_token"]
    assert any(
        e["target"] == "example-group/example-core:ffcss:color-primary"
        for e in uses
    )


def test_multi_core_raises() -> None:
    roles = {"A": "core", "B": "core"}
    with pytest.raises(ValueError, match="Multiple core repos"):
        resolve_ffcss(
            group="g",
            repo_graphs=[("A", {"nodes": [], "edges": []}), ("B", {"nodes": [], "edges": []})],
            repo_roles=roles,
            dry_detection=True,
        )
