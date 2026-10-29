from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from doctronic import (
    APIResponse,
    AsyncChatStream,
    AsyncDoctronic,
    ChatStream,
    Doctronic,
    UserScopedClient,
)
from doctronic.types import ChatResponse, UserCreatedResponse
from tests.helpers import USER_ID, collect, ok, recorded_stream, resolve, sse_response

AnyClient = Doctronic | AsyncDoctronic

CHAT = {"id": "chat_01", "createdAt": "2026-08-31T14:31:00Z"}
USER = {"id": USER_ID, "appointmentDemographicsComplete": True, "missingAppointmentFields": []}


@pytest.mark.asyncio
async def test_client_level_raw_response(client: AnyClient, api: respx.MockRouter) -> None:
    api.post("/users/").mock(
        return_value=ok(
            USER, 201, headers={"x-request-id": "req_9", "idempotency-replayed": "true"}
        )
    )

    raw = await resolve(client.with_raw_response.users.create(first_name="Test"))

    assert isinstance(raw, APIResponse)
    assert raw.status_code == 201
    assert raw.request_id == "req_9"
    assert raw.headers["x-request-id"] == "req_9"
    assert raw.idempotency_replayed is True
    assert raw.idempotency_key is not None
    assert uuid.UUID(raw.idempotency_key).version == 4
    user = raw.parse()
    assert isinstance(user, UserCreatedResponse)
    assert user is raw.parse()  # Parsed once.


@pytest.mark.asyncio
async def test_resource_level_raw_response(client: AnyClient, api: respx.MockRouter) -> None:
    api.get("/chats/chat_01/").mock(return_value=ok(CHAT, headers={"x-request-id": "req_10"}))

    raw = await resolve(client.for_user(USER_ID).chats.with_raw_response.retrieve("chat_01"))

    assert raw.request_id == "req_10"
    assert raw.idempotency_key is None
    assert raw.idempotency_replayed is False
    assert isinstance(raw.parse(), ChatResponse)


@pytest.mark.asyncio
async def test_user_client_raw_response(client: AnyClient, api: respx.MockRouter) -> None:
    api.put("/coverage/").mock(return_value=ok(None))

    raw = await resolve(
        client.for_user(USER_ID).with_raw_response.coverage.set(
            payer_id="00590", payer_name="Example Health Plan", member_id="ABC1234567"
        )
    )

    assert raw.status_code == 200
    assert raw.parse() is None


@pytest.mark.asyncio
async def test_raw_pending_artifact(client: AnyClient, api: respx.MockRouter) -> None:
    api.get("/artifacts/art_01/").mock(return_value=httpx.Response(202))

    raw = await resolve(client.for_user(USER_ID).with_raw_response.artifacts.retrieve("art_01"))

    assert raw.status_code == 202
    assert raw.parse() is None


@pytest.mark.asyncio
async def test_raw_stream(client: AnyClient, api: respx.MockRouter) -> None:
    response, _ = sse_response([recorded_stream()])
    api.post("/chats/chat_01/stream/").mock(return_value=response)

    user = client.for_user(USER_ID)
    raw: APIResponse[ChatStream] | APIResponse[AsyncChatStream]
    if isinstance(user, UserScopedClient):
        raw = user.with_raw_response.chats.stream("chat_01", user_input="Hi")
    else:
        raw = await user.with_raw_response.chats.stream("chat_01", user_input="Hi")

    assert raw.request_id == "req_stream"
    stream = raw.parse()
    assert isinstance(stream, (ChatStream, AsyncChatStream))
    assert len(await collect(stream)) == 14


@pytest.mark.asyncio
async def test_raw_mode_does_not_leak_into_later_calls(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.get("/chats/chat_01/").mock(return_value=ok(CHAT))
    user = client.for_user(USER_ID)

    await resolve(user.with_raw_response.chats.retrieve("chat_01"))
    chat = await resolve(user.chats.retrieve("chat_01"))

    assert isinstance(chat, ChatResponse)
