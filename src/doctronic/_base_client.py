"""The request engine shared by every resource: headers, idempotency keys, retries, errors."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast
from urllib.parse import quote

import httpx

from . import _retry
from ._errors import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    DoctronicError,
    make_status_error,
)
from ._generated.operations import OPERATIONS, Operation
from ._response import APIResponse, is_raw_response_requested
from ._types import Environment, NotGiven
from ._version import __version__

T = TypeVar("T")

ENVIRONMENTS: dict[str, str] = {
    "staging": "https://staging-partners.doctronic.ai/api/v1",
    "production": "https://partners.doctronic.ai/api/v1",
}
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
USER_ID_HEADER = "X-Doctronic-User-ID"


@dataclass(frozen=True)
class ClientConfig:
    api_token: str = field(repr=False)
    base_url: str
    timeout: httpx.Timeout
    max_retries: int


def resolve_config(
    *,
    api_token: str | None,
    environment: Environment | None,
    base_url: str | None,
    timeout: float | httpx.Timeout,
    max_retries: int,
) -> ClientConfig:
    token = api_token if api_token is not None else os.environ.get("DOCTRONIC_API_TOKEN")
    if not token:
        raise DoctronicError(
            "No API token. Pass `api_token` or set the DOCTRONIC_API_TOKEN environment variable."
        )
    env = environment or os.environ.get("DOCTRONIC_ENVIRONMENT") or "staging"
    if env not in ENVIRONMENTS:
        raise DoctronicError(f"Unknown environment {env!r}. Use 'staging' or 'production'.")
    if max_retries < 0:
        raise DoctronicError("`max_retries` can't be negative.")
    return ClientConfig(
        api_token=token,
        base_url=(base_url or ENVIRONMENTS[env]).rstrip("/"),
        timeout=timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout),
        max_retries=max_retries,
    )


@dataclass
class RequestOptions:
    method: str
    path: str
    """The contract path template, such as `/chats/{chatId}/`."""
    path_params: Mapping[str, str] = field(default_factory=dict)
    body: Any = None
    params: Mapping[str, Any] | None = None
    idempotency_key: str | NotGiven | None = None
    deadline: float | None = None
    """A `_retry.monotonic()` time after which the call gives up with `DeadlineExceeded`."""


class DeadlineExceeded(Exception):
    """A call with a deadline ran out of time: before an attempt, during one, or in a retry wait."""


@dataclass
class _Prepared:
    operation: Operation
    method: str
    url: str
    headers: dict[str, str]
    content: bytes | None
    params: Mapping[str, Any] | None
    idempotency_key: str | None
    stream: bool


def _format_path(template: str, params: Mapping[str, str]) -> str:
    values: dict[str, str] = {}
    for name, value in params.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"`{name}` must be a non-empty string.")
        values[name] = quote(value, safe="")
    return template.format(**values)


_PHASES = ("connect", "read", "write", "pool")


def _is_event_stream(response: httpx.Response) -> bool:
    content_type: str = response.headers.get("content-type", "")
    return content_type.lower().startswith("text/event-stream")


def _not_an_event_stream(response: httpx.Response) -> APIResponseValidationError:
    content_type = response.headers.get("content-type", "no content type")
    return APIResponseValidationError(
        f"Expected a text/event-stream response, got {content_type!r}.",
        status=response.status_code,
        headers=response.headers,
    )


def _lift_read_timeout(response: httpx.Response) -> None:
    """Leave the rest of a stream's body without a read timeout.

    The configured timeout covers the stream until it starts: the connection, the request, and
    the wait for the response headers. After that a turn stays open while the assistant replies,
    with gaps between events, so the body reads have no timeout. httpx hands this dict to the
    transport, which looks the read timeout up again when the body starts.
    """
    timeouts = response.request.extensions.get("timeout")
    if isinstance(timeouts, dict):
        timeouts["read"] = None


class _EngineBase:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config

    @property
    def base_url(self) -> str:
        return self._config.base_url

    @property
    def max_retries(self) -> int:
        return self._config.max_retries

    def _prepare(self, options: RequestOptions, user_id: str | None) -> _Prepared:
        operation = OPERATIONS[(options.method, options.path)]
        headers = {
            "Authorization": f"Bearer {self._config.api_token}",
            "Accept": "text/event-stream" if operation.stream else "application/json",
            "User-Agent": f"doctronic-python/{__version__}",
        }
        if operation.user_scoped:
            if not user_id:
                raise DoctronicError(
                    f"{options.method} {options.path} needs a user. Use `for_user()`."
                )
            headers[USER_ID_HEADER] = user_id
        idempotency_key: str | None = None
        if operation.idempotent:
            # One key per call, generated before the first attempt and reused by every retry.
            given = options.idempotency_key
            idempotency_key = given if isinstance(given, str) and given else str(uuid.uuid4())
            headers["Idempotency-Key"] = idempotency_key
        content: bytes | None = None
        if options.body is not None:
            # Serialized once, so every retry sends the same bytes.
            content = json.dumps(options.body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        return _Prepared(
            operation=operation,
            method=options.method,
            url=self._config.base_url + _format_path(options.path, options.path_params),
            headers=headers,
            content=content,
            params=options.params,
            idempotency_key=idempotency_key,
            stream=operation.stream,
        )

    def _attempt_timeout(self, deadline: float | None) -> tuple[httpx.Timeout, bool]:
        """The timeout for one attempt, and whether the call's deadline cut it short."""
        timeout = self._config.timeout
        if deadline is None:
            return timeout, False
        remaining = deadline - _retry.monotonic()
        if remaining <= 0:
            raise DeadlineExceeded
        phases: dict[str, float | None] = {name: getattr(timeout, name) for name in _PHASES}
        capped = any(value is None or value > remaining for value in phases.values())
        return (
            httpx.Timeout(
                **{
                    name: remaining if v is None else min(v, remaining)
                    for name, v in phases.items()
                }
            ),
            capped,
        )

    def _transport_failure(
        self, prepared: _Prepared, exc: httpx.TransportError, retries: int, capped: bool
    ) -> float:
        """The wait before retrying after a network failure, or raise the error it becomes."""
        if capped and isinstance(exc, httpx.TimeoutException):
            raise DeadlineExceeded from exc
        delay = None
        if retries < self._max_retries_for(prepared):
            delay = _retry.retry_delay(retries, None)
        if delay is None:
            if isinstance(exc, httpx.TimeoutException):
                raise APITimeoutError() from exc
            raise APIConnectionError() from exc
        return delay

    def _status_failure(self, prepared: _Prepared, error: APIError, retries: int) -> float:
        """The wait before retrying after an error status, or raise the error."""
        delay = None
        if retries < self._max_retries_for(prepared) and _retry.should_retry_status(
            prepared.operation, error.status, error.code
        ):
            delay = _retry.retry_delay(retries, error.retry_after)
        if delay is None:
            raise error
        return delay

    @staticmethod
    def _retry_wait(delay: float, deadline: float | None) -> tuple[float, bool]:
        """How long to wait before the next attempt, and whether the deadline ends the call then."""
        if deadline is None:
            return delay, False
        remaining = deadline - _retry.monotonic()
        if delay >= remaining:
            return max(remaining, 0.0), True
        return delay, False

    def _max_retries_for(self, prepared: _Prepared) -> int:
        return self._config.max_retries if _retry.retry_safe(prepared.operation) else 0


