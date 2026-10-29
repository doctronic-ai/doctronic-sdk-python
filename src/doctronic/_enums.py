"""The `Enum` base of the generated models: it accepts values the contract doesn't list yet.

The API can add an enum value, such as a new appointment status, without a new API version, and
the docs ask clients to ignore values they don't know. A plain `Enum` raises on such a value, and
the whole response would fail validation. `OpenEnum` returns a member for it instead:

- `AppointmentAPIStatus("booked")` is `AppointmentAPIStatus.booked`, as before.
- `AppointmentAPIStatus("on_hold")` is a new member that isn't one of the listed ones. It's an
  instance of `AppointmentAPIStatus` and of `str`, it equals `"on_hold"`, and its `value` and
  `name` are `"on_hold"`. Compare it with the members you handle and treat anything else as
  unknown.
- A value of the wrong type, such as `7` for a string enum, still raises.
"""

from __future__ import annotations

import enum
from typing import Any

__all__ = ["Enum", "OpenEnum"]


class OpenEnum(enum.Enum):
    """An `Enum` that also accepts values of its member type that it doesn't list."""

    @classmethod
    def _missing_(cls, value: object) -> Any:
        # The data type the members mix in, such as `str` for `class Status(str, OpenEnum)`.
        member_type: Any = getattr(cls, "_member_type_", object)
        if member_type is object or not isinstance(value, member_type):
            return None
        member: Any = member_type.__new__(cls, value)
        member._name_ = str(value)
        member._value_ = value
        return member


Enum = OpenEnum
"""The name the generated models import (`scripts/generate.py` passes `--import-overrides`)."""
