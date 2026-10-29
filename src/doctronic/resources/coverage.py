from __future__ import annotations

from functools import cached_property

from .._base_client import RequestOptions
from .._generated.models import CoverageRequest
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    build_body,
    parse_empty,
    to_raw_response_wrapper,
)
from .._types import NOT_GIVEN, NotGiven

__all__ = ["AsyncCoverageResource", "CoverageResource"]


def _set_options(
    payer_id: str,
    payer_name: str,
    member_id: str,
    group_number: str | NotGiven | None,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(
        CoverageRequest,
        payer_id=payer_id,
        payer_name=payer_name,
        member_id=member_id,
        group_number=group_number,
    )
    return RequestOptions("PUT", "/coverage/", body=body, idempotency_key=idempotency_key)


class CoverageResource(SyncAPIResource):
    """`client.for_user(user_id).coverage`: the patient's primary insurance coverage."""

    def set(
        self,
        *,
        payer_id: str,
        payer_name: str,
        member_id: str,
        group_number: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> None:
        """`PUT /coverage/`: store or replace the coverage. Send every required field."""
        return self._request(
            _set_options(payer_id, payer_name, member_id, group_number, idempotency_key),
            parse_empty,
        )

    @cached_property
    def with_raw_response(self) -> CoverageResourceWithRawResponse:
        return CoverageResourceWithRawResponse(self)


class AsyncCoverageResource(AsyncAPIResource):
    """`client.for_user(user_id).coverage`: the patient's primary insurance coverage."""

    async def set(
        self,
        *,
        payer_id: str,
        payer_name: str,
        member_id: str,
        group_number: str | NotGiven | None = NOT_GIVEN,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> None:
        """`PUT /coverage/`: store or replace the coverage. Send every required field."""
        return await self._request(
            _set_options(payer_id, payer_name, member_id, group_number, idempotency_key),
            parse_empty,
        )

    @cached_property
    def with_raw_response(self) -> AsyncCoverageResourceWithRawResponse:
        return AsyncCoverageResourceWithRawResponse(self)


class CoverageResourceWithRawResponse:
    def __init__(self, coverage: CoverageResource) -> None:
        self.set = to_raw_response_wrapper(coverage.set)


class AsyncCoverageResourceWithRawResponse:
    def __init__(self, coverage: AsyncCoverageResource) -> None:
        self.set = async_to_raw_response_wrapper(coverage.set)
