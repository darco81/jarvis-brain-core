from typing import Any

import pytest

from brain.federation.merger import FederationMerger


def test_namespace_union_preserves_nodes_and_edges() -> None:
    g_core = {"nodes": [{"id": "Button", "label": "Button", "file": "src/Button.vue"}], "edges": []}
    g_front_a = {
        "nodes": [{"id": "Checkout", "label": "Checkout", "file": "src/pages/Checkout.vue"}],
        "edges": [
            {
                "source": "Checkout",
                "target": "Button",
                "relation": "imports",
                "confidence": "EXTRACTED",
            }
        ],
    }
    merger = FederationMerger(detect_cross_repo_imports=False)
    master = merger.merge_group(
        group="example-group",
        repo_graphs=[("app-core", g_core), ("example-front-a", g_front_a)],
    )
    ids = {n["id"] for n in master["nodes"]}
    assert "example-group/app-core:Button" in ids
    assert "example-group/example-front-a:Checkout" in ids
    assert any(
        e["source"] == "example-group/example-front-a:Checkout" and e["target"] == "example-group/example-front-a:Button"
        for e in master["edges"]
    )


def test_cross_repo_import_detection_emits_parent_edge() -> None:
    g_core = {"nodes": [{"id": "Button", "label": "Button", "file": "src/Button.vue"}], "edges": []}
    g_front_a = {
        "nodes": [{"id": "ShoppingPage", "label": "ShoppingPage", "file": "src/ShoppingPage.vue"}],
        "edges": [
            {
                "source": "ShoppingPage",
                "target": "Button",
                "relation": "imports_external",
                "confidence": "EXTRACTED",
            }
        ],
    }
    roles = {"app-core": "core", "example-front-a": "frontend"}
    merger = FederationMerger(detect_cross_repo_imports=True, repo_roles=roles)
    master = merger.merge_group(
        group="example-group",
        repo_graphs=[("app-core", g_core), ("example-front-a", g_front_a)],
    )
    cross = [e for e in master["edges"] if e.get("relation") == "imports_from_parent_repo"]
    assert len(cross) == 1
    assert cross[0]["source"] == "example-group/example-front-a:ShoppingPage"
    assert cross[0]["target"] == "example-group/app-core:Button"


def test_merge_group_skips_malformed_nodes_and_edges() -> None:
    malformed = {
        "nodes": [
            {"id": "Good"},
            {"label": "Bad"},             # missing id
            "not a dict",                 # wrong type
            {"id": "AlsoGood", "label": "x"},
        ],
        "edges": [
            {"source": "Good", "target": "AlsoGood"},
            {"source": "Good"},            # missing target
            "not a dict",                  # wrong type
        ],
    }
    merger = FederationMerger(detect_cross_repo_imports=False)
    master = merger.merge_group(group="g", repo_graphs=[("r", malformed)])
    ids = {n["id"] for n in master["nodes"]}
    assert ids == {"g/r:Good", "g/r:AlsoGood"}
    assert len(master["edges"]) == 1


def test_merge_group_empty_inputs() -> None:
    merger = FederationMerger(detect_cross_repo_imports=False)
    master = merger.merge_group(group="g", repo_graphs=[])
    assert master["schema_version"] == "v1"
    assert master["group"] == "g"
    assert master["repo"] == "_master"
    assert master["nodes"] == []
    assert master["edges"] == []


def test_merge_group_runs_ffcss_resolver_when_flag_set() -> None:
    g_core = {
        "nodes": [
            {
                "id": "ffcss:color-primary",
                "kind": "ffcss_token",
                "name": "color-primary",
                "metadata": {
                    "token_type": "css-variable",
                    "value": "#000",
                    "definitions": [
                        {"file": "t.scss", "line": 1,
                         "syntax": "css-variable", "value": "#000"}
                    ],
                },
            },
            {"id": "tokens.scss", "kind": "module", "name": "tokens.scss"},
        ],
        "edges": [
            {
                "source": "tokens.scss",
                "target": "ffcss:color-primary",
                "relation": "defines_token",
                "confidence": "EXTRACTED",
            }
        ],
    }
    g_front_a = {
        "nodes": [
            {
                "id": "ffcss:color-primary",
                "kind": "ffcss_token",
                "name": "color-primary",
                "metadata": {
                    "token_type": "css-variable",
                    "value": "#111",
                    "definitions": [
                        {"file": "t.scss", "line": 1,
                         "syntax": "css-variable", "value": "#111"}
                    ],
                },
            },
        ],
        "edges": [],
    }
    roles = {"example-core": "core", "example-front-a": "frontend"}
    merger = FederationMerger(
        detect_cross_repo_imports=False,
        detect_ffcss_tokens=True,
        dry_detection=True,
        repo_roles=roles,
    )
    master = merger.merge_group(
        group="example-group",
        repo_graphs=[("example-core", g_core), ("example-front-a", g_front_a)],
    )
    relations = [e["relation"] for e in master["edges"]]
    assert "overrides_token" in relations
    canonical_nodes = [
        n for n in master["nodes"]
        if n.get("kind") == "ffcss_token"
        and n.get("metadata", {}).get("canonical") is True
    ]
    assert len(canonical_nodes) == 1
    assert canonical_nodes[0]["id"] == "example-group/example-core:ffcss:color-primary"


def test_merge_group_without_ffcss_flag_is_noop_for_tokens() -> None:
    g_core = {
        "nodes": [
            {"id": "ffcss:color-primary", "kind": "ffcss_token",
             "name": "color-primary", "metadata": {"value": "#000"}}
        ],
        "edges": [],
    }
    g_front_a = {
        "nodes": [
            {"id": "ffcss:color-primary", "kind": "ffcss_token",
             "name": "color-primary", "metadata": {"value": "#111"}}
        ],
        "edges": [],
    }
    merger = FederationMerger(
        detect_cross_repo_imports=False,
        detect_ffcss_tokens=False,
        repo_roles={"example-core": "core", "example-front-a": "frontend"},
    )
    master = merger.merge_group(
        group="example-group",
        repo_graphs=[("example-core", g_core), ("example-front-a", g_front_a)],
    )
    assert not any(e["relation"] == "overrides_token" for e in master["edges"])
    ff = next(
        n for n in master["nodes"]
        if n["id"] == "example-group/example-core:ffcss:color-primary"
    )
    assert "canonical" not in ff.get("metadata", {})


def test_imports_detector_raises_on_multiple_cores() -> None:
    from brain.federation.imports_detector import detect_cross_repo_imports

    g: dict[str, list[Any]] = {"nodes": [], "edges": []}
    roles = {"core1": "core", "core2": "core"}
    with pytest.raises(ValueError, match="Multi-core"):
        detect_cross_repo_imports([("core1", g), ("core2", g)], roles)


def test_pass_through_super_single_group_has_groups_key() -> None:
    merger = FederationMerger()
    master = {"version": 1, "group": "example-group", "nodes": [{"id": "X"}], "edges": []}
    sup = merger.pass_through_super([("example-group", master)])
    assert sup["super"] is True
    assert sup["groups"] == ["example-group"]
    assert sup["nodes"] == [{"id": "X"}]


def test_pass_through_super_multiple_groups_unions_nodes() -> None:
    merger = FederationMerger()
    m_a = {"nodes": [{"id": "a:X"}], "edges": []}
    m_b = {"nodes": [{"id": "b:Y"}], "edges": []}
    sup = merger.pass_through_super([("a", m_a), ("b", m_b)])
    assert sup["groups"] == ["a", "b"]
    ids = {n["id"] for n in sup["nodes"]}
    assert ids == {"a:X", "b:Y"}
