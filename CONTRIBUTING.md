# Contributing

Thanks for taking the time to read this. `jarvis-brain-core` is an educational destylat - the bulk of the value is in the README and the code itself. Contributions are welcome, with a few guidelines.

## What kind of changes fit

Good fits:

- Clearer comments, examples, or docstrings
- Bug fixes in `brain/extractors/`, `brain/federation/`, or the query layer
- Additional deterministic extractors (regex-based, no LLM)
- Tests for the existing in-scope modules
- Documentation that explains the method better

Out of scope (please do not PR these here):

- Reintroducing the production concerns intentionally stripped from the public version (auth, rate limiting, audit log, worker queue, webhooks, admin UI). Those belong in a deployment, not in the educational reference.
- New transport protocols beyond MCP and the existing JSON HTTP endpoints.
- Multi-tenancy features.

If you are unsure whether your change fits, open an issue first and ask.

Why the hard boundary: the production system behind this repo is a
commercial deployment. PRs that rebuild its surface here will be closed
regardless of code quality - the boundary is the point, not an oversight.
Modules ported *from* the private repo follow the sanitization checklist
in [RELEASING.md](RELEASING.md).

## Commit message style

Conventional commits. Keep the subject line under 70 characters; explain the *why* in the body.

```
feat(extractors): add Pinia store detection to the deterministic path
fix(federation): handle empty per-repo graphs without crashing
docs(architecture): clarify the FTS5 + camelCase trick
```

No `Co-Authored-By:` trailers from AI tools. No emoji in commit messages.

## Code style

- Python 3.11+, type-annotated, passes `mypy --strict`.
- `ruff check .` clean.
- `pytest` passes locally. New behaviour ships with a test.
- Public surface (anything imported by `brain/api/` or `brain/llm/`) gets a docstring that explains the *why*, not just the *what*.

Quick check before pushing:

```bash
uv sync --all-extras
pytest
mypy --strict brain/
ruff check .
```

## CHANGELOG

Notable changes go in `CHANGELOG.md` under the next unreleased version, [keep-a-changelog](https://keepachangelog.com/en/1.1.0/) style. Bumping the version is the maintainer's job after merge.

## Where to file issues

GitHub issues on this repo. For anything sensitive (suspected security issue in code I might have missed during sanitization), email me directly: see the contact links on [sdet.it](https://sdet.it).

## License

By contributing you agree your contribution is licensed under AGPL-3.0, matching the rest of the project.
