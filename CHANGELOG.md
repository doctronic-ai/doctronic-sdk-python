# Changelog

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
