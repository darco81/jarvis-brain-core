# Security

## What this code is - and is not

`jarvis-brain-core` is an educational distillation of a private production
system. **It ships with no real authentication**: `brain/api/_stubs.py`
contains a `TokenVerifier` that accepts every request and a no-op rate
limiter. They exist to show *where* auth attaches in a real deployment,
not to provide it.

Consequences:

- `brain.scripts.serve` binds to `127.0.0.1` by default. **Never expose it
  on a public interface.** Anyone who can reach the port can query your
  indexed graphs.
- There is no audit log, no rate limiting, no tenant isolation in this
  repo. The production deployment has all three; this code intentionally
  does not.

## Reporting a vulnerability

Two classes of report are welcome:

1. **Code vulnerabilities** in the in-scope modules (extractors,
   federation, query layer, MCP dispatch).
2. **Residual data leaks**: this repo was extracted from a private
   client-facing codebase. If you find anything that looks like a client
   name, internal hostname, credential, or other private identifier - in
   the tree *or* in git history - please report it privately rather than
   opening a public issue.

Contact: see the contact links on [sdet.it](https://sdet.it). Please allow
14 days before public disclosure of residual-leak findings.

## Automated controls

CI runs gitleaks over the full history and a client-identifier denylist
grep over the working tree on every PR (`.github/workflows/ci.yml`,
`.github/leak-denylist.txt`).
