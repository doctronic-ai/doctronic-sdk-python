from __future__ import annotations

from typing import Final, Literal, TypedDict


class NotGiven:
    """Marks an argument the caller left out. `None` means "send null"; `NOT_GIVEN` means "omit"."""

    _instance: NotGiven | None = None

    def __new__(cls) -> NotGiven:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> Literal[False]:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN: Final = NotGiven()

Environment = Literal["staging", "production"]


class LocationParam(TypedDict):
    """The patient's US state, as a two-letter code such as `"NY"`."""

    state: str
