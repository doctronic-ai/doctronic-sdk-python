"""Chat stream: the Server-Sent Events parser, typed events, and the stream objects.

The event models are generated from the contract; `_generated/events.py` maps each event type to
its model.

The parser is the reference parser from the streaming guide. It handles frames split across
network chunks; CRLF, LF, and CR line endings; comment lines; multiline `data` fields; and a
truncated final frame, which it drops.
"""

from __future__ import annotations

import codecs
import contextlib
import json
import re
import socket
from collections.abc import AsyncGenerator, AsyncIterator, Coroutine, Generator, Iterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, NamedTuple, TypeAlias, cast

import httpx
import pydantic
from pydantic import BaseModel

from ._errors import APIConnectionError, APITimeoutError, APIUserAbortError, DoctronicError
from ._generated.events import STREAM_EVENTS, KnownChatStreamEvent
from ._generated.models import (
    ConsultationArtifacts,
    StreamChatConsultationCompleteEvent,
    StreamChatConversationEndEvent,
    StreamChatConversationOfftopicEvent,
    StreamChatCTAEvent,
    StreamChatErrorEvent,
    StreamChatGuardianEvent,
    StreamChatMessageContentEvent,
    StreamChatMessageStartEvent,
    StreamChatMessageStopEvent,
)

__all__ = [
    "AiConsultationCompleteEvent",
    "AsyncChatStream",
    "AsyncChatStreamManager",
    "ChatStream",
    "ChatStreamEvent",
    "ConsultationArtifacts",
    "ConversationEndEvent",
    "ConversationOfftopicEvent",
    "FinalMessages",
    "GuardianEvent",
    "KnownChatStreamEvent",
    "MessageContentEvent",
    "MessageStartEvent",
    "MessageStopEvent",
    "SSEDecoder",
    "SSEFrame",
    "SkillCodeCtaEvent",
    "StreamErrorEvent",
    "StreamedMessage",
    "UnknownChatStreamEvent",
    "decode_frame",
    "parse_event",
]

FRAME_BOUNDARY = re.compile(r"\r\n\r\n|\n\n|\r\r")
LINE_BREAK = re.compile(r"\r\n|\r|\n")


class SSEFrame(NamedTuple):
    event: str
    data: str


def decode_frame(raw: str) -> SSEFrame | None:
    event = "message"
    data: list[str] = []
    for line in LINE_BREAK.split(raw):
        if not line or line.startswith(":"):
            continue  # Blank line or comment.
        name, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
    return SSEFrame(event, "\n".join(data)) if data else None


class SSEDecoder:
    """Incremental SSE decoder: feed it bytes as they arrive and collect complete frames."""

    def __init__(self) -> None:
        # Never raise on bytes: a stream cut inside a multibyte character only damages the
        # truncated frame, which is dropped anyway.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""

    def feed(self, chunk: bytes) -> list[SSEFrame]:
        self._buffer += self._decoder.decode(chunk)
        frames: list[SSEFrame] = []
        while match := FRAME_BOUNDARY.search(self._buffer):
            frame = decode_frame(self._buffer[: match.start()])
            self._buffer = self._buffer[match.end() :]
            if frame:
                frames.append(frame)
        return frames

    # Every complete frame ends with a blank line. Whatever is still buffered when the stream
    # ends was cut off mid-frame, so there is no `flush()`: it is dropped, never parsed.


# The models are generated from the contract's `StreamChatEvent`. These are the names the SDK has
# used for them since 0.1.0; `doctronic.types` exports both.
MessageStartEvent = StreamChatMessageStartEvent
MessageContentEvent = StreamChatMessageContentEvent
MessageStopEvent = StreamChatMessageStopEvent
GuardianEvent = StreamChatGuardianEvent
ConversationOfftopicEvent = StreamChatConversationOfftopicEvent
ConversationEndEvent = StreamChatConversationEndEvent
SkillCodeCtaEvent = StreamChatCTAEvent
AiConsultationCompleteEvent = StreamChatConsultationCompleteEvent
StreamErrorEvent = StreamChatErrorEvent


class UnknownChatStreamEvent(BaseModel):
    """An event this SDK version doesn't know, or one whose payload didn't parse.

    `data` is the parsed JSON payload, or the raw `data` text when it isn't JSON.
    """

    type: str
    data: Any = None


ChatStreamEvent: TypeAlias = KnownChatStreamEvent | UnknownChatStreamEvent
"""A chat stream event. Narrow it with `isinstance`; new event types are `UnknownChatStreamEvent`."""


_NULL_IS_DEFAULT: dict[str, tuple[str, ...]] = {"guardian": ("endsConversation", "category")}
"""Fields that read as their contract default when the stream sends `null`, as in the TypeScript
SDK. A `guardian` event is a safety signal, so it must not become an unknown event, which
integrators skip, over a `null` the contract's default covers."""


