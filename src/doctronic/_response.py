from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, ParamSpec, TypeVar, cast

import httpx
import pydantic

from ._construct import construct
from ._errors import APIResponseValidationError
from ._types import NotGiven

T = TypeVar("T")
P = ParamSpec("P")
M = TypeVar("M", bound=pydantic.BaseModel)

log = logging.getLogger("doctronic")

# Set while a `with_raw_response` wrapper runs, so the request returns an `APIResponse`.
_raw_response: ContextVar[bool] = ContextVar("doctronic_raw_response", default=False)


class APIResponse(Generic[T]):
    """The HTTP response behind a call. `parse()` returns what the method normally returns."""

    def __init__(
        self,
        http_response: httpx.Response,
        parser: Callable[[httpx.Response], T],
        idempotency_key: str | None,
    ) -> None:
        self.http_response = http_response
        self.idempotency_key = idempotency_key
        """The `Idempotency-Key` sent with the request, or `None` for an operation without one."""
        self._parser = parser
        self._parsed: tuple[T] | None = None

    @property
    def status_code(self) -> int:
        return self.http_response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self.http_response.headers

    @property
    def request_id(self) -> str | None:
        request_id: str | None = self.http_response.headers.get("x-request-id")
        return request_id

    @property
    def idempotency_replayed(self) -> bool:
        """`True` when the API served this response from its idempotency store."""
        replayed: str | None = self.http_response.headers.get("idempotency-replayed")
        return replayed == "true"

    def parse(self) -> T:
        if self._parsed is None:
            self._parsed = (self._parser(self.http_response),)
        return self._parsed[0]

    def __repr__(self) -> str:
        return f"<APIResponse [{self.status_code}] request_id={self.request_id!r}>"


def is_raw_response_requested() -> bool:
    return _raw_response.get()


def to_raw_response_wrapper(func: Callable[P, T]) -> Callable[P, APIResponse[T]]:
    @functools.wraps(func)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> APIResponse[T]:
        token = _raw_response.set(True)
        try:
            return cast("APIResponse[T]", func(*args, **kwargs))
        finally:
            _raw_response.reset(token)

    return wrapped


def async_to_raw_response_wrapper(
    func: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[APIResponse[T]]]:
    @functools.wraps(func)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> APIResponse[T]:
        token = _raw_response.set(True)
        try:
            return cast("APIResponse[T]", await func(*args, **kwargs))
        finally:
            _raw_response.reset(token)

    return wrapped


def _envelope_data(response: httpx.Response) -> Any:
    try:
        body = response.json()
    except ValueError as exc:
        raise APIResponseValidationError(
            "The response body isn't JSON.", status=response.status_code, headers=response.headers
        ) from exc
    if not isinstance(body, dict) or body.get("data") is None:
        raise APIResponseValidationError(
            "The response is missing `data`.",
            status=response.status_code,
            headers=response.headers,
        )
    return body["data"]


def _summarize(exc: pydantic.ValidationError) -> str:
    """Where and how the data differs from the contract, without the values, which can be PHI."""
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    parts = [
        f"{'.'.join(str(part) for part in error['loc']) or '(root)'} ({error['type']})"
        for error in errors[:10]
    ]
    if len(errors) > 10:
        parts.append(f"and {len(errors) - 10} more")
    return ", ".join(parts)


def parse_data(annotation: Any) -> Callable[[httpx.Response], Any]:
    """Unwrap the `{code, message, data}` envelope and validate `data` against `annotation`.

    Only a missing `data` raises. Data that doesn't match the contract, such as a missing field
    or a value of another type, is still returned, built by `_construct.construct()`, and logged
    as a warning on the `doctronic` logger. Unknown enum values and fields the contract doesn't
    list validate normally.
    """
    adapter: pydantic.TypeAdapter[Any] = pydantic.TypeAdapter(annotation)
    name = getattr(annotation, "__name__", repr(annotation))

    def parse(response: httpx.Response) -> Any:
        data = _envelope_data(response)
        try:
            return adapter.validate_python(data)
        except pydantic.ValidationError as exc:
            log.warning(
                "%s data (request ID %s) doesn't match the contract at %s. Those fields are "
                "returned as the API sent them, and missing ones are None.",
                name,
                response.headers.get("x-request-id", "unknown"),
                _summarize(exc),
            )
            return construct(annotation, data)

    return parse


def parse_model(model: type[M]) -> Callable[[httpx.Response], M]:
    parse: Callable[[httpx.Response], M] = parse_data(model)
    return parse


def parse_empty(response: httpx.Response) -> None:
    """For operations whose success envelope carries `data: null`."""
    return None


def none_while_pending(
    parser: Callable[[httpx.Response], T],
) -> Callable[[httpx.Response], T | None]:
    """`202` means the result isn't ready yet: return `None` instead of parsing."""

    def parse(response: httpx.Response) -> T | None:
        if response.status_code == 202:
            return None
        return parser(response)

    return parse


def to_jsonable(value: object) -> Any:
    if isinstance(value, pydantic.BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def build_body(model: type[pydantic.BaseModel], **values: object) -> dict[str, Any]:
    """Map snake_case arguments to the contract's camelCase names, dropping `NOT_GIVEN` ones.

    The names come from the generated request model, so they can't drift from the contract.
    """
    body: dict[str, Any] = {}
    for name, value in values.items():
        if isinstance(value, NotGiven):
            continue
        field = model.model_fields[name]
        body[field.alias or name] = to_jsonable(value)
    return body


def build_query(values: Mapping[str, object]) -> dict[str, Any]:
    return {
        name: to_jsonable(value)
        for name, value in values.items()
        if not isinstance(value, NotGiven) and value is not None
    }
