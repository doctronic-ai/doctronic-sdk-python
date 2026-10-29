from __future__ import annotations

from datetime import datetime
from functools import cached_property

from .._base_client import RequestOptions
from .._generated.models import (
    AppointmentAPIStatus,
    AppointmentResponse,
    AppointmentResultResponse,
    AsapAppointmentRequest,
    AsapAppointmentResponse,
    AvailableSlotsResponse,
    LocationSchema,
    PageAppointmentResponse,
    RescheduleAppointmentRequest,
    ScheduledAppointmentRequest,
    ScheduledAppointmentResponse,
)
from .._resource import AsyncAPIResource, SyncAPIResource
from .._response import (
    async_to_raw_response_wrapper,
    build_body,
    build_query,
    none_while_pending,
    parse_empty,
    parse_model,
    to_raw_response_wrapper,
)
from .._types import NOT_GIVEN, LocationParam, NotGiven

__all__ = ["AppointmentsResource", "AsyncAppointmentsResource"]

_parse_slots = parse_model(AvailableSlotsResponse)
_parse_scheduled = parse_model(ScheduledAppointmentResponse)
_parse_asap = parse_model(AsapAppointmentResponse)
_parse_appointment = parse_model(AppointmentResponse)
_parse_page = parse_model(PageAppointmentResponse)
_parse_result = none_while_pending(parse_model(AppointmentResultResponse))

_APPOINTMENT = "/appointments/{appointment_id}/"


def _available_slots_options(
    state: str, datetime_from: str | datetime | NotGiven, datetime_to: str | datetime | NotGiven
) -> RequestOptions:
    return RequestOptions(
        "GET",
        "/appointments/scheduled/available-slots/",
        params=build_query(
            {"state": state, "datetimeFrom": datetime_from, "datetimeTo": datetime_to}
        ),
    )


