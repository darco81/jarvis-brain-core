"""Test build_ffcss_section - FFCSS stats from a master graph.

Ported from the private jarvis-brain test suite (sanitized fixtures).
"""

from __future__ import annotations

from brain.viz.insights_ffcss import build_ffcss_section


def _make_master_with_tokens() -> dict:
    return {
        "nodes": [
            {
                "id": "example-group/app-core:ffcss:color-primary",
                "kind": "ffcss_token",
                "name": "color-primary",
                "metadata": {"canonical": True, "value": "#000", "_repo": "app-core"},
            },
            {
                "id": "example-group/app-core:ffcss:spacing-md",
                "kind": "ffcss_token",
                "name": "spacing-md",
                "metadata": {"canonical": True, "value": "1rem", "_repo": "app-core"},
            },
            {
                "id": "example-group/app-front-a:ffcss:color-primary",
                "kind": "ffcss_token",
                "name": "color-primary",
                "metadata": {"canonical": False, "value": "#111", "_repo": "app-front-a"},
            },
            {
                "id": "example-group/app-front-a:ffcss:radius-md",
                "kind": "ffcss_token",
                "name": "radius-md",
                "metadata": {"canonical": False, "value": "8px", "_repo": "app-front-a"},
            },
            {
                "id": "example-group/app-front-b:ffcss:radius-md",
                "kind": "ffcss_token",
                "name": "radius-md",
                "metadata": {"canonical": False, "value": "8px", "_repo": "app-front-b"},
            },
            {
                "id": "example-group/app-front-a:components/Hero.vue",
                "kind": "component",
                "name": "Hero.vue",
                "metadata": {"_repo": "app-front-a"},
            },
            {
                "id": "example-group/app-front-b:components/Nav.vue",
                "kind": "component",
                "name": "Nav.vue",
                "metadata": {"_repo": "app-front-b"},
            },
        ],
        "edges": [
            {
                "source": "example-group/app-front-a:components/Hero.vue",
                "target": "example-group/app-core:ffcss:color-primary",
                "relation": "uses_token",
                "confidence": "extracted",
            },
            {
                "source": "example-group/app-front-b:components/Nav.vue",
                "target": "example-group/app-core:ffcss:color-primary",
                "relation": "uses_token",
                "confidence": "extracted",
            },
            {
                "source": "example-group/app-front-a:ffcss:color-primary",
                "target": "example-group/app-core:ffcss:color-primary",
                "relation": "overrides_token",
                "confidence": "inferred",
            },
            {
                "source": "example-group/app-front-b:ffcss:radius-md",
                "target": "example-group/app-front-a:ffcss:radius-md",
                "relation": "duplicates_token",
                "confidence": "inferred",
            },
        ],
    }


def test_builds_canonical_and_local_totals() -> None:
    section = build_ffcss_section(_make_master_with_tokens())
    assert section["total_tokens_canonical"] == 2
    assert section["total_tokens_local"] == 3


def test_overrides_per_repo_counts() -> None:
    section = build_ffcss_section(_make_master_with_tokens())
    assert section["overrides_per_repo"] == {"app-front-a": 1}


def test_dry_violations_shape() -> None:
    section = build_ffcss_section(_make_master_with_tokens())
    dry = section["dry_violations"]
    assert len(dry) == 1
    v = dry[0]
    assert v["token"] == "radius-md"
    assert sorted(v["repos"]) == ["app-front-a", "app-front-b"]
    assert v["value"] == "8px"


def test_coverage_per_repo_is_ratio_of_used_canonical() -> None:
    section = build_ffcss_section(_make_master_with_tokens())
    cov = section["coverage_per_repo"]
    assert cov["app-front-a"] == 0.5
    assert cov["app-front-b"] == 0.5


def test_most_used_tokens_sorted_desc_limit_applied() -> None:
    section = build_ffcss_section(_make_master_with_tokens(), top_n=10)
    most = section["most_used_tokens"]
    assert most[0]["token"] == "color-primary"
    assert most[0]["count"] == 2


def test_empty_master_returns_zero_section() -> None:
    section = build_ffcss_section({"nodes": [], "edges": []})
    assert section == {
        "total_tokens_canonical": 0,
        "total_tokens_local": 0,
        "overrides_per_repo": {},
        "dry_violations": [],
        "coverage_per_repo": {},
        "most_used_tokens": [],
    }


def test_dry_violation_repos_handle_ids_with_embedded_colons() -> None:
    """dry_violations[].repos is derived via _token_repo. Node ids are
    'group/repo:original_id' and original_id may contain colons (merger
    docstring). When metadata._repo is absent the repo must still be
    'repo', not a colon-suffixed fragment."""
    from brain.viz.insights_ffcss import build_ffcss_section

    master = {
        "nodes": [
            {
                "id": "g/repoA:ffcss:radius:md",  # original_id = 'ffcss:radius:md'
                "kind": "ffcss_token",
                "name": "radius-md",
                "metadata": {"canonical": False, "value": "8px"},  # NO _repo
            },
            {
                "id": "g/repoB:ffcss:radius:md",
                "kind": "ffcss_token",
                "name": "radius-md",
                "metadata": {"canonical": False, "value": "8px"},  # NO _repo
            },
        ],
        "edges": [
            {
                "source": "g/repoA:ffcss:radius:md",
                "target": "g/repoB:ffcss:radius:md",
                "relation": "duplicates_token",
                "confidence": "inferred",
            },
        ],
    }
    section = build_ffcss_section(master)
    dry = section["dry_violations"]
    assert len(dry) == 1
    assert sorted(dry[0]["repos"]) == ["repoA", "repoB"]
