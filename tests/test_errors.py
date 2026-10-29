from __future__ import annotations

import httpx
import pytest
import respx

from doctronic import (
    APIError,
    APIResponseValidationError,
    AsyncDoctronic,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    Doctronic,
    DoctronicError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
)
from doctronic.types import AppointmentWaitingRoomUnavailableData
from tests.helpers import TOKEN, USER_ID, error, resolve

AnyClient = Doctronic | AsyncDoctronic


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "error_type"),
    [
        (400, "error.user.conflict", BadRequestError),
        (401, "error.auth.unauthorized", AuthenticationError),
        (403, "error.member.forbidden", PermissionDeniedError),
        (404, "error.address.not_found", NotFoundError),
        (409, "error.appointments.cannot_be_cancelled_or_rescheduled", ConflictError),
        (422, "error.unknown", BadRequestError),
        (429, "error.rate_limited", RateLimitError),
        (500, "error.internal", InternalServerError),
        (502, "error.appointments.provisioning_failed", InternalServerError),
        (503, "error.validation.phone_number.unavailable", ServiceUnavailableError),
        (418, "error.teapot", APIError),
    ],
)
async def test_status_maps_to_error_class(
    client: AnyClient,
    api: respx.MockRouter,
    status: int,
    code: str,
    error_type: type[APIError],
) -> None:
    api.get("/address/").mock(
        return_value=error(
            status, code, "Human-readable.", headers={"x-request-id": "req_42", "retry-after": "2"}
        )
    )

    with pytest.raises(error_type) as raised:
        await resolve(client.for_user(USER_ID).address.retrieve())

    err = raised.value
    assert type(err) is error_type
    assert isinstance(err, DoctronicError)
    assert (err.status, err.code, err.message) == (status, code, "Human-readable.")
    assert err.request_id == "req_42"
    assert err.headers["x-request-id"] == "req_42"
    assert err.retry_after == 2
    assert str(err) == f"{status} {code}: Human-readable. (request ID req_42)"
    assert TOKEN not in str(err)
    assert TOKEN not in repr(err)


@pytest.mark.asyncio
async def test_validation_error_exposes_field_errors(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.post("/users/").mock(
        return_value=error(
            400,
            "error.validation_error",
            "Validation error",
            data=[
                {
                    "field": "body.dateOfBirth",
                    "message": "Too young",
                    "code": "error.validation.age",
                },
                {"field": "body.email", "message": "Invalid", "code": "error.validation.email"},
            ],
        )
    )

    with pytest.raises(BadRequestError) as raised:
        await resolve(client.users.create(date_of_birth="2020-01-01"))

    assert raised.value.code == "error.validation_error"
    assert [(e.field, e.code) for e in raised.value.field_errors] == [
        ("body.dateOfBirth", "error.validation.age"),
        ("body.email", "error.validation.email"),
    ]


@pytest.mark.asyncio
async def test_error_data_is_kept(client: AnyClient, api: respx.MockRouter) -> None:
    api.post("/appointments/asap/").mock(
        return_value=error(
            502,
            "error.appointments.waiting_room_unavailable",
            data={"appointmentId": "dc_01", "status": "booked"},
        )
    )

    with pytest.raises(InternalServerError) as raised:
        await resolve(
            client.for_user(USER_ID).appointments.create_asap(
                chat_id="chat_01", location={"state": "NY"}
            )
        )

    data = AppointmentWaitingRoomUnavailableData.model_validate(raised.value.data)
    assert data.appointment_id == "dc_01"


@pytest.mark.asyncio
async def test_error_without_json_body(client: AnyClient, api: respx.MockRouter) -> None:
    api.get("/users/").mock(return_value=httpx.Response(404, text="<html>Not Found</html>"))

    with pytest.raises(NotFoundError) as raised:
        await resolve(client.for_user(USER_ID).users.retrieve())

    assert raised.value.code is None
    assert raised.value.message == "Request failed with status 404"
    assert raised.value.data is None
    assert str(raised.value) == "404: Request failed with status 404"


@pytest.mark.asyncio
async def test_response_that_breaks_the_contract(client: AnyClient, api: respx.MockRouter) -> None:
    api.get("/users/").mock(return_value=httpx.Response(200, json={"data": {"id": 7}}))
    api.get("/address/").mock(return_value=httpx.Response(200, text="not json"))

    with pytest.raises(APIResponseValidationError) as raised:
        await resolve(client.for_user(USER_ID).users.retrieve())
    with pytest.raises(APIResponseValidationError):
        await resolve(client.for_user(USER_ID).address.retrieve())

    assert raised.value.status == 200


@pytest.mark.asyncio
async def test_field_errors_only_for_validation_errors(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.post("/users/").mock(
        side_effect=[
            error(
                400,
                "error.user.conflict",
                data=[{"field": "body.email", "message": "x", "code": "y"}],
            ),
            error(400, "error.validation_error", data=[{"field": "body.email"}, "junk"]),
        ]
    )

    with pytest.raises(BadRequestError) as conflict:
        await resolve(client.users.create(email="patient@example.com"))
    with pytest.raises(BadRequestError) as malformed:
        await resolve(client.users.create(email="patient@example.com"))

    assert conflict.value.field_errors == []
    assert malformed.value.field_errors == []
