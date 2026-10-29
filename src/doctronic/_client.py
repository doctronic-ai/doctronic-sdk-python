from __future__ import annotations

from functools import cached_property
from types import TracebackType

import httpx

from ._base_client import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    AsyncEngine,
    SyncEngine,
    resolve_config,
)
from ._errors import DoctronicError
from ._types import Environment
from .resources.address import (
    AddressResource,
    AddressResourceWithRawResponse,
    AsyncAddressResource,
    AsyncAddressResourceWithRawResponse,
)
from .resources.appointments import (
    AppointmentsResource,
    AppointmentsResourceWithRawResponse,
    AsyncAppointmentsResource,
    AsyncAppointmentsResourceWithRawResponse,
)
from .resources.artifacts import (
    ArtifactsResource,
    ArtifactsResourceWithRawResponse,
    AsyncArtifactsResource,
    AsyncArtifactsResourceWithRawResponse,
)
from .resources.chats import (
    AsyncChatsResource,
    AsyncChatsResourceWithRawResponse,
    ChatsResource,
    ChatsResourceWithRawResponse,
)
from .resources.coverage import (
    AsyncCoverageResource,
    AsyncCoverageResourceWithRawResponse,
    CoverageResource,
    CoverageResourceWithRawResponse,
)
from .resources.pharmacy import (
    AsyncPharmacyResource,
    AsyncPharmacyResourceWithRawResponse,
    AsyncScopedPharmacyResource,
    AsyncScopedPharmacyResourceWithRawResponse,
    PharmacyResource,
    PharmacyResourceWithRawResponse,
    ScopedPharmacyResource,
    ScopedPharmacyResourceWithRawResponse,
)
from .resources.users import (
    AsyncScopedUsersResource,
    AsyncScopedUsersResourceWithRawResponse,
    AsyncUsersResource,
    AsyncUsersResourceWithRawResponse,
    ScopedUsersResource,
    ScopedUsersResourceWithRawResponse,
    UsersResource,
    UsersResourceWithRawResponse,
)

__all__ = ["AsyncDoctronic", "AsyncUserScopedClient", "Doctronic", "UserScopedClient"]


def _check_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id.strip():
        raise DoctronicError("`user_id` must be the Doctronic user ID, such as `mem_...`.")
    return user_id


