"""HTTP transports. The ``Transport``/``AsyncTransport`` protocols are the
client-facing contract (``post_json`` + ``close``); the httpx
implementations additionally expose ``get_json`` for the models listing.
``post_json`` accepts an optional per-call ``timeout`` (seconds; ``None``
keeps the transport's configured default). A transport constructed without
a ``timeout`` passes :data:`DEFAULT_TIMEOUT_SECONDS` (60.0) to httpx
instead of letting httpx's own 5-second default silently cap slow LLM
calls.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

import httpx

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "AsyncHttpxTransport",
    "AsyncTransport",
    "HttpxTransport",
    "Transport",
]


@runtime_checkable
class Transport(Protocol):
    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response: ...

    def close(self) -> None: ...


@runtime_checkable
class AsyncTransport(Protocol):
    async def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response: ...

    async def close(self) -> None: ...


# httpx silently applies its own 5-second default when constructed without
# a timeout, capping slow LLM calls; the transports substitute this value
# so the effective default is explicit and generous.
DEFAULT_TIMEOUT_SECONDS: float = 60.0


def _normalize_base_url(base_url: str) -> str:
    """Ensure a base URL with a path component ends with ``/``.

    httpx merges the base path with the request path by concatenation, so
    ``https://x/api`` + ``/v1/systemone`` would produce ``/apiv1/...``; a
    trailing slash yields the intended ``/api/v1/...``. Host-only bases are
    unaffected.
    """
    parts = urllib.parse.urlsplit(base_url)
    path = parts.path
    if path and not path.endswith("/"):
        return urllib.parse.urlunsplit(parts._replace(path=path + "/"))
    return base_url


class HttpxTransport:
    """Synchronous httpx transport implementing ``Transport``."""

    def __init__(
        self,
        base_url: str,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "base_url": _normalize_base_url(base_url),
            "timeout": DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout,
        }
        if headers:
            kwargs["headers"] = dict(headers)
        self._client = httpx.Client(**kwargs)

    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        # httpx treats an explicit timeout=None as "no timeout", so only pass
        # the per-call override when set; otherwise the client default applies.
        if timeout is not None:
            return self._client.post(
                path, json=json_body, headers=headers, timeout=timeout
            )
        return self._client.post(path, json=json_body, headers=headers)

    def get_json(self, path: str, headers: dict[str, str]) -> httpx.Response:
        """GET used by the client's models listing (beyond the protocol)."""
        return self._client.get(path, headers=headers)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpxTransport:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class AsyncHttpxTransport:
    """Asynchronous httpx transport implementing ``AsyncTransport``."""

    def __init__(
        self,
        base_url: str,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "base_url": _normalize_base_url(base_url),
            "timeout": DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout,
        }
        if headers:
            kwargs["headers"] = dict(headers)
        self._client = httpx.AsyncClient(**kwargs)

    async def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        # httpx treats an explicit timeout=None as "no timeout", so only pass
        # the per-call override when set; otherwise the client default applies.
        if timeout is not None:
            return await self._client.post(
                path, json=json_body, headers=headers, timeout=timeout
            )
        return await self._client.post(path, json=json_body, headers=headers)

    async def get_json(self, path: str, headers: dict[str, str]) -> httpx.Response:
        """GET used by the client's models listing (beyond the protocol)."""
        return await self._client.get(path, headers=headers)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncHttpxTransport:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
