from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import httpx

from ._base_client import AsyncEngine, RequestOptions, SyncEngine

T = TypeVar("T")


class SyncAPIResource:
    def __init__(self, engine: SyncEngine, user_id: str | None) -> None:
        self._engine = engine
        self._user_id = user_id

    def _request(
        self,
        options: RequestOptions,
        parser: Callable[[httpx.Response], T],
    ) -> T:
        return self._engine.request(options, user_id=self._user_id, parser=parser)


class AsyncAPIResource:
    def __init__(self, engine: AsyncEngine, user_id: str | None) -> None:
        self._engine = engine
        self._user_id = user_id

    async def _request(
        self,
        options: RequestOptions,
        parser: Callable[[httpx.Response], T],
    ) -> T:
        return await self._engine.request(options, user_id=self._user_id, parser=parser)
