"""Unit tests for AsyncJevClient and AsyncHttpxTransport over the stub.

Same no-mock convention as test_client.py: the async client talks to a real
local HTTP server through the real AsyncHttpxTransport. Tests drive asyncio
via ``asyncio.run`` inside plain sync test functions (no plugins needed).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import daf_jev
from daf_jev import AsyncJevClient, NoulQuestion, RetryPolicy
from daf_jev._errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    TypeSafeError,
)


def _questions() -> dict:
    return {
        "billing": NoulQuestion(instructions="Is this about billing?"),
    }


def _answers_body() -> dict:
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": 120, "output_tokens": 45},
        "answers": {
            "billing": {"type": "noul", "noul": 0.87},
            "tone": {
                "type": "choice",
                "choice": "angry",
                "probabilities": {"calm": 0.2, "angry": 0.8},
                "confidence": 0.76,
            },
            "severity": {
                "type": "score",
                "score": 0.4,
                "legend": {"0": "low", "1": "high"},
                "probabilities": {"0": 0.6, "1": 0.4},
                "confidence": 0.9,
            },
        },
    }


def _make_client(stub, **overrides):
    kwargs = {
        "api_key": "test-key",
        "base_url": stub.base_url,
        "retry": RetryPolicy(jitter=0.0),
    }
    kwargs.update(overrides)
    return AsyncJevClient(**kwargs)


def test_ask_happy_path(stub) -> None:
    stub.enqueue(
        body=_answers_body(), headers={"x-typesafe-request-id": "req-async"}
    )

    async def main() -> None:
        async with _make_client(stub) as client:
            return await client.ask("I was charged twice.", _questions())

    resp = asyncio.run(main())

    assert len(stub.hits) == 1
    hit = stub.hits[0]
    assert hit["method"] == "POST"
    assert hit["path"] == "/v1/systemone"
    assert hit["headers"]["authorization"] == "Bearer test-key"
    assert hit["headers"]["content-type"] == "application/json"
    assert hit["json"] == {
        "state": "I was charged twice.",
        "model": "jev-latest",
        "questions": {qid: q.to_wire() for qid, q in _questions().items()},
    }

    assert resp.model == "jev-latest"
    assert resp.request_id == "req-async"
    assert resp.usage.input_tokens == 120 and resp.usage.output_tokens == 45
    # Typed views over the mixed answer dict.
    assert resp.nouls["billing"].noul == 0.87
    assert resp.choices["tone"].choice == "angry"
    assert resp.scores["severity"].score == 0.4


def test_ask_retries_after_429_then_succeeds(stub) -> None:
    stub.enqueue(
        status=429, body={"error": "rate limited"}, headers={"Retry-After": "0"}
    )
    stub.enqueue(body=_answers_body())
    sleeps: list[float] = []

    async def recorder(seconds: float) -> None:
        sleeps.append(seconds)

    async def main():
        client = _make_client(stub, sleep=recorder)
        try:
            return await client.ask("state", _questions())
        finally:
            await client.close()

    resp = asyncio.run(main())

    assert len(stub.hits) == 2
    assert sleeps == [0.0]  # server-requested Retry-After wins verbatim
    assert resp.request_id is None


def test_exhausted_429s_raise_rate_limit_error(stub) -> None:
    for _ in range(3):
        stub.enqueue(status=429, body={"error": "rate limited"})
    sleeps: list[float] = []

    async def recorder(seconds: float) -> None:
        sleeps.append(seconds)

    async def main():
        client = _make_client(stub, sleep=recorder)
        try:
            await client.ask("state", _questions())
        finally:
            await client.close()

    with pytest.raises(RateLimitError) as excinfo:
        asyncio.run(main())

    assert excinfo.value.status_code == 429
    assert len(stub.hits) == 3  # initial request + two retries, then raise
    assert sleeps == [0.5, 1.0]  # exponential backoff, jitter disabled


def test_ask_529_retries_then_succeeds(stub) -> None:
    # One 529 (retryable) followed by success: the retry path returns a
    # parsed response instead of raising.
    stub.enqueue(status=529, body={"error": {"message": "overloaded"}})
    stub.enqueue(
        body=_answers_body(), headers={"x-typesafe-request-id": "req-529-ok"}
    )
    sleeps: list[float] = []

    async def recorder(seconds: float) -> None:
        sleeps.append(seconds)

    async def main():
        client = _make_client(stub, sleep=recorder)
        try:
            return await client.ask("state", _questions())
        finally:
            await client.close()

    resp = asyncio.run(main())
    assert len(stub.hits) == 2
    assert sleeps == [0.5]  # exponential backoff, jitter disabled
    assert resp.request_id == "req-529-ok"


def test_ask_401_maps_to_authentication_error(stub) -> None:
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})

    async def main():
        client = _make_client(stub)
        try:
            await client.ask("state", _questions())
        finally:
            await client.close()

    with pytest.raises(AuthenticationError) as excinfo:
        asyncio.run(main())
    assert excinfo.value.status_code == 401


def test_connection_error_maps_to_api_connection_error(stub) -> None:
    async def main():
        # Nothing listens on port 1; the transport-level failure surfaces.
        client = AsyncJevClient(
            api_key="test-key",
            base_url="http://127.0.0.1:1",
            retry=RetryPolicy(max_attempts=1, jitter=0.0),
        )
        try:
            await client.ask("state", _questions())
        finally:
            await client.close()

    with pytest.raises(APIConnectionError):
        asyncio.run(main())


def test_tiny_timeout_raises_api_timeout_error(stub) -> None:
    stub.set_delay(0.5)  # handler sleeps; the 0.05s client timeout fires first

    async def main():
        client = _make_client(
            stub, timeout=0.05, retry=RetryPolicy(max_attempts=1, jitter=0.0)
        )
        try:
            await client.ask("state", _questions())
        finally:
            await client.close()

    with pytest.raises(APITimeoutError):
        asyncio.run(main())


def test_models_happy_path(stub) -> None:
    stub.enqueue(
        body={
            "models": [
                {
                    "name": "jev-latest",
                    "description": "current",
                    "release_date": "2026-01-01",
                },
                {
                    "name": "jev-stable",
                    "description": "stable",
                    "release_date": "2025-06-01",
                },
            ]
        },
        headers={"x-typesafe-request-id": "req-models"},
    )

    async def main():
        async with _make_client(stub) as client:
            return await client.models()

    cards = asyncio.run(main())

    assert len(stub.hits) == 1
    hit = stub.hits[0]
    assert hit["method"] == "GET"
    assert hit["path"] == "/v1/models"
    assert hit["headers"]["authorization"] == "Bearer test-key"
    assert [card.name for card in cards] == ["jev-latest", "jev-stable"]
    assert all(card.description and card.release_date for card in cards)


def test_models_rejects_payload_without_a_model_list(stub) -> None:
    stub.enqueue(body={})  # no "models" key: nothing list-shaped to parse

    async def main():
        client = _make_client(stub)
        try:
            await client.models()
        finally:
            await client.close()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(main())
    assert "must contain a list" in str(excinfo.value)


def test_models_rejects_entry_missing_name(stub) -> None:
    stub.enqueue(body={"models": [{"description": "no name here"}]})

    async def main():
        client = _make_client(stub)
        try:
            await client.models()
        finally:
            await client.close()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(main())
    assert "invalid model entry" in str(excinfo.value)


def _models_body() -> dict:
    return {
        "models": [
            {
                "name": "jev-latest",
                "description": "current",
                "release_date": "2026-01-01",
            }
        ]
    }


def test_models_per_call_timeout_tightens_default(stub) -> None:
    # Constructor timeout (5.0s) is generous relative to the 0.5s stub delay;
    # the per-call 0.05s timeout wins for this call only.
    stub.set_delay(0.5)
    stub.enqueue(body=_models_body())
    client = _make_client(stub, timeout=5.0)

    async def main():
        try:
            with pytest.raises(APITimeoutError):
                await client.models(timeout=0.05)
        finally:
            await client.close()

    asyncio.run(main())
    assert len(stub.hits) == 1


def test_models_per_call_timeout_none_keeps_constructor_default(stub) -> None:
    # An explicit per-call timeout=None must NOT be forwarded to httpx (where
    # it would mean "no timeout"): the constructor default still fires.
    stub.set_delay(0.5)
    stub.enqueue(body=_models_body())
    client = _make_client(stub, timeout=0.05)

    async def main():
        try:
            with pytest.raises(APITimeoutError):
                await client.models(timeout=None)
        finally:
            await client.close()

    asyncio.run(main())
    assert len(stub.hits) == 1


def test_models_request_headers_merge_with_defaults(stub) -> None:
    stub.enqueue(body=_models_body())
    client = _make_client(stub)

    async def main():
        try:
            await client.models(request_headers={"X-Experiment": "async-models"})
        finally:
            await client.close()

    asyncio.run(main())
    headers = stub.hits[-1]["headers"]
    assert headers["x-experiment"] == "async-models"
    assert headers["authorization"] == "Bearer test-key"
    assert headers["content-type"] == "application/json"


def test_async_context_manager_support(stub) -> None:
    stub.enqueue(body=_answers_body(), headers={"x-typesafe-request-id": "req-ctx"})

    async def main():
        async with _make_client(stub) as client:
            assert isinstance(client, AsyncJevClient)
            return await client.ask("state", _questions())

    resp = asyncio.run(main())
    assert resp.request_id == "req-ctx"


def test_ask_empty_questions_raises_without_hitting_the_wire(stub) -> None:
    async def main():
        client = _make_client(stub)
        try:
            await client.ask("state", {})
        finally:
            await client.close()

    with pytest.raises(TypeSafeError) as excinfo:
        asyncio.run(main())
    assert len(stub.hits) == 0  # rejected before any request is sent
    assert "nonempty" in str(excinfo.value)


def test_ask_after_close_raises(stub) -> None:
    stub.enqueue(body=_answers_body())

    async def main():
        client = _make_client(stub)
        await client.ask("state", _questions())
        await client.close()
        await client.close()  # closing twice is a no-op
        # The closed guard refuses further asks before any request is sent.
        await client.ask("state", _questions())

    with pytest.raises(TypeSafeError) as excinfo:
        asyncio.run(main())
    assert "closed" in str(excinfo.value)  # the client-level guard, not raw httpx
    assert len(stub.hits) == 1  # the guarded ask never reaches the wire


def test_transport_protocol_satisfied_by_async_httpx_transport(stub) -> None:
    from daf_jev._http import AsyncHttpxTransport, AsyncTransport

    transport = AsyncHttpxTransport(base_url=stub.base_url, timeout=5.0, headers={})
    assert isinstance(transport, AsyncTransport)

    async def main():
        await transport.post_json(
            "/v1/systemone", {}, {"Authorization": "Bearer test-key"}
        )
        await transport.close()
        # A closed httpx.AsyncClient refuses further requests.
        await transport.post_json("/v1/systemone", {}, {})

    with pytest.raises(RuntimeError):
        asyncio.run(main())
    assert len(stub.hits) == 1


def test_async_httpx_transport_get_json_via_context_manager(stub) -> None:
    from daf_jev._http import AsyncHttpxTransport

    stub.enqueue(
        body={
            "models": [
                {
                    "name": "jev-latest",
                    "description": "current",
                    "release_date": "2026-01-01",
                }
            ]
        }
    )

    async def main():
        async with AsyncHttpxTransport(
            base_url=stub.base_url, timeout=5.0
        ) as transport:
            return await transport.get_json("/v1/models", {"Authorization": "B k"})

    response = asyncio.run(main())
    assert response.status_code == 200
    assert [m["name"] for m in response.json()["models"]] == ["jev-latest"]
    assert stub.hits[0]["method"] == "GET"
    assert stub.hits[0]["headers"]["authorization"] == "B k"


def test_async_httpx_transport_default_timeout_is_60_seconds(stub) -> None:
    # httpx's own default is 5s; the transport must substitute the explicit
    # 60s default instead of letting slow LLM calls be capped silently.
    from daf_jev._http import DEFAULT_TIMEOUT_SECONDS, AsyncHttpxTransport

    transport = AsyncHttpxTransport(base_url=stub.base_url)

    async def main():
        await transport.close()

    asyncio.run(main())
    assert transport._client.timeout == httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)


def test_missing_key_raises_with_empty_env_mapping(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # isolated cwd: no .env file to fall back to
    with pytest.raises(daf_jev.TypeSafeError):
        AsyncJevClient(env={})