class Doctronic:
    """Synchronous client for the Doctronic API.

    Org-scoped operations live here: `users.create()` and `pharmacy.search()`. Everything else
    acts on one patient: call `for_user(user_id)` for a client that sends `X-Doctronic-User-ID`.

    Args:
        api_token: Defaults to the `DOCTRONIC_API_TOKEN` environment variable.
        environment: `"staging"` or `"production"`. Defaults to `DOCTRONIC_ENVIRONMENT`, then
            `"staging"`.
        base_url: Overrides the environment's base URL.
        timeout: Seconds, or an `httpx.Timeout`, for JSON requests. Streams keep this connect
            timeout and leave the read timeout unbounded.
        max_retries: Retries for reads and idempotent mutations. Defaults to 2.
        http_client: An `httpx.Client` to send requests with. You close it.
    """

    users: UsersResource
    pharmacy: PharmacyResource

    def __init__(
        self,
        api_token: str | None = None,
        *,
        environment: Environment | None = None,
        base_url: str | None = None,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ) -> None:
        config = resolve_config(
            api_token=api_token,
            environment=environment,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._engine = SyncEngine(config, http_client)
        self.users = UsersResource(self._engine, None)
        self.pharmacy = PharmacyResource(self._engine, None)

    @property
    def base_url(self) -> str:
        return self._engine.base_url

    @property
    def max_retries(self) -> int:
        return self._engine.max_retries

    def for_user(self, user_id: str) -> UserScopedClient:
        """A client for one patient. It shares this client's connection pool and settings."""
        return UserScopedClient(self._engine, _check_user_id(user_id))

    @cached_property
    def with_raw_response(self) -> DoctronicWithRawResponse:
        """The same methods, returning an `APIResponse` with the status, headers, and request ID."""
        return DoctronicWithRawResponse(self)

    def close(self) -> None:
        self._engine.close()

    def __enter__(self) -> Doctronic:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Doctronic base_url={self.base_url!r}>"


class UserScopedClient:
    """Acts on one patient: every request sends `X-Doctronic-User-ID`."""

    users: ScopedUsersResource
    chats: ChatsResource
    appointments: AppointmentsResource
    address: AddressResource
    pharmacy: ScopedPharmacyResource
    coverage: CoverageResource
    artifacts: ArtifactsResource

    def __init__(self, engine: SyncEngine, user_id: str) -> None:
        self.user_id = user_id
        self.users = ScopedUsersResource(engine, user_id)
        self.chats = ChatsResource(engine, user_id)
        self.appointments = AppointmentsResource(engine, user_id)
        self.address = AddressResource(engine, user_id)
        self.pharmacy = ScopedPharmacyResource(engine, user_id)
        self.coverage = CoverageResource(engine, user_id)
        self.artifacts = ArtifactsResource(engine, user_id)

    @cached_property
    def with_raw_response(self) -> UserScopedClientWithRawResponse:
        """The same methods, returning an `APIResponse` with the status, headers, and request ID."""
        return UserScopedClientWithRawResponse(self)

    def __repr__(self) -> str:
        return f"<UserScopedClient user_id={self.user_id!r}>"


class AsyncDoctronic:
    """Asynchronous client for the Doctronic API. See `Doctronic` for the arguments.

    `http_client` is an `httpx.AsyncClient`.
    """

    users: AsyncUsersResource
    pharmacy: AsyncPharmacyResource

    def __init__(
        self,
        api_token: str | None = None,
        *,
        environment: Environment | None = None,
        base_url: str | None = None,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        config = resolve_config(
            api_token=api_token,
            environment=environment,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._engine = AsyncEngine(config, http_client)
        self.users = AsyncUsersResource(self._engine, None)
        self.pharmacy = AsyncPharmacyResource(self._engine, None)

    @property
    def base_url(self) -> str:
        return self._engine.base_url

    @property
    def max_retries(self) -> int:
        return self._engine.max_retries

    def for_user(self, user_id: str) -> AsyncUserScopedClient:
        """A client for one patient. It shares this client's connection pool and settings."""
        return AsyncUserScopedClient(self._engine, _check_user_id(user_id))

    @cached_property
    def with_raw_response(self) -> AsyncDoctronicWithRawResponse:
        """The same methods, returning an `APIResponse` with the status, headers, and request ID."""
        return AsyncDoctronicWithRawResponse(self)

    async def close(self) -> None:
        await self._engine.close()

    async def __aenter__(self) -> AsyncDoctronic:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"<AsyncDoctronic base_url={self.base_url!r}>"


class AsyncUserScopedClient:
    """Acts on one patient: every request sends `X-Doctronic-User-ID`."""

    users: AsyncScopedUsersResource
    chats: AsyncChatsResource
    appointments: AsyncAppointmentsResource
    address: AsyncAddressResource
    pharmacy: AsyncScopedPharmacyResource
    coverage: AsyncCoverageResource
    artifacts: AsyncArtifactsResource

    def __init__(self, engine: AsyncEngine, user_id: str) -> None:
        self.user_id = user_id
        self.users = AsyncScopedUsersResource(engine, user_id)
        self.chats = AsyncChatsResource(engine, user_id)
        self.appointments = AsyncAppointmentsResource(engine, user_id)
        self.address = AsyncAddressResource(engine, user_id)
        self.pharmacy = AsyncScopedPharmacyResource(engine, user_id)
        self.coverage = AsyncCoverageResource(engine, user_id)
        self.artifacts = AsyncArtifactsResource(engine, user_id)

    @cached_property
    def with_raw_response(self) -> AsyncUserScopedClientWithRawResponse:
        """The same methods, returning an `APIResponse` with the status, headers, and request ID."""
        return AsyncUserScopedClientWithRawResponse(self)

    def __repr__(self) -> str:
        return f"<AsyncUserScopedClient user_id={self.user_id!r}>"


class DoctronicWithRawResponse:
    def __init__(self, client: Doctronic) -> None:
        self.users: UsersResourceWithRawResponse = client.users.with_raw_response
        self.pharmacy: PharmacyResourceWithRawResponse = client.pharmacy.with_raw_response


class UserScopedClientWithRawResponse:
    def __init__(self, client: UserScopedClient) -> None:
        self.users: ScopedUsersResourceWithRawResponse = client.users.with_raw_response
        self.chats: ChatsResourceWithRawResponse = client.chats.with_raw_response
        self.appointments: AppointmentsResourceWithRawResponse = (
            client.appointments.with_raw_response
        )
        self.address: AddressResourceWithRawResponse = client.address.with_raw_response
        self.pharmacy: ScopedPharmacyResourceWithRawResponse = client.pharmacy.with_raw_response
        self.coverage: CoverageResourceWithRawResponse = client.coverage.with_raw_response
        self.artifacts: ArtifactsResourceWithRawResponse = client.artifacts.with_raw_response


class AsyncDoctronicWithRawResponse:
    def __init__(self, client: AsyncDoctronic) -> None:
        self.users: AsyncUsersResourceWithRawResponse = client.users.with_raw_response
        self.pharmacy: AsyncPharmacyResourceWithRawResponse = client.pharmacy.with_raw_response


class AsyncUserScopedClientWithRawResponse:
    def __init__(self, client: AsyncUserScopedClient) -> None:
        self.users: AsyncScopedUsersResourceWithRawResponse = client.users.with_raw_response
        self.chats: AsyncChatsResourceWithRawResponse = client.chats.with_raw_response
        self.appointments: AsyncAppointmentsResourceWithRawResponse = (
            client.appointments.with_raw_response
        )
        self.address: AsyncAddressResourceWithRawResponse = client.address.with_raw_response
        self.pharmacy: AsyncScopedPharmacyResourceWithRawResponse = (
            client.pharmacy.with_raw_response
        )
        self.coverage: AsyncCoverageResourceWithRawResponse = client.coverage.with_raw_response
        self.artifacts: AsyncArtifactsResourceWithRawResponse = client.artifacts.with_raw_response
