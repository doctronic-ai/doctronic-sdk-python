from __future__ import annotations

import asyncio
import json
import random
from typing import Any, get_args

import httpx
import pytest
import respx

from doctronic import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIUserAbortError,
    AsyncChatStream,
    AsyncChatStreamManager,
    AsyncDoctronic,
    ChatStream,
    ConflictError,
    Doctronic,
    ServiceUnavailableError,
)
from doctronic._generated.events import STREAM_EVENTS
from doctronic._streaming import SSEDecoder, SSEFrame, decode_frame, parse_event
from doctronic.types import (
    AiConsultationCompleteEvent,
    ChatStreamEvent,
    ConsultationArtifacts,
    ConversationEndEvent,
    ConversationOfftopicEvent,
    GuardianCategory,
    GuardianEvent,
    KnownChatStreamEvent,
    MessageContentEvent,
    MessageStartEvent,
    MessageStopEvent,
    PartnerGuardianId,
    SkillCodeCtaEvent,
    StreamChatConsultationCompleteEvent,
    StreamChatConversationEndEvent,
    StreamChatConversationOfftopicEvent,
    StreamChatCTAEvent,
    StreamChatErrorEvent,
    StreamChatGuardianEvent,
    StreamChatMessageContentEvent,
    StreamChatMessageStartEvent,
    StreamChatMessageStopEvent,
    StreamErrorEvent,
    UnknownChatStreamEvent,
)
from tests.helpers import (
    BASE_URL,
    TOKEN,
    USER_ID,
    collect,
    drain,
    error,
    ok,
    open_stream,
    pinned_contract,
    recorded_stream,
    resolve,
    sse_response,
)

AnyClient = Doctronic | AsyncDoctronic

EXPECTED_TYPES = [
    "message.start",
    "message.content",
    "message.start",
    "guardian",
    "message.content",
    "message.content",
    "message.stop",
    "conversation.offtopic",
    "skill_code.cta",
    "message.stop",
    "conversation.end",
    "ai_consultation.complete",
    "error",
    "future.event",
]


def parse_chunks(chunks: list[bytes]) -> list[ChatStreamEvent]:
    decoder = SSEDecoder()
    return [parse_event(frame) for chunk in chunks for frame in decoder.feed(chunk)]


def with_line_endings(data: bytes, ending: bytes) -> bytes:
    return data.replace(b"\n", ending)


EXPECTED = parse_chunks([recorded_stream()])


def test_recorded_stream_parses_into_typed_events() -> None:
    assert [event.type for event in EXPECTED] == EXPECTED_TYPES
    start = EXPECTED[0]
    assert isinstance(start, MessageStartEvent)
    assert (start.role, start.message_id, start.message_timestamp) == (
        "assistant",
        "ac_hist_01",
        1741856873000,
    )
    multiline = EXPECTED[4]
    assert isinstance(multiline, MessageContentEvent)
    assert multiline.content == "A fever of 101.5 °F — let\u2019s look at it."
    guardian = EXPECTED[3]
    assert isinstance(guardian, GuardianEvent)
    assert guardian.guardian_id == "emergency_breathing"
    assert isinstance(EXPECTED[7], ConversationOfftopicEvent)
    cta = EXPECTED[8]
    assert isinstance(cta, SkillCodeCtaEvent)
    assert (cta.skill_code, cta.widget, cta.text) == (
        "109",
        "cta_doctor_visit_in_person_widget",
        "See doctor in person",
    )
    assert isinstance(EXPECTED[9], MessageStopEvent)
    end = EXPECTED[10]
    assert isinstance(end, ConversationEndEvent)
    assert end.reason == "AGENT_STOP_CODE"
    complete = EXPECTED[11]
    assert isinstance(complete, AiConsultationCompleteEvent)
    assert complete.artifacts.long_summary == "art_01"
    assert complete.artifacts.soap_note is None
    stream_error = EXPECTED[12]
    assert isinstance(stream_error, StreamErrorEvent)
    assert (stream_error.error_code, stream_error.retry_after_seconds) == ("error.rate_limited", 7)
    unknown = EXPECTED[13]
    assert isinstance(unknown, UnknownChatStreamEvent)
    assert unknown.data == {"type": "future.event", "anything": [1, 2, 3]}


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"], ids=["LF", "CRLF", "CR"])
def test_split_at_every_byte_offset(ending: bytes) -> None:
    data = with_line_endings(recorded_stream(), ending)
    for offset in range(len(data) + 1):
        assert parse_chunks([data[:offset], data[offset:]]) == EXPECTED, offset


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"], ids=["LF", "CRLF", "CR"])
def test_one_byte_chunks(ending: bytes) -> None:
    data = with_line_endings(recorded_stream(), ending)
    assert parse_chunks([data[i : i + 1] for i in range(len(data))]) == EXPECTED


