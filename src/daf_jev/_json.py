"""Decode response JSON without silently discarding ambiguous values."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from decimal import Decimal, DecimalException
from typing import Any, NoReturn


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("non-finite JSON constant")


def strict_json_loads(
    value: str | bytes | bytearray, *, parse_float: Callable[[str], Any] = float
) -> Any:
    """Preserve insertion order and reject duplicate keys at every depth.

    Nonstandard NaN/Infinity constants and overflowing floating-point numbers
    are rejected. Decimal parsing preserves exact finite billing numbers;
    schema-specific numeric bounds remain the caller's responsibility.
    Never choose one of two purported charges or answers.
    """
    def number(literal: str) -> Any:
        result = parse_float(literal)
        if ((isinstance(result, float) and not math.isfinite(result))
                or (isinstance(result, Decimal) and not result.is_finite())):
            raise ValueError("JSON number must be finite")
        return result

    try:
        return json.loads(value, object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant, parse_float=number)
    except RecursionError as exc:
        # Callers finalize malformed-response receipts on ValueError. A hostile
        # nesting depth must reach that same path rather than strand a receipt.
        raise ValueError("JSON exceeds supported nesting depth") from exc
    except (DecimalException, OverflowError) as exc:
        raise ValueError("JSON number exceeds supported precision") from exc
