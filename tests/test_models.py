"""Generated models and the operations table derived from the contract."""

from __future__ import annotations

import inspect
from typing import Any

import pydantic
import pytest
from pydantic.alias_generators import to_camel

from doctronic._generated import models
from doctronic._generated.operations import OPERATIONS
from doctronic._resource import SyncAPIResource
from doctronic.resources import (
    AddressResource,
    AppointmentsResource,
    ArtifactsResource,
    AsyncAddressResource,
    AsyncAppointmentsResource,
    AsyncArtifactsResource,
    AsyncChatsResource,
    AsyncCoverageResource,
    AsyncPharmacyResource,
    AsyncScopedPharmacyResource,
    AsyncScopedUsersResource,
    AsyncUsersResource,
    ChatsResource,
    CoverageResource,
    PharmacyResource,
    ScopedPharmacyResource,
    ScopedUsersResource,
    UsersResource,
)
from doctronic.types import (
    AppointmentResponse,
    ArtifactResponse,
    ClinicianNoteArtifactResponse,
    UserCreatedResponse,
)

GENERATED_MODELS = [
    value
    for value in vars(models).values()
    if inspect.isclass(value)
    and issubclass(value, pydantic.BaseModel)
    and value.__module__ == models.__name__
]


def test_operations_table_matches_the_contract_shape() -> None:
    assert len(OPERATIONS) == 22
    assert sum(op.idempotent for op in OPERATIONS.values()) == 11
    no_data = {key for key, op in OPERATIONS.items() if not op.data_required}
    assert no_data == {
        ("POST", "/chats/{chatId}/stream/"),
        ("POST", "/appointments/{appointment_id}/cancel/"),
        ("POST", "/appointments/{appointment_id}/reschedule/"),
        ("PUT", "/address/"),
        ("PUT", "/pharmacy/"),
        ("PUT", "/coverage/"),
    }
    org_scoped = {key for key, op in OPERATIONS.items() if not op.user_scoped}
    assert org_scoped == {("POST", "/users/"), ("POST", "/pharmacy/search/")}
    assert OPERATIONS[("POST", "/appointments/{appointment_id}/reschedule/")].conflict_codes == {
        "error.appointments.cannot_be_cancelled_or_rescheduled",
        "error.appointments.unavailable_time",
        "error.idempotency.payload_mismatch",
    }


@pytest.mark.parametrize("model", GENERATED_MODELS, ids=lambda model: model.__name__)
def test_aliases_are_the_camel_case_of_the_attributes(model: type[pydantic.BaseModel]) -> None:
    for name, field in model.model_fields.items():
        assert (field.alias or name) == to_camel(name), f"{model.__name__}.{name}"


def test_wire_payload_round_trips() -> None:
    wire: dict[str, Any] = {
        "id": "dc_01",
        "createdAt": "2026-08-31T15:00:00Z",
        "chatId": "chat_01",
        "status": "booked",
        "durationMinutes": 15,
        "location": {"state": "NY"},
        "startsAt": None,
        "endsAt": None,
        "waitingRoomUrl": "https://example.com/w",
        "fieldFromTheFuture": {"kept": True},
    }

    appointment = AppointmentResponse.model_validate(wire)

    assert appointment.chat_id == "chat_01"
    assert appointment.status == "booked"
    assert appointment.waiting_room_url == "https://example.com/w"
    dumped = appointment.model_dump(mode="json", by_alias=True)
    assert dumped == {**wire, "createdAt": "2026-08-31T15:00:00Z"}


def test_models_accept_snake_case_names_too() -> None:
    user = UserCreatedResponse(
        id="mem_01",
        appointment_demographics_complete=False,
        missing_appointment_fields=["firstName"],
    )
    assert user.model_dump(by_alias=True, exclude_none=True) == {
        "id": "mem_01",
        "appointmentDemographicsComplete": False,
        "missingAppointmentFields": ["firstName"],
    }


def test_artifact_union_discriminates_on_artifact_type() -> None:
    adapter: pydantic.TypeAdapter[Any] = pydantic.TypeAdapter(ArtifactResponse)
    artifact = adapter.validate_python(
        {
            "artifactType": "clinician_note",
            "artifactId": "art_09",
            "content": {"chatId": "chat_01", "createdAt": "2026-08-16T15:30:00Z", "body": "Note"},
        }
    )
    assert isinstance(artifact, ClinicianNoteArtifactResponse)