@pytest.mark.parametrize("seed", range(25))
def test_random_chunk_boundaries(seed: int) -> None:
    rng = random.Random(seed)
    data = with_line_endings(recorded_stream(), rng.choice([b"\n", b"\r\n", b"\r"]))
    cuts = sorted(rng.sample(range(1, len(data)), 12))
    chunks = [data[start:end] for start, end in zip([0, *cuts], [*cuts, len(data)], strict=True)]
    assert parse_chunks(chunks) == EXPECTED


def test_truncated_final_frame_is_dropped() -> None:
    data = recorded_stream()
    complete, _, _ = data.rstrip(b"\n").rpartition(b"\n\n")
    for cut in range(len(complete) + 2, len(data) - 1):
        events = parse_chunks([data[:cut]])
        assert [event.type for event in events] == EXPECTED_TYPES[:-1], cut


def test_stream_cut_inside_a_multibyte_character_never_raises() -> None:
    data = 'event: message.content\ndata: {"messageId":"m","content":"°'.encode()
    assert parse_chunks([data[:-1]]) == []


def test_decode_frame_rules() -> None:
    assert decode_frame(": only a comment") is None
    assert decode_frame("event: ping") is None  # No data: not an event.
    assert decode_frame("data:no-space") == SSEFrame("message", "no-space")
    assert decode_frame("data:  two spaces") == SSEFrame("message", " two spaces")
    assert decode_frame("data") == SSEFrame("message", "")
    assert decode_frame("event:x\ndata: a\ndata: b\nid: 1\nretry: 5") == SSEFrame("x", "a\nb")


def test_unknown_and_malformed_events_never_raise() -> None:
    assert parse_event(
        SSEFrame("brand.new", '{"type":"brand.new","x":1}')
    ) == UnknownChatStreamEvent(type="brand.new", data={"type": "brand.new", "x": 1})
    assert parse_event(SSEFrame("message.start", "not json")) == UnknownChatStreamEvent(
        type="message.start", data="not json"
    )
    # A known name whose payload doesn't match is passed through rather than raised.
    assert parse_event(SSEFrame("message.start", '{"role":"assistant"}')) == UnknownChatStreamEvent(
        type="message.start", data={"role": "assistant"}
    )
    assert parse_event(SSEFrame("guardian", "[1, 2]")) == UnknownChatStreamEvent(
        type="guardian", data=[1, 2]
    )


def test_frame_without_event_name_uses_payload_type() -> None:
    event = parse_event(SSEFrame("message", '{"type":"message.stop","messageId":"m1"}'))
    assert event == MessageStopEvent(message_id="m1")


def test_events_keep_extra_fields_and_round_trip_to_the_wire_shape() -> None:
    payload = {"type": "message.start", "role": "assistant", "messageId": "m1", "newField": True}
    event = parse_event(SSEFrame("message.start", json.dumps(payload)))
    assert event.model_dump(by_alias=True, exclude_none=True) == payload


