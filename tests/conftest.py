"""Shared fixtures for the daf-jev test suite.

Template "no-mock" convention: daf_jev internals are NEVER patched or
monkeypatched. The network stand-in is a REAL local HTTP server
(http.server.ThreadingHTTPServer on 127.0.0.1, ephemeral port) with
programmable responses and per-request hit recording. Tests drive the real
HttpxTransport/JevClient through it.

Only stdlib + httpx are used here; the project `.env` is never read.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


class StubTypeSafeServer:
    """Programmable local stand-in for https://api.typesafe.ai.

    - ``enqueue(status, body=..., text=..., headers=..., delay=...)`` queues a
      response program; each incoming request pops the next program (an empty
      program means 200 with ``{}``).
    - ``set_delay(seconds)`` delays every response (for timeout tests).
    - ``hits`` records one dict per request:
      ``{method, path, headers (lower-cased), body (raw str), json (parsed)}``.
      A malformed/non-JSON request body records ``json: None`` and answers
      with an immediate 400 text/plain response without consuming a queued
      program — the handler thread never dies on bad input.
    """

    def __init__(self) -> None:
        self.hits: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._queue: deque[dict[str, Any]] = deque()
        self._delay = 0.0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _respond(
                self,
                status: int,
                payload: bytes,
                content_type: str,
                headers: dict[str, str] | None = None,
            ) -> None:
                try:
                    self.send_response(status)
                    for key, value in (headers or {}).items():
                        self.send_header(key, str(value))
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client gave up (timeout tests); server thread just exits

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    parsed = json.loads(raw) if raw else None
                except ValueError:
                    # Malformed/non-JSON body: record the hit and answer 400
                    # instead of letting the exception kill the handler thread
                    # (which would leave the client with a connection reset).
                    # Queued programs stay untouched for the next request.
                    with outer._lock:
                        outer.hits.append(
                            {
                                "method": self.command,
                                "path": self.path,
                                "headers": {
                                    k.lower(): v for k, v in self.headers.items()
                                },
                                "body": raw.decode("utf-8", "replace") if raw else "",
                                "json": None,
                            }
                        )
                    self._respond(
                        400,
                        b"malformed request body: expected JSON",
                        "text/plain",
                    )
                    return
                with outer._lock:
                    program = outer._queue.popleft() if outer._queue else {}
                    outer.hits.append(
                        {
                            "method": self.command,
                            "path": self.path,
                            "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": raw.decode("utf-8", "replace") if raw else "",
                            "json": parsed,
                        }
                    )
                delay = program.get("delay")
                if delay is None:
                    delay = outer._delay
                if delay:
                    time.sleep(delay)
                status = program.get("status", 200)
                if "text" in program:
                    payload = program["text"].encode("utf-8")
                    content_type = program.get("content_type", "text/plain")
                else:
                    payload = json.dumps(program.get("body", {})).encode("utf-8")
                    content_type = "application/json"
                self._respond(status, payload, content_type, program.get("headers"))

            def do_GET(self) -> None:
                self._handle()

            def do_POST(self) -> None:
                self._handle()

            def log_message(self, format: str, *args: Any) -> None:
                pass  # keep pytest output clean

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="stub-typesafe-server"
        )
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def enqueue(
        self,
        status: int = 200,
        body: Any = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        delay: float | None = None,
        content_type: str | None = None,
    ) -> None:
        """Queue the next response program.

        ``body`` is JSON-encoded (default ``{}``); ``text`` replaces it with a
        raw payload; ``headers`` adds response headers (e.g. ``Retry-After`` or
        ``x-typesafe-request-id``); ``delay`` sleeps before responding.
        """
        program: dict[str, Any] = {"status": status, "headers": headers, "delay": delay}
        if text is not None:
            program["text"] = text
            if content_type:
                program["content_type"] = content_type
        elif body is not None:
            program["body"] = body
        with self._lock:
            self._queue.append(program)

    def set_delay(self, seconds: float) -> None:
        """Delay every response by ``seconds`` (per-program delay wins)."""
        with self._lock:
            self._delay = seconds

    def reset(self) -> None:
        with self._lock:
            self._queue.clear()
            self.hits.clear()
            self._delay = 0.0

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture(scope="module")
def stub():
    """Module-scoped stub server; state is reset before every test."""
    server = StubTypeSafeServer()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def _fresh_stub(stub):
    """Guarantee per-test isolation of queued programs, hits, and delays."""
    stub.reset()
    return stub
