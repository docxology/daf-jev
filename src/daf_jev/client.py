"""JevClient / AsyncJevClient: the public HTTP surface for the TypeSafe
Jev (System One) API.

Retry policy and the default request timeout resolve from the environment
(``config.resolve_retry`` / ``config.resolve_timeout``) unless passed
explicitly. ``ask`` additionally accepts a per-call ``timeout`` override and
extra ``request_headers`` merged over the defaults for that call only.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import time
from typing import Any, Callable, Mapping, Optional

import httpx

from daf_jev._errors import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
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

__all__ = ["ModelCard", "JevClient", "AsyncJevClient"]

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
    description: Optional[str] = None
    release_date: Optional[str] = None


def _body_of(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        text = response.text
        return text if text else None


def _retry_after_of(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
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
        api_key: Optional[str],
        *,
        base_url: Optional[str],
        model: str,
        transport: Optional[Any],
        retry: Optional[RetryPolicy],
        timeout: Optional[float],
        env: Optional[Mapping[str, str]],
    ) -> None:
        # Lazy import: config.py is a sibling module built concurrently;
        # importing lazily keeps this module importable mid-build and only
        # pays for it when environment resolution is needed.
        from daf_jev import config

        self._retry = retry if retry is not None else config.resolve_retry(env)
        self._timeout = (
            timeout if timeout is not None else config.resolve_timeout(env)
        )
        self._transport = transport
        self._closed = False
        if api_key is None:
            api_key = config.resolve_api_key(env)
        self._api_key = api_key
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
        self._model = model


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
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        model: str = "jev-latest",
        transport: Optional[Transport] = None,
        retry: Optional[RetryPolicy] = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
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
        self, send: Callable[[], httpx.Response], timeout: Optional[float] = None
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
            except httpx.TransportError as exc:
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
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        request_headers: Optional[Mapping[str, str]] = None,
    ) -> SystemOneResponse:
        """Answer named questions about the given state in a single POST.

        ``timeout`` overrides the client default for this call only;
        ``request_headers`` are merged over the default headers for this
        call only (per-call entries win).
        """
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
        response = self._send_with_retries(
            lambda: self._transport.post_json(
                SYSTEM_ONE_PATH, body, headers, timeout=timeout
            ),
            timeout=timeout,
        )
        return self._parse_system_one(response)

    def models(self) -> list[ModelCard]:
        """List the models available to the account."""
        getter = getattr(self._transport, "get_json", None)
        if getter is None:
            raise TypeSafeError(
                "the injected transport does not support model listing "
                "(no get_json method)"
            )
        response = self._send_with_retries(
            lambda: getter(MODELS_PATH, self._request_headers())
        )
        return _parse_models(_body_of(response))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def __enter__(self) -> "JevClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AsyncJevClient(_BaseClient):
    """Asynchronous client for the TypeSafe Jev (System One) API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        model: str = "jev-latest",
        transport: Optional[AsyncTransport] = None,
        retry: Optional[RetryPolicy] = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        timeout: Optional[float] = None,
        env: Optional[Mapping[str, str]] = None,
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
        self, send: Callable[[], Any], timeout: Optional[float] = None
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
            except httpx.TransportError as exc:
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
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        request_headers: Optional[Mapping[str, str]] = None,
    ) -> SystemOneResponse:
        """Answer named questions about the given state in a single POST.

        ``timeout`` overrides the client default for this call only;
        ``request_headers`` are merged over the default headers for this
        call only (per-call entries win).
        """
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
        response = await self._send_with_retries(
            lambda: self._transport.post_json(
                SYSTEM_ONE_PATH, body, headers, timeout=timeout
            ),
            timeout=timeout,
        )
        return self._parse_system_one(response)

    async def models(self) -> list[ModelCard]:
        """List the models available to the account."""
        getter = getattr(self._transport, "get_json", None)
        if getter is None:
            raise TypeSafeError(
                "the injected transport does not support model listing "
                "(no get_json method)"
            )
        response = await self._send_with_retries(
            lambda: getter(MODELS_PATH, self._request_headers())
        )
        return _parse_models(_body_of(response))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        result = self._transport.close()
        if inspect.isawaitable(result):
            await result

    async def __aenter__(self) -> "AsyncJevClient":
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
        cards.append(
            ModelCard(
                name=str(item["name"]),
                description=item.get("description"),
                release_date=item.get("release_date"),
            )
        )
    return cards