# The models generated from the contract's `StreamChatEvent`.

GUARDIAN_NEW_ID: dict[str, Any] = {
    "type": "guardian",
    "guardianId": "brand_new_detector",
    "message": "",
    "endsConversation": False,
    "category": "brand_new_category",
}
COMPLETE_WITH_NULLS: dict[str, Any] = {
    "type": "ai_consultation.complete",
    "artifacts": {"longSummary": None, "shortSummary": None, "soapNote": None},
}


def frame(payload: dict[str, Any]) -> SSEFrame:
    return SSEFrame(str(payload["type"]), json.dumps(payload))


def sse(*payloads: dict[str, Any]) -> bytes:
    return b"".join(
        f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n".encode()
        for payload in payloads
    )


def test_the_event_classes_are_the_generated_models() -> None:
    assert (
        MessageStartEvent,
        MessageContentEvent,
        MessageStopEvent,
        GuardianEvent,
        ConversationOfftopicEvent,
        ConversationEndEvent,
        SkillCodeCtaEvent,
        AiConsultationCompleteEvent,
        StreamErrorEvent,
    ) == (
        StreamChatMessageStartEvent,
        StreamChatMessageContentEvent,
        StreamChatMessageStopEvent,
        StreamChatGuardianEvent,
        StreamChatConversationOfftopicEvent,
        StreamChatConversationEndEvent,
        StreamChatCTAEvent,
        StreamChatConsultationCompleteEvent,
        StreamChatErrorEvent,
    )
    assert set(get_args(KnownChatStreamEvent)) == set(STREAM_EVENTS.values())
    for name, model in STREAM_EVENTS.items():
        assert model.model_fields["type"].default == name


def test_every_documented_stream_example_parses_into_its_model() -> None:
    media = pinned_contract()["paths"]["/chats/{chatId}/stream/"]["post"]["responses"]["200"][
        "content"
    ]["text/event-stream"]

    for name, example in media["examples"].items():
        (event,) = parse_chunks([example["value"].encode()])
        assert isinstance(event, STREAM_EVENTS[event.type]), name


def test_guardian_event_has_the_contract_fields() -> None:
    event = parse_event(
        frame(
            {
                "type": "guardian",
                "guardianId": "harmful_content_detector",
                "message": "I'm not able to help with that topic.",
                "title": "Let's stay on health",
                "text": "Ask me a health question.",
                "endsConversation": True,
                "category": "safety",
            }
        )
    )

    assert isinstance(event, GuardianEvent)
    assert event.guardian_id == PartnerGuardianId.harmful_content_detector
    assert type(event.guardian_id) is str  # The wire string, as in 0.1, so logs read the same.
    assert (event.title, event.text, event.ends_conversation) == (
        "Let's stay on health",
        "Ask me a health question.",
        True,
    )
    assert event.category == GuardianCategory.safety


def test_unknown_guardian_id_and_category_still_parse() -> None:
    event = parse_event(frame(GUARDIAN_NEW_ID))

    assert isinstance(event, GuardianEvent)
    assert event.guardian_id == "brand_new_detector"
    assert event.category == "brand_new_category"
    assert event.model_dump(by_alias=True, exclude_none=True) == GUARDIAN_NEW_ID


def test_guardian_event_without_the_optional_fields_gets_the_contract_defaults() -> None:
    event = parse_event(frame({"type": "guardian", "guardianId": "emergency_breathing"}))

    assert isinstance(event, GuardianEvent)
    assert (event.message, event.title, event.text, event.ends_conversation) == (
        "",
        None,
        None,
        False,
    )
    assert event.category == GuardianCategory.other


