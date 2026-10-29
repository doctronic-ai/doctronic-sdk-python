from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
import respx

from doctronic import (
    APIConnectionError,
    APITimeoutError,
    AsyncDoctronic,
    BadRequestError,
    ConflictError,
    Doctronic,
    DoctronicError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    _retry,
)
from doctronic._base_client import RequestOptions
from doctronic._generated.operations import OPERATIONS, Operation
from doctronic._response import parse_empty
from tests.conftest import FakeClock
from tests.helpers import (
    BASE_URL,
    TOKEN,
    USER_ID,
    ChunkedStream,
    error,
    ok,
    pinned_contract,
    resolve,
)
from tests.test_codegen import CONCURRENT, PAYLOAD_MISMATCH, facts, with_retryable_codes

AnyClient = Doctronic | AsyncDoctronic

CHAT = {"id": "chat_01", "createdAt": "2026-08-31T14:31:00Z"}
SLOT_TAKEN = "error.appointments.slot_unavailable"
SCHEDULED = {
    "id": "dc_01",
    "chatId": "chat_01",
    "status": "booked",
    "durationMinutes": 15,
    "location": {"state": "NY"},
}


def create_chat(client: AnyClient) -> object:
    return client.for_user(USER_ID).chats.create(timezone="America/New_York")


@pytest.mark.asyncio
async def test_idempotent_retry_reuses_key_and_body(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    route = api.post("/chats/").mock(
        side_effect=[
            error(503, headers={"retry-after": "3"}),
            httpx.ConnectError("reset"),
            ok(CHAT, 201),
        ]
    )

    await resolve(create_chat(client))

    assert route.call_count == 3
    keys = {call.request.headers["idempotency-key"] for call in route.calls}
    bodies = {call.request.content for call in route.calls}
    assert len(keys) == 1
    assert bodies == {json.dumps({"timezone": "America/New_York"}, separators=(",", ":")).encode()}
    assert clock.sleeps[0] == 3  # Honors Retry-After.
    assert len(clock.sleeps) == 2


@pytest.mark.asyncio
async def test_caller_key_is_reused_across_retries(
    client: AnyClient, api: respx.MockRouter
) -> None:
    route = api.post("/chats/").mock(side_effect=[httpx.ReadTimeout("slow"), ok(CHAT, 201)])

    await resolve(client.for_user(USER_ID).chats.create(idempotency_key="mine"))

    assert [call.request.headers["idempotency-key"] for call in route.calls] == ["mine", "mine"]


@pytest.mark.asyncio
async def test_retries_stop_after_max_retries(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.post("/chats/").mock(return_value=error(503, "error.idempotency.unavailable"))

    with pytest.raises(ServiceUnavailableError):
        await resolve(create_chat(client))

    assert route.call_count == 3  # The first attempt plus max_retries=2.


@pytest.mark.asyncio
@pytest.mark.parametrize("client_type", [Doctronic, AsyncDoctronic])
async def test_max_retries_zero_disables_retries(
    api: respx.MockRouter, client_type: type[AnyClient]
) -> None:
    route = api.get("/users/").mock(return_value=error(503))
    client = client_type(api_token=TOKEN, base_url=BASE_URL, max_retries=0)

    with pytest.raises(ServiceUnavailableError):
        await resolve(client.for_user(USER_ID).users.retrieve())

    assert route.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        error(500),
        error(502),
        error(503),
        error(504),
        error(429),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
    ids=["500", "502", "503", "504", "429", "connect-error", "timeout"],
)
async def test_reads_retry_transient_failures(
    client: AnyClient, api: respx.MockRouter, failure: httpx.Response | Exception
) -> None:
    route = api.get("/chats/chat_01/").mock(side_effect=[failure, ok(CHAT)])

    chat = await resolve(client.for_user(USER_ID).chats.retrieve("chat_01"))

    assert chat.id == "chat_01"
    assert route.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 504])
