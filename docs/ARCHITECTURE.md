# Architecture

A walkthrough of why jarvis-brain looks the way it does. Read this alongside [Part 2 of the From-the-Field series](https://portfolio.sdet.it/from-the-field/jarvis-brain-part-2) - that article is the narrative, this file is the map of the codebase.

## The problem space

Claude Code is excellent at code questions when the codebase fits in one repo. It gets expensive when it does not. A 5-repo monorepo (one shared core, four brand-variant fronts) makes Claude Code run `Glob` + `Grep` + `Read` in a loop, fourteen tool calls per cross-repo question, thousands of fresh input tokens every time. Anthropic's prompt cache helps, but the *fresh* tokens scale with how often Claude Code re-explores the same code, and it re-explores constantly because tool results are not persistent memory.

The fix is to pre-compute the structure once and serve it as a native tool.

## The graph schema

`brain/core/graph_schema.py` is the contract. A graph has nodes (functions, components, modules, design tokens) and edges (imports, calls, extends, renders, uses_token, defines_token, duplicates_token, semantically_similar_to). Every node id is fully qualified: `<group>/<repo>:<path>`. Every edge has a confidence (`extracted` vs `inferred`). Both extraction paths target the same shape.

## Two ingestion paths

**Path A: LLM extraction.** `brain/llm/prompts.py` builds the system prompt; `brain/graphify_adapter/` is the machinery that runs it - an `LLMBackend` protocol with three implementations (`QwenLocalBackend` against any OpenAI-compatible endpoint with a circuit breaker, `OpenRouterBackend` as the hosted fallback, `MockBackend` for tests), a `ModelRouter` that picks per job size, and a `GraphifyRunner` that collects files, dispatches with qwen-to-openrouter fallthrough, and writes the graph atomically. Output is strict JSON, validated against the schema. Good for messy real-world code where regex breaks.

**Path B: deterministic regex.** `brain/extractors/ffcss.py` is the canonical example - it finds `dt-*` design-token definitions and usages without any LLM. Runs in milliseconds, costs zero, useful as a sanity floor under Path A. Both paths emit the same node and edge shapes, so the federation layer is path-agnostic.

## Federation

Per-repo graphs are independent. The interesting questions are cross-repo: "does brand B override the cart button from core?", "which design tokens are duplicated between brand A and brand B?". `brain/federation/merger.py` reads N per-repo graphs and emits one group master graph plus three classes of derived edges:

- `imports_from_parent_repo` - cross-repo import detection (`imports_detector.py`)
- `defines_token` / `uses_token` - hoisted to the master graph
- `duplicates_token` / `overrides_token` - DRY violations on canonical tokens (`ffcss_resolver.py`)

Federation runs lazily. The merger is pure; no network, no DB, just JSON in and out.

## Query layer

`brain/api/query.py` exposes the FTS5 index over the federated graph. The non-obvious bit is in `brain/utils/camelcase.py`: before indexing, every identifier is preprocessed so that `useUserSession` also matches `user`, `session`, `use`, and `use user session`. That trick is what makes the index feel like it "understands" code naming without an embedding model.

`brain/api/query_path.py` wraps NetworkX shortest-path on the master graph, cached per `(graph_path, mtime_ns)`. Answers questions like "how does `LoginButton.vue` in brand A reach `useUserSession` in core?".

## Why MCP, not a custom HTTP tool

The whole project is shaped around one constraint: Claude Code should not have to learn a new tool family. Native `Glob` / `Grep` / `Read` are predictable and cheap to call. A custom HTTP search endpoint would sit next to them and need prompt engineering to compete. MCP solves this by exposing tools that Claude Code treats as first-class. The 5 tools in `brain/api/mcp_tools.py` are deliberately named to feel like extensions of the native primitives: `brain_query` for search, `brain_graph` for raw structure, `brain_path` for navigation, `brain_explain` for context, `brain_ffcss` for the design-token-specific query mode.

## What is intentionally not here

Production multi-tenant concerns are out of scope: per-dev auth tokens, rate limiting, query audit log, the ARQ worker queue, GitHub webhook ingestion, git mirror operations with SSH keys, the PostgreSQL schema, the admin UI, the Discord alerter. Each of those has good reasons to exist in the deployed version. None of them are needed to understand the method. If you want the deployment story, that is what [sdet.it/services](https://sdet.it/services) is for.

## Where to start reading

1. `brain/core/graph_schema.py` - the data contract
2. `brain/llm/prompts.py` - what the LLM extractor is told to produce
3. `brain/extractors/ffcss.py` - the deterministic counterpart
4. `brain/federation/merger.py` - how per-repo graphs combine
5. `brain/api/mcp_tools.py` - the tool schemas Claude Code sees
6. `brain/api/query.py` - the FTS5 endpoint
7. `benchmark/runner.py` - how the system is evaluated

That ordering follows the dataflow: schema, ingest, merge, expose, evaluate.