@pytest.mark.parametrize(
    "missing",
    [("endsConversation",), ("category",), ("endsConversation", "category")],
    ids=["no-ends-conversation", "no-category", "neither"],
)
def test_guardian_event_missing_fields_is_never_demoted_to_unknown(
    missing: tuple[str, ...],
) -> None:
    # A safety signal: integrators skip unknown events, so it stays a typed `GuardianEvent` with
    # the contract's defaults, as the TypeScript SDK delivers it.
    payload: dict[str, Any] = {
        "type": "guardian",
        "guardianId": "emergency_breathing",
        "message": "Please call emergency services now.",
        "endsConversation": True,
        "category": "emergency",
    }
    for name in missing:
        del payload[name]

    event = parse_event(frame(payload))

    assert isinstance(event, GuardianEvent)
    assert event.ends_conversation is ("endsConversation" not in missing)
    assert event.category == ("other" if "category" in missing else "emergency")


def test_consultation_complete_with_null_artifacts() -> None:
    event = parse_event(frame(COMPLETE_WITH_NULLS))

    assert isinstance(event, AiConsultationCompleteEvent)
    assert event.artifacts == ConsultationArtifacts(
        long_summary=None, short_summary=None, soap_note=None
    )
    assert event.model_dump(by_alias=True) == COMPLETE_WITH_NULLS


def test_consultation_complete_without_artifact_keys_reads_them_as_null() -> None:
    event = parse_event(frame({"type": "ai_consultation.complete", "artifacts": {}}))

    assert isinstance(event, AiConsultationCompleteEvent)
    assert (event.artifacts.long_summary, event.artifacts.soap_note) == (None, None)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "ai_consultation.complete", "artifacts": None},
        {"type": "ai_consultation.complete"},
        {"type": "skill_code.cta", "widget": "w"},
        {"type": "error", "errorCode": "error.internal", "message": "x", "retryAfterSeconds": 1.5},
    ],
    ids=["null-artifacts-object", "no-artifacts", "cta-without-skill-code", "fractional-retry"],
)
def test_a_known_event_the_contract_rejects_is_unknown(payload: dict[str, Any]) -> None:
    assert parse_event(frame(payload)) == UnknownChatStreamEvent(
        type=str(payload["type"]), data=payload
    )


def test_message_role_is_an_open_enum() -> None:
    user = parse_event(frame({"type": "message.start", "role": "user", "messageId": "m1"}))
    narrator = parse_event(frame({"type": "message.start", "role": "narrator", "messageId": "m2"}))
    default = parse_event(frame({"type": "message.start", "messageId": "m3"}))

    assert isinstance(user, MessageStartEvent)
    assert user.role == "user"
    assert isinstance(narrator, MessageStartEvent)
    assert narrator.role == "narrator"
    assert isinstance(default, MessageStartEvent)
    assert default.role == "assistant"


def test_skill_code_cta_without_a_widget() -> None:
    event = parse_event(frame({"type": "skill_code.cta", "skillCode": "109"}))

    assert event == SkillCodeCtaEvent(skill_code="109")
    assert isinstance(event, SkillCodeCtaEvent)
    assert event.widget is None


# Through the client, sync and async.


def mock_stream(api: respx.MockRouter, chunks: list[bytes], **kwargs: object) -> respx.Route:
    response, _ = sse_response(chunks, **kwargs)  # type: ignore[arg-type]
    return api.post("/chats/chat_01/stream/").mock(return_value=response)


@pytest.mark.asyncio
async def test_stream_request_and_events(client: AnyClient, api: respx.MockRouter) -> None:
    data = recorded_stream()
    route = mock_stream(api, [data[:100], data[100:333], data[333:]])

    stream = await open_stream(
        client.for_user(USER_ID).chats.stream(
            "chat_01",
            user_input="I have had a sore throat and fever since yesterday.",
            message_prompt_context="Temperature entered in intake.",
            timezone="America/New_York",
        )
    )
    assert isinstance(stream, (ChatStream, AsyncChatStream))
    assert stream.status_code == 200
    assert stream.request_id == "req_stream"
    events = await collect(stream)

    assert events == EXPECTED
    request = route.calls.last.request
    assert request.headers["accept"] == "text/event-stream"
    assert request.headers["x-doctronic-user-id"] == USER_ID
    assert "idempotency-key" not in request.headers
    assert json.loads(request.content) == {
        "userEvent": {
            "type": "user_message",
            "userInput": "I have had a sore throat and fever since yesterday.",
            "messagePromptContext": "Temperature entered in intake.",
        },
        "timezone": "America/New_York",
    }


