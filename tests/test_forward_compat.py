"""Responses from a newer API: unknown enum values, extra fields, and data that drifted.

The docs promise that clients can ignore values they don't know. Only a success envelope
without `data`, for an operation that returns data, raises `APIResponseValidationError`.
"""

from __future__ import annotations

import copy
import logging
import pickle
from datetime import datetime, timezone
from typing import Any

import httpx
import pydantic
import pytest
import respx

from doctronic import APIResponseValidationError, AsyncDoctronic, Doctronic, PermissionDeniedError
from doctronic._construct import construct
from doctronic.types import (
    AppointmentResponse,
    AppointmentStatus,
    ArtifactContent,
    ArtifactResponse,
    InsufficientScopeData,
    MessageResponse,
    PageAppointmentResponse,
    Role,
    Scope,
    ShortSummaryArtifactResponse,
    SoapNoteArtifactResponse,
    State,
    UserCreatedResponse,
)
from tests.helpers import USER_ID, error, ok, resolve
from tests.test_resources import APPOINTMENT, ARTIFACT, CASES, PAGE, USER, Case, check_none

AnyClient = Doctronic | AsyncDoctronic


# Open enums.


def test_known_values_are_the_listed_members() -> None:
    assert AppointmentStatus("booked") is AppointmentStatus.booked
    assert State("NY") is State.ny
    assert len(AppointmentStatus) == 5  # Unknown values never become listed members.


def test_unknown_value_is_a_member_that_equals_the_string() -> None:
    status = AppointmentStatus("on_hold")

    assert isinstance(status, AppointmentStatus)
    assert isinstance(status, str)
    assert status == "on_hold"
    assert status.value == "on_hold"
    assert status.name == "on_hold"
    assert status not in list(AppointmentStatus)
    assert status != AppointmentStatus.booked
    assert repr(status) == "<AppointmentAPIStatus.on_hold: 'on_hold'>"
    assert pickle.loads(pickle.dumps(status)) == status
    assert copy.deepcopy(status) == status


def test_wrong_type_still_raises() -> None:
    with pytest.raises(ValueError, match="not a valid"):
        AppointmentStatus(7)


@pytest.mark.parametrize(
    ("model", "payload", "attribute", "value"),
    [
        (
            InsufficientScopeData,
            {"requiredScope": "billing:read"},
            "required_scope",
            "billing:read",
        ),
        (
            MessageResponse,
            {"role": "system", "content": "Hi", "messageId": "m1"},
            "role",
            "system",
        ),
    ],
)
def test_models_accept_unknown_enum_values(
    model: type[pydantic.BaseModel], payload: dict[str, Any], attribute: str, value: str
) -> None:
    parsed = model.model_validate(payload)
    assert getattr(parsed, attribute) == value
    assert parsed.model_dump(mode="json", by_alias=True, exclude_unset=True) == payload
    assert isinstance(getattr(parsed, attribute), (Scope, Role))