async def test_mutations_do_not_retry_other_5xx(
    client: AnyClient, api: respx.MockRouter, status: int
) -> None:
    route = api.post("/chats/").mock(
        return_value=error(status, "error.appointments.provisioning_failed")
    )

    with pytest.raises(InternalServerError):
        await resolve(create_chat(client))

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_idempotent_mutation_retries_429(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.post("/chats/").mock(side_effect=[error(429), ok(CHAT, 201)])

    await resolve(create_chat(client))

    assert route.call_count == 2


@pytest.mark.asyncio
async def test_idempotency_conflict_409_is_retried(
    client: AnyClient, api: respx.MockRouter
) -> None:
    # The contract documents no code for an idempotency 409: the first request is in progress.
    route = api.post("/appointments/scheduled/").mock(side_effect=[error(409), ok(SCHEDULED, 201)])

    await resolve(
        client.for_user(USER_ID).appointments.create_scheduled(
            chat_id="chat_01", starts_at="2026-09-01T15:00:00Z", location={"state": "NY"}
        )
    )

    assert route.call_count == 2
    assert len({call.request.headers["idempotency-key"] for call in route.calls}) == 1


@pytest.mark.asyncio
async def test_state_conflict_409_is_not_retried(client: AnyClient, api: respx.MockRouter) -> None:
    assert SLOT_TAKEN in OPERATIONS[("POST", "/appointments/scheduled/")].conflict_codes
    route = api.post("/appointments/scheduled/").mock(return_value=error(409, SLOT_TAKEN))

    with pytest.raises(ConflictError) as raised:
        await resolve(
            client.for_user(USER_ID).appointments.create_scheduled(
                chat_id="chat_01", starts_at="2026-09-01T15:00:00Z", location={"state": "NY"}
            )
        )

    assert raised.value.code == SLOT_TAKEN
    assert route.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "attempts"),
    [
        (CONCURRENT, 2),  # Listed in x-doctronic-retryable-codes.
        (PAYLOAD_MISMATCH, 1),  # Documented, not listed: final.
        (SLOT_TAKEN, 1),  # Documented, not listed: final.
        ("error.idempotency.something_new", 2),  # Undocumented: an idempotency conflict.
        (None, 2),
    ],
)
async def test_409_codes_follow_the_retryable_codes_extension(
    client: AnyClient,
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    code: str | None,
    attempts: int,
) -> None:
    key = ("POST", "/appointments/scheduled/")
    generated = facts(with_retryable_codes(pinned_contract(), extension=[CONCURRENT]))[key]
    monkeypatch.setitem(
        OPERATIONS,
        key,
        dataclasses.replace(OPERATIONS[key], conflict_codes=frozenset(generated["conflict_codes"])),
    )
    route = api.post("/appointments/scheduled/").mock(
        side_effect=[error(409, code), ok(SCHEDULED, 201)]
    )

    def book() -> object:
        return client.for_user(USER_ID).appointments.create_scheduled(
            chat_id="chat_01", starts_at="2026-09-01T15:00:00Z", location={"state": "NY"}
        )

    if attempts == 2:
        await resolve(book())
    else:
        with pytest.raises(ConflictError) as raised:
            await resolve(book())
        assert raised.value.code == code

    assert route.call_count == attempts
    assert len({call.request.headers["idempotency-key"] for call in route.calls}) == 1


@pytest.mark.asyncio
async def test_409_on_a_read_is_not_retried(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.get("/appointments/dc_01/result/").mock(
        return_value=error(409, "error.appointments.result_unavailable")
    )

    with pytest.raises(ConflictError):
        await resolve(client.for_user(USER_ID).appointments.result("dc_01"))

    assert route.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(
    client: AnyClient, api: respx.MockRouter, status: int
) -> None:
    route = api.post("/chats/").mock(return_value=error(status, "error.some_code"))

    with pytest.raises(Exception):  # noqa: B017, PT011 - mapping is tested in test_errors.py.
        await resolve(create_chat(client))

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_artifact_generation_failure_is_not_retried(
    client: AnyClient, api: respx.MockRouter
) -> None:
    route = api.get("/artifacts/art_01/").mock(return_value=error(500, "error.internal"))

    with pytest.raises(InternalServerError):
        await resolve(client.for_user(USER_ID).artifacts.retrieve("art_01"))

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_long_retry_after_ends_retries(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.get("/users/").mock(return_value=error(429, headers={"retry-after": "3600"}))

    with pytest.raises(RateLimitError) as raised:
        await resolve(client.for_user(USER_ID).users.retrieve())

    assert raised.value.retry_after == 3600
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_retry_after_http_date(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    api.get("/users/").mock(
        side_effect=[
            error(503, headers={"retry-after": when}),
            ok(
                {
                    "id": USER_ID,
                    "appointmentDemographicsComplete": False,
                    "missingAppointmentFields": ["firstName"],
                }
            ),
        ]
    )

    await resolve(client.for_user(USER_ID).users.retrieve())

    assert 25 <= clock.sleeps[0] <= 30


@pytest.mark.asyncio
async def test_exhausted_network_retries_raise_connection_errors(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.get("/users/").mock(side_effect=httpx.ConnectError("refused"))
    api.get("/address/").mock(side_effect=httpx.ConnectTimeout("slow"))
    user = client.for_user(USER_ID)

    with pytest.raises(APIConnectionError) as connection:
        await resolve(user.users.retrieve())
    with pytest.raises(APITimeoutError):
        await resolve(user.address.retrieve())

    assert not isinstance(connection.value, APITimeoutError)
    assert isinstance(connection.value.__cause__, httpx.ConnectError)


def test_backoff_is_exponential_with_jitter_and_capped() -> None:
    for retries, base in [(0, 0.5), (1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0), (10, 8.0)]:
        for _ in range(50):
            delay = _retry.retry_delay(retries, None)
            assert delay is not None
            assert base <= delay <= 1.25 * base
    # Retry-After replaces the backoff, up to the 60-second limit.
    assert _retry.retry_delay(0, 5.0) == 5.0
    assert _retry.retry_delay(3, 0.0) == 0.0
    assert _retry.retry_delay(0, 60.0) == 60.0
    assert _retry.retry_delay(0, 61.0) is None


def test_retry_after_parsing() -> None:
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "7"})) == 7
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "-3"})) == 0
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "soon"})) is None
    assert _retry.parse_retry_after(httpx.Headers({"retry-after": "nan"})) is None
    assert _retry.parse_retry_after(httpx.Headers()) is None