@pytest.mark.asyncio
async def test_final_messages_assembles_by_message_id(
    client: AnyClient, api: respx.MockRouter
) -> None:
    mock_stream(api, [recorded_stream()])
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    first = await resolve(
        stream.__anext__() if isinstance(stream, AsyncChatStream) else next(stream)
    )
    assert isinstance(first, MessageStartEvent)
    final = await resolve(stream.final_messages())

    assert final.messages[0].message_timestamp == 1741856873000
    assert type(final.messages[0].role) is str  # The plain string, as in 0.1.
    assert [(m.message_id, m.role, m.content, m.complete) for m in final.messages] == [
        (
            "ac_hist_01",
            "assistant",
            "I can help with that. A fever of 101.5 °F — let\u2019s look at it.",
            True,
        ),
        ("ac_hist_02", "assistant", "Second message.", True),
    ]
    assert [event.type for event in final.control_events] == [
        "guardian",
        "conversation.offtopic",
        "skill_code.cta",
        "conversation.end",
        "ai_consultation.complete",
        "error",
        "future.event",
    ]


@pytest.mark.asyncio
async def test_final_messages_marks_messages_cut_off(
    client: AnyClient, api: respx.MockRouter
) -> None:
    mock_stream(
        api,
        [
            b'event: message.start\ndata: {"role":"assistant","messageId":"m1"}\n\n',
            b'event: message.content\ndata: {"messageId":"m1","content":"Partial"}\n\n',
            b'event: message.content\ndata: {"messageId":"orphan","content":"No start"}\n\n',
        ],
    )
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    final = await resolve(stream.final_messages())

    assert [(m.message_id, m.content, m.complete) for m in final.messages] == [
        ("m1", "Partial", False)
    ]


@pytest.mark.asyncio
async def test_contract_events_through_the_client(client: AnyClient, api: respx.MockRouter) -> None:
    future: dict[str, Any] = {"type": "conversation.handoff", "to": "clinician"}
    mock_stream(api, [sse(GUARDIAN_NEW_ID, COMPLETE_WITH_NULLS, future)])
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    final = await resolve(stream.final_messages())

    guardian, complete, unknown = final.control_events
    assert isinstance(guardian, GuardianEvent)
    assert (guardian.guardian_id, guardian.category) == ("brand_new_detector", "brand_new_category")
    assert isinstance(complete, AiConsultationCompleteEvent)
    assert complete.artifacts.short_summary is None
    assert unknown == UnknownChatStreamEvent(type="conversation.handoff", data=future)


@pytest.mark.asyncio
async def test_error_event_is_yielded_not_raised(client: AnyClient, api: respx.MockRouter) -> None:
    mock_stream(
        api,
        [
            b'event: error\ndata: {"type":"error","errorCode":"error.consultation_not_ready",'
            b'"message":"Not ready."}\n\n'
        ],
    )
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    events = await collect(stream)

    assert events == [
        StreamErrorEvent(error_code="error.consultation_not_ready", message="Not ready.")
    ]


@pytest.mark.asyncio
async def test_context_manager_closes_the_connection(
    client: AnyClient, api: respx.MockRouter
) -> None:
    response, body = sse_response([recorded_stream()])
    api.post("/chats/chat_01/stream/").mock(return_value=response)
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    if isinstance(stream, AsyncChatStream):
        async with stream:
            first = await stream.__anext__()
    else:
        with stream:
            first = next(stream)

    assert isinstance(first, MessageStartEvent)
    assert body.closed
    assert stream.response.is_closed
    # Closed before the turn ended: reading on reports the abort instead of a clean end.
    with pytest.raises(APIUserAbortError):
        await collect(stream)
    with pytest.raises(APIUserAbortError):
        await resolve(stream.final_messages())