@pytest.mark.asyncio
async def test_unknown_enum_value_and_extra_fields_in_a_response(
    client: AnyClient, api: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    wire = {**APPOINTMENT, "status": "on_hold", "rescheduledFrom": {"id": "dc_00"}}
    api.get("/appointments/dc_01/").mock(return_value=ok(wire))

    with caplog.at_level(logging.WARNING, logger="doctronic"):
        appointment = await resolve(client.for_user(USER_ID).appointments.retrieve("dc_01"))

    assert isinstance(appointment, AppointmentResponse)
    assert appointment.status == "on_hold"
    assert isinstance(appointment.status, AppointmentStatus)
    assert appointment.starts_at == datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
    assert appointment.model_extra == {"rescheduledFrom": {"id": "dc_00"}}
    assert appointment.model_dump(mode="json", by_alias=True)["status"] == "on_hold"
    assert caplog.records == []  # Nothing here differs from what the contract allows.


@pytest.mark.asyncio
async def test_unknown_scope_in_an_error(client: AnyClient, api: respx.MockRouter) -> None:
    api.get("/users/").mock(
        return_value=error(
            403,
            "error.auth.insufficient_scope",
            message="This API key does not have the scope this endpoint requires.",
            data={"requiredScope": "patients:export"},
        )
    )

    with pytest.raises(PermissionDeniedError) as raised:
        await resolve(client.for_user(USER_ID).users.retrieve())

    data = InsufficientScopeData.model_validate(raised.value.data)
    assert data.required_scope == "patients:export"


# Data that doesn't match the contract is returned, not raised.


@pytest.mark.asyncio
async def test_missing_field_is_none_and_logged_without_values(
    client: AnyClient, api: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    wire = {key: value for key, value in USER.items() if key != "appointmentDemographicsComplete"}
    api.get("/users/").mock(return_value=ok(wire, headers={"x-request-id": "req_drift"}))

    with caplog.at_level(logging.WARNING, logger="doctronic"):
        user = await resolve(client.for_user(USER_ID).users.retrieve())

    assert isinstance(user, UserCreatedResponse)
    assert user.appointment_demographics_complete is None
    assert user.first_name == "Test"
    assert user.created_at == datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert "UserCreatedResponse" in message
    assert "req_drift" in message
    assert "appointmentDemographicsComplete (missing)" in message
    # The log names fields, never their values: responses carry patient data.
    for value in ("Test", "Patient", "patient@example.com", "+15555550100", "1990-01-01"):
        assert value not in message


@pytest.mark.asyncio
async def test_value_of_another_type_is_kept_as_sent(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.get("/appointments/dc_01/").mock(
        return_value=ok({**APPOINTMENT, "startsAt": "next Tuesday", "durationMinutes": "15"})
    )

    appointment = await resolve(client.for_user(USER_ID).appointments.retrieve("dc_01"))

    assert isinstance(appointment, AppointmentResponse)
    assert appointment.starts_at == "next Tuesday"
    assert appointment.duration_minutes == 15  # Lax validation still converts this one.
    assert appointment.status is AppointmentStatus.booked
    assert appointment.created_at == datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_one_drifted_item_leaves_the_rest_of_a_page_typed(
    client: AnyClient, api: respx.MockRouter
) -> None:
    broken = {key: value for key, value in APPOINTMENT.items() if key != "chatId"}
    api.get("/appointments/").mock(
        return_value=ok({**PAGE, "items": [APPOINTMENT, broken], "total": 2})
    )

    page = await resolve(client.for_user(USER_ID).appointments.list())

    assert isinstance(page, PageAppointmentResponse)
    assert page.total == 2
    first, second = page.items
    assert isinstance(first, AppointmentResponse)
    assert isinstance(second, AppointmentResponse)
    assert first.chat_id == "chat_01"
    assert second.chat_id is None
    assert second.starts_at == datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_unknown_artifact_type_is_still_a_model(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.get("/artifacts/art_02/").mock(
        return_value=ok({**ARTIFACT, "artifactType": "visit_summary"})
    )

    artifact = await resolve(client.for_user(USER_ID).artifacts.retrieve("art_02"))

    assert artifact is not None
    # Typed as the known literals, but it holds the type as sent.
    assert artifact.model_dump(by_alias=True)["artifactType"] == "visit_summary"
    assert artifact.artifact_id == "art_02"
    assert isinstance(artifact.content, ArtifactContent)
    assert artifact.content.body.startswith("## Summary")


def test_known_artifact_type_with_drift_keeps_its_model() -> None:
    wire = {**ARTIFACT, "content": {"chatId": "chat_01", "body": "Text"}}

    artifact = construct(ArtifactResponse, wire)

    assert isinstance(artifact, ShortSummaryArtifactResponse)
    assert not isinstance(artifact, SoapNoteArtifactResponse)
    assert artifact.content.created_at is None


def test_construct_returns_valid_data_as_validated() -> None:
    appointment = construct(AppointmentResponse, APPOINTMENT)
    assert appointment == AppointmentResponse.model_validate(APPOINTMENT)
    assert construct(list[AppointmentStatus], ["booked", "on_hold"]) == ["booked", "on_hold"]


# Only a missing `data` raises.

DATA_CASES = [case for case in CASES if case.check is not check_none]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", DATA_CASES, ids=[case.id for case in DATA_CASES])
@pytest.mark.parametrize(
    "body",
    [{"code": "success", "message": "Request successful"}, {"code": "success", "data": None}],
    ids=["no-data", "null-data"],
)
async def test_operations_that_return_data_raise_without_it(
    case: Case, body: dict[str, Any], client: AnyClient, api: respx.MockRouter
) -> None:
    api.request(case.method, case.path).mock(return_value=httpx.Response(case.status, json=body))

    with pytest.raises(APIResponseValidationError, match="missing `data`"):
        await resolve(case.call(client))


NO_DATA_CASES = [case for case in CASES if case.check is check_none]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", NO_DATA_CASES, ids=[case.id for case in NO_DATA_CASES])
async def test_operations_without_data_accept_any_envelope(
    case: Case, client: AnyClient, api: respx.MockRouter
) -> None:
    api.request(case.method, case.path).mock(
        return_value=httpx.Response(case.status, json={"code": "success", "newField": 1})
    )

    assert await resolve(case.call(client)) is None
