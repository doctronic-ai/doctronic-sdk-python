# Contributing

Thanks for helping improve the Doctronic Python SDK. This page covers setting up, the checks,
generated code, dependencies, pull requests, and releases.

**Never put API tokens, webhook secrets, patient data, or PHI in an issue, a pull request, a
commit, a test, or a fixture.** Tests use synthetic data against a mock API and never call
Doctronic. Report security vulnerabilities privately at
<https://github.com/doctronic-ai/doctronic-sdk-python/security/advisories/new>, not in a public
issue. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Set up

You need [uv](https://docs.astral.sh/uv/). CI uses the version in `UV_VERSION` in
`.github/workflows/ci.yml`; use the same one when you change `uv.lock`.

```bash
uv sync                      # The pinned Python and the locked dev tools
```

## Checks

CI runs these, and every pull request must pass them:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy                  # Strict
uv run pytest                # Against a mock API. No network calls.
uv build                     # The sdist and wheel
```

CI also runs the tests on every supported Python (3.10 to 3.15) and with the lowest supported
httpx and pydantic (`uv sync --resolution lowest-direct`). That changes `uv.lock`, so don't commit
the result.

## Generated code

`src/doctronic/_generated/` is generated from `openapi/doctronic-v1.json`, a pinned copy of the
public contract at <https://docs.doctronic.ai/openapi/doctronic-v1.json>. Don't edit either by
hand.

```bash
uv run python scripts/generate.py                              # From the pinned copy
uv run python scripts/generate.py --contract <path|url>        # From another copy
uv run python scripts/contract_changes.py <old> <new>          # What changes between two copies
```

- `models.py` has the pydantic models (datamodel-code-generator). `operations.py` has the facts the
  client reads at runtime: idempotency, user scope, streaming, whether `data` is required, the
  documented statuses, and the final `409` codes.
- `events.py` maps each chat stream event `type` to its model, from the union the stream's
  `x-doctronic-event-schema` names, and each webhook `event` to its payload model, from the
  contract's `webhooks`. `src/doctronic/_streaming.py` and `src/doctronic/webhooks.py` parse with
  them. The generator stops with an error when the contract lacks either section.
- The generator covers the operations that take the organization API token: those whose security
  names `HTTPBearer`. Others, such as browser-only operations, are skipped and listed, along with
  the schemas only they use.
- The required check **Generated code matches the pinned contract** regenerates from the pinned
  copy and fails on any difference.

A new contract normally arrives through `regenerate.yml`. When the docs publish a contract, and
daily, it updates the pinned copy, regenerates, runs the checks, and opens a pull request from
`automation/regenerate`. `contract-drift.yml` reports daily when the pinned copy is behind. To take
a contract by hand, replace `openapi/doctronic-v1.json` with the published file, unchanged, then
regenerate and commit both.

A new operation gets models and runtime facts from the generator, but no method. Add the resource
method (sync and async) in `src/doctronic/resources/`, its entry in `RESOURCES` in
`tests/test_models.py`, a case in `tests/test_resources.py`, and a CHANGELOG entry. The tests fail
until every operation has exactly one method.

## Dependencies

Every dependency must be at least two weeks old.

- `exclude-newer = "14 days"` in `pyproject.toml` makes uv skip anything newer whenever it
  resolves: `uv lock`, `uv lock --upgrade`, and `uv lock --upgrade-package <package>`.
- Dependabot's version updates wait 14 days too (`cooldown` in `.github/dependabot.yml`).
- Lock with the uv version CI uses, and check that `uv lock --check` passes.

### Security updates

Dependabot skips its cooldown for security updates, but uv's floor still applies to them, so a
fix released less than two weeks ago doesn't resolve. Let the one package through, temporarily:

1. Add the package to `exclude-newer-package` under `[tool.uv]` in `pyproject.toml`, with a
   comment that names the advisory, the fixed version, and the date to remove the entry: two
   weeks after the release you lock.

   ```toml
   # - certifi: GHSA-6q48-6c7w-9gw2 (emSign roots), fixed in 2026.10.18. Remove after 2026-11-06.
   exclude-newer-package = { certifi = false }
   ```

2. Run `uv lock --upgrade-package <package>`, then `uv lock --check` and the checks above.
3. Open the pull request with the advisory in the description. Merge or close Dependabot's own
   security pull request for the package afterwards.
4. After the removal date, delete the entry and check that `uv lock --check` still passes.

## Pull requests

- `main` requires a pull request with one approval, resolved conversations, signed commits, and
  these checks passing on a branch that's up to date: Lint and type check; Test (Python 3.10)
  through Test (Python 3.15); Test (lowest supported httpx and pydantic); Build; and Generated
  code matches the pinned contract.
- Title the pull request the way you'd write a [Conventional Commit](https://www.conventionalcommits.org/),
  such as `fix: ...`, `feat: ...`, `build: ...`, `ci: ...`, or `docs: ...`. Pull requests are
  squash-merged under that title.
- Describe user-visible changes in `CHANGELOG.md`, under `## Unreleased` at the top, and in the
  README when they change how the SDK is used.

## Releases

Maintainers release from `main`; nobody uploads to PyPI by hand.

1. In a pull request, set the version in `pyproject.toml` and `src/doctronic/_version.py`, run
   `uv lock`, and turn `## Unreleased` in `CHANGELOG.md` into `## X.Y.Z (YYYY-MM-DD)`.
2. After it merges, a repository admin pushes the tag `vX.Y.Z` on that commit. The tag ruleset
   lets only admins create `v*` tags.
3. `release.yml` checks that the tag, the version, and the CHANGELOG entry match, runs the checks,
   and builds. After a reviewer approves the `pypi` environment, it publishes through PyPI trusted
   publishing, then creates the GitHub Release from the CHANGELOG entry.
