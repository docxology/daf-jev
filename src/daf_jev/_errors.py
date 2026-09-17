"""Exception hierarchy mirroring the official TypeSafe SDK (JS-flavoured
names per docs/ARCHITECTURE.md). See docs/reference/sdk/python/api/
exceptions.md for the documented semantics.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Optional

__all__ = [
    "TypeSafeError",
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "UnprocessableEntityError",
    "RateLimitError",
    "OverloadedError",
    "InternalServerError",
    "error_from_status",
]


def _summarize_body(body: Any) -> str:
    if body is None:
        return "(empty body)"
    if isinstance(body, str):
        summary = body.strip()
        if not summary:
            return "(empty body)"
    else:
        try:
            summary = json.dumps(body)
        except (TypeError, ValueError):
            summary = str(body)
    if len(summary) > 300:
        summary = summary[:297] + "..."
    return summary


class TypeSafeError(Exception):
    """Base exception for all SDK failures."""


class APIConnectionError(TypeSafeError, ConnectionError):
    """A request failed without an HTTP response."""

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or "TypeSafe API connection error")


class APITimeoutError(APIConnectionError, TimeoutError):
    """A request exceeded its configured timeout."""

    def __init__(
        self, message: Optional[str] = None, *, timeout: Optional[float] = None
    ) -> None:
        if message is None:
            shown = "unknown" if timeout is None else f"{timeout}s"
            message = f"TypeSafe API request timed out after {shown}"
        super().__init__(message)
        self.timeout = timeout


class APIStatusError(TypeSafeError):
    """An unsuccessful HTTP response with its body and request metadata."""

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        status_code: int,
        body: Any = None,
        request_id: Optional[str] = None,
    ) -> None:
        if message is None:
            message = (
                f"TypeSafe API error (HTTP {status_code}): "
                f"{_summarize_body(body)}"
            )
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.request_id = request_id


class _HTTPStatusError(APIStatusError):
    """Shared plumbing for status-specific subclasses."""

    _STATUS: ClassVar[int] = 0
    _LABEL: ClassVar[str] = "error"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        status_code: Optional[int] = None,
        body: Any = None,
        request_id: Optional[str] = None,
    ) -> None:
        code = self._STATUS if status_code is None else status_code
        if message is None:
            message = (
                f"TypeSafe API {self._LABEL} error (HTTP {code}): "
                f"{_summarize_body(body)}"
            )
        super().__init__(
            message, status_code=code, body=body, request_id=request_id
        )


class BadRequestError(_HTTPStatusError):
    """The request was invalid (400)."""

    _STATUS = 400
    _LABEL = "bad request"


class AuthenticationError(_HTTPStatusError):
    """Authentication failed (401)."""

    _STATUS = 401
    _LABEL = "authentication"


class PermissionDeniedError(_HTTPStatusError):
    """Access was denied (403)."""

    _STATUS = 403
    _LABEL = "permission denied"


class NotFoundError(_HTTPStatusError):
    """The resource was not found (404)."""

    _STATUS = 404
    _LABEL = "not found"


class UnprocessableEntityError(_HTTPStatusError):
    """The request failed server validation (422)."""

    _STATUS = 422
    _LABEL = "unprocessable entity"


class RateLimitError(_HTTPStatusError):
    """The rate limit was exceeded (429)."""

    _STATUS = 429
    _LABEL = "rate limit"


class OverloadedError(_HTTPStatusError):
    """The server is overloaded (529)."""

    _STATUS = 529
    _LABEL = "overloaded"


class InternalServerError(_HTTPStatusError):
    """The server failed to process the request (5xx)."""

    _STATUS = 500
    _LABEL = "internal server error"


_EXACT_STATUS_ERRORS: dict[int, type[_HTTPStatusError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    422: UnprocessableEntityError,
    429: RateLimitError,
    529: OverloadedError,
}


def error_from_status(
    status_code: int, body: Any = None, request_id: Optional[str] = None
) -> Optional[APIStatusError]:
    """Map an HTTP status to the matching APIStatusError subclass.

    Returns None for non-error statuses (< 400). Unmapped 5xx codes map to
    InternalServerError; any other unmapped error status maps to the generic
    APIStatusError.
    """
    if not isinstance(status_code, int) or status_code < 400:
        return None
    cls = _EXACT_STATUS_ERRORS.get(status_code)
    if cls is None and 500 <= status_code <= 599:
        cls = InternalServerError
    if cls is None:
        return APIStatusError(
            f"TypeSafe API error (HTTP {status_code}): {_summarize_body(body)}",
            status_code=status_code,
            body=body,
            request_id=request_id,
        )
    return cls(status_code=status_code, body=body, request_id=request_id)
