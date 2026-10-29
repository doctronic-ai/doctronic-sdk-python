<!--
Never include API tokens, webhook secrets, patient data, or PHI in a pull request, its commits,
its tests, or its fixtures. Use synthetic data only.
-->

## Why

<!-- The problem, with a link to the issue or the docs page it comes from. -->

## Change

<!-- What changes for SDK users, and anything a reviewer should look at closely. -->

## Checks

- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, and `uv run pytest` pass.
- [ ] Tests cover the change, with both the sync and the async client where it applies.
- [ ] `src/doctronic/_generated/` changed only through `scripts/generate.py`, and `openapi/doctronic-v1.json` only through a contract update.
- [ ] The README and the CHANGELOG describe any change SDK users can see.
- [ ] No tokens, secrets, patient data, or PHI anywhere in the diff.
