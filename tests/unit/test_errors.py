"""Unit tests for daf_jev._errors: status -> exception mapping and hierarchy."""

from __future__ import annotations

import pytest

from daf_jev._errors import (
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
    TypeSafeError,
    UnprocessableEntityError,
    error_from_status,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (529, OverloadedError),
        (500, InternalServerError),
        (503, InternalServerError),
    ],
)
def test_error_from_status_mapping(status: int, expected: type) -> None:
    body = {"error": {"message": "boom"}}
    err = error_from_status(status, body, "req-1")
    assert isinstance(err, expected)
    assert isinstance(err, APIStatusError)
    assert isinstance(err, TypeSafeError)
    assert err.status_code == status
    assert err.body == body
    assert err.request_id == "req-1"


def test_error_from_status_200_is_none() -> None:
    assert error_from_status(200, {"ok": True}, "req-2") is None



def test_status_error_default_message_names_status_and_body() -> None:
    err = APIStatusError(status_code=418, body={"teapot": True})
    assert "HTTP 418" in str(err)
    assert "teapot" in str(err)
    assert err.status_code == 418


def test_status_error_missing_or_blank_body_summarizes_as_empty() -> None:
    assert "(empty body)" in str(APIStatusError(status_code=500))
    assert "(empty body)" in str(APIStatusError(status_code=500, body="   \n"))


def test_status_error_unserializable_body_is_stringified() -> None:
    sentinel = object()
    err = APIStatusError(status_code=500, body=sentinel)
    assert str(sentinel) in str(err)


def test_status_error_long_body_is_truncated() -> None:
    err = APIStatusError(status_code=500, body="x" * 400)
    message = str(err)
    assert message.endswith("...")
    assert message.count("x") < 400


def test_error_from_status_unmapped_4xx_is_generic_api_status_error() -> None:
    err = error_from_status(418, {"teapot": True}, "req-9")
    assert type(err) is APIStatusError
    assert err.status_code == 418
    assert err.body == {"teapot": True}
    assert err.request_id == "req-9"


def test_error_from_status_non_integer_status_is_none() -> None:
    # Only real ints map; a string status (or None) yields no error at all.
    assert error_from_status("500", {"error": "boom"}, "req-1") is None
    assert error_from_status(None) is None


def test_error_from_status_5xx_boundaries() -> None:
    assert isinstance(error_from_status(599), InternalServerError)
    # 600 is outside the 5xx window: it falls back to the generic
    # APIStatusError rather than InternalServerError.
    err = error_from_status(600)
    assert type(err) is APIStatusError
    assert err.status_code == 600


def test_api_timeout_error_message_variants() -> None:
    from daf_jev._errors import APITimeoutError

    known = APITimeoutError(timeout=0.05)
    assert str(known) == "TypeSafe API request timed out after 0.05s"
    assert known.timeout == 0.05

    unknown = APITimeoutError()
    assert str(unknown) == "TypeSafe API request timed out after unknown"
    assert unknown.timeout is None

    custom = APITimeoutError("custom timeout text")
    assert str(custom) == "custom timeout text"

    # The timeout surfaces as both a TimeoutError and a ConnectionError.
    assert isinstance(known, TimeoutError)
    assert isinstance(known, ConnectionError)
