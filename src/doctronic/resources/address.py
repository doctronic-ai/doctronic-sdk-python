from __future__ import annotations

from functools import cached_property

from .._base_client import RequestOptions
from .._generated.models import AddressRequest, AddressResponse
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    build_body,
    parse_empty,
    parse_model,
    to_raw_response_wrapper,
)
from .._types import NOT_GIVEN, NotGiven

__all__ = ["AddressResource", "AsyncAddressResource"]

_parse_address = parse_model(AddressResponse)


def _set_options(
    line1: str | NotGiven | None,
    line2: str | NotGiven | None,
    city: str | NotGiven | None,
    state: str | NotGiven | None,
    postal_code: str | NotGiven | None,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(
        AddressRequest,
        line1=line1,
        line2=line2,
        city=city,
        state=state,
        postal_code=postal_code,
    )
    return RequestOptions("PUT", "/address/", body=body, idempotency_key=idempotency_key)


class AddressResource(SyncAPIResource):
    """`client.for_user(user_id).address`: the address on file, which booking needs."""

    def retrieve(self) -> AddressResponse:
        """`GET /address/`. Raises `NotFoundError` (`error.address.not_found`) when none is set."""
        return self._request(RequestOptions("GET", "/address/"), _parse_address)

    def set(
        self,
        *,
        line1: str | NotGiven | None = NOT_GIVEN,
        line2: str | NotGiven | None = NOT_GIVEN,
        city: str | NotGiven | None = NOT_GIVEN,
        state: str | NotGiven | None = NOT_GIVEN,
        postal_code: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> None:
        """`PUT /address/`: create or replace the address. Booking needs `line1`, `city`,
        `state`, and `postal_code`."""
        return self._request(
            _set_options(line1, line2, city, state, postal_code, idempotency_key), parse_empty
        )

    @cached_property
    def with_raw_response(self) -> AddressResourceWithRawResponse:
        return AddressResourceWithRawResponse(self)


class AsyncAddressResource(AsyncAPIResource):
    """`client.for_user(user_id).address`: the address on file, which booking needs."""

    async def retrieve(self) -> AddressResponse:
        """`GET /address/`. Raises `NotFoundError` (`error.address.not_found`) when none is set."""
        return await self._request(RequestOptions("GET", "/address/"), _parse_address)

    async def set(
        self,
        *,
        line1: str | NotGiven | None = NOT_GIVEN,
        line2: str | NotGiven | None = NOT_GIVEN,
        city: str | NotGiven | None = NOT_GIVEN,
        state: str | NotGiven | None = NOT_GIVEN,
        postal_code: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> None:
        """`PUT /address/`: create or replace the address. Booking needs `line1`, `city`,
        `state`, and `postal_code`."""
        return await self._request(
            _set_options(line1, line2, city, state, postal_code, idempotency_key), parse_empty
        )

    @cached_property
    def with_raw_response(self) -> AsyncAddressResourceWithRawResponse:
        return AsyncAddressResourceWithRawResponse(self)


class AddressResourceWithRawResponse:
    def __init__(self, address: AddressResource) -> None:
        self.retrieve = to_raw_response_wrapper(address.retrieve)
        self.set = to_raw_response_wrapper(address.set)


class AsyncAddressResourceWithRawResponse:
    def __init__(self, address: AsyncAddressResource) -> None:
        self.retrieve = async_to_raw_response_wrapper(address.retrieve)
        self.set = async_to_raw_response_wrapper(address.set)
