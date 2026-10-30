# Doctronic Python SDK

Python client for the [Doctronic API](https://docs.doctronic.ai). Sync and async clients, typed
models generated from the OpenAPI contract, typed chat stream events, safe retries, and webhook
verification. For Node.js, use the [TypeScript SDK](https://github.com/doctronic-ai/doctronic-sdk-typescript)
(`@doctronic-ai/sdk` on npm), which covers the same operations.

Requires Python 3.10 or later; CI tests 3.10 to 3.15. Runtime dependencies: `httpx` and
`pydantic` v2.

## Install

```bash
pip install doctronic
# or
uv add doctronic
```

## Quickstart

Stream an assistant message in staging, using a synthetic patient. You need a staging API token;
see [get access](https://docs.doctronic.ai/docs/authentication/#get-access). Run this from a
terminal or your backend, and keep the token there.

```bash
export DOCTRONIC_API_TOKEN="replace-with-your-staging-token"
```

```python
import uuid

from doctronic import Doctronic
from doctronic.types import MessageContentEvent, MessageStartEvent, MessageStopEvent

client = Doctronic()  # Reads DOCTRONIC_API_TOKEN. Defaults to staging.

# 1. Create a user, and save user.id on the patient record in your system.
user = client.users.create(
    first_name="Avery",
    last_name="Chen",
    date_of_birth="1990-06-15",
    # Email and phone number must be unique per user, so each run uses a new email and no phone.
    email=f"avery+quickstart-{uuid.uuid4()}@example.com",
    sex="female",
)
patient = client.for_user(user.id)

# 2. Create a chat.
chat = patient.chats.create(timezone="America/New_York")

# 3. Stream a patient turn.
messages: dict[str, dict[str, str]] = {}
with patient.chats.stream(
    chat.id,
    user_input="I have had a sore throat and fever since yesterday.",
    timezone="America/New_York",
) as stream:
    for event in stream:
        if isinstance(event, MessageStartEvent):
            messages[event.message_id] = {"role": event.role.value, "text": ""}
        elif isinstance(event, MessageContentEvent):
            messages[event.message_id]["text"] += event.content
        elif isinstance(event, MessageStopEvent):
            print(messages[event.message_id])
        else:
            print(event.type, event)  # guardian, conversation.end, error, and any new event
```

[`examples/quickstart.py`](https://github.com/doctronic-ai/doctronic-sdk-python/blob/main/examples/quickstart.py) is the same program. A turn can emit a
`guardian` event that your product must act on; read
[Safety](https://docs.doctronic.ai/docs/safety/) before you show the stream to patients.

### Async

`AsyncDoctronic` has the same methods. Await each call, open the stream with `async with`, and
iterate it with `async for`:

```python
import asyncio

from doctronic import AsyncDoctronic


async def main() -> None:
    async with AsyncDoctronic() as client:
        patient = client.for_user("mem_01K1EXAMPLE00000000000000")
        chat = await patient.chats.create(timezone="America/New_York")
        async with patient.chats.stream(chat.id, user_input="Hello") as stream:
            async for event in stream:
                print(event.type)


asyncio.run(main())
```

`await patient.chats.stream(...)` also works, and returns the `AsyncChatStream` for you to
`close()`. So does `async with await ...`, the form 0.1.0 needed.

## Configuration

```python
client = Doctronic(
    api_token="...",  # Default: DOCTRONIC_API_TOKEN. Required.
    environment="production",  # "staging" or "production". Default: DOCTRONIC_ENVIRONMENT, then "staging".
    base_url=None,  # Overrides the environment's base URL.
    timeout=60.0,  # Seconds, or an httpx.Timeout. See below.
    max_retries=2,  # Retries for reads and idempotent mutations.
    http_client=None,  # Your own httpx.Client (httpx.AsyncClient for AsyncDoctronic).
)
```

| Environment | Base URL |
| --- | --- |
| `staging` | `https://staging-partners.doctronic.ai/api/v1` |
| `production` | `https://partners.doctronic.ai/api/v1` |

`timeout` applies to each attempt, with httpx's semantics: connecting, sending, and each wait for
data get up to that long. It isn't a wall-clock limit on the whole response. For a stream it
covers the wait until the stream starts; after that, gaps between events never time out.

Constructing a client without a token raises `DoctronicError`. The SDK never logs the token or
puts it in an error message. Keep it on your backend: never in browser code, mobile apps, or
model prompts.

## User scope

The token authenticates your organization; `X-Doctronic-User-ID` selects the patient. Two
operations take the token alone, and they live on the base client:

```python
user = client.users.create(first_name="Avery")
pharmacies = client.pharmacy.search(latitude=40.7608, longitude=-111.891)
```

Everything else acts on one patient. `for_user()` returns a client that sends the header on every
request, so a user-scoped call can't go out without a user:

```python
patient = client.for_user(user.id)
patient.users.update(phone_number="+15555550100", email=None)  # None clears; omitted keeps.
```

| Resource | Methods |
| --- | --- |
| `client.users` | `create` |
| `client.pharmacy` | `search` |
| `patient.users` | `retrieve`, `update` |
| `patient.chats` | `create`, `list`, `retrieve`, `messages`, `stream` |
| `patient.appointments` | `available_slots`, `create_scheduled`, `create_asap`, `list`, `retrieve`, `result`, `cancel`, `reschedule` |
| `patient.address` | `retrieve`, `set` |
| `patient.pharmacy` | `set` |
| `patient.coverage` | `set` |
| `patient.artifacts` | `retrieve`, `wait_until_ready` |

Your backend decides which patient a request is for. Derive the user ID from the patient your
system authenticated, never from an ID a browser or app sent you.

## Models

Methods return the `data` of the `{code, message, data}` envelope as pydantic models from
`doctronic.types`. Each model has its contract name, such as `UserCreatedResponse`, and the short
name the TypeScript SDK uses, such as `User`. Attributes are snake_case; the camelCase wire names
are aliases, so `model.model_dump(by_alias=True)` gives the wire shape back.

Responses from a newer API don't fail, so you can ignore what you don't know yet:

- Fields the contract doesn't list yet are kept, in `model.model_extra`.
- Enums accept values this version doesn't list. A new appointment status arrives as an
  `AppointmentStatus` that equals the string, such as `"on_hold"`; the known values are the usual
  members. Compare with the members you handle and treat anything else as unknown.
- Data that doesn't match the contract, such as a missing field or a value of another type, is
  returned rather than raised: fields that match are typed, and the rest are kept as sent.
  Missing required fields are `None`; optional fields keep their defaults. The SDK logs a warning
  on the `doctronic` logger with the request ID and the field names, never their values.

| Short name | Contract model |
| --- | --- |
| `User` | `UserCreatedResponse` |
| `Chat`, `ChatPage` | `ChatResponse`, `PageChatResponse` |
| `ChatMessage`, `ChatMessagePage` | `MessageResponse`, `PageMessageResponse` |
| `Appointment`, `AppointmentPage`, `AppointmentStatus` | `AppointmentResponse`, `PageAppointmentResponse`, `AppointmentAPIStatus` |
| `ScheduledAppointment`, `AsapAppointment` | `ScheduledAppointmentResponse`, `AsapAppointmentResponse` |
| `AppointmentResult`, `AvailableSlots` | `AppointmentResultResponse`, `AvailableSlotsResponse` |
| `Address`, `UsState` | `AddressResponse`, `State` |
| `PharmacySearchResults` | `PharmacySearchResponse` |
| `Artifact` | `ArtifactResponse`: one of `SoapNoteArtifactResponse`, `ClinicianNoteArtifactResponse`, `LongSummaryArtifactResponse`, `ShortSummaryArtifactResponse` |

```python
appointment = patient.appointments.retrieve("dc_01K1EXAMPLE00000000000000")
appointment.waiting_room_url
appointment.model_dump(mode="json", by_alias=True)  # {"waitingRoomUrl": ..., ...}
```

## Streaming

`chats.stream()` sends one patient turn and returns the reply as typed events: a plain iterator
on `Doctronic`, an async iterator on `AsyncDoctronic`. Use it as a context manager, or call
`close()`, to release the connection when you stop early. The client's `timeout` covers the wait
until the stream starts; after that the stream stays open as long as the assistant replies.

Give the patient a cancel action that calls `close()`. It's safe to call from another thread or
task: the code reading the stream then raises `APIUserAbortError`, and so does iterating any
stream closed before its end, so a cancelled turn never looks finished. On `AsyncDoctronic`,
cancelling the reading task also releases the connection; the `asyncio.CancelledError`
propagates unchanged.

The event classes are generated from the contract's `StreamChatEvent` schema. `doctronic.types`
exports each one under the name below and under its contract name, such as
`StreamChatMessageStartEvent`.

| Event | Class | Fields |
| --- | --- | --- |
| `message.start` | `MessageStartEvent` | `role`, `message_id`, `message_timestamp` |
| `message.content` | `MessageContentEvent` | `message_id`, `content` |
| `message.stop` | `MessageStopEvent` | `message_id` |
| `guardian` | `GuardianEvent` | `guardian_id`, `message`, `title`, `text`, `ends_conversation`, `category` |
| `conversation.offtopic` | `ConversationOfftopicEvent` | `message_id` |
| `conversation.end` | `ConversationEndEvent` | `message_id`, `reason` |
| `skill_code.cta` | `SkillCodeCtaEvent` | `skill_code`, `widget`, `text` |
| `ai_consultation.complete` | `AiConsultationCompleteEvent` | `artifacts.long_summary`, `.short_summary`, `.soap_note` |
| `error` | `StreamErrorEvent` | `error_code`, `message`, `retry_after_seconds` |
| Anything else | `UnknownChatStreamEvent` | `type`, `data` (the parsed payload) |

- **Unknown events never raise.** New event names arrive as `UnknownChatStreamEvent`; ignore the ones you
  don't use yet.
- **Guardian IDs and categories are open.** `guardian_id` and `category` arrive as the strings the
  API sent. Compare them with the `PartnerGuardianId` and `GuardianCategory` members you handle,
  and treat any other value as new rather than ignoring the event.
- **An `error` event is yielded, not raised.** Handle it apart from message text.
- **Errors before the stream starts raise:** `ConflictError` for
  `error.partner.chat_stream_in_progress`, `ServiceUnavailableError` for
  `error.partner.chat_stream_unavailable`. A `200` that isn't `text/event-stream` raises
  `APIResponseValidationError` rather than reading as an empty turn.
- **The stream is never retried.** It takes no idempotency key, and the first attempt may already
  have produced a reply. After a dropped connection (`APIConnectionError`) or an `error` event,
  read `chats.messages(chat_id)` before you let the patient resend the turn.

To relay events to your frontend, serialize them in the wire shape:
`event.model_dump(by_alias=True, exclude_none=True)`.

### Assemble messages

`final_messages()` reads the rest of the stream and returns each message assembled by
`message_id`, with the role from its `message.start`, plus every other event in arrival order. It
includes events you already iterated over.

```python
with patient.chats.stream(chat.id, user_input="My fever is 101.5 F.") as stream:
    final = stream.final_messages()

for message in final.messages:
    print(message.role, message.content, message.complete)  # complete: its message.stop arrived
for event in final.control_events:
    print(event.type)  # guardian, skill_code.cta, ai_consultation.complete, ...
```

## Consultation documents

`artifacts.retrieve()` returns the document, or `None` while it's still generating (`202`).
`wait_until_ready()` polls with exponential backoff from 1 to 16 seconds, for up to `timeout`
seconds (default 120):

```python
from doctronic.types import AiConsultationCompleteEvent

for event in final.control_events:
    if isinstance(event, AiConsultationCompleteEvent) and event.artifacts.short_summary:
        summary = patient.artifacts.wait_until_ready(event.artifacts.short_summary, timeout=120)
        assert summary.content.chat_id == chat.id
        print(summary.content.body)  # Markdown. Sanitize it before you render it.
```

`timeout` must be positive, and one deadline covers the whole wait: every poll, the retries
inside each poll, and the waits between them. Each request's timeouts are capped by the time
left. It stops with `NotFoundError` on `404`, `InternalServerError` on `500` (generation failed
permanently), and `ArtifactNotReadyError` at the deadline. On `AsyncDoctronic`, cancel the task to
stop early.

`appointments.result()` works the same way: it returns `None` while the result isn't available
yet.

## Idempotency and retries

The SDK sends an `Idempotency-Key` on the 11 operations whose contract declares one: every
mutation except `chats.stream()`. It generates one key per call and reuses the same key and body
on every retry of that call. Pass your own key to make a change safe to replay later, for example
after your process restarts:

```python
patient.appointments.create_scheduled(
    chat_id=chat.id,
    starts_at=slot,
    location={"state": "NY"},
    idempotency_key=booking.id,  # One key per intended change; up to 255 characters.
)
```

Retries follow the [retry checklist](https://docs.doctronic.ai/docs/errors/#retry-checklist):

| Failure | Reads (`GET`) | Idempotent mutations | `chats.stream()` |
| --- | --- | --- | --- |
| Network error or timeout | Retried | Retried | Never |
| `429`, `503` | Retried | Retried | Never |
| Other `5xx` | Retried, unless the contract documents the status, like `500` from `artifacts.retrieve()` | Not retried | Never |
| `409` whose code isn't final for the operation (see below) | Not retried | Retried | Never |
| Other `4xx` | Not retried | Not retried | Never |

A `409` code the contract documents for the operation, such as
`error.appointments.slot_unavailable`, is final and isn't retried, unless the contract lists it in
`x-doctronic-retryable-codes` as safe to retry with the same key, such as
`error.idempotency.concurrent_request`. A `409` without a code, or with one the contract doesn't
document, is an idempotency conflict and is retried with the same key.

Retries back off exponentially from 0.5 to 8 seconds, plus up to 25% jitter. A `Retry-After`
header replaces the backoff; one over 60 seconds ends the retries so you decide when to try
again.
`max_retries` (default 2) caps the attempts; `max_retries=0` turns retries off. An error response
cut off mid-body keeps its status and `Retry-After`, so the rules above still apply. A success
response cut off mid-body counts as a network error.

## Errors

Every error subclasses `DoctronicError`. Responses with an error status raise an `APIError`
subclass; branch on `status` and `code`, and show or log `message`.

| Status | Class |
| --- | --- |
| `400`, `422` | `BadRequestError` |
| `401` | `AuthenticationError` |
| `403` | `PermissionDeniedError` |
| `404` | `NotFoundError` |
| `409` | `ConflictError` |
| `429` | `RateLimitError` |
| `503` | `ServiceUnavailableError` |
| Other `5xx` | `InternalServerError` |
| No response | `APIConnectionError`, and `APITimeoutError` for timeouts |
| Stream closed before its end | `APIUserAbortError` |

```python
from doctronic import BadRequestError, ConflictError

try:
    patient.appointments.create_scheduled(chat_id=chat.id, starts_at=slot, location={"state": "NY"})
except ConflictError as err:
    if err.code == "error.appointments.slot_unavailable":
        ...  # Refresh availability and ask the patient to choose again.
except BadRequestError as err:
    for field_error in err.field_errors:  # Set for error.validation_error, else empty.
        print(field_error.field, field_error.code)
```

`APIError` carries `status`, `code` (`None` when the body has none), `message`, `data`, `headers`,
`retry_after`, and `request_id` (from `X-Request-ID`). Keep `request_id` with your record of every
failure so Doctronic can trace it.

A `403` is `error.auth.insufficient_scope`: the API key lacks a scope.
`InsufficientScopeData.model_validate(err.data).required_scope` names it. A user your organization
can't act on is a `404`.

A success response the SDK can't use raises `APIResponseValidationError`, a subclass of `APIError`
that is never retried: a body that isn't JSON, a missing or `null` `data` for an operation that
returns data, or a `200` stream that isn't `text/event-stream`. Data that only differs from the
contract doesn't raise; see Models above.

## Raw responses

Prefix a call with `with_raw_response` to get an `APIResponse` with the status, headers, and
request ID. `parse()` returns what the method normally returns.

```python
raw = client.with_raw_response.users.create(first_name="Avery")
raw.status_code  # 201
raw.request_id  # X-Request-ID
raw.idempotency_key  # The key the SDK sent
raw.idempotency_replayed  # True when the API replayed a stored response
user = raw.parse()

raw = patient.chats.with_raw_response.retrieve(chat.id)  # Also available per resource.
```

## Webhooks

Verify each delivery against the raw request body before you parse it. `verify_webhook()` checks
the `X-Doctronic-Signature` HMAC-SHA256 in constant time and returns a typed event. It raises
`WebhookVerificationError` when the signature doesn't match, when the signed body isn't a valid
event, and when the secret is empty, so a missing secret rejects every delivery.

With FastAPI:

```python
import os

from fastapi import FastAPI, Request, Response

from doctronic import WEBHOOK_SIGNATURE_HEADER, WebhookVerificationError, verify_webhook
from doctronic.types import AppointmentWaitingRoomReadyEvent, ArtifactReadyEvent

app = FastAPI()
# Your app's own setting. The SDK doesn't read environment variables for webhooks.
WEBHOOK_SECRET = os.environ["DOCTRONIC_WEBHOOK_SECRET"]


@app.post("/webhooks/doctronic")
async def doctronic_webhook(request: Request) -> Response:
    try:
        event = verify_webhook(
            await request.body(), request.headers.get(WEBHOOK_SIGNATURE_HEADER), WEBHOOK_SECRET
        )
    except WebhookVerificationError:
        return Response(status_code=400)
    # seen_before, store_waiting_room_url, and enqueue_artifact_fetch stand for your own code.
    if not seen_before(event.event_id):  # Deduplicate on event_id.
        if isinstance(event, AppointmentWaitingRoomReadyEvent):
            store_waiting_room_url(event.data.appointment_id, event.data.waiting_room_url)
        elif isinstance(event, ArtifactReadyEvent):
            enqueue_artifact_fetch(event.data.artifact_id)
    return Response(status_code=200)  # Acknowledge unknown events too.
```

`WEBHOOK_SIGNATURE_HEADER` is the TypeScript SDK's name for the header. `SIGNATURE_HEADER`, the
0.1.0 name, still works.

Events: `AppointmentWaitingRoomReadyEvent`, `AppointmentPractitionerJoinedEvent`,
`AppointmentCallEndedEvent`, `ArtifactReadyEvent`, and `UnknownWebhookEvent` for event names this
version doesn't know. The four known ones are generated from the contract's `webhooks`, and
`doctronic.types` also exports them under their contract names, such as `ArtifactReadyPayload`.

## Versioning

The SDK follows [semantic versioning](https://semver.org). Before 1.0, a minor release (0.2.0) can
change the public API; a patch release (0.1.2) fixes bugs and adds features without breaking code
written for the same minor version. Every change SDK users can see is in the
[CHANGELOG](https://github.com/doctronic-ai/doctronic-sdk-python/blob/main/CHANGELOG.md) and on the
[GitHub Releases](https://github.com/doctronic-ai/doctronic-sdk-python/releases) page.

Each release is generated from a pinned copy of the API contract, and its CHANGELOG entry names
the contract version. The SDK keeps working when the API adds fields, enum values, stream events,
or webhook events (see Models above). New operations need a new SDK release.

Each release supports the Python versions that CI tests, 3.10 to 3.15 today. A Python version is
dropped only in a minor release, after it reaches its end of life.

## Support

- **Using the API:** the [Doctronic API documentation](https://docs.doctronic.ai) has the guides,
  the reference, and the [errors](https://docs.doctronic.ai/docs/errors/) and webhook pages. For
  access or account questions, see [get access](https://docs.doctronic.ai/docs/authentication/#get-access).
- **SDK bugs and requests:** open an [issue](https://github.com/doctronic-ai/doctronic-sdk-python/issues/new/choose).
  Issues are public: **never post API tokens, webhook secrets, patient data, or PHI.** Include the
  `request_id` of a failed call.
- **Security vulnerabilities:** report them privately at
  <https://github.com/doctronic-ai/doctronic-sdk-python/security/advisories/new>, never in an issue.
  See the [security policy](https://github.com/doctronic-ai/doctronic-sdk-python/blob/main/SECURITY.md).
- **Supported releases:** fixes, including security fixes, go to the latest release. Upgrade to
  get them.

## Development

```bash
uv sync                                  # Python environment with the pinned dev tools
uv run pytest                            # Tests, against a mock API. No network calls.
uv run ruff check . && uv run ruff format --check .
uv run mypy                              # Strict
uv run python scripts/generate.py        # Regenerate src/doctronic/_generated/
```

`scripts/generate.py` regenerates the models (datamodel-code-generator) and the operations table
from `openapi/doctronic-v1.json`, a pinned copy of the public contract at
`https://docs.doctronic.ai/openapi/doctronic-v1.json`. Pass `--contract <path|url>` to read
another copy. The operations table is where the SDK reads which operations are idempotent and
user-scoped. Commit the output. CI regenerates from the pinned copy and fails on any difference.
`regenerate.yml` opens a pull request when the docs publish a new contract, and
`contract-drift.yml` reports daily when the pinned copy falls behind.
[CONTRIBUTING.md](https://github.com/doctronic-ai/doctronic-sdk-python/blob/main/CONTRIBUTING.md) has the details.

## License

MIT. See [LICENSE](https://github.com/doctronic-ai/doctronic-sdk-python/blob/main/LICENSE).
