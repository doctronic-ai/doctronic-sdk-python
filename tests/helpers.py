from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Iterator
from pathlib import Path
from typing import Any, TypeVar

import httpx

from doctronic import AsyncChatStream, ChatStream
from doctronic.types import ChatStreamEvent

T = TypeVar("T")

BASE_URL = "https://api.test/api/v1"
TOKEN = "test-token-not-a-real-credential"
USER_ID = "mem_test_user"
FIXTURES = Path(__file__).parent / "fixtures"


async def resolve(value: Awaitable[T] | T) -> T:
    """Await the result of an async client call; pass a sync client's result through."""
    if inspect.isawaitable(value):
        return await value
    return value


def envelope(data: Any) -> dict[str, Any]:
    return {"code": "success", "message": "Request successful", "data": data}


def ok(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=envelope(data), headers=headers)


def error(
    status: int,
    code: str | None = None,
    message: str = "Request failed",
    data: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    if code is None:
        return httpx.Response(status, headers=headers)
    body: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return httpx.Response(status, json=body, headers=headers)


class ChunkedStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A response body delivered in the given chunks, for both sync and async clients."""

    def __init__(self, chunks: list[bytes], fail_with: Exception | None = None) -> None:
        self.chunks = chunks
        self.fail_with = fail_with
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.chunks
        if self.fail_with is not None:
            raise self.fail_with

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        if self.fail_with is not None:
            raise self.fail_with

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.closed = True


def sse_response(
    chunks: list[bytes], *, fail_with: Exception | None = None
) -> tuple[httpx.Response, ChunkedStream]:
    stream = ChunkedStream(chunks, fail_with)
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream", "x-request-id": "req_stream"},
        stream=stream,
    )
    return response, stream


def recorded_stream() -> bytes:
    return (FIXTURES / "chat_stream.txt").read_bytes()


async def open_stream(
    value: ChatStream | Awaitable[AsyncChatStream],
) -> ChatStream | AsyncChatStream:
    """Await an async client's `chats.stream()`; pass a sync client's stream through."""
    if isinstance(value, ChatStream):
        return value
    return await value


async def drain(stream: ChatStream | AsyncChatStream, seen: list[ChatStreamEvent]) -> None:
    """Iterate the stream to its end, keeping each event, so a test can see a failure midway."""
    if isinstance(stream, AsyncChatStream):
        async for event in stream:
            seen.append(event)
    else:
        seen.extend(stream)


async def collect(stream: ChatStream | AsyncChatStream) -> list[ChatStreamEvent]:
    if isinstance(stream, AsyncChatStream):
        return [event async for event in stream]
    return list(stream)