def _create_scheduled_options(
    chat_id: str,
    starts_at: str | datetime,
    location: LocationParam | LocationSchema,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(
        ScheduledAppointmentRequest, chat_id=chat_id, starts_at=starts_at, location=location
    )
    return RequestOptions(
        "POST", "/appointments/scheduled/", body=body, idempotency_key=idempotency_key
    )


def _create_asap_options(
    chat_id: str, location: LocationParam | LocationSchema, idempotency_key: str | NotGiven
) -> RequestOptions:
    body = build_body(AsapAppointmentRequest, chat_id=chat_id, location=location)
    return RequestOptions("POST", "/appointments/asap/", body=body, idempotency_key=idempotency_key)


def _list_options(
    status: AppointmentAPIStatus | str | NotGiven, page: int | NotGiven, size: int | NotGiven
) -> RequestOptions:
    return RequestOptions(
        "GET", "/appointments/", params=build_query({"status": status, "page": page, "size": size})
    )


def _appointment_options(appointment_id: str, suffix: str = "") -> RequestOptions:
    return RequestOptions(
        "GET", _APPOINTMENT + suffix, path_params={"appointment_id": appointment_id}
    )


def _cancel_options(appointment_id: str, idempotency_key: str | NotGiven) -> RequestOptions:
    return RequestOptions(
        "POST",
        _APPOINTMENT + "cancel/",
        path_params={"appointment_id": appointment_id},
        idempotency_key=idempotency_key,
    )


def _reschedule_options(
    appointment_id: str,
    starts_at: str | datetime,
    location: LocationParam | LocationSchema,
    idempotency_key: str | NotGiven,
) -> RequestOptions:
    body = build_body(RescheduleAppointmentRequest, starts_at=starts_at, location=location)
    return RequestOptions(
        "POST",
        _APPOINTMENT + "reschedule/",
        path_params={"appointment_id": appointment_id},
        body=body,
        idempotency_key=idempotency_key,
    )


class AppointmentsResource(SyncAPIResource):
    """`client.for_user(user_id).appointments`: book, track, and change visits."""

    def available_slots(
        self,
        *,
        state: str,
        datetime_from: str | datetime | NotGiven = NOT_GIVEN,
        datetime_to: str | datetime | NotGiven = NOT_GIVEN,
    ) -> AvailableSlotsResponse:
        """`GET /appointments/scheduled/available-slots/`: bookable slots in a US state."""
        return self._request(
            _available_slots_options(state, datetime_from, datetime_to), _parse_slots
        )

    def create_scheduled(
        self,
        *,
        chat_id: str,
        starts_at: str | datetime,
        location: LocationParam | LocationSchema,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> ScheduledAppointmentResponse:
        """`POST /appointments/scheduled/`: book a slot from `available_slots()`."""
        return self._request(
            _create_scheduled_options(chat_id, starts_at, location, idempotency_key),
            _parse_scheduled,
        )

    def create_asap(
        self,
        *,
        chat_id: str,
        location: LocationParam | LocationSchema,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> AsapAppointmentResponse:
        """`POST /appointments/asap/`: place the patient in the next available waiting room."""
        return self._request(_create_asap_options(chat_id, location, idempotency_key), _parse_asap)

    def list(
        self,
        *,
        status: AppointmentAPIStatus | str | NotGiven = NOT_GIVEN,
        page: int | NotGiven = NOT_GIVEN,
        size: int | NotGiven = NOT_GIVEN,
    ) -> PageAppointmentResponse:
        """`GET /appointments/`: the user's appointments."""
        return self._request(_list_options(status, page, size), _parse_page)

    def retrieve(self, appointment_id: str) -> AppointmentResponse:
        """`GET /appointments/{appointment_id}/`: one appointment, with its current state."""
        return self._request(_appointment_options(appointment_id), _parse_appointment)

    def result(self, appointment_id: str) -> AppointmentResultResponse | None:
        """`GET /appointments/{appointment_id}/result/`: the visit result.

        Returns `None` while the result isn't available yet (`202`). Raises `ConflictError`
        (`error.appointments.result_unavailable`) when no result will exist.
        """
        return self._request(_appointment_options(appointment_id, "result/"), _parse_result)

    def cancel(self, appointment_id: str, *, idempotency_key: str | NotGiven = NOT_GIVEN) -> None:
        """`POST /appointments/{appointment_id}/cancel/`."""
        return self._request(_cancel_options(appointment_id, idempotency_key), parse_empty)

    def reschedule(
        self,
        appointment_id: str,
        *,
        starts_at: str | datetime,
        location: LocationParam | LocationSchema,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> None:
        """`POST /appointments/{appointment_id}/reschedule/`: move a booked appointment."""
        return self._request(
            _reschedule_options(appointment_id, starts_at, location, idempotency_key), parse_empty
        )

    @cached_property
    def with_raw_response(self) -> AppointmentsResourceWithRawResponse:
        return AppointmentsResourceWithRawResponse(self)


class AsyncAppointmentsResource(AsyncAPIResource):
    """`client.for_user(user_id).appointments`: book, track, and change visits."""

    async def available_slots(
        self,
        *,
        state: str,
        datetime_from: str | datetime | NotGiven = NOT_GIVEN,
        datetime_to: str | datetime | NotGiven = NOT_GIVEN,
    ) -> AvailableSlotsResponse:
        """`GET /appointments/scheduled/available-slots/`: bookable slots in a US state."""
        return await self._request(
            _available_slots_options(state, datetime_from, datetime_to), _parse_slots
        )

    async def create_scheduled(
        self,
        *,
        chat_id: str,
        starts_at: str | datetime,
        location: LocationParam | LocationSchema,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> ScheduledAppointmentResponse:
        """`POST /appointments/scheduled/`: book a slot from `available_slots()`."""
        return await self._request(
            _create_scheduled_options(chat_id, starts_at, location, idempotency_key),
            _parse_scheduled,
        )

    async def create_asap(
        self,
        *,
        chat_id: str,
        location: LocationParam | LocationSchema,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> AsapAppointmentResponse:
        """`POST /appointments/asap/`: place the patient in the next available waiting room."""
        return await self._request(
            _create_asap_options(chat_id, location, idempotency_key), _parse_asap
        )

    async def list(
        self,
        *,
        status: AppointmentAPIStatus | str | NotGiven = NOT_GIVEN,
        page: int | NotGiven = NOT_GIVEN,
        size: int | NotGiven = NOT_GIVEN,
    ) -> PageAppointmentResponse:
        """`GET /appointments/`: the user's appointments."""
        return await self._request(_list_options(status, page, size), _parse_page)

    async def retrieve(self, appointment_id: str) -> AppointmentResponse:
        """`GET /appointments/{appointment_id}/`: one appointment, with its current state."""
        return await self._request(_appointment_options(appointment_id), _parse_appointment)

    async def result(self, appointment_id: str) -> AppointmentResultResponse | None:
        """`GET /appointments/{appointment_id}/result/`: the visit result.

        Returns `None` while the result isn't available yet (`202`). Raises `ConflictError`
        (`error.appointments.result_unavailable`) when no result will exist.
        """
        return await self._request(_appointment_options(appointment_id, "result/"), _parse_result)

    async def cancel(
        self, appointment_id: str, *, idempotency_key: str | NotGiven = NOT_GIVEN
    ) -> None:
        """`POST /appointments/{appointment_id}/cancel/`."""
        return await self._request(_cancel_options(appointment_id, idempotency_key), parse_empty)

    async def reschedule(
        self,
        appointment_id: str,
        *,
        starts_at: str | datetime,
        location: LocationParam | LocationSchema,
        idempotency_key: str | NotGiven = NOT_GIVEN,
    ) -> None:
        """`POST /appointments/{appointment_id}/reschedule/`: move a booked appointment."""
        return await self._request(
            _reschedule_options(appointment_id, starts_at, location, idempotency_key), parse_empty
        )

    @cached_property
    def with_raw_response(self) -> AsyncAppointmentsResourceWithRawResponse:
        return AsyncAppointmentsResourceWithRawResponse(self)


class AppointmentsResourceWithRawResponse:
    def __init__(self, appointments: AppointmentsResource) -> None:
        self.available_slots = to_raw_response_wrapper(appointments.available_slots)
        self.create_scheduled = to_raw_response_wrapper(appointments.create_scheduled)
        self.create_asap = to_raw_response_wrapper(appointments.create_asap)
        self.list = to_raw_response_wrapper(appointments.list)
        self.retrieve = to_raw_response_wrapper(appointments.retrieve)
        self.result = to_raw_response_wrapper(appointments.result)
        self.cancel = to_raw_response_wrapper(appointments.cancel)
        self.reschedule = to_raw_response_wrapper(appointments.reschedule)


class AsyncAppointmentsResourceWithRawResponse:
    def __init__(self, appointments: AsyncAppointmentsResource) -> None:
        self.available_slots = async_to_raw_response_wrapper(appointments.available_slots)
        self.create_scheduled = async_to_raw_response_wrapper(appointments.create_scheduled)
        self.create_asap = async_to_raw_response_wrapper(appointments.create_asap)
        self.list = async_to_raw_response_wrapper(appointments.list)
        self.retrieve = async_to_raw_response_wrapper(appointments.retrieve)
        self.result = async_to_raw_response_wrapper(appointments.result)
        self.cancel = async_to_raw_response_wrapper(appointments.cancel)
        self.reschedule = async_to_raw_response_wrapper(appointments.reschedule)