def parse_event(frame: SSEFrame) -> ChatStreamEvent:
    """Turn a frame into a typed event. Never raises: anything unrecognized is unknown."""
    try:
        payload: Any = json.loads(frame.data)
    except ValueError:
        return UnknownChatStreamEvent(type=frame.event, data=frame.data)
    name = frame.event
    if name == "message" and isinstance(payload, dict) and isinstance(payload.get("type"), str):
        name = payload["type"]  # A frame without an `event:` line; fall back to the payload.
    model = STREAM_EVENTS.get(name)
    if model is None or not isinstance(payload, dict):
        return UnknownChatStreamEvent(type=name, data=payload)
    fields = {**payload, "type": name}
    for key in _NULL_IS_DEFAULT.get(name, ()):
        if key in fields and fields[key] is None:
            del fields[key]
    try:
        return cast("ChatStreamEvent", model.model_validate(fields))
    except pydantic.ValidationError:
        return UnknownChatStreamEvent(type=name, data=payload)


@dataclass
class StreamedMessage:
    """One message assembled from its `message.*` events."""

    message_id: str
    role: str
    """The role from `message.start`, as a plain string such as `"assistant"`."""
    content: str = ""
    message_timestamp: int | float | None = None
    complete: bool = False
    """`True` once its `message.stop` arrived."""


@dataclass
class FinalMessages:
    """What `final_messages()` returns: the assembled messages and every other event."""

    messages: list[StreamedMessage] = field(default_factory=list)
    """Messages in the order their `message.start` arrived."""
    control_events: list[ChatStreamEvent] = field(default_factory=list)
    """Every event other than `message.*`, in arrival order, including unknown event types."""


class _Accumulator:
    def __init__(self) -> None:
        self._messages: dict[str, StreamedMessage] = {}
        self._control_events: list[ChatStreamEvent] = []

    def add(self, event: ChatStreamEvent) -> None:
        if isinstance(event, MessageStartEvent):
            self._messages[event.message_id] = StreamedMessage(
                event.message_id, event.role.value, message_timestamp=event.message_timestamp
            )
        elif isinstance(event, MessageContentEvent):
            # Content for a message whose `message.start` never arrived has no role; like the
            # reference parser, leave it out of the assembled messages. The iterator still
            # yields it.
            message = self._messages.get(event.message_id)
            if message is not None:
                message.content += event.content
        elif isinstance(event, MessageStopEvent):
            message = self._messages.get(event.message_id)
            if message is not None:
                message.complete = True
        else:
            self._control_events.append(event)

    def result(self) -> FinalMessages:
        return FinalMessages(list(self._messages.values()), list(self._control_events))


def _interrupt(response: httpx.Response) -> bool:
    """Wake a read blocked on this response in another thread or task.

    Shutting the socket down makes the pending read return, so the reader can stop. Returns
    `False` when the transport exposes no socket.
    """
    network_stream = response.extensions.get("network_stream")
    get_extra_info = getattr(network_stream, "get_extra_info", None)
    sock = get_extra_info("socket") if callable(get_extra_info) else None
    if not isinstance(sock, socket.socket):
        return False
    with contextlib.suppress(OSError):  # Already closed.
        sock.shutdown(socket.SHUT_RDWR)
    return True


class _StreamBase:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        """The HTTP response. The body is the event stream, so don't read it directly."""
        self._accumulator = _Accumulator()
        self._finished = False  # The server ended the stream.
        self._closed = False
        self._aborted = False  # Closed before the server ended it.
        self._reading = False  # A read is in progress, possibly in another thread or task.

    @property
    def status_code(self) -> int:
        return self.response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self.response.headers

    @property
    def request_id(self) -> str | None:
        request_id: str | None = self.response.headers.get("x-request-id")
        return request_id

    def _mark_closed(self) -> bool:
        """Record a `close()`. Returns `False` if the stream was already closed."""
        if self._closed:
            return False
        self._closed = True
        self._aborted = not self._finished
        return True

    def _translate(self, exc: Exception) -> DoctronicError | None:
        if self._aborted:
            return APIUserAbortError()
        if isinstance(exc, httpx.TimeoutException):
            return APITimeoutError("The stream timed out.")
        if isinstance(exc, httpx.TransportError):
            return APIConnectionError("The stream connection failed.")
        return None


