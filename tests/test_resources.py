"""Every resource method against the mock API, with both the sync and the async client.

Each case checks the method, path, query, body, the auth / user / idempotency headers, and that
the `{code, message, data}` envelope is unwrapped into the documented model.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pytest
import respx

from doctronic import AsyncDoctronic, Doctronic
from doctronic._generated.operations import OPERATIONS
from doctronic.types import (
    AddressResponse,
    AppointmentResponse,
    AppointmentResultResponse,
    AsapAppointmentResponse,
    AvailableSlotsResponse,
    ChatResponse,
    PageAppointmentResponse,
    PageChatResponse,
    PageMessageResponse,
    PharmacySearchResponse,
    ScheduledAppointmentResponse,
    ShortSummaryArtifactResponse,
    UserCreatedResponse,
)
from tests.helpers import TOKEN, USER_ID, ok, resolve

AnyClient = Doctronic | AsyncDoctronic

USER = {
    "id": USER_ID,
    "createdAt": "2026-08-31T14:30:00Z",
    "firstName": "Test",
    "lastName": "Patient",
    "dateOfBirth": "1990-01-01",
    "email": "patient@example.com",
    "phoneNumber": "+15555550100",
    "sex": "female",
    "appointmentDemographicsComplete": True,
    "missingAppointmentFields": [],
}
CHAT = {"id": "chat_01", "createdAt": "2026-08-31T14:31:00Z"}
PAGE = {"total": 1, "page": 1, "size": 20, "pages": 1, "hasNext": False, "hasPrev": False}
MESSAGE = {
    "role": "assistant",
    "content": "I can help with that.",
    "messageId": "ac_hist_01",
    "createdAt": "2026-08-31T14:32:04Z",
}
APPOINTMENT = {
    "id": "dc_01",
    "createdAt": "2026-08-31T15:00:00Z",
    "chatId": "chat_01",
    "status": "booked",
    "durationMinutes": 15,
    "location": {"state": "NY"},
    "startsAt": "2026-09-01T15:00:00Z",
    "endsAt": "2026-09-01T15:15:00Z",
    "waitingRoomUrl": None,
}
WAITING_ROOM = "https://waiting-room.example.com/dc_02"
ASAP = {
    "id": "dc_02",
    "chatId": "chat_01",
    "status": "booked",
    "durationMinutes": 15,
    "location": {"state": "NY"},
    "waitingRoomUrl": WAITING_ROOM,
}
RESULT = {
    "appointmentId": "dc_01",
    "prescriptions": [
        {
            "displayName": "Amoxicillin 500 mg",
            "pharmacy": {
                "ncpdpId": "1234567",
                "name": "Example Pharmacy",
                "address": {"line1": "1 Main St", "city": "New York", "state": "NY"},
                "phoneNumber": None,
            },
        }
    ],
    "clinicianNote": "art_clinician",
}
ARTIFACT = {
    "artifactType": "short_summary",
    "artifactId": "art_02",
    "content": {
        "chatId": "chat_01",
        "createdAt": "2026-08-16T15:30:00Z",
        "body": "## Summary\n\nSymptoms began yesterday.",
    },
}
ADDRESS = {
    "line1": "100 Example Street",
    "line2": None,
    "city": "New York",
    "state": "NY",
    "postalCode": "10001",
}
PHARMACIES = {
    "pharmacies": [
        {
            "name": "Example Pharmacy",
            "ncpdpId": "1234567",
            "address": {"line1": "1 Main St", "city": "Salt Lake City", "state": "UT"},
            "phoneNumber": "+15555550101",
            "distanceMiles": 0.4,
        }
    ]
}


@dataclass
class Case:
    id: str
    call: Callable[[AnyClient], Any]
    method: str
    template: str
    """The contract path template, to tie the case to its operation."""
    path: str
    user_scoped: bool
    idempotent: bool
    data: Any = None
    status: int = 200
    body: Any = None
    query: dict[str, str] = field(default_factory=dict)
    check: Callable[[Any], None] = lambda result: None


def user(client: AnyClient) -> Any:
    return client.for_user(USER_ID)


def check_user(result: Any) -> None:
    assert isinstance(result, UserCreatedResponse)
    assert result.id == USER_ID
    assert result.first_name == "Test"
    assert result.date_of_birth == date(1990, 1, 1)
    assert result.appointment_demographics_complete is True


def check_chat(result: Any) -> None:
    assert isinstance(result, ChatResponse)
    assert result.id == "chat_01"
    assert result.created_at == datetime(2026, 8, 31, 14, 31, tzinfo=timezone.utc)


def check_chat_page(result: Any) -> None:
    assert isinstance(result, PageChatResponse)
    assert [chat.id for chat in result.items] == ["chat_01"]
    assert result.has_next is False


def check_message_page(result: Any) -> None:
    assert isinstance(result, PageMessageResponse)
    assert result.items[0].message_id == "ac_hist_01"
    assert result.items[0].role == "assistant"


def check_slots(result: Any) -> None:
    assert isinstance(result, AvailableSlotsResponse)
    assert result.slots == ["2026-09-01T15:00:00Z"]


def check_scheduled(result: Any) -> None:
    assert isinstance(result, ScheduledAppointmentResponse)
    assert result.id == "dc_01"
    assert result.location.state == "NY"


def check_asap(result: Any) -> None:
    assert isinstance(result, AsapAppointmentResponse)
    assert result.waiting_room_url == WAITING_ROOM


def check_appointment_page(result: Any) -> None:
    assert isinstance(result, PageAppointmentResponse)
    assert result.items[0].status == "booked"


def check_appointment(result: Any) -> None:
    assert isinstance(result, AppointmentResponse)
    assert result.duration_minutes == 15
    assert result.waiting_room_url is None


def check_result(result: Any) -> None:
    assert isinstance(result, AppointmentResultResponse)
    assert result.clinician_note == "art_clinician"
    pharmacy = result.prescriptions[0].pharmacy
    assert pharmacy is not None
    assert pharmacy.ncpdp_id == "1234567"


def check_address(result: Any) -> None:
    assert isinstance(result, AddressResponse)
    assert result.postal_code == "10001"
    assert result.line2 is None


def check_pharmacies(result: Any) -> None:
    assert isinstance(result, PharmacySearchResponse)
    assert result.pharmacies[0].distance_miles == 0.4


def check_artifact(result: Any) -> None:
    assert isinstance(result, ShortSummaryArtifactResponse)
    assert result.artifact_id == "art_02"
    assert result.content.chat_id == "chat_01"


def check_none(result: Any) -> None:
    assert result is None


CASES = [
    Case(
        "users.create",
        lambda c: c.users.create(
            first_name="Test",
            last_name="Patient",
            date_of_birth=date(1990, 1, 1),
            email="patient@example.com",
            phone_number="+15555550100",
            sex="female",
        ),
        "POST",
        "/users/",
        "/users/",
        user_scoped=False,
        idempotent=True,
        status=201,
        data=USER,
        body={
            "firstName": "Test",
            "lastName": "Patient",
            "dateOfBirth": "1990-01-01",
            "email": "patient@example.com",
            "phoneNumber": "+15555550100",
            "sex": "female",
        },
        check=check_user,
    ),
    Case(
        "users.retrieve",
        lambda c: user(c).users.retrieve(),
        "GET",
        "/users/",
        "/users/",
        user_scoped=True,
        idempotent=False,
        data=USER,
        check=check_user,
    ),
    Case(
        "users.update",
        # PATCH semantics: a value changes the field, None clears it, omitted keeps it.
        lambda c: user(c).users.update(phone_number="+15555550100", email=None),
        "PATCH",
        "/users/",
        "/users/",
        user_scoped=True,
        idempotent=True,
        data=USER,
        body={"phoneNumber": "+15555550100", "email": None},
        check=check_user,
    ),
    Case(
        "chats.create",
        lambda c: user(c).chats.create(
            timezone="America/New_York", conversation_prompt_context="Sore-throat intake."
        ),
        "POST",
        "/chats/",
        "/chats/",
        user_scoped=True,
        idempotent=True,
        status=201,
        data=CHAT,
        body={"timezone": "America/New_York", "conversationPromptContext": "Sore-throat intake."},
        check=check_chat,
    ),
    Case(
        "chats.list",
        lambda c: user(c).chats.list(page=2, size=50, order_by="-updatedAt"),
        "GET",
        "/chats/",
        "/chats/",
        user_scoped=True,
        idempotent=False,
        data={**PAGE, "items": [CHAT]},
        query={"page": "2", "size": "50", "orderBy": "-updatedAt"},
        check=check_chat_page,
    ),
    Case(
        "chats.retrieve",
        lambda c: user(c).chats.retrieve("chat_01"),
        "GET",
        "/chats/{chatId}/",
        "/chats/chat_01/",
        user_scoped=True,
        idempotent=False,
        data=CHAT,
        check=check_chat,
    ),
    Case(
        "chats.messages",
        lambda c: user(c).chats.messages("chat_01", page=1, size=50),
        "GET",
        "/chats/{chatId}/messages/",
        "/chats/chat_01/messages/",
        user_scoped=True,
        idempotent=False,
        data={**PAGE, "items": [MESSAGE]},
        query={"page": "1", "size": "50"},
        check=check_message_page,
    ),
    Case(
        "appointments.available_slots",
        lambda c: user(c).appointments.available_slots(
            state="NY",
            datetime_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
            datetime_to="2026-09-02T00:00:00Z",
        ),
        "GET",
        "/appointments/scheduled/available-slots/",
        "/appointments/scheduled/available-slots/",
        user_scoped=True,
        idempotent=False,
        data={"slots": ["2026-09-01T15:00:00Z"]},
        query={
            "state": "NY",
            "datetimeFrom": "2026-09-01T00:00:00+00:00",
            "datetimeTo": "2026-09-02T00:00:00Z",
        },
        check=check_slots,
    ),
    Case(
        "appointments.create_scheduled",
        lambda c: user(c).appointments.create_scheduled(
            chat_id="chat_01", starts_at="2026-09-01T15:00:00Z", location={"state": "NY"}
        ),
        "POST",
        "/appointments/scheduled/",
        "/appointments/scheduled/",
        user_scoped=True,
        idempotent=True,
        status=201,
        data={
            key: APPOINTMENT[key]
            for key in ("id", "chatId", "status", "durationMinutes", "location")
        },
        body={"chatId": "chat_01", "startsAt": "2026-09-01T15:00:00Z", "location": {"state": "NY"}},
        check=check_scheduled,
    ),
    Case(
        "appointments.create_asap",
        lambda c: user(c).appointments.create_asap(chat_id="chat_01", location={"state": "NY"}),
        "POST",
        "/appointments/asap/",
        "/appointments/asap/",
        user_scoped=True,
        idempotent=True,
        status=201,
        data=ASAP,
        body={"chatId": "chat_01", "location": {"state": "NY"}},
        check=check_asap,
    ),
    Case(
        "appointments.list",
        lambda c: user(c).appointments.list(status="booked", page=1, size=100),
        "GET",
        "/appointments/",
        "/appointments/",
        user_scoped=True,
        idempotent=False,
        data={**PAGE, "items": [APPOINTMENT]},
        query={"status": "booked", "page": "1", "size": "100"},
        check=check_appointment_page,
    ),
    Case(
        "appointments.retrieve",
        lambda c: user(c).appointments.retrieve("dc_01"),
        "GET",
        "/appointments/{appointment_id}/",
        "/appointments/dc_01/",
        user_scoped=True,
        idempotent=False,
        data=APPOINTMENT,
        check=check_appointment,
    ),
    Case(
        "appointments.result",
        lambda c: user(c).appointments.result("dc_01"),
        "GET",
        "/appointments/{appointment_id}/result/",
        "/appointments/dc_01/result/",
        user_scoped=True,
        idempotent=False,
        data=RESULT,
        check=check_result,
    ),
    Case(
        "appointments.cancel",
        lambda c: user(c).appointments.cancel("dc_01"),
        "POST",
        "/appointments/{appointment_id}/cancel/",
        "/appointments/dc_01/cancel/",
        user_scoped=True,
        idempotent=True,
        check=check_none,
    ),
    Case(
        "appointments.reschedule",
        lambda c: user(c).appointments.reschedule(
            "dc_01", starts_at="2026-09-02T16:00:00Z", location={"state": "NY"}
        ),
        "POST",
        "/appointments/{appointment_id}/reschedule/",
        "/appointments/dc_01/reschedule/",
        user_scoped=True,
        idempotent=True,
        body={"startsAt": "2026-09-02T16:00:00Z", "location": {"state": "NY"}},
        check=check_none,
    ),
    Case(
        "address.retrieve",
        lambda c: user(c).address.retrieve(),
        "GET",
        "/address/",
        "/address/",
        user_scoped=True,
        idempotent=False,
        data=ADDRESS,
        check=check_address,
    ),
    Case(
        "address.set",
        lambda c: user(c).address.set(
            line1="100 Example Street", city="New York", state="NY", postal_code="10001"
        ),
        "PUT",
        "/address/",
        "/address/",
        user_scoped=True,
        idempotent=True,
        body={
            "line1": "100 Example Street",
            "city": "New York",
            "state": "NY",
            "postalCode": "10001",
        },
        check=check_none,
    ),
    Case(
        "pharmacy.search",
        lambda c: c.pharmacy.search(
            latitude=40.7608, longitude=-111.891, search_term="Main Street", state="UT"
        ),
        "POST",
        "/pharmacy/search/",
        "/pharmacy/search/",
        user_scoped=False,
        idempotent=True,
        data=PHARMACIES,
        body={
            "latitude": 40.7608,
            "longitude": -111.891,
            "searchTerm": "Main Street",
            "state": "UT",
        },
        check=check_pharmacies,
    ),
    Case(
        "pharmacy.set",
        lambda c: user(c).pharmacy.set(ncpdp_id="1234567"),
        "PUT",
        "/pharmacy/",
        "/pharmacy/",
        user_scoped=True,
        idempotent=True,
        body={"ncpdpId": "1234567"},
        check=check_none,
    ),
    Case(
        "coverage.set",
        lambda c: user(c).coverage.set(
            payer_id="00590",
            payer_name="Example Health Plan",
            member_id="ABC1234567",
            group_number=None,
        ),
        "PUT",
        "/coverage/",
        "/coverage/",
        user_scoped=True,
        idempotent=True,
        body={
            "payerId": "00590",
            "payerName": "Example Health Plan",
            "memberId": "ABC1234567",
            "groupNumber": None,
        },
        check=check_none,
    ),
    Case(
        "artifacts.retrieve",
        lambda c: user(c).artifacts.retrieve("art_02"),
        "GET",
        "/artifacts/{artifactId}/",
        "/artifacts/art_02/",
        user_scoped=True,
        idempotent=False,
        data=ARTIFACT,
        check=check_artifact,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_resource_method(case: Case, client: AnyClient, api: respx.MockRouter) -> None:
    route = api.request(case.method, case.path).mock(
        return_value=ok(case.data, case.status, headers={"x-request-id": "req_1"})
    )

    result = await resolve(case.call(client))

    case.check(result)
    assert route.call_count == 1
    request = route.calls.last.request
    assert request.method == case.method
    assert request.url.path == "/api/v1" + case.path
    assert dict(request.url.params) == case.query
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"].startswith("doctronic-python/")
    if case.user_scoped:
        assert request.headers["x-doctronic-user-id"] == USER_ID
    else:
        assert "x-doctronic-user-id" not in request.headers
    if case.idempotent:
        assert uuid.UUID(request.headers["idempotency-key"]).version == 4
    else:
        assert "idempotency-key" not in request.headers
    if case.body is None:
        assert request.content == b""
        assert "content-type" not in request.headers
    else:
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == case.body


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_case_matches_contract(case: Case) -> None:
    operation = OPERATIONS[(case.method, case.template)]
    assert operation.user_scoped is case.user_scoped
    assert operation.idempotent is case.idempotent
    # Methods that return None are exactly the ones whose success envelope carries no data.
    assert (case.check is check_none) is not operation.data_required


def test_cases_cover_every_contract_operation() -> None:
    covered = {(case.method, case.template) for case in CASES}
    covered.add(("POST", "/chats/{chatId}/stream/"))  # Covered by test_streaming.py.
    assert covered == set(OPERATIONS)


@pytest.mark.asyncio
async def test_caller_idempotency_key_is_sent(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.post("/chats/").mock(return_value=ok(CHAT, 201))

    await resolve(user(client).chats.create(idempotency_key="booking-123"))

    assert route.calls.last.request.headers["idempotency-key"] == "booking-123"
    assert json.loads(route.calls.last.request.content) == {}


@pytest.mark.asyncio
async def test_each_call_gets_its_own_idempotency_key(
    client: AnyClient, api: respx.MockRouter
) -> None:
    route = api.post("/chats/").mock(return_value=ok(CHAT, 201))

    await resolve(user(client).chats.create())
    await resolve(user(client).chats.create())

    keys = {call.request.headers["idempotency-key"] for call in route.calls}
    assert len(keys) == 2


@pytest.mark.asyncio
async def test_patch_sends_only_given_fields(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.patch("/users/").mock(return_value=ok(USER))

    await resolve(user(client).users.update(last_name=None))

    assert json.loads(route.calls.last.request.content) == {"lastName": None}


@pytest.mark.asyncio
async def test_path_parameters_are_escaped(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.get("/chats/a%2Fb%3Fc/").mock(return_value=ok(CHAT))

    await resolve(user(client).chats.retrieve("a/b?c"))

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_empty_path_parameter_is_rejected(client: AnyClient) -> None:
    with pytest.raises(ValueError, match="chatId"):
        await resolve(user(client).chats.retrieve(""))


@pytest.mark.asyncio
async def test_artifact_retrieve_returns_none_while_generating(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.get("/artifacts/art_02/").mock(return_value=httpx.Response(202))

    assert await resolve(user(client).artifacts.retrieve("art_02")) is None


@pytest.mark.asyncio
async def test_appointment_result_returns_none_while_pending(
    client: AnyClient, api: respx.MockRouter
) -> None:
    api.get("/appointments/dc_01/result/").mock(
        return_value=ok({"appointmentId": "dc_01", "status": "booked"}, 202)
    )

    assert await resolve(user(client).appointments.result("dc_01")) is None


@pytest.mark.asyncio
async def test_location_accepts_the_model(client: AnyClient, api: respx.MockRouter) -> None:
    from doctronic.types import LocationSchema, State

    route = api.post("/appointments/asap/").mock(return_value=ok(ASAP, 201))

    await resolve(
        user(client).appointments.create_asap(
            chat_id="chat_01", location=LocationSchema(state=State.ny)
        )
    )

    assert json.loads(route.calls.last.request.content)["location"] == {"state": "NY"}