RESOURCES = [
    (UsersResource, {"create": ("POST", "/users/")}),
    (ScopedUsersResource, {"retrieve": ("GET", "/users/"), "update": ("PATCH", "/users/")}),
    (
        ChatsResource,
        {
            "create": ("POST", "/chats/"),
            "list": ("GET", "/chats/"),
            "retrieve": ("GET", "/chats/{chatId}/"),
            "messages": ("GET", "/chats/{chatId}/messages/"),
            "stream": ("POST", "/chats/{chatId}/stream/"),
        },
    ),
    (
        AppointmentsResource,
        {
            "available_slots": ("GET", "/appointments/scheduled/available-slots/"),
            "create_scheduled": ("POST", "/appointments/scheduled/"),
            "create_asap": ("POST", "/appointments/asap/"),
            "list": ("GET", "/appointments/"),
            "retrieve": ("GET", "/appointments/{appointment_id}/"),
            "result": ("GET", "/appointments/{appointment_id}/result/"),
            "cancel": ("POST", "/appointments/{appointment_id}/cancel/"),
            "reschedule": ("POST", "/appointments/{appointment_id}/reschedule/"),
        },
    ),
    (AddressResource, {"retrieve": ("GET", "/address/"), "set": ("PUT", "/address/")}),
    (PharmacyResource, {"search": ("POST", "/pharmacy/search/")}),
    (ScopedPharmacyResource, {"set": ("PUT", "/pharmacy/")}),
    (CoverageResource, {"set": ("PUT", "/coverage/")}),
    (ArtifactsResource, {"retrieve": ("GET", "/artifacts/{artifactId}/")}),
]
ASYNC_TWINS = {
    UsersResource: AsyncUsersResource,
    ScopedUsersResource: AsyncScopedUsersResource,
    ChatsResource: AsyncChatsResource,
    AppointmentsResource: AsyncAppointmentsResource,
    AddressResource: AsyncAddressResource,
    PharmacyResource: AsyncPharmacyResource,
    ScopedPharmacyResource: AsyncScopedPharmacyResource,
    CoverageResource: AsyncCoverageResource,
    ArtifactsResource: AsyncArtifactsResource,
}


def test_every_operation_has_exactly_one_method() -> None:
    mapped = [operation for _, methods in RESOURCES for operation in methods.values()]
    assert sorted(mapped) == sorted(OPERATIONS)


@pytest.mark.parametrize(
    ("resource", "methods"), RESOURCES, ids=lambda r: getattr(r, "__name__", "")
)
def test_idempotency_key_argument_follows_the_contract(
    resource: type[SyncAPIResource], methods: dict[str, tuple[str, str]]
) -> None:
    for cls in (resource, ASYNC_TWINS[resource]):
        for method, operation in methods.items():
            parameters = inspect.signature(getattr(cls, method)).parameters
            assert ("idempotency_key" in parameters) is OPERATIONS[operation].idempotent, (
                f"{cls.__name__}.{method}"
            )


@pytest.mark.parametrize(
    ("resource", "methods"), RESOURCES, ids=lambda r: getattr(r, "__name__", "")
)
def test_sync_and_async_resources_match(
    resource: type[SyncAPIResource], methods: dict[str, tuple[str, str]]
) -> None:
    twin = ASYNC_TWINS[resource]
    public = {name for name in vars(resource) if not name.startswith("_")}
    assert public == {name for name in vars(twin) if not name.startswith("_")}
    for name in public - {"with_raw_response"}:
        sync_signature = inspect.signature(getattr(resource, name))
        async_signature = inspect.signature(getattr(twin, name))
        assert list(sync_signature.parameters) == list(async_signature.parameters), name
        if (twin, name) == (AsyncChatsResource, "stream"):
            # Returns an AsyncChatStreamManager: a coroutine that is also an async context manager.
            assert async_signature.return_annotation == "AsyncChatStreamManager"
        else:
            assert inspect.iscoroutinefunction(getattr(twin, name)), name
