# Releasing - private-to-public port checklist

This repo is distilled from a private production codebase. Every module
ported from the private repo goes through the same sanitization pass.
This file makes that pass a checklist instead of tribal memory.

## Per-port checklist

Before committing any file ported from the private repo:

1. **Docstring scrub** - remove or generalize anything that describes the
   live deployment: hostnames, tunnel/SSH topology, VPS layout, port
   numbers, internal service names. Describe roles ("an OpenAI-compatible
   endpoint"), not infrastructure.
2. **Fixture rename** - test fixtures use the public example names
   (`example-group`, `app-core`, `app-front-a/b`). Never client or product
   names.
3. **Dependency decoupling** - production-only backends (Redis, PostgreSQL,
   ARQ) get an in-memory or stub equivalent behind the same interface
   (see `brain/core/circuit.py`, `brain/api/_stubs.py`). The public install
   must not grow infra dependencies.
4. **Provenance header** - the module/test docstring notes it was ported
   from the private repo and sanitized, so future contributors know which
   files carry ongoing redaction obligations when syncing fixes.
5. **Em-dash sweep** - the public repo uses plain `-` in code and docs.
6. **Final grep** - run the denylist sweep locally before committing:

   ```bash
   patterns=$(grep -v '^#' .github/leak-denylist.txt | grep -v '^$' | paste -sd'|' -)
   git diff --cached --name-only | xargs grep -liwE "$patterns"
   # no output = clean
   ```

   CI repeats this on every PR, but catching it locally avoids a leaked
   string ever reaching a pushed ref.

## Benchmark artifacts policy

`benchmark/results/` may only contain runs against the public fixture
repos. Agent transcripts and HTML reports embed file paths and code
snippets verbatim - a run against a real workspace can leak client code
even when the question set is generic. Same rule applies to README
GIFs/screenshots: record against fixtures only, review frame by frame.

## Release steps

1. All tasks for the milestone merged, CI green on `main`.
2. Update `CHANGELOG.md`, bump `version` in `pyproject.toml`.
3. Re-run the full denylist sweep over the tree and `git log --all -p`.
4. Tag (`git tag vX.Y.Z`), push the tag, create the GitHub release.
