"""HTTP transports. The ``Transport``/``AsyncTransport`` protocols are the
client-facing contract (``post_json`` + ``close``); the httpx
implementations additionally expose ``get_json`` for the models listing.
``post_json`` accepts an optional per-call ``timeout`` (seconds; ``None``
keeps the transport's configured default).
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Mapping, Optional, Protocol, Type, runtime_checkable

import httpx

__all__ = [
    "Transport",
    "HttpxTransport",
    "AsyncTransport",
    "AsyncHttpxTransport",
]


@runtime_checkable
class Transport(Protocol):
    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: Optional[float] = None,
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
        timeout: Optional[float] = None,
    ) -> httpx.Response: ...

    async def close(self) -> None: ...


class HttpxTransport:
    """Synchronous httpx transport implementing ``Transport``."""

    def __init__(
        self,
        base_url: str,
        timeout: Optional[float] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        kwargs: dict[str, Any] = {"base_url": base_url}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if headers:
            kwargs["headers"] = dict(headers)
        self._client = httpx.Client(**kwargs)

    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: Optional[float] = None,
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

    def __enter__(self) -> "HttpxTransport":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()


class AsyncHttpxTransport:
    """Asynchronous httpx transport implementing ``AsyncTransport``."""

    def __init__(
        self,
        base_url: str,
        timeout: Optional[float] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        kwargs: dict[str, Any] = {"base_url": base_url}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if headers:
            kwargs["headers"] = dict(headers)
        self._client = httpx.AsyncClient(**kwargs)

    async def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: Optional[float] = None,
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

    async def __aenter__(self) -> "AsyncHttpxTransport":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()