class ChatStream(_StreamBase):
    """The events of one chat turn, as a plain iterator.

    Use it as a context manager, or call `close()`, to release the connection if you stop
    before the stream ends. `close()` is safe to call from another thread, such as a cancel
    action: the reading thread then raises `APIUserAbortError`. Iterating a stream closed before
    its end raises `APIUserAbortError`, so a cancelled turn never looks finished.

    The stream is never retried: after a dropped connection or an `error` event, read the
    transcript before you let the patient resend the turn.
    """

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(response)
        self._iterator = self._iter_events()

    def __iter__(self) -> Iterator[ChatStreamEvent]:
        return self

    def __next__(self) -> ChatStreamEvent:
        if self._aborted:
            raise APIUserAbortError()
        self._reading = True
        try:
            return next(self._iterator)
        finally:
            self._reading = False

    def _iter_events(self) -> Generator[ChatStreamEvent, None, None]:
        decoder = SSEDecoder()
        try:
            for chunk in self.response.iter_bytes():
                for frame in decoder.feed(chunk):
                    if self._aborted:
                        # Closed mid-chunk: drop the frames already read instead of yielding them.
                        raise APIUserAbortError()
                    event = parse_event(frame)
                    self._accumulator.add(event)
                    yield event
            self._finished = True
        except (httpx.TransportError, httpx.StreamError) as exc:
            error = self._translate(exc)
            if error is None:
                raise
            raise error from exc
        finally:
            self.response.close()

    def final_messages(self) -> FinalMessages:
        """Read the rest of the stream, then return the assembled messages and other events.

        Includes events you already iterated over.
        """
        for _ in self:
            pass
        return self._accumulator.result()

    def close(self) -> None:
        """Release the connection. Safe to call more than once, and from another thread."""
        if not self._mark_closed():
            return
        if self._reading:
            # Another thread is blocked on a read. Wake it instead of touching the running
            # generator: it closes the response itself and raises `APIUserAbortError`.
            if not _interrupt(self.response):
                self.response.close()
            return
        self._iterator.close()
        self.response.close()

    def __enter__(self) -> ChatStream:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class AsyncChatStream(_StreamBase):
    """The events of one chat turn, as an async iterator. See `ChatStream`.

    `close()` is safe to await from another task. Cancelling the task that iterates also releases
    the connection; the cancellation propagates as `asyncio.CancelledError`.
    """

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(response)
        self._iterator = self._iter_events()

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self

    async def __anext__(self) -> ChatStreamEvent:
        if self._aborted:
            raise APIUserAbortError()
        self._reading = True
        try:
            return await self._iterator.__anext__()
        finally:
            self._reading = False

    async def _iter_events(self) -> AsyncGenerator[ChatStreamEvent, None]:
        decoder = SSEDecoder()
        try:
            async for chunk in self.response.aiter_bytes():
                for frame in decoder.feed(chunk):
                    if self._aborted:
                        # Closed mid-chunk: drop the frames already read instead of yielding them.
                        raise APIUserAbortError()
                    event = parse_event(frame)
                    self._accumulator.add(event)
                    yield event
            self._finished = True
        except (httpx.TransportError, httpx.StreamError) as exc:
            error = self._translate(exc)
            if error is None:
                raise
            raise error from exc
        finally:
            await self.response.aclose()

    async def final_messages(self) -> FinalMessages:
        """Read the rest of the stream, then return the assembled messages and other events.

        Includes events you already iterated over.
        """
        async for _ in self:
            pass
        return self._accumulator.result()

    async def close(self) -> None:
        """Release the connection. Safe to call more than once, and from another task."""
        if not self._mark_closed():
            return
        if self._reading:
            # Another task is waiting on a read. Wake it instead of touching the running
            # generator: it closes the response itself and raises `APIUserAbortError`.
            if not _interrupt(self.response):
                await self.response.aclose()
            return
        await self._iterator.aclose()
        await self.response.aclose()

    async def __aenter__(self) -> AsyncChatStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()


class AsyncChatStreamManager(Coroutine[Any, Any, AsyncChatStream]):
    """What `chats.stream()` returns on `AsyncDoctronic`: use it with `async with`, or await it.

    `async with patient.chats.stream(...) as stream:` opens the stream and closes it when the
    block ends. `stream = await patient.chats.stream(...)` opens it and leaves `close()` to you,
    as in 0.1.0, and `async with await patient.chats.stream(...)` still works too. It's a
    coroutine, so `asyncio.create_task()` and `asyncio.gather()` accept it as before.

    Nothing is sent until you enter or await it.
    """

    def __init__(self, opening: Coroutine[Any, Any, AsyncChatStream]) -> None:
        self._opening = opening
        self._stream: AsyncChatStream | None = None

    def __await__(self) -> Generator[Any, None, AsyncChatStream]:
        return self._opening.__await__()

    def send(self, value: Any) -> Any:
        return self._opening.send(value)

    def throw(self, *args: Any) -> Any:
        return self._opening.throw(*args)

    def close(self) -> None:
        self._opening.close()

    async def __aenter__(self) -> AsyncChatStream:
        self._stream = await self._opening
        return self._stream

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._stream is not None:
            await self._stream.close()
