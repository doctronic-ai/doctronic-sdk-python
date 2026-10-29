from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
import respx

from doctronic import AsyncDoctronic, Doctronic, _retry
from tests.helpers import BASE_URL, TOKEN


@dataclass
class FakeClock:
    """Stands in for real time: sleeping advances the clock and records the delay."""

    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    async def async_sleep(self, seconds: float) -> None:
        self.sleep(seconds)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(_retry, "sleep", fake.sleep)
    monkeypatch.setattr(_retry, "async_sleep", fake.async_sleep)
    monkeypatch.setattr(_retry, "monotonic", fake.monotonic)
    return fake


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCTRONIC_API_TOKEN", raising=False)
    monkeypatch.delenv("DOCTRONIC_ENVIRONMENT", raising=False)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    """The mock Doctronic API. Requests that match no route fail the test."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest_asyncio.fixture(params=["sync", "async"])
async def client(
    request: pytest.FixtureRequest, api: respx.MockRouter
) -> AsyncIterator[Doctronic | AsyncDoctronic]:
    if request.param == "sync":
        sync_client = Doctronic(api_token=TOKEN, base_url=BASE_URL)
        yield sync_client
        sync_client.close()
    else:
        async_client = AsyncDoctronic(api_token=TOKEN, base_url=BASE_URL)
        yield async_client
        await async_client.close()
