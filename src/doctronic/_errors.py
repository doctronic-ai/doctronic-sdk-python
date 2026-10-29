from __future__ import annotations

import json
from typing import Any

import httpx
import pydantic

from ._generated.models import ValidationErrorDetail
from ._retry import parse_retry_after

__all__ = [
    "APIConnectionError",
    "APIError",
    "APIResponseValidationError",
    "APITimeoutError",
    "APIUserAbortError",
    "ArtifactNotReadyError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "DoctronicError",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServiceUnavailableError",
    "WebhookVerificationError",
]

VALIDATION_ERROR_CODE = "error.validation_error"


class DoctronicError(Exception):
    """Base class for every error the SDK raises."""


class APIError(DoctronicError):
    """The API answered with a non-success status.

    Branch on `status` and `code`; show or log `message`. Keep `request_id` with your record of
    the failure so Doctronic can trace it.
    """

    status: int
    code: str | None
    """The machine-readable `code`, such as `error.appointments.slot_unavailable`, when sent."""
    message: str
    data: Any
    request_id: str | None
    headers: httpx.Headers
    retry_after: float | None
    """Seconds from the `Retry-After` header, when the response sent one."""

    def __init__(
        self,
        *,
        status: int,
        code: str | None,
        message: str,
        data: Any,
        headers: httpx.Headers,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.data = data
        self.headers = headers
        self.request_id = headers.get("x-request-id")
        self.retry_after = parse_retry_after(headers)
        detail = f"{status} {code}: {message}" if code else f"{status}: {message}"
        if self.request_id:
            detail += f" (request ID {self.request_id})"
        super().__init__(detail)


class BadRequestError(APIError):
    """400, or the legacy 422: the request is invalid. Retrying it unchanged fails the same way."""

    field_errors: list[ValidationErrorDetail]
    """For `error.validation_error`, one entry per field that failed. Empty for other codes."""

    def __init__(
        self,
        *,
        status: int,
        code: str | None,
        message: str,
        data: Any,
        headers: httpx.Headers,
    ) -> None:
        super().__init__(status=status, code=code, message=message, data=data, headers=headers)
        items = data if code == VALIDATION_ERROR_CODE and isinstance(data, list) else []
        self.field_errors = []
        for item in items:
            try:
                self.field_errors.append(ValidationErrorDetail.model_validate(item))
            except pydantic.ValidationError:
                continue


class AuthenticationError(APIError):
    """401: the token is missing, invalid, or inactive. Stop and check the credential."""


class PermissionDeniedError(APIError):
    """403: the API key lacks the scope the operation requires (`error.auth.insufficient_scope`),
    or the organization can't act on the user in `X-Doctronic-User-ID`."""


class NotFoundError(APIError):
    """404: the resource doesn't exist in your organization and user scope."""


class ConflictError(APIError):
    """409: a state conflict, or an idempotency conflict. Read `code` to tell them apart."""


class RateLimitError(APIError):
    """429: returned by a proxy or gateway in your path. The API itself doesn't send it."""


class InternalServerError(APIError):
    """A 5xx other than 503."""


class ServiceUnavailableError(APIError):
    """503: the operation couldn't start safely. Retry the same request after `retry_after`."""


class APIConnectionError(DoctronicError):
    """The request didn't get a response: a network failure, so the outcome is unknown."""

    def __init__(self, message: str = "Connection error.") -> None:
        super().__init__(message)


class APITimeoutError(APIConnectionError):
    """The request timed out, so the outcome is unknown."""

    def __init__(self, message: str = "Request timed out.") -> None:
        super().__init__(message)


class APIUserAbortError(DoctronicError):
    """The stream was closed before it ended, so the turn may be incomplete.

    Raised to the code iterating a stream when `close()` interrupts it, for example from a cancel
    action in another thread or task, and when a stream closed early is iterated again.
    """

    def __init__(self, message: str = "The stream was closed before it ended.") -> None:
        super().__init__(message)


class APIResponseValidationError(APIError):
    """A success response that doesn't match the contract, such as a missing `data` field.

    An `APIError`, so handlers for API errors catch it too. Not retried.
    """

    def __init__(self, message: str, *, status: int, headers: httpx.Headers) -> None:
        super().__init__(status=status, code=None, message=message, data=None, headers=headers)


class ArtifactNotReadyError(DoctronicError):
    """`artifacts.wait_until_ready()` timed out while the document was still generating."""

    def __init__(self, artifact_id: str, timeout: float) -> None:
        self.artifact_id = artifact_id
        self.timeout = timeout
        super().__init__(f"Artifact {artifact_id} was still generating after {timeout:g} seconds.")


class WebhookVerificationError(DoctronicError):
    """The webhook signature didn't match, or the signed body isn't a valid event envelope."""


_STATUS_ERRORS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: BadRequestError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


def make_status_error(status: int, headers: httpx.Headers, content: bytes) -> APIError:
    """Build the typed error for a non-success response from its status, headers, and body."""
    code: str | None = None
    message = f"Request failed with status {status}"
    data: Any = None
    try:
        body = json.loads(content) if content else None
    except ValueError:
        body = None
    if isinstance(body, dict):
        if isinstance(body.get("code"), str) and body["code"]:
            code = body["code"]
        if isinstance(body.get("message"), str) and body["message"]:
            message = body["message"]
        data = body.get("data")

    cls: type[APIError]
    if status in _STATUS_ERRORS:
        cls = _STATUS_ERRORS[status]
    elif status >= 500:
        cls = InternalServerError
    else:
        cls = APIError
    return cls(status=status, code=code, message=message, data=data, headers=headers)
