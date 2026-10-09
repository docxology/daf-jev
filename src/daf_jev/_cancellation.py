"""Recover cancellation evidence through supported exception chaining.

Python 3.10 Task boundaries can raise a fresh CancelledError whose context is
the original exception. Only cancellation/timeout normalization nodes are read,
and recovery stops at the nearest explicitly owned cancellation boundary.
Receipts remain observer-owned; unrelated handled exceptions are never searched.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

_OWNED_CANCELLATION = object()


def mark_cancellation(error: asyncio.CancelledError) -> None:
    """Mark the cancellation caught by the current owned request/workflow.

    Mark even a cancellation with no partial work. Its context can contain a
    previously handled request's cancellation and must not supply evidence.
    """
    error.__dict__["_dafjev_owned_cancellation"] = _OWNED_CANCELLATION


def _normalization_chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while isinstance(current, (asyncio.CancelledError, asyncio.TimeoutError)):
        if id(current) in seen:
            return
        seen.add(id(current))
        yield current
        if current.__dict__.get("_dafjev_owned_cancellation") is _OWNED_CANCELLATION:
            return
        # wait_for explicitly chains its timeout from the canceled task. Its
        # incidental context can instead be an earlier handled request.
        # Python 3.10 Task cancellation wrappers retain the original in context.
        current = current.__cause__ if isinstance(current, asyncio.TimeoutError) else current.__context__


def original_cancellation(error: asyncio.CancelledError) -> asyncio.CancelledError:
    """Return the nearest owned cancellation, otherwise the supplied error."""
    for current in _normalization_chain(error):
        if (isinstance(current, asyncio.CancelledError) and
                current.__dict__.get("_dafjev_owned_cancellation") is _OWNED_CANCELLATION):
            return current
    return error


def cancellation_workflow(error: BaseException) -> dict[str, Any] | None:
    """Read direct failure work or the nearest owned cancellation's work.

    Arbitrary Exception contexts/causes are not traversed. A marked current
    cancellation with no workflow terminates recovery rather than borrowing a
    previously handled cancellation's work.
    """
    if not isinstance(error, (asyncio.CancelledError, asyncio.TimeoutError)):
        record = error.__dict__.get("dafjev_workflow")
        return record if isinstance(record, dict) else None
    for current in _normalization_chain(error):
        if current.__dict__.get("_dafjev_owned_cancellation") is _OWNED_CANCELLATION:
            record = current.__dict__.get("dafjev_workflow")
            return record if isinstance(record, dict) else None
    return None
