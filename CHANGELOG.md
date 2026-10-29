# Changelog

## 0.1.1 (2026-10-29)

Built from the same contract as 0.1.0 (`info.version` 0.1.0, 22 operations).

### Changed

- **Responses from a newer API no longer fail.** The docs promise that clients can ignore values
  they don't know, and 0.1.0 raised `APIResponseValidationError` instead:
  - Enums accept values this version doesn't list. A new appointment status comes back as an
    `AppointmentStatus` that equals the string, such as `"on_hold"`, with that `value`; the known
    values are the same members as before. Compare with the members you handle and treat
    anything else as unknown. This applies to every enum in `doctronic.types`, including
    `Scope`, `Role`, `Sex`, and `State`.
  - Data that doesn't match the contract, such as a missing field or a value of another type, is
    returned instead of raised. Fields that match are typed as usual, and the others are kept as
    the API sent them. Missing required fields are `None`; optional fields keep their defaults.
    The SDK logs a warning on the `doctronic` logger that names the request ID and the fields,
    never their values.
  - `APIResponseValidationError` now means the SDK can't use the response at all: the body isn't
    JSON, `data` is missing or `null` for an operation that returns data, or a `200` stream isn't
    `text/event-stream`.
- `verify_webhook()` raises `WebhookVerificationError` for an empty secret instead of
  `ValueError`, as the TypeScript SDK does. A handler that answers `WebhookVerificationError`
  with `400` now also rejects deliveries when its secret isn't configured. Code that caught
  `ValueError` for this case should catch `WebhookVerificationError`.
- Retries of `409` read the contract's `x-doctronic-retryable-codes` extension. A code the
  contract documents for the operation is final unless that list names it, such as
  `error.idempotency.concurrent_request`; `error.idempotency.payload_mismatch` is final. Without
  the extension, the rules are the same as in 0.1.0.
- `scripts/generate.py` reads `openapi/doctronic-v1.json`, a pinned copy of the public contract,
  by default, and the required codegen check compares against it. It covers only operations that
  take the organization API token (`HTTPBearer`), so browser-only operations such as `/embed/*`
  and the schemas only they use stay out of the SDK. For today's contract the generated
  operations are unchanged.

### Added

- `WEBHOOK_SIGNATURE_HEADER`, the TypeScript SDK's name for the signature header.
  `SIGNATURE_HEADER` stays.
- `async with patient.chats.stream(...) as stream:` on `AsyncDoctronic`, without the extra
  `await`. `stream()` returns an `AsyncChatStreamManager`. Awaiting it still returns the
  `AsyncChatStream`, `async with await ...` still works, and it's still a coroutine for
  `asyncio.create_task()` and `asyncio.gather()`.
- Python 3.14 and 3.15 in the classifiers and the CI test matrix.
- Package metadata: keywords, and classifiers for the development status, audience, operating
  system, topics, AsyncIO, and Pydantic 2.
- `regenerate.yml`: when the docs publish a contract, and daily, it updates the pinned contract,
  regenerates, runs the checks, and opens a pull request that lists new operations and is
  labeled `breaking-change` when the docs flag one.
- `contract-drift.yml`: a daily job that reports when the pinned contract falls behind the
  published one. It isn't a required check.
- README sections on versioning and support, and a link to the TypeScript SDK.
- `CONTRIBUTING.md`, a code of conduct (Contributor Covenant 2.1), issue and pull request
  templates that warn against posting tokens or patient data, and `CODEOWNERS`.
- Each release gets a GitHub Release with its CHANGELOG entry as the notes. The release workflow
  stops before publishing when the CHANGELOG has no entry for the version.

### Fixed

- The README's links to `examples/quickstart.py` and `LICENSE` were relative and broke on PyPI;
  every link in the README is absolute now. Its webhook example imports what it uses.
- `examples/quickstart.py` no longer reads `DOCTRONIC_API_URL`, which the SDK never reads. Pass
  `base_url=` to point the client somewhere else.
- Building from the sdist accepts any hatchling from 1.27 (the first with PEP 639 license
  metadata) up to 2, instead of exactly 1.32.4.
- The sdist no longer includes the repository's `.gitignore`.
- `PermissionDeniedError` described a `403` for a user the organization can't act on. The
  contract documents `403` only for `error.auth.insufficient_scope`; that user case is a `404`.

### Security

- certifi before 2026.10.18 bundles emSign root CAs whose intermediate keys were compromised
  (GHSA-6q48-6c7w-9gw2). httpx uses certifi for TLS verification. The SDK doesn't pin certifi,
  so upgrade it in your environment: `pip install --upgrade "certifi>=2026.10.18"`. The
  repository's lockfile now has 2026.10.23.

## 0.1.0 (2026-10-28)

First version of the Python SDK for the Doctronic API, built from the public OpenAPI contract
(`info.version` 0.1.0, 22 operations).

### Added

- `Doctronic` and `AsyncDoctronic` clients, configured from `DOCTRONIC_API_TOKEN` and
  `DOCTRONIC_ENVIRONMENT`, with staging and production base URLs.
- `for_user(user_id)`: a user-scoped client that sends `X-Doctronic-User-ID`. Only
  `users.create()` and `pharmacy.search()` are on the base client.
- Resources: `users`, `chats`, `appointments`, `address`, `pharmacy`, `coverage`, and `artifacts`,
  covering every operation in the contract.
- `chats.stream()`: typed Server-Sent Events as an iterator (sync) or async iterator, a context
  manager with `close()`, unknown events passed through as `UnknownChatStreamEvent`, and
  `final_messages()`. The timeout covers the wait until the stream starts. `close()` is safe
  from another thread or task, and the reader raises `APIUserAbortError`.
- Idempotency keys generated per call for the 11 operations whose contract declares
  `Idempotency-Key`, reused on every retry.
- Retries with exponential backoff and jitter that honor `Retry-After`, following the facts the
  contract declares for each operation. The stream is never retried.
- Typed errors: `APIError` and one subclass per documented status, `BadRequestError.field_errors`
  for `error.validation_error`, connection and timeout errors, and `APIUserAbortError`.
- `403 error.auth.insufficient_scope` raises `PermissionDeniedError`. Its `data` validates as
  `doctronic.types.InsufficientScopeData`, whose `required_scope` names the `Scope` the API key
  lacks.
- `artifacts.wait_until_ready()`: polls a consultation document with bounded backoff, under one
  deadline that covers every poll, retry, and wait.
- `verify_webhook()`: HMAC-SHA256 verification and typed webhook events.
- `with_raw_response` on every client and resource, for the status, headers, and request ID.
- Pydantic v2 models generated from the contract, with snake_case attributes and camelCase
  aliases.
