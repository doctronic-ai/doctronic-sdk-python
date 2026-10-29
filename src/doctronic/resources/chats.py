from __future__ import annotations

from functools import cached_property
from typing import Any

import httpx

from .._base_client import RequestOptions
from .._generated.models import (
    ChatResponse,
    CreateChatRequest,
    PageChatResponse,
    PageMessageResponse,
    StreamChatRequest,
    UserMessageEvent,
)
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    build_body,
    build_query,
    parse_model,
    to_raw_response_wrapper,
)
from .._streaming import AsyncChatStream, ChatStream
from .._types import NOT_GIVEN, NotGiven

__all__ = ["AsyncChatsResource", "ChatsResource"]

_parse_chat = parse_model(ChatResponse)
_parse_chat_page = parse_model(PageChatResponse)
_parse_message_page = parse_model(PageMessageResponse)


def _create_options(
    timezone: str | NotGiven,
    conversation_prompt_context: str | NotGiven | None,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(
        CreateChatRequest,
        timezone=timezone,
        conversation_prompt_context=conversation_prompt_context,
    )
    return RequestOptions("POST", "/chats/", body=body, idempotency_key=idempotency_key)


def _list_options(
    page: int | NotGiven, size: int | NotGiven, order_by: str | NotGiven
) -> RequestOptions:
    return RequestOptions(
        "GET", "/chats/", params=build_query({"page": page, "size": size, "orderBy": order_by})
    )


def _retrieve_options(chat_id: str) -> RequestOptions:
    return RequestOptions("GET", "/chats/{chatId}/", path_params={"chatId": chat_id})


def _messages_options(
    chat_id: str, page: int | NotGiven, size: int | NotGiven, order_by: str | NotGiven
) -> RequestOptions:
    return RequestOptions(
        "GET",
        "/chats/{chatId}/messages/",
        path_params={"chatId": chat_id},
        params=build_query({"page": page, "size": size, "orderBy": order_by}),
    )


def _stream_options(
    chat_id: str,
    user_input: str,
    message_prompt_context: str | NotGiven | None,
    timezone: str | NotGiven,
) -> RequestOptions:
    body: dict[str, Any] = {
        "userEvent": build_body(
            UserMessageEvent,
            type="user_message",
            user_input=user_input,
            message_prompt_context=message_prompt_context,
        ),
        **build_body(StreamChatRequest, timezone=timezone),
    }
    return RequestOptions(
        "POST", "/chats/{chatId}/stream/", path_params={"chatId": chat_id}, body=body
    )


def _open_stream(response: httpx.Response) -> ChatStream:
    return ChatStream(response)


def _open_async_stream(response: httpx.Response) -> AsyncChatStream:
    return AsyncChatStream(response)


class ChatsResource(SyncAPIResource):
    """`client.for_user(user_id).chats`: one chat per consultation."""

    def create(
        self,
        *,
        timezone: str | NotGiven = NOT_GIVEN,
        conversation_prompt_context: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> ChatResponse:
        """`POST /chats/`: create a chat. Save the returned `id` with the consultation."""
        return self._request(
            _create_options(timezone, conversation_prompt_context, idempotency_key), _parse_chat
        )

    def list(
        self,
        *,
        page: int | NotGiven = NOT_GIVEN,
        size: int | NotGiven = NOT_GIVEN,
        order_by: str | NotGiven = NOT_GIVEN,
    ) -> PageChatResponse:
        """`GET /chats/`: the user's chats, newest first by default."""
        return self._request(_list_options(page, size, order_by), _parse_chat_page)

    def retrieve(self, chat_id: str) -> ChatResponse:
        """`GET /chats/{chatId}/`: one chat."""
        return self._request(_retrieve_options(chat_id), _parse_chat)

    def messages(
        self,
        chat_id: str,
        *,
        page: int | NotGiven = NOT_GIVEN,
        size: int | NotGiven = NOT_GIVEN,
        order_by: str | NotGiven = NOT_GIVEN,
    ) -> PageMessageResponse:
        """`GET /chats/{chatId}/messages/`: the transcript, oldest first by default."""
        return self._request(_messages_options(chat_id, page, size, order_by), _parse_message_page)

    def stream(
        self,
        chat_id: str,
        *,
        user_input: str,
        message_prompt_context: str | NotGiven | None = NOT_GIVEN,
        timezone: str | NotGiven = NOT_GIVEN,
    ) -> ChatStream:
        """`POST /chats/{chatId}/stream/`: send one patient turn and stream the reply.

        Raises `ConflictError` (`error.partner.chat_stream_in_progress`) or
        `ServiceUnavailableError` (`error.partner.chat_stream_unavailable`) before the stream
        starts. Never retried.
        """
        return self._request(
            _stream_options(chat_id, user_input, message_prompt_context, timezone),
            _open_stream,
        )

    @cached_property
    def with_raw_response(self) -> ChatsResourceWithRawResponse:
        return ChatsResourceWithRawResponse(self)


class AsyncChatsResource(AsyncAPIResource):
    """`client.for_user(user_id).chats`: one chat per consultation."""

    async def create(
        self,
        *,
        timezone: str | NotGiven = NOT_GIVEN,
        conversation_prompt_context: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> ChatResponse:
        """`POST /chats/`: create a chat. Save the returned `id` with the consultation."""
        return await self._request(
            _create_options(timezone, conversation_prompt_context, idempotency_key), _parse_chat
        )

    async def list(
        self,
        *,
        page: int | NotGiven = NOT_GIVEN,
        size: int | NotGiven = NOT_GIVEN,
        order_by: str | NotGiven = NOT_GIVEN,
    ) -> PageChatResponse:
        """`GET /chats/`: the user's chats, newest first by default."""
        return await self._request(_list_options(page, size, order_by), _parse_chat_page)

    async def retrieve(self, chat_id: str) -> ChatResponse:
        """`GET /chats/{chatId}/`: one chat."""
        return await self._request(_retrieve_options(chat_id), _parse_chat)

    async def messages(
        self,
        chat_id: str,
        *,
        page: int | NotGiven = NOT_GIVEN,
        size: int | NotGiven = NOT_GIVEN,
        order_by: str | NotGiven = NOT_GIVEN,
    ) -> PageMessageResponse:
        """`GET /chats/{chatId}/messages/`: the transcript, oldest first by default."""
        return await self._request(
            _messages_options(chat_id, page, size, order_by), _parse_message_page
        )

    async def stream(
        self,
        chat_id: str,
        *,
        user_input: str,
        message_prompt_context: str | NotGiven | None = NOT_GIVEN,
        timezone: str | NotGiven = NOT_GIVEN,
    ) -> AsyncChatStream:
        """`POST /chats/{chatId}/stream/`: send one patient turn and stream the reply.

        Raises `ConflictError` (`error.partner.chat_stream_in_progress`) or
        `ServiceUnavailableError` (`error.partner.chat_stream_unavailable`) before the stream
        starts. Never retried.
        """
        return await self._request(
            _stream_options(chat_id, user_input, message_prompt_context, timezone),
            _open_async_stream,
        )

    @cached_property
    def with_raw_response(self) -> AsyncChatsResourceWithRawResponse:
        return AsyncChatsResourceWithRawResponse(self)


class ChatsResourceWithRawResponse:
    def __init__(self, chats: ChatsResource) -> None:
        self.create = to_raw_response_wrapper(chats.create)
        self.list = to_raw_response_wrapper(chats.list)
        self.retrieve = to_raw_response_wrapper(chats.retrieve)
        self.messages = to_raw_response_wrapper(chats.messages)
        self.stream = to_raw_response_wrapper(chats.stream)


class AsyncChatsResourceWithRawResponse:
    def __init__(self, chats: AsyncChatsResource) -> None:
        self.create = async_to_raw_response_wrapper(chats.create)
        self.list = async_to_raw_response_wrapper(chats.list)
        self.retrieve = async_to_raw_response_wrapper(chats.retrieve)
        self.messages = async_to_raw_response_wrapper(chats.messages)
        self.stream = async_to_raw_response_wrapper(chats.stream)
