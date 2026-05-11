# jarvis-brain-core

> Educational destylat: how to build a pre-computed semantic map for Claude Code, expose it as 5 native MCP tools, and stop burning tokens on Glob/Grep in a multi-repo codebase.
>
> This is not a production multi-tenant system. It is the method, distilled. Production runs privately at [brain.sdet.it](https://brain.sdet.it).

## What this is

A 30-file Python project that shows the architecture behind jarvis-brain. Read the code, copy what is useful, replace the parts I had to redact for the public release.

Core ideas, ordered by how much value each one carries on its own:

1. **Code structure as a graph**, not a vector store. Functions, components, modules, imports, design-token usage. The graph is built once per commit and queried hundreds of times.
2. **Two ingestion paths** that produce the same shape. Path A: LLM extraction with Qwen-local or Gemini fallback. Path B: deterministic regex skill that runs inside Claude Code. Same graph schema either way.
3. **Federation**: per-repo graphs merge into a group master graph. Cross-repo imports detected. DRY violations on design-token (dt-) prefixes surfaced as `duplicates_token` edges.
4. **FTS5 + camelCase preprocessing**: SQLite full-text search with a small trick that makes `useUserSession` matchable as `user`, `session`, `useUserSession`, and `use user session` without bloating the index.
5. **5 MCP tools** exposed over HTTP, shaped to feel native to Claude Code: `brain_query`, `brain_graph`, `brain_path`, `brain_explain`, `brain_ffcss`.

## What is in this repo

| Path | What it does |
|---|---|
| `brain/extractors/` | Deterministic regex extractors. `ffcss.py` finds `dt-*` design-token definitions and usages in `.scss`/`.css`/`.vue`. |
| `brain/federation/` | Merges per-repo graphs into a group master. Detects cross-repo imports, canonical vs override tokens, DRY violations. |
| `brain/llm/prompts.py` | The LLM extraction prompt. Same JSON shape that the regex path emits. |
| `brain/api/mcp.py` + `mcp_tools.py` | JSON-RPC 2.0 dispatch and Pydantic schemas for the 5 tools. |
| `brain/api/query.py` + `query_path.py` | FTS5 search endpoint and NetworkX shortest-path endpoint. |
| `brain/viz/` | Thin facade over [graphifyy](https://pypi.org/project/graphifyy/). Renders the master graph as an interactive HTML page with community detection. |
| `brain/core/graph_schema.py` | The Pydantic v2 schema all of the above target. Nodes, edges, kinds, relations, confidence levels. |
| `benchmark/` | The 50-question benchmark methodology. The sample `questions.json` here is 5 generic questions; the production set is anchored to private repos and stays private. |
| `config/groups.example.yml` | Group/repo topology that the merger consumes. |

## What is not in this repo

Intentionally removed during the public extraction:

- Multi-tenant auth (per-dev tokens with scopes, dashboard, session cookies)
- Worker queue (ARQ + Redis) and the polling/cost-tracking loop
- GitHub webhook handler, git mirror operations, SSH key management
- Admin UI, query audit log, rate limiter
- PostgreSQL schema, Alembic migrations, docker-compose deployment
- Discord/Slack alerting, Quartz/Wiki publishers
- The production data itself

If you want a deployed multi-tenant version on your own infra, that is a separate conversation: [sdet.it/services](https://sdet.it/services).

## Quick start

The educational version is meant to be read, but you can also run it.

```bash
git clone https://github.com/darco81/jarvis-brain-core.git
cd jarvis-brain-core

# 3.11+ required, uv recommended
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run the in-scope tests
pytest

# Generate an extraction prompt
python -c "from brain.llm.prompts import build_extraction_system_prompt; \
           print(build_extraction_system_prompt(include_ffcss=True))"

# Inspect the MCP tool schemas
python -c "from brain.api.mcp_tools import TOOL_DEFINITIONS; \
           import json; print(json.dumps(TOOL_DEFINITIONS, indent=2))"
```

To run the benchmark against your own indexed graph, see `benchmark/runner.py`. The runner requires `BRAIN_DEV_TOKEN` and `BRAIN_URL` env vars pointing at a deployment - the educational version intentionally does not ship a default token.

## The articles

This repo is a companion to the "From the field #02" series on jarvis-brain:

- [Part 1: Stop CC from burning tokens on Grep/Glob](https://portfolio.sdet.it/from-the-field/jarvis-brain-part-1)
- Part 2: Architecture of the indexing engine (publishes 2026-05-13)
- Part 3: When this makes sense and when it does not (publishes 2026-05-14)

The articles are the narrative. The code in this repo is the receipts.

## License

[AGPL-3.0](LICENSE). If you deploy a network-accessible service derived from this code, you must publish the source of your derivative under AGPL-3.0 as well.

## Author

Dariusz Kowalski - [LinkedIn](https://www.linkedin.com/in/dar-kow) - [sdet.it](https://sdet.it) - [portfolio.sdet.it](https://portfolio.sdet.it)
