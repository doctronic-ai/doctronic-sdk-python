from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from doctronic import SIGNATURE_HEADER, WebhookVerificationError, verify_webhook
from doctronic.types import (
    AppointmentCallEndedEvent,
    AppointmentPractitionerJoinedEvent,
    AppointmentWaitingRoomReadyEvent,
    ArtifactReadyEvent,
    UnknownWebhookEvent,
)

SECRET = "whsec_test_not_a_real_secret"
EVENT_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def delivery(event: str, data: Any) -> bytes:
    return json.dumps(
        {"eventId": EVENT_ID, "event": event, "occurredAt": "2026-08-25T18:30:00Z", "data": data}
    ).encode()


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_header_name() -> None:
    assert SIGNATURE_HEADER == "X-Doctronic-Signature"


def test_waiting_room_ready() -> None:
    body = delivery(
        "appointment.waiting_room_ready",
        {"appointmentId": "dc_01", "userId": "mem_01", "waitingRoomUrl": "https://example.com/w"},
    )

    event = verify_webhook(body, sign(body), SECRET)

    assert isinstance(event, AppointmentWaitingRoomReadyEvent)
    assert event.event_id == EVENT_ID
    assert event.occurred_at == datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc)
    assert event.data.waiting_room_url == "https://example.com/w"


@pytest.mark.parametrize(
    ("name", "event_type"),
    [
        ("appointment.practitioner_joined", AppointmentPractitionerJoinedEvent),
        ("appointment.call_ended", AppointmentCallEndedEvent),
    ],
)
def test_appointment_events(name: str, event_type: type[object]) -> None:
    body = delivery(name, {"appointmentId": "dc_01", "userId": "mem_01"})

    event = verify_webhook(body, sign(body), SECRET)

    assert isinstance(event, event_type)


def test_artifact_ready_allows_null_user() -> None:
    body = delivery(
        "artifact.ready",
        {
            "artifactId": "art_01",
            "artifactType": "clinician_note",
            "chatId": "chat_01",
            "userId": None,
        },
    )

    event = verify_webhook(body, sign(body), SECRET)

    assert isinstance(event, ArtifactReadyEvent)
    assert event.data.user_id is None
    assert event.data.artifact_type == "clinician_note"


def test_unknown_event_is_returned_not_raised() -> None:
    body = delivery("appointment.rescheduled", {"anything": 1})

    event = verify_webhook(body, sign(body), SECRET)

    assert isinstance(event, UnknownWebhookEvent)
    assert event.event == "appointment.rescheduled"
    assert event.data == {"anything": 1}


def test_accepts_the_body_as_text() -> None:
    body = delivery("appointment.call_ended", {"appointmentId": "dc_01", "userId": "mem_01"})

    event = verify_webhook(body.decode(), sign(body), SECRET)

    assert isinstance(event, AppointmentCallEndedEvent)


def test_tampered_body_fails() -> None:
    body = delivery("appointment.call_ended", {"appointmentId": "dc_01", "userId": "mem_01"})
    signature = sign(body)

    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(body.replace(b"dc_01", b"dc_02"), signature, SECRET)


def test_reserialized_body_fails() -> None:
    body = delivery("appointment.call_ended", {"appointmentId": "dc_01", "userId": "mem_01"})

    with pytest.raises(WebhookVerificationError):
        verify_webhook(json.dumps(json.loads(body), indent=2), sign(body), SECRET)


def test_wrong_secret_fails() -> None:
    body = delivery("appointment.call_ended", {"appointmentId": "dc_01", "userId": "mem_01"})

    with pytest.raises(WebhookVerificationError):
        verify_webhook(body, sign(body, "whsec_other"), SECRET)


@pytest.mark.parametrize("header", [None, "", "abc", "é" * 64, "not-hex-" * 8])
def test_missing_or_malformed_signature_fails(header: str | None) -> None:
    body = delivery("appointment.call_ended", {"appointmentId": "dc_01", "userId": "mem_01"})

    with pytest.raises(WebhookVerificationError):
        verify_webhook(body, header, SECRET)


def test_uppercase_signature_fails() -> None:
    # The header is lowercase hex; compare it exactly as the docs' verifiers do.
    body = delivery("appointment.call_ended", {"appointmentId": "dc_01", "userId": "mem_01"})

    with pytest.raises(WebhookVerificationError):
        verify_webhook(body, sign(body).upper(), SECRET)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1, 2, 3]",
        json.dumps({"event": "appointment.call_ended"}).encode(),
        json.dumps(
            {"eventId": EVENT_ID, "event": ["x"], "occurredAt": "2026-08-25T18:30:00Z"}
        ).encode(),
        delivery("appointment.call_ended", {"appointmentId": "dc_01"}),
    ],
    ids=["not-json", "not-object", "no-envelope", "bad-event-name", "missing-data-field"],
)
def test_signed_but_invalid_envelope_fails(body: bytes) -> None:
    with pytest.raises(WebhookVerificationError, match=r"envelope|JSON"):
        verify_webhook(body, sign(body), SECRET)


def test_empty_secret_is_rejected() -> None:
    body = b"{}"
    with pytest.raises(ValueError, match="secret"):
        verify_webhook(body, sign(body, ""), "")
