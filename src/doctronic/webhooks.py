"""Verify and parse signed webhook deliveries.

`X-Doctronic-Signature` carries the lowercase hex HMAC-SHA256 of the exact request body bytes,
keyed with your webhook secret. Verify the raw body before you parse it: reserializing the JSON
changes the bytes and breaks the signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Literal, TypeAlias, cast

import pydantic
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ._errors import WebhookVerificationError

__all__ = [
    "SIGNATURE_HEADER",
    "WEBHOOK_SIGNATURE_HEADER",
    "AppointmentCallEndedData",
    "AppointmentCallEndedEvent",
    "AppointmentPractitionerJoinedData",
    "AppointmentPractitionerJoinedEvent",
    "AppointmentWaitingRoomReadyData",
    "AppointmentWaitingRoomReadyEvent",
    "ArtifactReadyData",
    "ArtifactReadyEvent",
    "KnownWebhookEvent",
    "UnknownWebhookEvent",
    "WebhookEvent",
    "verify_webhook",
]

WEBHOOK_SIGNATURE_HEADER = "X-Doctronic-Signature"
"""The header that carries the signature. The TypeScript SDK exports the same name."""
SIGNATURE_HEADER = WEBHOOK_SIGNATURE_HEADER
"""The same header. Kept for code written against 0.1.0."""


class _WebhookModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")


class AppointmentWaitingRoomReadyData(_WebhookModel):
    appointment_id: str
    user_id: str
    waiting_room_url: str


class AppointmentPractitionerJoinedData(_WebhookModel):
    appointment_id: str
    user_id: str


class AppointmentCallEndedData(_WebhookModel):
    appointment_id: str
    user_id: str


class ArtifactReadyData(_WebhookModel):
    artifact_id: str
    artifact_type: str
    chat_id: str
    user_id: str | None


class _Envelope(_WebhookModel):
    event_id: str
    """Stable across every delivery attempt of one event. Deduplicate on it."""
    occurred_at: datetime
    """When the event happened, not when this attempt arrived."""


class AppointmentWaitingRoomReadyEvent(_Envelope):
    """A join URL is ready. Replace any URL you stored earlier."""

    event: Literal["appointment.waiting_room_ready"]
    data: AppointmentWaitingRoomReadyData


class AppointmentPractitionerJoinedEvent(_Envelope):
    """A practitioner joined the appointment."""

    event: Literal["appointment.practitioner_joined"]
    data: AppointmentPractitionerJoinedData


class AppointmentCallEndedEvent(_Envelope):
    """The appointment call ended."""

    event: Literal["appointment.call_ended"]
    data: AppointmentCallEndedData


class ArtifactReadyEvent(_Envelope):
    """A consultation document is ready to retrieve."""

    event: Literal["artifact.ready"]
    data: ArtifactReadyData


class UnknownWebhookEvent(_Envelope):
    """An event name this SDK version doesn't know. Acknowledge it with `2xx`."""

    event: str
    data: Any = None


KnownWebhookEvent: TypeAlias = (
    AppointmentWaitingRoomReadyEvent
    | AppointmentPractitionerJoinedEvent
    | AppointmentCallEndedEvent
    | ArtifactReadyEvent
)
"""Every webhook event the docs list."""

WebhookEvent: TypeAlias = KnownWebhookEvent | UnknownWebhookEvent
"""A verified webhook delivery. Narrow it with `isinstance`."""

_EVENT_TYPES: dict[str, type[_Envelope]] = {
    "appointment.waiting_room_ready": AppointmentWaitingRoomReadyEvent,
    "appointment.practitioner_joined": AppointmentPractitionerJoinedEvent,
    "appointment.call_ended": AppointmentCallEndedEvent,
    "artifact.ready": ArtifactReadyEvent,
}


def verify_webhook(
    raw_body: bytes | bytearray | memoryview | str,
    signature_header: str | None,
    secret: str,
) -> WebhookEvent:
    """Verify a delivery's signature, then parse it into a typed event.

    Pass the request body exactly as received, the `X-Doctronic-Signature` header value, and
    your webhook secret. Raises `WebhookVerificationError` when the secret is empty, the
    signature doesn't match, or the signed body isn't a valid event envelope.
    """
    if not isinstance(secret, str) or not secret:
        # An unset secret must fail like a bad signature, so a handler that answers
        # `WebhookVerificationError` with 400 can't accept forged deliveries.
        raise WebhookVerificationError("A webhook secret is required.")
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    # Compare bytes: `compare_digest` rejects non-ASCII str, and the header is attacker input.
    supplied = (signature_header or "").encode("utf-8")
    if not hmac.compare_digest(supplied, expected.encode("ascii")):
        raise WebhookVerificationError("Invalid Doctronic webhook signature.")

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise WebhookVerificationError("The signed webhook body isn't JSON.") from exc
    if not isinstance(payload, dict):
        raise WebhookVerificationError("The signed webhook body isn't an event envelope.")
    name = payload.get("event")
    model = (_EVENT_TYPES.get(name) if isinstance(name, str) else None) or UnknownWebhookEvent
    try:
        return cast("WebhookEvent", model.model_validate(payload))
    except pydantic.ValidationError as exc:
        raise WebhookVerificationError(
            f"The signed webhook body isn't a valid event envelope: {exc}"
        ) from exc