@pytest.mark.asyncio
async def test_close_before_iterating(client: AnyClient, api: respx.MockRouter) -> None:
    response, body = sse_response([recorded_stream()])
    api.post("/chats/chat_01/stream/").mock(return_value=response)
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    for _ in range(2):  # Closing twice is safe.
        if isinstance(stream, AsyncChatStream):
            await stream.close()
        else:
            stream.close()

    assert body.closed
    with pytest.raises(APIUserAbortError):
        await collect(stream)


@pytest.mark.asyncio
async def test_closing_a_finished_stream_is_not_an_abort(
    client: AnyClient, api: respx.MockRouter
) -> None:
    mock_stream(api, [recorded_stream()])
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    if isinstance(stream, AsyncChatStream):
        async with stream:
            events = [event async for event in stream]
    else:
        with stream:
            events = list(stream)

    assert len(events) == len(EXPECTED)
    assert await collect(stream) == []
    final = await resolve(stream.final_messages())
    assert len(final.messages) == 2


@pytest.mark.asyncio
async def test_reading_to_the_end_closes_the_connection(
    client: AnyClient, api: respx.MockRouter
) -> None:
    response, body = sse_response([recorded_stream()])
    api.post("/chats/chat_01/stream/").mock(return_value=response)
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    await collect(stream)

    assert body.closed


@pytest.mark.asyncio
async def test_dropped_connection_raises_connection_error(
    client: AnyClient, api: respx.MockRouter
) -> None:
    data = recorded_stream()
    cut = data.index(b"event: message.start", 20)  # After the first two events.
    route = mock_stream(api, [data[:cut]], fail_with=httpx.ReadError("connection reset"))
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    seen: list[ChatStreamEvent] = []
    with pytest.raises(APIConnectionError):
        await drain(stream, seen)

    assert seen == EXPECTED[:2]
    assert route.call_count == 1  # Never resent.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "error_type"),
    [
        (409, "error.partner.chat_stream_in_progress", ConflictError),
        (503, "error.partner.chat_stream_unavailable", ServiceUnavailableError),
    ],
)
async def test_errors_before_the_stream_starts_raise_and_are_not_retried(
    client: AnyClient,
    api: respx.MockRouter,
    status: int,
    code: str,
    error_type: type[Exception],
) -> None:
    route = api.post("/chats/chat_01/stream/").mock(
        return_value=error(status, code, headers={"retry-after": "1"})
    )

    with pytest.raises(error_type) as raised:
        await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    assert getattr(raised.value, "code", None) == code
    assert route.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(500),
        httpx.Response(429),
    ],
    ids=["connect-error", "timeout", "500", "429"],
)
async def test_stream_is_never_retried(
    client: AnyClient, api: respx.MockRouter, failure: Exception | httpx.Response
) -> None:
    route = api.post("/chats/chat_01/stream/").mock(side_effect=[failure, sse_response([b""])[0]])

    with pytest.raises(Exception):  # noqa: B017, PT011 - the error type is tested elsewhere.
        await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_stream_response_that_is_not_an_event_stream(
    client: AnyClient, api: respx.MockRouter
) -> None:
    route = api.post("/chats/chat_01/stream/").mock(return_value=ok({"unexpected": True}))

    with pytest.raises(APIResponseValidationError) as raised:
        await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))

    assert isinstance(raised.value, APIError)
    assert raised.value.status == 200
    assert "text/event-stream" in raised.value.message
    assert route.call_count == 1