class SyncEngine(_EngineBase):
    def __init__(self, config: ClientConfig, http_client: httpx.Client | None) -> None:
        super().__init__(config)
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(timeout=config.timeout)

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def request(
        self,
        options: RequestOptions,
        *,
        user_id: str | None,
        parser: Callable[[httpx.Response], T],
    ) -> T:
        raw = is_raw_response_requested()
        prepared = self._prepare(options, user_id)
        response = self._send(prepared, options.deadline)
        result = APIResponse(response, parser, prepared.idempotency_key)
        # `with_raw_response` wrappers cast the result back to `APIResponse`.
        return cast("T", result) if raw else result.parse()

    def _send(self, prepared: _Prepared, deadline: float | None) -> httpx.Response:
        retries = 0
        while True:
            timeout, capped = self._attempt_timeout(deadline)
            request = self._http.build_request(
                prepared.method,
                prepared.url,
                headers=prepared.headers,
                content=prepared.content,
                params=prepared.params,
                timeout=timeout,
            )
            try:
                response = self._http.send(request, stream=True)
            except httpx.TransportError as exc:
                delay = self._transport_failure(prepared, exc, retries, capped)
            else:
                if response.is_success and prepared.stream:
                    if not _is_event_stream(response):
                        response.close()
                        raise _not_an_event_stream(response)
                    _lift_read_timeout(response)
                    return response
                if response.is_success:
                    try:
                        response.read()
                    except httpx.TransportError as exc:
                        # The body was cut off, so the outcome is unknown: a network failure.
                        response.close()
                        delay = self._transport_failure(prepared, exc, retries, capped)
                    else:
                        return response
                else:
                    try:
                        content = response.read()
                    except httpx.TransportError:
                        content = b""  # Cut off: the status and headers still decide.
                    finally:
                        response.close()
                    error = make_status_error(response.status_code, response.headers, content)
                    delay = self._status_failure(prepared, error, retries)
            wait, expires = self._retry_wait(delay, deadline)
            _retry.sleep(wait)
            if expires:
                raise DeadlineExceeded
            retries += 1


