from __future__ import annotations

from datetime import date
from functools import cached_property

from .._base_client import RequestOptions
from .._generated.models import CreateUserRequest, Sex, UpdateUserRequest, UserCreatedResponse
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    build_body,
    parse_model,
    to_raw_response_wrapper,
)
from .._types import NOT_GIVEN, NotGiven

__all__ = [
    "AsyncScopedUsersResource",
    "AsyncUsersResource",
    "ScopedUsersResource",
    "UsersResource",
]

_parse_user = parse_model(UserCreatedResponse)


def _profile_options(
    method: str,
    model: type[CreateUserRequest] | type[UpdateUserRequest],
    first_name: str | NotGiven | None,
    last_name: str | NotGiven | None,
    date_of_birth: str | date | NotGiven | None,
    email: str | NotGiven | None,
    phone_number: str | NotGiven | None,
    sex: Sex | str | NotGiven | None,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(
        model,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        email=email,
        phone_number=phone_number,
        sex=sex,
    )
    return RequestOptions(method, "/users/", body=body, idempotency_key=idempotency_key)


class UsersResource(SyncAPIResource):
    """`client.users`: creating a user takes the token alone."""

    def create(
        self,
        *,
        first_name: str | NotGiven | None = NOT_GIVEN,
        last_name: str | NotGiven | None = NOT_GIVEN,
        date_of_birth: str | date | NotGiven | None = NOT_GIVEN,
        email: str | NotGiven | None = NOT_GIVEN,
        phone_number: str | NotGiven | None = NOT_GIVEN,
        sex: Sex | str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> UserCreatedResponse:
        """`POST /users/`: create the Doctronic user for a patient. Save the returned `id`."""
        options = _profile_options(
            "POST",
            CreateUserRequest,
            first_name,
            last_name,
            date_of_birth,
            email,
            phone_number,
            sex,
            idempotency_key,
        )
        return self._request(options, _parse_user)

    @cached_property
    def with_raw_response(self) -> UsersResourceWithRawResponse:
        return UsersResourceWithRawResponse(self)


class ScopedUsersResource(SyncAPIResource):
    """`client.for_user(user_id).users`: the profile of the selected user."""

    def retrieve(self) -> UserCreatedResponse:
        """`GET /users/`: the profile for the selected user."""
        return self._request(RequestOptions("GET", "/users/"), _parse_user)

    def update(
        self,
        *,
        first_name: str | NotGiven | None = NOT_GIVEN,
        last_name: str | NotGiven | None = NOT_GIVEN,
        date_of_birth: str | date | NotGiven | None = NOT_GIVEN,
        email: str | NotGiven | None = NOT_GIVEN,
        phone_number: str | NotGiven | None = NOT_GIVEN,
        sex: Sex | str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> UserCreatedResponse:
        """`PATCH /users/`: change only the fields you pass. Pass `None` to clear a field."""
        options = _profile_options(
            "PATCH",
            UpdateUserRequest,
            first_name,
            last_name,
            date_of_birth,
            email,
            phone_number,
            sex,
            idempotency_key,
        )
        return self._request(options, _parse_user)

    @cached_property
    def with_raw_response(self) -> ScopedUsersResourceWithRawResponse:
        return ScopedUsersResourceWithRawResponse(self)


class AsyncUsersResource(AsyncAPIResource):
    """`client.users`: creating a user takes the token alone."""

    async def create(
        self,
        *,
        first_name: str | NotGiven | None = NOT_GIVEN,
        last_name: str | NotGiven | None = NOT_GIVEN,
        date_of_birth: str | date | NotGiven | None = NOT_GIVEN,
        email: str | NotGiven | None = NOT_GIVEN,
        phone_number: str | NotGiven | None = NOT_GIVEN,
        sex: Sex | str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> UserCreatedResponse:
        """`POST /users/`: create the Doctronic user for a patient. Save the returned `id`."""
        options = _profile_options(
            "POST",
            CreateUserRequest,
            first_name,
            last_name,
            date_of_birth,
            email,
            phone_number,
            sex,
            idempotency_key,
        )
        return await self._request(options, _parse_user)

    @cached_property
    def with_raw_response(self) -> AsyncUsersResourceWithRawResponse:
        return AsyncUsersResourceWithRawResponse(self)


class AsyncScopedUsersResource(AsyncAPIResource):
    """`client.for_user(user_id).users`: the profile of the selected user."""

    async def retrieve(self) -> UserCreatedResponse:
        """`GET /users/`: the profile for the selected user."""
        return await self._request(RequestOptions("GET", "/users/"), _parse_user)

    async def update(
        self,
        *,
        first_name: str | NotGiven | None = NOT_GIVEN,
        last_name: str | NotGiven | None = NOT_GIVEN,
        date_of_birth: str | date | NotGiven | None = NOT_GIVEN,
        email: str | NotGiven | None = NOT_GIVEN,
        phone_number: str | NotGiven | None = NOT_GIVEN,
        sex: Sex | str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> UserCreatedResponse:
        """`PATCH /users/`: change only the fields you pass. Pass `None` to clear a field."""
        options = _profile_options(
            "PATCH",
            UpdateUserRequest,
            first_name,
            last_name,
            date_of_birth,
            email,
            phone_number,
            sex,
            idempotency_key,
        )
        return await self._request(options, _parse_user)

    @cached_property
    def with_raw_response(self) -> AsyncScopedUsersResourceWithRawResponse:
        return AsyncScopedUsersResourceWithRawResponse(self)


class UsersResourceWithRawResponse:
    def __init__(self, users: UsersResource) -> None:
        self.create = to_raw_response_wrapper(users.create)


class ScopedUsersResourceWithRawResponse:
    def __init__(self, users: ScopedUsersResource) -> None:
        self.retrieve = to_raw_response_wrapper(users.retrieve)
        self.update = to_raw_response_wrapper(users.update)


class AsyncUsersResourceWithRawResponse:
    def __init__(self, users: AsyncUsersResource) -> None:
        self.create = async_to_raw_response_wrapper(users.create)


class AsyncScopedUsersResourceWithRawResponse:
    def __init__(self, users: AsyncScopedUsersResource) -> None:
        self.retrieve = async_to_raw_response_wrapper(users.retrieve)
        self.update = async_to_raw_response_wrapper(users.update)
