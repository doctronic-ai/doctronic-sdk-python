from __future__ import annotations

import httpx
import pytest
import respx

from doctronic import (
    ArtifactNotReadyError,
    AsyncDoctronic,
    Doctronic,
    InternalServerError,
    NotFoundError,
)
from doctronic.types import SoapNoteArtifactResponse
from tests.conftest import FakeClock
from tests.helpers import USER_ID, error, ok, resolve

AnyClient = Doctronic | AsyncDoctronic

SOAP_NOTE = {
    "artifactType": "soap_note",
    "artifactId": "art_03",
    "content": {"chatId": "chat_01", "createdAt": "2026-08-16T15:30:00Z", "body": "S: ..."},
}
GENERATING = httpx.Response(202)


@pytest.mark.asyncio
async def test_polls_until_ready_with_exponential_backoff(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    route = api.get("/artifacts/art_03/").mock(side_effect=[GENERATING] * 7 + [ok(SOAP_NOTE)])
    patient = client.for_user(USER_ID)

    artifact = await resolve(patient.artifacts.wait_until_ready("art_03"))

    assert isinstance(artifact, SoapNoteArtifactResponse)
    assert artifact.content.body == "S: ..."
    assert route.call_count == 8
    bases = [1, 2, 4, 8, 16, 16, 16]
    assert len(clock.sleeps) == len(bases)
    for delay, base in zip(clock.sleeps, bases, strict=True):
        assert base <= delay <= 1.1 * base


@pytest.mark.asyncio
async def test_times_out_while_still_generating(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    route = api.get("/artifacts/art_03/").mock(return_value=GENERATING)

    with pytest.raises(ArtifactNotReadyError) as raised:
        await resolve(client.for_user(USER_ID).artifacts.wait_until_ready("art_03", timeout=10))

    assert raised.value.artifact_id == "art_03"
    assert clock.now == pytest.approx(10)  # Raised at the deadline...
    assert route.call_count == 4  # ...polling at about 0, 1, 3, and 7s, and never at the deadline.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "error_type"),
    [
        (404, "error.artifact.not_found", NotFoundError),
        (500, "error.internal", InternalServerError),
    ],
)
async def test_stops_on_permanent_errors(
    client: AnyClient,
    api: respx.MockRouter,
    status: int,
    code: str,
    error_type: type[Exception],
) -> None:
    route = api.get("/artifacts/art_03/").mock(side_effect=[GENERATING, error(status, code)])

    with pytest.raises(error_type):
        await resolve(client.for_user(USER_ID).artifacts.wait_until_ready("art_03"))

    assert route.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1])
async def test_timeout_must_be_positive(client: AnyClient, timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        await resolve(
            client.for_user(USER_ID).artifacts.wait_until_ready("art_03", timeout=timeout)
        )


@pytest.mark.asyncio
async def test_deadline_covers_retries_inside_a_poll(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    route = api.get("/artifacts/art_03/").mock(
        return_value=error(503, headers={"retry-after": "30"})
    )

    with pytest.raises(ArtifactNotReadyError):
        await resolve(client.for_user(USER_ID).artifacts.wait_until_ready("art_03", timeout=10))

    assert route.call_count == 1  # The 30-second retry wait would end past the deadline.
    assert clock.now == pytest.approx(10)


@pytest.mark.asyncio
async def test_each_attempt_is_capped_by_the_time_left(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    route = api.get("/artifacts/art_03/").mock(side_effect=[GENERATING, ok(SOAP_NOTE)])

    await resolve(client.for_user(USER_ID).artifacts.wait_until_ready("art_03", timeout=5))

    first, second = (call.request.extensions["timeout"] for call in route.calls)
    assert first == {"connect": 5, "read": 5, "write": 5, "pool": 5}
    left = 5 - clock.sleeps[0]
    assert second == pytest.approx({"connect": left, "read": left, "write": left, "pool": left})


@pytest.mark.asyncio
async def test_a_request_cut_short_by_the_deadline_ends_the_wait(
    client: AnyClient, api: respx.MockRouter
) -> None:
    route = api.get("/artifacts/art_03/").mock(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(ArtifactNotReadyError):
        await resolve(client.for_user(USER_ID).artifacts.wait_until_ready("art_03", timeout=5))

    assert route.call_count == 1  # Not retried: the deadline, not the server, ended it.


@pytest.mark.asyncio
async def test_default_timeout_is_two_minutes(
    client: AnyClient, api: respx.MockRouter, clock: FakeClock
) -> None:
    api.get("/artifacts/art_03/").mock(return_value=GENERATING)

    with pytest.raises(ArtifactNotReadyError) as raised:
        await resolve(client.for_user(USER_ID).artifacts.wait_until_ready("art_03"))

    assert raised.value.timeout == 120
    assert clock.now == pytest.approx(120)