def test_only_documented_5xx_on_reads_is_final() -> None:
    reads_with_documented_5xx = {
        key
        for key, operation in OPERATIONS.items()
        if operation.method == "GET" and any(status >= 500 for status in operation.statuses)
    }
    assert reads_with_documented_5xx == {("GET", "/artifacts/{artifactId}/")}
    artifact = OPERATIONS[("GET", "/artifacts/{artifactId}/")]
    assert not _retry.should_retry_status(artifact, 500, "error.internal")
    assert _retry.should_retry_status(artifact, 502, None)


def test_only_reads_and_contract_idempotent_operations_are_retry_safe() -> None:
    retry_safe = {key for key, operation in OPERATIONS.items() if _retry.retry_safe(operation)}
    unsafe = set(OPERATIONS) - retry_safe
    assert unsafe == {("POST", "/chats/{chatId}/stream/")}
    assert [key for key, operation in OPERATIONS.items() if operation.stream] == [
        ("POST", "/chats/{chatId}/stream/")
    ]
    assert sum(operation.idempotent for operation in OPERATIONS.values()) == 11


SYNTHETIC_POST = Operation(
    operation_id="synthetic_post",
    method="POST",
    path="/synthetic/",
    idempotent=False,
    user_scoped=False,
    stream=False,
    data_required=False,
    statuses=frozenset({200, 503}),
    conflict_codes=frozenset(),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [error(503), error(429), error(409), error(502), httpx.ConnectError("refused")],
    ids=["503", "429", "409", "502", "connect-error"],
)
async def test_non_idempotent_post_is_never_retried(
    client: AnyClient,
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    failure: httpx.Response | Exception,
) -> None:
    # Every mutation in today's contract except the stream is idempotent, so exercise the rule
    # with a synthetic operation that has no Idempotency-Key.
    monkeypatch.setitem(OPERATIONS, ("POST", "/synthetic/"), SYNTHETIC_POST)
    route = api.post("/synthetic/").mock(side_effect=[failure, ok(None)])

    with pytest.raises(DoctronicError):
        await resolve(
            client._engine.request(
                RequestOptions("POST", "/synthetic/", body={}), user_id=None, parser=parse_empty
            )
        )

    assert route.call_count == 1
    assert "idempotency-key" not in route.calls.last.request.headers
    assert not _retry.retry_safe(SYNTHETIC_POST)


@pytest.mark.asyncio
async def test_cut_off_error_body_keeps_its_status_and_retry_after(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    cut_off = ChunkedStream([b'{"code":"error.idem'], fail_with=httpx.ReadError("reset"))
    route = api.post("/chats/").mock(
        side_effect=[
            httpx.Response(503, headers={"retry-after": "2"}, stream=cut_off),
            ok(CHAT, 201),
        ]
    )

    await resolve(create_chat(client))

    assert route.call_count == 2
    assert clock.sleeps == [2]


@pytest.mark.asyncio
async def test_cut_off_client_error_is_not_retried(
    client: AnyClient, api: respx.MockRouter
) -> None:
    cut_off = ChunkedStream([b'{"code":"error.user.con'], fail_with=httpx.ReadError("reset"))
    route = api.post("/chats/").mock(return_value=httpx.Response(400, stream=cut_off))

    with pytest.raises(BadRequestError) as raised:
        await resolve(create_chat(client))

    assert raised.value.code is None
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_cut_off_success_body_is_a_connection_error(
    client: AnyClient, api: respx.MockRouter
) -> None:
    def cut_off() -> httpx.Response:
        stream = ChunkedStream([b'{"code":"success","da'], fail_with=httpx.ReadError("reset"))
        return httpx.Response(200, stream=stream)

    retried = api.get("/chats/chat_01/").mock(side_effect=[cut_off(), ok(CHAT)])
    exhausted = api.get("/users/").mock(side_effect=[cut_off(), cut_off(), cut_off()])
    user = client.for_user(USER_ID)

    chat = await resolve(user.chats.retrieve("chat_01"))
    with pytest.raises(APIConnectionError):
        await resolve(user.users.retrieve())

    assert chat.id == "chat_01"
    assert retried.call_count == 2
    assert exhausted.call_count == 3
