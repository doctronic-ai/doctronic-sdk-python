"""Stream timeouts and cancellation over real sockets, against a server on 127.0.0.1."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import httpx
import pytest
import pytest_asyncio

from doctronic import (
    APITimeoutError,
    APIUserAbortError,
    AsyncChatStream,
    AsyncDoctronic,
    ChatStream,
    Doctronic,
)
from doctronic.types import ChatStreamEvent, MessageStartEvent
from tests.local_server import LocalServer, serve

TIMEOUT = 0.2


@pytest.fixture
def server() -> Iterator[LocalServer]:
    yield from serve()


@pytest.fixture
def sync_stream(server: LocalServer) -> Iterator[Callable[..., ChatStream]]:
    """Opens a stream with test headers that steer the server. Closes the clients afterwards."""
    clients: list[Doctronic] = []

    def open_stream(**headers: str) -> ChatStream:
        http_client = httpx.Client(headers={f"X-Test-{k}": v for k, v in headers.items()})
        client = Doctronic(
            api_token="test-token",
            base_url=server.base_url,
            timeout=TIMEOUT,
            http_client=http_client,
        )
        clients.append(client)
        return client.for_user("mem_test").chats.stream("chat_01", user_input="Hi")

    yield open_stream
    for client in clients:
        client._engine._http.close()


@pytest_asyncio.fixture
async def async_stream(
    server: LocalServer,
) -> AsyncIterator[Callable[..., Awaitable[AsyncChatStream]]]:
    clients: list[AsyncDoctronic] = []

    async def open_stream(**headers: str) -> AsyncChatStream:
        http_client = httpx.AsyncClient(headers={f"X-Test-{k}": v for k, v in headers.items()})
        client = AsyncDoctronic(
            api_token="test-token",
            base_url=server.base_url,
            timeout=TIMEOUT,
            http_client=http_client,
        )
        clients.append(client)
        return await client.for_user("mem_test").chats.stream("chat_01", user_input="Hi")

    yield open_stream
    for client in clients:
        await client._engine._http.aclose()


def test_stream_start_is_bounded_by_the_timeout(
    server: LocalServer, sync_stream: Callable[..., ChatStream]
) -> None:
    started = time.monotonic()
    with pytest.raises(APITimeoutError):
        sync_stream(**{"Delay-Headers": "1.5"})
    assert time.monotonic() - started < 1.0
    assert server.requests == 1  # Never retried.


@pytest.mark.asyncio
async def test_async_stream_start_is_bounded_by_the_timeout(
    server: LocalServer, async_stream: Callable[..., Awaitable[AsyncChatStream]]
) -> None:
    started = time.monotonic()
    with pytest.raises(APITimeoutError):
        await async_stream(**{"Delay-Headers": "1.5"})
    assert time.monotonic() - started < 1.0
    assert server.requests == 1


def test_gaps_between_events_never_time_out(
    server: LocalServer, sync_stream: Callable[..., ChatStream]
) -> None:
    with sync_stream(Gap="0.4", Frames="3") as stream:
        events = list(stream)
    assert len(events) == 3


@pytest.mark.asyncio
async def test_async_gaps_between_events_never_time_out(
    server: LocalServer, async_stream: Callable[..., Awaitable[AsyncChatStream]]
) -> None:
    async with await async_stream(Gap="0.4", Frames="3") as stream:
        events = [event async for event in stream]
    assert len(events) == 3


def test_close_from_another_thread_aborts_the_reader(
    server: LocalServer, sync_stream: Callable[..., ChatStream]
) -> None:
    stream = sync_stream(Gap="30", Frames="2")
    assert isinstance(next(stream), MessageStartEvent)
    outcome: list[BaseException | list[ChatStreamEvent]] = []

    def read_rest() -> None:
        try:
            outcome.append(list(stream))
        except BaseException as exc:
            outcome.append(exc)

    reader = threading.Thread(target=read_rest)
    reader.start()
    time.sleep(0.2)  # Let the reader block on the socket.
    started = time.monotonic()
    stream.close()
    reader.join(timeout=5)

    assert not reader.is_alive()
    assert time.monotonic() - started < 2
    assert len(outcome) == 1
    assert isinstance(outcome[0], APIUserAbortError)
    assert stream.response.is_closed
    with pytest.raises(APIUserAbortError):
        next(stream)


@pytest.mark.asyncio
async def test_close_from_another_task_aborts_the_reader(
    server: LocalServer, async_stream: Callable[..., Awaitable[AsyncChatStream]]
) -> None:
    stream = await async_stream(Gap="30", Frames="2")
    assert isinstance(await stream.__anext__(), MessageStartEvent)

    async def read_rest() -> list[ChatStreamEvent]:
        return [event async for event in stream]

    reader = asyncio.create_task(read_rest())
    await asyncio.sleep(0.2)  # Let the reader wait on the socket.
    await stream.close()

    with pytest.raises(APIUserAbortError):
        await asyncio.wait_for(reader, timeout=2)
    assert stream.response.is_closed


@pytest.mark.asyncio
async def test_cancelling_the_reading_task_propagates_and_releases(
    server: LocalServer, async_stream: Callable[..., Awaitable[AsyncChatStream]]
) -> None:
    stream = await async_stream(Gap="30", Frames="2")

    async def read_all() -> list[ChatStreamEvent]:
        return [event async for event in stream]

    reader = asyncio.create_task(read_all())
    await asyncio.sleep(0.2)
    reader.cancel()

    with pytest.raises(asyncio.CancelledError):
        await reader
    assert stream.response.is_closed
