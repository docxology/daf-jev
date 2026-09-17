"""Unit tests for daf_jev.client over the real local HTTP stub.

The client talks to a real http.server on 127.0.0.1 through the real
HttpxTransport — no patching of daf_jev internals anywhere.
"""

from __future__ import annotations

import pytest
import asyncio

import daf_jev
from daf_jev import NoulQuestion, RetryPolicy, ScoreQuestion, ChoiceQuestion
from daf_jev._errors import (
    APITimeoutError,
    AuthenticationError,
    OverloadedError,
    RateLimitError,
    TypeSafeError,
    UnprocessableEntityError,
)


def _questions() -> dict:
    return {
        "billing": NoulQuestion(instructions="Is this about billing?"),
        "tone": ChoiceQuestion(
            instructions="What is the tone?", criteria={"calm": None, "angry": "hostile"}
        ),
        "severity": ScoreQuestion(instructions="Rate severity", criteria=["low", "high"]),
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
        "sleep": lambda _seconds: None,  # injected no-op sleep; never patch internals
        "retry": RetryPolicy(jitter=0.0),
    }
    kwargs.update(overrides)
    return daf_jev.JevClient(**kwargs)


def test_ask_happy_path(stub) -> None:
    stub.enqueue(
        body=_answers_body(), headers={"x-typesafe-request-id": "req-42"}
    )
    with _make_client(stub) as client:
        resp = client.ask("I was charged twice.", _questions())

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
    assert resp.request_id == "req-42"
    assert resp.usage.input_tokens == 120 and resp.usage.output_tokens == 45
    assert resp.nouls["billing"].noul == 0.87
    assert resp.choices["tone"].choice == "angry"
    assert resp.scores["severity"].score == 0.4


def test_ask_retry_then_success_after_429(stub) -> None:
    stub.enqueue(status=429, body={"error": "rate limited"}, headers={"Retry-After": "0"})
    stub.enqueue(body=_answers_body(), headers={"x-typesafe-request-id": "req-ok"})

    sleeps: list[float] = []
    client = _make_client(stub, sleep=sleeps.append)
    resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    client.close()

    assert len(stub.hits) == 2  # exactly one 429, then the 200
    assert resp.request_id == "req-ok"
    assert "billing" in resp.nouls


def test_ask_exhausted_retries_raises_rate_limit(stub) -> None:
    for _ in range(3):
        stub.enqueue(status=429, body={"error": "rate limited"})

    with _make_client(stub) as client:  # RetryPolicy(max_attempts=3)
        with pytest.raises(RateLimitError):
            client.ask("state", {"billing": NoulQuestion(instructions="q")})

    assert len(stub.hits) == 3


def test_ask_401_maps_to_authentication_error(stub) -> None:
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    with _make_client(stub) as client:
        with pytest.raises(AuthenticationError) as excinfo:
            client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert excinfo.value.status_code == 401


def test_ask_422_maps_to_unprocessable_entity_error(stub) -> None:
    stub.enqueue(status=422, body={"error": {"message": "invalid question"}})
    with _make_client(stub) as client:
        with pytest.raises(UnprocessableEntityError):
            client.ask("state", {"billing": NoulQuestion(instructions="q")})


def test_ask_529_maps_to_overloaded_error(stub) -> None:
    # 529 is retryable (default max_attempts=3): exhaust all three attempts.
    for _ in range(3):
        stub.enqueue(status=529, body={"error": {"message": "overloaded"}})
    with _make_client(stub) as client:
        with pytest.raises(OverloadedError):
            client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert len(stub.hits) == 3


def test_tiny_timeout_raises_api_timeout_error(stub) -> None:
    stub.set_delay(0.5)  # handler sleeps; the 0.05s client timeout fires first
    client = _make_client(
        stub, timeout=0.05, retry=RetryPolicy(max_attempts=1, jitter=0.0)
    )
    try:
        with pytest.raises(APITimeoutError):
            client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()


def test_models_happy_path(stub) -> None:
    stub.enqueue(
        body={
            "models": [
                {"name": "jev-latest", "description": "current", "release_date": "2026-01-01"},
                {"name": "jev-stable", "description": "stable", "release_date": "2025-06-01"},
            ]
        },
        headers={"x-typesafe-request-id": "req-models"},
    )
    with _make_client(stub) as client:
        cards = client.models()

    assert len(stub.hits) == 1
    hit = stub.hits[0]
    assert hit["method"] == "GET"
    assert hit["path"] == "/v1/models"
    assert hit["headers"]["authorization"] == "Bearer test-key"
    assert [card.name for card in cards] == ["jev-latest", "jev-stable"]
    assert all(card.description and card.release_date for card in cards)


