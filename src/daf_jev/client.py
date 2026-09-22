"""JevClient / AsyncJevClient: the public HTTP surface for the TypeSafe
Jev (System One) API.

Retry policy and the default request timeout resolve from the environment
(``config.resolve_retry`` / ``config.resolve_timeout``) unless passed
explicitly; the default model resolves from ``JEV_MODEL`` /
``TYPESAFE_DEFAULT_MODEL`` (falling back to ``jev-latest``) unless passed
explicitly. ``ask`` additionally accepts a per-call ``timeout`` override and
extra ``request_headers`` merged over the defaults for that call only.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from daf_jev._errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    TypeSafeError,
    error_from_status,
)
from daf_jev._http import AsyncHttpxTransport, AsyncTransport, HttpxTransport, Transport
from daf_jev._retry import RetryPolicy
from daf_jev._types import (
    JSONContent,
    Question,
    SystemOneResponse,
    parse_response,
)

__all__ = ["AsyncJevClient", "JevClient", "ModelCard"]

REQUEST_ID_HEADER = "x-typesafe-request-id"
SYSTEM_ONE_PATH = "/v1/systemone"
# Assumption: the docs snapshot documents the Models resource and the
# ModelMetadata shape (name, description, release_date) but not the HTTP
# path, so per the contract we use the conventional REST listing path.
MODELS_PATH = "/v1/models"


@dataclasses.dataclass(frozen=True)
class ModelCard:
    """One entry of the models listing (per ModelMetadata in the snapshot)."""

    name: str
    description: str | None = None
    release_date: str | None = None


def _body_of(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        text = response.text
        return text if text else None


_MAX_RETRY_AFTER_SECONDS = 300.0


def _clamp_retry_after(seconds: float) -> float:
    """Clamp a server-provided delay to [0, 300] seconds.

    A hostile ``inf``/``1e9`` header must not stall the retry loop; NaN is
    treated as 0.
    """
    if math.isnan(seconds):
        return 0.0
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _retry_after_of(response: httpx.Response) -> float | None:
    """Seconds to wait before the retry, or ``None`` for exponential backoff.

    ``Retry-After-ms`` (integer milliseconds) wins when present, then the
    numeric ``Retry-After`` form; both are clamped to [0, 300] seconds. The
    HTTP-date ``Retry-After`` form is intentionally unsupported (parsing it
    requires a wall clock and ``RetryPolicy.next_delay`` is pure): it, like
    any unparseable value, falls back to exponential backoff.
    """
    milliseconds = response.headers.get("Retry-After-ms")
    if milliseconds is not None:
        with contextlib.suppress(ValueError):
            return _clamp_retry_after(float(milliseconds) / 1000.0)
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return _clamp_retry_after(float(value))
    except ValueError:
        return None  # HTTP-date Retry-After is not supported


def _question_to_wire(question: Any) -> dict:
    # Raw dicts are accepted alongside Question dataclasses (as in the
    # official SDK's system_one).
    if isinstance(question, dict):
        return dict(question)
    return question.to_wire()


class _BaseClient:
    """Shared setup and helpers for the sync and async clients."""

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str | None,
        model: str | None,
        transport: Any | None,
        retry: RetryPolicy | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> None:
        # config has no import cycle with this module; resolving retry/timeout
        # pays for the import when environment resolution is needed.
        import daf_jev.config as config

        self._retry = retry if retry is not None else config.resolve_retry(env)
        self._timeout = (
            timeout if timeout is not None else config.resolve_timeout(env)
        )
        self._transport = transport
        self._closed = False
        if api_key is None:
            api_key = config.resolve_api_key(env)
        if api_key is not None and not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key
        if model is None:
            model = config.resolve_model(env)
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        self._model = model
        if self._api_key is None and self._transport is None:
            raise TypeSafeError(
                "No API key found: pass api_key, set JEV_API_KEY (or "
                "TYPESAFE_API_KEY), or inject a transport."
            )
        if self._transport is None:
            self._transport = self._default_transport(
                base_url
                if base_url is not None
                else config.resolve_base_url(env)
            )


    def _default_transport(self, base_url: str) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def _request_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _raise_for_response(self, response: httpx.Response) -> None:
        request_id = response.headers.get(REQUEST_ID_HEADER)
        error = error_from_status(
            response.status_code, _body_of(response), request_id
        )
        if error is None:
            error = APIStatusError(
                f"TypeSafe API returned unexpected status "
                f"{response.status_code}: {_body_of(response)}",
                status_code=response.status_code,
                body=_body_of(response),
                request_id=request_id,
            )
        raise error

    def _parse_system_one(self, response: httpx.Response) -> SystemOneResponse:
        request_id = response.headers.get(REQUEST_ID_HEADER)
        return parse_response(_body_of(response), request_id)


class JevClient(_BaseClient):
    """Synchronous client for the TypeSafe Jev (System One) API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        transport: Transport | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            model=model,
            transport=transport,
            retry=retry,
            timeout=timeout,
            env=env,
        )
        self._sleep = sleep

    def _default_transport(self, base_url: str) -> HttpxTransport:
        return HttpxTransport(base_url=base_url, timeout=self._timeout)

    def _send_with_retries(
        self, send: Callable[[], httpx.Response], timeout: float | None = None
    ) -> httpx.Response:
        policy = self._retry
        attempt = 1
        while True:
            try:
                response = send()
            except httpx.TimeoutException as exc:
                raise APITimeoutError(
                    timeout=self._timeout if timeout is None else timeout
                ) from exc
            except httpx.HTTPError as exc:
                raise APIConnectionError(f"TypeSafe API connection error: {exc}") from exc
            except httpx.StreamError as exc:
                raise APIConnectionError(f"TypeSafe API connection error: {exc}") from exc
            if 200 <= response.status_code < 300:
                return response
            if (
                response.status_code in policy.retryable_statuses
                and attempt < policy.max_attempts
            ):
                retry_after = (
                    _retry_after_of(response)
                    if policy.respect_retry_after
                    else None
                )
                self._sleep(policy.next_delay(attempt, retry_after))
                attempt += 1
                continue
            self._raise_for_response(response)

    def ask(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        timeout: float | None = None,
        request_headers: Mapping[str, str] | None = None,
    ) -> SystemOneResponse:
        """Answer named questions about the given state in a single POST.

        ``timeout`` overrides the client default for this call only;
        ``request_headers`` are merged over the default headers for this
        call only (per-call entries win).
        """
        if self._closed:
            raise TypeSafeError("client is closed")
        if not questions:
            raise TypeSafeError("questions must be a nonempty mapping")
        body = {
            "state": state,
            "model": model if model is not None else self._model,
            "questions": {
                qid: _question_to_wire(q) for qid, q in questions.items()
            },
        }
        headers = self._request_headers()
        if request_headers:
            headers.update(request_headers)
        transport = self._transport
        assert transport is not None  # set in __init__
        response = self._send_with_retries(
            lambda: transport.post_json(
                SYSTEM_ONE_PATH, body, headers, timeout=timeout
            ),
            timeout=timeout,
        )
        return self._parse_system_one(response)

    def models(
        self,
        *,
        timeout: float | None = None,
        request_headers: Mapping[str, str] | None = None,
    ) -> list[ModelCard]:
        """List the models available to the account.

        ``timeout`` overrides the client default for this call only;
        ``request_headers`` are merged over the default headers for this
        call only (per-call entries win). Retries per the configured
        policy, like ``ask``.
        """
        if self._closed:
            raise TypeSafeError("client is closed")
        getter = getattr(self._transport, "get_json", None)
        if getter is None:
            raise TypeSafeError(
                "the injected transport does not support model listing "
                "(no get_json method)"
            )
        headers = self._request_headers()
        if request_headers:
            headers.update(request_headers)
        response = self._send_with_retries(
            lambda: getter(MODELS_PATH, headers, timeout=timeout), timeout=timeout
        )
        return _parse_models(_body_of(response))

    def close(self) -> None:
        if self._closed:
            return
        transport = self._transport
        assert transport is not None  # set in __init__
        transport.close()
        self._closed = True

    def __enter__(self) -> JevClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AsyncJevClient(_BaseClient):
    """Asynchronous client for the TypeSafe Jev (System One) API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        transport: AsyncTransport | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            api_key,
            base_url=base_url,
            model=model,
            transport=transport,
            retry=retry,
            timeout=timeout,
            env=env,
        )
        self._sleep = sleep

    def _default_transport(self, base_url: str) -> AsyncHttpxTransport:
        return AsyncHttpxTransport(base_url=base_url, timeout=self._timeout)

    async def _send_with_retries(
        self, send: Callable[[], Any], timeout: float | None = None
    ) -> httpx.Response:
        policy = self._retry
        attempt = 1
        while True:
            try:
                response = await send()
            except httpx.TimeoutException as exc:
                raise APITimeoutError(
                    timeout=self._timeout if timeout is None else timeout
                ) from exc
            except httpx.HTTPError as exc:
                raise APIConnectionError(f"TypeSafe API connection error: {exc}") from exc
            except httpx.StreamError as exc:
                raise APIConnectionError(f"TypeSafe API connection error: {exc}") from exc
            if 200 <= response.status_code < 300:
                return response
            if (
                response.status_code in policy.retryable_statuses
                and attempt < policy.max_attempts
            ):
                retry_after = (
                    _retry_after_of(response)
                    if policy.respect_retry_after
                    else None
                )
                result = self._sleep(policy.next_delay(attempt, retry_after))
                if inspect.isawaitable(result):
                    await result
                attempt += 1
                continue
            self._raise_for_response(response)

    async def ask(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        timeout: float | None = None,
        request_headers: Mapping[str, str] | None = None,
    ) -> SystemOneResponse:
        """Answer named questions about the given state in a single POST.

        ``timeout`` overrides the client default for this call only;
        ``request_headers`` are merged over the default headers for this
        call only (per-call entries win).
        """
        if self._closed:
            raise TypeSafeError("client is closed")
        if not questions:
            raise TypeSafeError("questions must be a nonempty mapping")
        body = {
            "state": state,
            "model": model if model is not None else self._model,
            "questions": {
                qid: _question_to_wire(q) for qid, q in questions.items()
            },
        }
        headers = self._request_headers()
        if request_headers:
            headers.update(request_headers)
        transport = self._transport
        assert transport is not None  # set in __init__
        response = await self._send_with_retries(
            lambda: transport.post_json(
                SYSTEM_ONE_PATH, body, headers, timeout=timeout
            ),
            timeout=timeout,
        )
        return self._parse_system_one(response)

    async def models(
        self,
        *,
        timeout: float | None = None,
        request_headers: Mapping[str, str] | None = None,
    ) -> list[ModelCard]:
        """List the models available to the account.

        ``timeout`` overrides the client default for this call only;
        ``request_headers`` are merged over the default headers for this
        call only (per-call entries win). Retries per the configured
        policy, like ``ask``.
        """
        if self._closed:
            raise TypeSafeError("client is closed")
        getter = getattr(self._transport, "get_json", None)
        if getter is None:
            raise TypeSafeError(
                "the injected transport does not support model listing "
                "(no get_json method)"
            )
        headers = self._request_headers()
        if request_headers:
            headers.update(request_headers)
        response = await self._send_with_retries(
            lambda: getter(MODELS_PATH, headers, timeout=timeout), timeout=timeout
        )
        return _parse_models(_body_of(response))

    async def close(self) -> None:
        if self._closed:
            return
        transport = self._transport
        assert transport is not None  # set in __init__
        result = transport.close()
        if inspect.isawaitable(result):
            await result
        self._closed = True

    async def __aenter__(self) -> AsyncJevClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()


def _parse_models(payload: Any) -> list[ModelCard]:
    # Assumption (see MODELS_PATH): {"models": [{name, description,
    # release_date}, ...]}; a bare top-level list is also accepted.
    items = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(
            "models response must contain a list of models, got "
            f"{type(items).__name__}"
        )
    cards: list[ModelCard] = []
    for item in items:
        if not isinstance(item, dict) or "name" not in item:
            raise ValueError(f"invalid model entry: {item!r}")
        name = item["name"]
        if not isinstance(name, str):
            raise ValueError(
                f"invalid model entry: 'name' must be a string, got {name!r}"
            )
        description = item.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError(
                f"invalid model entry: 'description' must be a string or "
                f"null, got {description!r}"
            )
        release_date = item.get("release_date")
        if release_date is not None and not isinstance(release_date, str):
            raise ValueError(
                f"invalid model entry: 'release_date' must be a string or "
                f"null, got {release_date!r}"
            )
        cards.append(
            ModelCard(name=name, description=description, release_date=release_date)
        )
    return cards
