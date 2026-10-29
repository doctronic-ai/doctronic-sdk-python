from __future__ import annotations

import logging

import httpx
import pytest
import respx

from doctronic import (
    AsyncDoctronic,
    AsyncUserScopedClient,
    AuthenticationError,
    Doctronic,
    DoctronicError,
    UserScopedClient,
)
from tests.helpers import BASE_URL, TOKEN, USER_ID, error, ok, resolve

AnyClient = Doctronic | AsyncDoctronic
CLIENT_TYPES = [Doctronic, AsyncDoctronic]

USER = {"id": USER_ID, "appointmentDemographicsComplete": False, "missingAppointmentFields": []}


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_environments(client_type: type[AnyClient]) -> None:
    assert client_type(api_token=TOKEN).base_url == "https://staging-partners.doctronic.ai/api/v1"
    assert (
        client_type(api_token=TOKEN, environment="production").base_url
        == "https://partners.doctronic.ai/api/v1"
    )
    assert (
        client_type(
            api_token=TOKEN, environment="production", base_url="http://localhost:8000/v1/"
        ).base_url
        == "http://localhost:8000/v1"
    )


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_settings_from_the_environment(
    client_type: type[AnyClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCTRONIC_API_TOKEN", TOKEN)
    monkeypatch.setenv("DOCTRONIC_ENVIRONMENT", "production")

    client = client_type()

    assert client.base_url == "https://partners.doctronic.ai/api/v1"
    assert client_type(environment="staging").base_url.startswith("https://staging-partners.")


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_missing_token_raises(client_type: type[AnyClient]) -> None:
    with pytest.raises(DoctronicError, match="DOCTRONIC_API_TOKEN"):
        client_type()
    with pytest.raises(DoctronicError):
        client_type(api_token="")


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_invalid_settings_raise(client_type: type[AnyClient]) -> None:
    with pytest.raises(DoctronicError, match="environment"):
        client_type(api_token=TOKEN, environment="prod")  # type: ignore[arg-type]
    with pytest.raises(DoctronicError, match="max_retries"):
        client_type(api_token=TOKEN, max_retries=-1)


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_default_max_retries(client_type: type[AnyClient]) -> None:
    assert client_type(api_token=TOKEN).max_retries == 2


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_token_never_appears_in_reprs(client_type: type[AnyClient]) -> None:
    client = client_type(api_token=TOKEN)
    user = client.for_user(USER_ID)
    for text in (
        repr(client),
        str(client),
        repr(user),
        repr(vars(client)),
        repr(client._engine._config),
    ):
        assert TOKEN not in text


@pytest.mark.asyncio
async def test_token_never_appears_in_errors_or_logs(
    client: AnyClient, api: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    api.get("/users/").mock(return_value=error(401, "error.auth.unauthorized", "Unauthorized."))

    with pytest.raises(AuthenticationError) as raised:
        await resolve(client.for_user(USER_ID).users.retrieve())

    assert TOKEN not in str(raised.value)
    assert TOKEN not in repr(raised.value.headers)
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
def test_user_scoped_resources_need_a_user(client_type: type[AnyClient]) -> None:
    client = client_type(api_token=TOKEN)

    for name in ("chats", "appointments", "address", "coverage", "artifacts"):
        assert not hasattr(client, name)
    assert not hasattr(client.users, "retrieve")
    assert not hasattr(client.users, "update")
    assert not hasattr(client.pharmacy, "set")

    user = client.for_user(USER_ID)
    assert isinstance(user, (UserScopedClient, AsyncUserScopedClient))
    assert user.user_id == USER_ID
    assert not hasattr(user.users, "create")
    assert not hasattr(user.pharmacy, "search")


@pytest.mark.parametrize("client_type", CLIENT_TYPES)
@pytest.mark.parametrize("user_id", ["", "   ", None, 42])
def test_for_user_rejects_blank_ids(client_type: type[AnyClient], user_id: object) -> None:
    with pytest.raises(DoctronicError, match="user_id"):
        client_type(api_token=TOKEN).for_user(user_id)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_user_clients_are_independent(client: AnyClient, api: respx.MockRouter) -> None:
    route = api.get("/users/").mock(return_value=ok(USER))

    await resolve(client.for_user("mem_a").users.retrieve())
    await resolve(client.for_user("mem_b").users.retrieve())

    assert [call.request.headers["x-doctronic-user-id"] for call in route.calls] == [
        "mem_a",
        "mem_b",
    ]


def test_custom_sync_http_client_is_used_and_left_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return ok(USER)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    with Doctronic(api_token=TOKEN, base_url=BASE_URL, http_client=http_client) as client:
        assert client.for_user(USER_ID).users.retrieve().id == USER_ID
    assert not http_client.is_closed
    http_client.close()


@pytest.mark.asyncio
async def test_custom_async_http_client_is_used_and_left_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok(USER)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with AsyncDoctronic(
        api_token=TOKEN, base_url=BASE_URL, http_client=http_client
    ) as client:
        assert (await client.for_user(USER_ID).users.retrieve()).id == USER_ID
    assert not http_client.is_closed
    await http_client.aclose()


def test_owned_http_client_is_closed() -> None:
    client = Doctronic(api_token=TOKEN, base_url=BASE_URL)
    client.close()
    assert client._engine._http.is_closed


@pytest.mark.asyncio
async def test_timeouts_are_applied(api: respx.MockRouter) -> None:
    route = api.get("/users/").mock(return_value=ok(USER))
    client = Doctronic(api_token=TOKEN, base_url=BASE_URL, timeout=httpx.Timeout(5.0, connect=2.0))

    client.for_user(USER_ID).users.retrieve()

    timeout = route.calls.last.request.extensions["timeout"]
    assert timeout == {"connect": 2.0, "read": 5.0, "write": 5.0, "pool": 5.0}