async def next_from_generator(stream: ChatStream | AsyncChatStream) -> ChatStreamEvent:
    """Advance the underlying generator, skipping the stream's own closed check."""
    if isinstance(stream, AsyncChatStream):
        return await stream._iterator.__anext__()
    return next(stream._iterator)


@pytest.mark.asyncio
async def test_frames_already_read_are_dropped_after_an_abort(
    client: AnyClient, api: respx.MockRouter
) -> None:
    mock_stream(api, [recorded_stream()])  # One chunk: every frame is read at once.
    stream = await open_stream(client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"))
    first = await resolve(
        stream.__anext__() if isinstance(stream, AsyncChatStream) else next(stream)
    )
    assert isinstance(first, MessageStartEvent)

    # A close from another thread or task that lands while the reader is between frames.
    stream._mark_closed()

    with pytest.raises(APIUserAbortError):
        await next_from_generator(stream)


# `AsyncDoctronic` `chats.stream()` works with `async with`, `await`, and asyncio's task APIs.


async def async_client(api: respx.MockRouter) -> AsyncDoctronic:
    mock_stream(api, [recorded_stream()])
    return AsyncDoctronic(api_token=TOKEN, base_url=BASE_URL)


@pytest.mark.asyncio
async def test_async_stream_works_with_async_with_and_no_await(api: respx.MockRouter) -> None:
    async with await async_client(api) as client:
        async with client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi") as stream:
            assert isinstance(stream, AsyncChatStream)
            first = await stream.__anext__()
            assert isinstance(first, MessageStartEvent)

        # Leaving the block closed the stream before its end.
        with pytest.raises(APIUserAbortError):
            await stream.__anext__()


@pytest.mark.asyncio
async def test_async_stream_can_still_be_awaited(api: respx.MockRouter) -> None:
    async with await async_client(api) as client:
        patient = client.for_user(USER_ID)
        stream = await patient.chats.stream("chat_01", user_input="Hi")
        assert isinstance(stream, AsyncChatStream)
        await stream.close()

        async with await patient.chats.stream("chat_01", user_input="Hi") as again:
            assert isinstance(again, AsyncChatStream)


@pytest.mark.asyncio
async def test_async_stream_is_a_coroutine_for_asyncio(api: respx.MockRouter) -> None:
    async with await async_client(api) as client:
        manager = client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi")
        assert isinstance(manager, AsyncChatStreamManager)
        assert asyncio.iscoroutine(manager)

        stream = await asyncio.create_task(manager)
        (gathered,) = await asyncio.gather(
            client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi")
        )
        assert isinstance(stream, AsyncChatStream)
        assert isinstance(gathered, AsyncChatStream)
        await stream.close()
        await gathered.close()


@pytest.mark.asyncio
async def test_async_stream_sends_nothing_until_entered(api: respx.MockRouter) -> None:
    async with await async_client(api) as client:
        route = api.routes[0]
        manager = client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi")
        assert route.call_count == 0
        async with manager as stream:
            assert route.call_count == 1
            assert stream.request_id == "req_stream"


@pytest.mark.asyncio
async def test_async_stream_errors_raise_from_async_with(api: respx.MockRouter) -> None:
    api.post("/chats/chat_01/stream/").mock(
        return_value=error(409, "error.partner.chat_stream_in_progress")
    )
    async with AsyncDoctronic(api_token=TOKEN, base_url=BASE_URL) as client:
        with pytest.raises(ConflictError):
            async with client.for_user(USER_ID).chats.stream("chat_01", user_input="Hi"):
                pytest.fail("The block must not run when the stream doesn't start.")


@pytest.mark.asyncio
async def test_async_stream_raw_response(api: respx.MockRouter) -> None:
    async with await async_client(api) as client:
        chats = client.for_user(USER_ID).chats
        raw = await chats.with_raw_response.stream("chat_01", user_input="Hi")
        assert raw.status_code == 200
        stream = raw.parse()
        assert isinstance(stream, AsyncChatStream)
        await stream.close()
