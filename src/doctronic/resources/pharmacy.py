from __future__ import annotations

from functools import cached_property

from .._base_client import RequestOptions
from .._generated.models import PharmacySearchRequest, PharmacySearchResponse, PharmacySetRequest
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    build_body,
    parse_empty,
    parse_model,
    to_raw_response_wrapper,
)
from .._types import NOT_GIVEN, NotGiven

__all__ = [
    "AsyncPharmacyResource",
    "AsyncScopedPharmacyResource",
    "PharmacyResource",
    "ScopedPharmacyResource",
]

_parse_search = parse_model(PharmacySearchResponse)


def _search_options(
    latitude: float,
    longitude: float,
    search_term: str | NotGiven | None,
    state: str | NotGiven | None,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(
        PharmacySearchRequest,
        latitude=latitude,
        longitude=longitude,
        search_term=search_term,
        state=state,
    )
    return RequestOptions("POST", "/pharmacy/search/", body=body, idempotency_key=idempotency_key)


def _set_options(ncpdp_id: str, idempotency_key: str | NotGiven) -> RequestOptions:
    body = build_body(PharmacySetRequest, ncpdp_id=ncpdp_id)
    return RequestOptions("PUT", "/pharmacy/", body=body, idempotency_key=idempotency_key)


class PharmacyResource(SyncAPIResource):
    """`client.pharmacy`: searching pharmacies takes the token alone."""

    def search(
        self,
        *,
        latitude: float,
        longitude: float,
        search_term: str | NotGiven | None = NOT_GIVEN,
        state: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> PharmacySearchResponse:
        """`POST /pharmacy/search/`: pharmacies near a point, ranked by proximity unless
        `search_term` is set."""
        return self._request(
            _search_options(latitude, longitude, search_term, state, idempotency_key),
            _parse_search,
        )

    @cached_property
    def with_raw_response(self) -> PharmacyResourceWithRawResponse:
        return PharmacyResourceWithRawResponse(self)


class ScopedPharmacyResource(SyncAPIResource):
    """`client.for_user(user_id).pharmacy`: the user's preferred pharmacy."""

    def set(self, *, ncpdp_id: str, idempotency_key: str | NotGiven = NOT_GIVEN) -> None:
        """`PUT /pharmacy/`: save or replace the preferred pharmacy by its NCPDP ID."""
        return self._request(_set_options(ncpdp_id, idempotency_key), parse_empty)

    @cached_property
    def with_raw_response(self) -> ScopedPharmacyResourceWithRawResponse:
        return ScopedPharmacyResourceWithRawResponse(self)


class AsyncPharmacyResource(AsyncAPIResource):
    """`client.pharmacy`: searching pharmacies takes the token alone."""

    async def search(
        self,
        *,
        latitude: float,
        longitude: float,
        search_term: str | NotGiven | None = NOT_GIVEN,
        state: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> PharmacySearchResponse:
        """`POST /pharmacy/search/`: pharmacies near a point, ranked by proximity unless
        `search_term` is set."""
        return await self._request(
            _search_options(latitude, longitude, search_term, state, idempotency_key),
            _parse_search,
        )

    @cached_property
    def with_raw_response(self) -> AsyncPharmacyResourceWithRawResponse:
        return AsyncPharmacyResourceWithRawResponse(self)


class AsyncScopedPharmacyResource(AsyncAPIResource):
    """`client.for_user(user_id).pharmacy`: the user's preferred pharmacy."""

    async def set(self, *, ncpdp_id: str, idempotency_key: str | NotGiven = NOT_GIVEN) -> None:
        """`PUT /pharmacy/`: save or replace the preferred pharmacy by its NCPDP ID."""
        return await self._request(_set_options(ncpdp_id, idempotency_key), parse_empty)

    @cached_property
    def with_raw_response(self) -> AsyncScopedPharmacyResourceWithRawResponse:
        return AsyncScopedPharmacyResourceWithRawResponse(self)


class PharmacyResourceWithRawResponse:
    def __init__(self, pharmacy: PharmacyResource) -> None:
        self.search = to_raw_response_wrapper(pharmacy.search)


class ScopedPharmacyResourceWithRawResponse:
    def __init__(self, pharmacy: ScopedPharmacyResource) -> None:
        self.set = to_raw_response_wrapper(pharmacy.set)


class AsyncPharmacyResourceWithRawResponse:
    def __init__(self, pharmacy: AsyncPharmacyResource) -> None:
        self.search = async_to_raw_response_wrapper(pharmacy.search)


class AsyncScopedPharmacyResourceWithRawResponse:
    def __init__(self, pharmacy: AsyncScopedPharmacyResource) -> None:
        self.set = async_to_raw_response_wrapper(pharmacy.set)
