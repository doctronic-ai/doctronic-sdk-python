"""Retry rules, from the retry checklist in the Doctronic errors guide.

Each rule reads the facts the contract declares about the operation (`_generated/operations.py`).

- A streamed turn is never resent: it takes no idempotency key and may already have produced a
  reply.
- Only reads (`GET`) and the operations whose contract declares an `Idempotency-Key` header are
  retried. Every other mutation is sent once.
- Network errors, timeouts, `429`, and `503` are retried.
- `409` is retried on idempotent operations only, and only when its `code` isn't a final one
  for that operation (`Operation.conflict_codes`). The final codes are the ones the contract's
  409 examples document, such as `error.appointments.slot_unavailable`, minus any the 409
  response lists in `x-doctronic-retryable-codes`, such as an idempotency conflict whose first
  request is still in progress. Without that list, every documented code is final. A `409`
  without a code, or with one the contract doesn't document, is treated as an idempotency
  conflict and retried with the same key.
- Other `5xx` are retried on reads only, unless the contract documents that status for the
  operation as a definitive result, like `500` for an artifact whose generation failed.
- Delays grow exponentially with jitter. A `Retry-After` replaces the backoff.
"""

from __future__ import annotations

import asyncio
import email.utils
import random
import time
from datetime import datetime, timezone

import httpx

from ._generated.operations import Operation

INITIAL_DELAY = 0.5
MAX_DELAY = 8.0
JITTER = 0.25
MAX_RETRY_AFTER = 60.0
"""A `Retry-After` longer than this ends the retries, so the caller decides when to try again."""

# Indirections, so tests can run without real waiting.
sleep = time.sleep
async_sleep = asyncio.sleep
monotonic = time.monotonic


def retry_safe(operation: Operation) -> bool:
    """Whether a failed attempt of this operation may be sent again at all."""
    return not operation.stream and (operation.method == "GET" or operation.idempotent)


def should_retry_status(operation: Operation, status: int, code: str | None) -> bool:
    if not retry_safe(operation):
        return False
    if status in (429, 503):
        return True
    if status == 409:
        return operation.idempotent and (code is None or code not in operation.conflict_codes)
    if status >= 500:
        return operation.method == "GET" and status not in operation.statuses
    return False


def parse_retry_after(headers: httpx.Headers) -> float | None:
    value: str | None = headers.get("retry-after")
    if value is None:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if seconds != seconds:  # NaN
        return None
    return max(seconds, 0.0)


def retry_delay(retries_so_far: int, retry_after: float | None) -> float | None:
    """Seconds to wait before the next attempt, or `None` when `Retry-After` is too long."""
    if retry_after is not None:
        return None if retry_after > MAX_RETRY_AFTER else retry_after
    backoff = min(MAX_DELAY, INITIAL_DELAY * 2.0**retries_so_far)
    return backoff + random.random() * backoff * JITTER
