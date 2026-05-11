# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-12

Initial educational release. Public destylat of jarvis-brain v0.4.0 (private).

### Added

- `brain/extractors/ffcss.py` - deterministic regex extractor for design tokens (default prefix `dt-`).
- `brain/federation/` - per-repo graphs merged into a group master graph; cross-repo import detection; DRY-violation edges on canonical tokens.
- `brain/llm/prompts.py` - extraction prompt that yields the same JSON shape as the regex path.
- `brain/api/mcp.py` + `mcp_tools.py` - JSON-RPC 2.0 dispatch and Pydantic schemas for 5 MCP tools (`brain_query`, `brain_graph`, `brain_path`, `brain_explain`, `brain_ffcss`).
- `brain/api/executors.py` - `_build_explain_executor` + `_build_ffcss_executor`, the per-tool logic that reads the master graph.
- `brain/api/query.py` + `query_path.py` - FTS5 search endpoint and NetworkX shortest-path endpoint.
- `brain/publishers/api_index.py` - builds the SQLite FTS5 index that `query.py` reads.
- `brain/viz/` - thin facade over [graphifyy](https://pypi.org/project/graphifyy/) for HTML graph visualization.
- `brain/core/graph_schema.py` - Pydantic v2 schema (nodes, edges, kinds, relations).
- `brain/utils/camelcase.py` - identifier preprocessing for the FTS5 index.
- `brain/scripts/demo_ingest.py` - runnable demo: writes a synthetic graph, builds the FTS5 index, runs three queries, walks a shortest path.
- `benchmark/` - runner + analyze methodology + 5-question sample dataset.
- `docs/ARCHITECTURE.md` - educational walkthrough of the method.
- AGPL-3.0 LICENSE, CONTRIBUTING.md.

### Not included (intentional)

Removed from the private source repo during the public extraction: per-dev auth tokens with scopes, rate limiting, query audit log, ARQ worker queue, GitHub webhook handler, git mirror operations with SSH keys, admin UI, PostgreSQL schema with Alembic migrations, Discord alerts, Quartz/Wiki publishers. Stubs for the auth/rate-limit/audit layer ship in `brain/api/_stubs.py` so router signatures match the production version - readers can wire production concerns back in without changing the dispatch logic.

[0.1.0]: https://github.com/darco81/jarvis-brain-core/releases/tag/v0.1.0