class AsyncEngine(_EngineBase):
    def __init__(self, config: ClientConfig, http_client: httpx.AsyncClient | None) -> None:
        super().__init__(config)
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=config.timeout)

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def request(
        self,
        options: RequestOptions,
        *,
        user_id: str | None,
        parser: Callable[[httpx.Response], T],
    ) -> T:
        raw = is_raw_response_requested()
        prepared = self._prepare(options, user_id)
        response = await self._send(prepared, options.deadline)
        result = APIResponse(response, parser, prepared.idempotency_key)
        # `with_raw_response` wrappers cast the result back to `APIResponse`.
        return cast("T", result) if raw else result.parse()

    async def _send(self, prepared: _Prepared, deadline: float | None) -> httpx.Response:
        retries = 0
        while True:
            timeout, capped = self._attempt_timeout(deadline)
            request = self._http.build_request(
                prepared.method,
                prepared.url,
                headers=prepared.headers,
                content=prepared.content,
                params=prepared.params,
                timeout=timeout,
            )
            try:
                response = await self._http.send(request, stream=True)
            except httpx.TransportError as exc:
                delay = self._transport_failure(prepared, exc, retries, capped)
            else:
                if response.is_success and prepared.stream:
                    if not _is_event_stream(response):
                        await response.aclose()
                        raise _not_an_event_stream(response)
                    _lift_read_timeout(response)
                    return response
                if response.is_success:
                    try:
                        await response.aread()
                    except httpx.TransportError as exc:
                        # The body was cut off, so the outcome is unknown: a network failure.
                        await response.aclose()
                        delay = self._transport_failure(prepared, exc, retries, capped)
                    else:
                        return response
                else:
                    try:
                        content = await response.aread()
                    except httpx.TransportError:
                        content = b""  # Cut off: the status and headers still decide.
                    finally:
                        await response.aclose()
                    error = make_status_error(response.status_code, response.headers, content)
                    delay = self._status_failure(prepared, error, retries)
            wait, expires = self._retry_wait(delay, deadline)
            await _retry.async_sleep(wait)
            if expires:
                raise DeadlineExceeded
            retries += 1
