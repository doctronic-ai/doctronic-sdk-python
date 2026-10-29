from __future__ import annotations

import random
from functools import cached_property

import pydantic

from .. import _retry
from .._base_client import DeadlineExceeded, RequestOptions
from .._errors import ArtifactNotReadyError
from .._generated.models import ArtifactResponse
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    none_while_pending,
    parse_data,
    to_raw_response_wrapper,
)

__all__ = ["ArtifactsResource", "AsyncArtifactsResource"]

DEFAULT_WAIT_TIMEOUT = 120.0
_FIRST_POLL_DELAY = 1.0
_MAX_POLL_DELAY = 16.0

_parse_artifact = none_while_pending(parse_data(pydantic.TypeAdapter(ArtifactResponse)))


def _retrieve_options(artifact_id: str, deadline: float | None = None) -> RequestOptions:
    # The contract documents `500` here as permanent generation failure, so it isn't retried.
    return RequestOptions(
        "GET",
        "/artifacts/{artifactId}/",
        path_params={"artifactId": artifact_id},
        deadline=deadline,
    )


class _Poll:
    """One deadline for the whole wait: every poll, the retries inside it, and the waits between."""

    def __init__(self, timeout: float) -> None:
        if not timeout > 0:
            raise ValueError("`timeout` must be a positive number of seconds.")
        self.deadline = _retry.monotonic() + timeout
        self._polls = 0

    def next_wait(self) -> tuple[float, bool]:
        """Seconds to wait before the next poll, and whether the deadline arrives first."""
        delay = min(_MAX_POLL_DELAY, _FIRST_POLL_DELAY * 2.0**self._polls)
        delay += random.random() * delay * 0.1
        self._polls += 1
        remaining = self.deadline - _retry.monotonic()
        if delay >= remaining:
            return max(remaining, 0.0), True
        return delay, False


class ArtifactsResource(SyncAPIResource):
    """`client.for_user(user_id).artifacts`: consultation documents and clinician notes."""

    def retrieve(self, artifact_id: str) -> ArtifactResponse | None:
        """`GET /artifacts/{artifactId}/`. Returns `None` while the document is still generating.

        Raises `NotFoundError` when it's absent from your scope, and `InternalServerError` when
        generation failed permanently.
        """
        return self._request(_retrieve_options(artifact_id), _parse_artifact)

    def wait_until_ready(
        self, artifact_id: str, *, timeout: float = DEFAULT_WAIT_TIMEOUT
    ) -> ArtifactResponse:
        """Poll `retrieve()` until the document is ready, backing off from 1s to 16s.

        `timeout` bounds the whole wait, including retries and requests in flight. Stops with
        `NotFoundError` on 404 and `InternalServerError` on 500, and raises
        `ArtifactNotReadyError` when the deadline passes first.
        """
        poll = _Poll(timeout)
        try:
            while True:
                artifact = self._request(
                    _retrieve_options(artifact_id, poll.deadline), _parse_artifact
                )
                if artifact is not None:
                    return artifact
                wait, expires = poll.next_wait()
                _retry.sleep(wait)
                if expires:
                    raise DeadlineExceeded
        except DeadlineExceeded:
            raise ArtifactNotReadyError(artifact_id, timeout) from None

    @cached_property
    def with_raw_response(self) -> ArtifactsResourceWithRawResponse:
        return ArtifactsResourceWithRawResponse(self)


class AsyncArtifactsResource(AsyncAPIResource):
    """`client.for_user(user_id).artifacts`: consultation documents and clinician notes."""

    async def retrieve(self, artifact_id: str) -> ArtifactResponse | None:
        """`GET /artifacts/{artifactId}/`. Returns `None` while the document is still generating.

        Raises `NotFoundError` when it's absent from your scope, and `InternalServerError` when
        generation failed permanently.
        """
        return await self._request(_retrieve_options(artifact_id), _parse_artifact)

    async def wait_until_ready(
        self, artifact_id: str, *, timeout: float = DEFAULT_WAIT_TIMEOUT
    ) -> ArtifactResponse:
        """Poll `retrieve()` until the document is ready, backing off from 1s to 16s.

        `timeout` bounds the whole wait, including retries and requests in flight. Stops with
        `NotFoundError` on 404 and `InternalServerError` on 500, and raises
        `ArtifactNotReadyError` when the deadline passes first. Cancel the task to stop early.
        """
        poll = _Poll(timeout)
        try:
            while True:
                artifact = await self._request(
                    _retrieve_options(artifact_id, poll.deadline), _parse_artifact
                )
                if artifact is not None:
                    return artifact
                wait, expires = poll.next_wait()
                await _retry.async_sleep(wait)
                if expires:
                    raise DeadlineExceeded
        except DeadlineExceeded:
            raise ArtifactNotReadyError(artifact_id, timeout) from None

    @cached_property
    def with_raw_response(self) -> AsyncArtifactsResourceWithRawResponse:
        return AsyncArtifactsResourceWithRawResponse(self)


class ArtifactsResourceWithRawResponse:
    def __init__(self, artifacts: ArtifactsResource) -> None:
        self.retrieve = to_raw_response_wrapper(artifacts.retrieve)


class AsyncArtifactsResourceWithRawResponse:
    def __init__(self, artifacts: AsyncArtifactsResource) -> None:
        self.retrieve = async_to_raw_response_wrapper(artifacts.retrieve)
