<!-- Thanks! Two minutes of reading saves both of us a review round. -->

## What

<!-- One paragraph: what changes and why. -->

## Scope check

This repo is an educational reference, not a product. Confirm your PR does
NOT reintroduce intentionally-removed production concerns (see
CONTRIBUTING "Out of scope"): multi-tenant auth, rate limiting, audit log,
worker queue, webhooks, git mirror ops, admin UI, deployment tooling.

- [ ] In scope per CONTRIBUTING
- [ ] `pytest`, `mypy --strict brain/`, `ruff check .` pass locally
- [ ] New behaviour ships with a test
- [ ] No client names / internal hostnames (CI denylist will check too)