def test_missing_key_raises_with_empty_env_mapping(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # isolated cwd: no .env file to fall back to
    with pytest.raises((TypeSafeError, ValueError)):
        daf_jev.JevClient(env={})


def test_context_manager_support(stub) -> None:
    stub.enqueue(
        body=_answers_body(), headers={"x-typesafe-request-id": "req-ctx"}
    )
    with _make_client(stub) as client:
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert resp.request_id == "req-ctx"


def test_transport_close_releases_connection(stub) -> None:
    from daf_jev._http import HttpxTransport

    stub.enqueue(body=_answers_body())
    transport = HttpxTransport(base_url=stub.base_url, timeout=5.0, headers={})
    transport.post_json("/v1/systemone", {}, {"Authorization": "Bearer test-key"})
    transport.close()
    # A closed httpx.Client refuses further requests.
    with pytest.raises(Exception):
        transport.post_json("/v1/systemone", {}, {})
    assert len(stub.hits) == 1


# ------------------------------- per-call timeout and request header overrides


def test_ask_per_call_timeout_tightens_default(stub) -> None:
    # Constructor timeout (5.0s) is generous relative to the 0.5s stub delay;
    # the per-call 0.05s timeout wins for this call only.
    stub.set_delay(0.5)
    with _make_client(stub, timeout=5.0) as client:
        with pytest.raises(APITimeoutError):
            client.ask(
                "state",
                {"billing": NoulQuestion(instructions="q")},
                timeout=0.05,
            )
        stub.reset()  # clears the delay; the next call finishes well within 5.0s
        stub.enqueue(body=_answers_body())
        resp = client.ask(
            "state",
            {"billing": NoulQuestion(instructions="q")},
            timeout=5.0,
        )
    assert resp.nouls["billing"].noul == pytest.approx(0.87)


def test_ask_per_call_timeout_loosens_default(stub) -> None:
    # Constructor timeout (0.05s) times out against the 0.5s stub delay; the
    # per-call 5.0s timeout completes the same call.
    stub.set_delay(0.5)
    with _make_client(stub, timeout=0.05) as client:
        with pytest.raises(APITimeoutError):
            client.ask("state", {"billing": NoulQuestion(instructions="q")})
        stub.reset()
        stub.enqueue(body=_answers_body())
        resp = client.ask(
            "state",
            {"billing": NoulQuestion(instructions="q")},
            timeout=5.0,
        )
    assert "billing" in resp.answers


def test_ask_request_headers_merge_with_defaults(stub) -> None:
    with _make_client(stub) as client:
        stub.enqueue(body=_answers_body())
        client.ask(
            "state",
            _questions(),
            request_headers={
                "X-Experiment": "wave-a",
                "Content-Type": "application/custom+json",
                "Authorization": "Bearer per-call-key",
            },
        )
        headers = stub.hits[-1]["headers"]
        assert headers["x-experiment"] == "wave-a"
        assert headers["content-type"] == "application/custom+json"
        assert headers["authorization"] == "Bearer per-call-key"

        # No request_headers argument: defaults only.
        stub.enqueue(body=_answers_body())
        client.ask("state", _questions())
        headers = stub.hits[-1]["headers"]
        assert "x-experiment" not in headers
        assert headers["content-type"] == "application/json"
        assert headers["authorization"] == "Bearer test-key"


def test_async_ask_per_call_timeout_and_headers(stub) -> None:
    client = daf_jev.AsyncJevClient(
        api_key="test-key",
        base_url=stub.base_url,
        retry=RetryPolicy(jitter=0.0),
        timeout=5.0,
    )

    async def scenario():
        try:
            stub.set_delay(0.5)
            with pytest.raises(APITimeoutError):
                await client.ask(
                    "state",
                    {"billing": NoulQuestion(instructions="q")},
                    timeout=0.05,
                )
            stub.reset()  # clears the delay for the comfortable second call
            stub.enqueue(body=_answers_body())
            return await client.ask(
                "state",
                {"billing": NoulQuestion(instructions="q")},
                timeout=5.0,
                request_headers={"X-Experiment": "async"},
            )
        finally:
            # The transport's connections are bound to this loop: close here,
            # like the rest of the async suite, never from a fresh loop.
            await client.close()

    stub.reset()
    resp = asyncio.run(scenario())
    assert stub.hits[-1]["headers"]["x-experiment"] == "async"
    assert "billing" in resp.answers


# ----------------------------------------- env-resolved retry/timeout defaults


def test_retry_resolved_from_env_when_not_explicit(stub, monkeypatch) -> None:
    # Two env-configured attempts: both 429s exhaust the policy after 2 hits;
    # a default policy (3 attempts) would need a third.
    monkeypatch.setenv("JEV_MAX_ATTEMPTS", "2")
    for _ in range(2):
        stub.enqueue(
            status=429,
            body={"error": {"message": "rate limited"}},
            headers={"Retry-After": "0"},
        )
    client = _make_client(stub, retry=None)  # retry=None -> config.resolve_retry(env)
    with pytest.raises(RateLimitError):
        client.ask("state", _questions())
    assert len(stub.hits) == 2


def test_explicit_retry_beats_env(stub, monkeypatch) -> None:
    # JEV_MAX_ATTEMPTS=1 would exhaust on the first 429; the explicit default
    # policy (3 attempts) retries through to the queued success.
    monkeypatch.setenv("JEV_MAX_ATTEMPTS", "1")
    stub.enqueue(
        status=429, body={"error": {"message": "rate limited"}}, headers={"Retry-After": "0"}
    )
    stub.enqueue(
        status=429, body={"error": {"message": "rate limited"}}, headers={"Retry-After": "0"}
    )
    stub.enqueue(body=_answers_body())
    client = _make_client(stub)  # explicit RetryPolicy(jitter=0.0), max_attempts=3
    resp = client.ask("state", _questions())
    assert len(stub.hits) == 3
    assert "billing" in resp.answers


def test_timeout_resolved_from_env_when_not_explicit(stub, monkeypatch) -> None:
    monkeypatch.setenv("JEV_TIMEOUT", "0.05")
    stub.set_delay(0.5)
    client = _make_client(stub, timeout=None)  # timeout=None -> resolve_timeout(env)
    with pytest.raises(APITimeoutError):
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    client.close()


def test_explicit_timeout_beats_env(stub, monkeypatch) -> None:
    monkeypatch.setenv("JEV_TIMEOUT", "0.05")
    stub.set_delay(0.5)
    stub.enqueue(body=_answers_body())
    client = _make_client(stub, timeout=5.0)  # explicit arg wins over the env
    resp = client.ask("state", _questions())  # env timeout would have fired
    client.close()
    assert "billing" in resp.answers

