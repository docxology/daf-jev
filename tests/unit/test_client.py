"""Unit tests for daf_jev.client over the real local HTTP stub.

The client talks to a real http.server on 127.0.0.1 through the real
HttpxTransport — no patching of daf_jev internals anywhere.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import daf_jev
from daf_jev import ChoiceQuestion, NoulQuestion, RetryPolicy, ScoreQuestion
from daf_jev._errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OverloadedError,
    PermissionDeniedError,
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

    with _make_client(stub) as client, pytest.raises(RateLimitError):
        client.ask("state", {"billing": NoulQuestion(instructions="q")})

    assert len(stub.hits) == 3


def test_ask_401_maps_to_authentication_error(stub) -> None:
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    with _make_client(stub) as client, pytest.raises(AuthenticationError) as excinfo:
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert excinfo.value.status_code == 401


def test_ask_422_maps_to_unprocessable_entity_error(stub) -> None:
    stub.enqueue(status=422, body={"error": {"message": "invalid question"}})
    with _make_client(stub) as client, pytest.raises(UnprocessableEntityError):
        client.ask("state", {"billing": NoulQuestion(instructions="q")})


@pytest.mark.parametrize(
    ("status", "expected"),
    [(400, BadRequestError), (403, PermissionDeniedError), (404, NotFoundError)],
)
def test_ask_maps_exact_status_errors(stub, status: int, expected: type) -> None:
    stub.enqueue(status=status, body={"error": {"message": "nope"}})
    with _make_client(stub) as client, pytest.raises(expected) as excinfo:
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert excinfo.value.status_code == status
    assert excinfo.value.request_id is None  # no x-typesafe-request-id header


def test_ask_unmapped_418_raises_generic_api_status_error(stub) -> None:
    stub.enqueue(status=418, body={"error": "teapot"})
    with _make_client(stub) as client, pytest.raises(APIStatusError) as excinfo:
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert type(excinfo.value) is APIStatusError  # not a status-specific subclass
    assert excinfo.value.status_code == 418
    assert excinfo.value.body == {"error": "teapot"}


def test_ask_500_with_text_body_maps_to_internal_server_error(stub) -> None:
    # A non-JSON body falls back to the raw text; InternalServerError carries
    # it in .body instead of losing it.
    stub.enqueue(status=500, text="upstream exploded", content_type="text/plain")
    with _make_client(stub) as client, pytest.raises(InternalServerError) as excinfo:
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert excinfo.value.status_code == 500
    assert excinfo.value.body == "upstream exploded"
    assert "upstream exploded" in str(excinfo.value)


def test_connection_refused_maps_to_api_connection_error() -> None:
    # Nothing listens on port 1; the transport-level failure surfaces.
    client = daf_jev.JevClient(
        api_key="test-key",
        base_url="http://127.0.0.1:1",
        retry=RetryPolicy(max_attempts=1, jitter=0.0),
    )
    try:
        with pytest.raises(APIConnectionError):
            client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()


def test_ask_529_maps_to_overloaded_error(stub) -> None:
    # 529 is retryable (default max_attempts=3): exhaust all three attempts.
    for _ in range(3):
        stub.enqueue(status=529, body={"error": {"message": "overloaded"}})
    with _make_client(stub) as client, pytest.raises(OverloadedError):
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert len(stub.hits) == 3


def test_ask_529_retries_then_succeeds(stub) -> None:
    # One 529 (retryable) followed by success: the retry path returns a
    # parsed response instead of raising.
    stub.enqueue(status=529, body={"error": {"message": "overloaded"}})
    stub.enqueue(
        body=_answers_body(), headers={"x-typesafe-request-id": "req-after-529"}
    )
    sleeps: list[float] = []
    client = _make_client(stub, sleep=sleeps.append)
    resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    client.close()
    assert len(stub.hits) == 2
    assert sleeps == [0.5]  # exponential backoff, jitter disabled
    assert resp.request_id == "req-after-529"


def test_retry_after_http_date_falls_back_to_exponential_backoff(stub) -> None:
    # HTTP-date Retry-After is unsupported by design (parsing it needs a wall
    # clock): the client falls back to the exponential delay, never to 0.
    stub.enqueue(
        status=429,
        body={"error": "rate limited"},
        headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
    )
    stub.enqueue(body=_answers_body())
    sleeps: list[float] = []
    client = _make_client(stub, sleep=sleeps.append)
    resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    client.close()
    assert len(stub.hits) == 2
    assert sleeps == [0.5]
    assert "billing" in resp.answers


def test_retry_after_ms_header_wins_in_seconds(stub) -> None:
    stub.enqueue(
        status=429,
        body={"error": "rate limited"},
        headers={"Retry-After-ms": "250"},
    )
    stub.enqueue(body=_answers_body())
    sleeps: list[float] = []
    client = _make_client(stub, sleep=sleeps.append)
    client.ask("state", {"billing": NoulQuestion(instructions="q")})
    client.close()
    assert len(stub.hits) == 2
    assert sleeps == [0.25]  # 250 ms converted to seconds


def test_retry_after_hostile_value_capped_at_300(stub) -> None:
    stub.enqueue(
        status=429, body={"error": "rate limited"}, headers={"Retry-After": "1e9"}
    )
    stub.enqueue(body=_answers_body())
    sleeps: list[float] = []
    client = _make_client(stub, sleep=sleeps.append)
    client.ask("state", {"billing": NoulQuestion(instructions="q")})
    client.close()
    assert len(stub.hits) == 2
    assert sleeps == [300.0]  # clamped to [0, 300] seconds


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


def test_ask_per_call_timeout_none_keeps_constructor_default(stub) -> None:
    # An explicit per-call timeout=None must NOT be forwarded to httpx (where
    # it would mean "no timeout"): the constructor default still fires.
    stub.set_delay(0.5)
    with (
        _make_client(stub, timeout=0.05) as client,
        pytest.raises(APITimeoutError) as excinfo,
    ):
        client.ask(
            "state",
            {"billing": NoulQuestion(instructions="q")},
            timeout=None,
        )
    assert excinfo.value.timeout == 0.05
    assert len(stub.hits) == 1


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


def test_models_rejects_payload_without_a_model_list(stub) -> None:
    stub.enqueue(body={})  # no "models" key: nothing list-shaped to parse
    with _make_client(stub) as client, pytest.raises(ValueError) as excinfo:
        client.models()
    assert "must contain a list" in str(excinfo.value)


def test_models_rejects_entry_missing_name(stub) -> None:
    stub.enqueue(body={"models": [{"description": "no name here"}]})
    with _make_client(stub) as client, pytest.raises(ValueError) as excinfo:
        client.models()
    assert "invalid model entry" in str(excinfo.value)


def test_models_per_call_timeout_tightens_default(stub) -> None:
    # Constructor timeout (5.0s) is generous relative to the 0.5s stub delay;
    # the per-call 0.05s timeout wins for this call only.
    stub.set_delay(0.5)
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
    with _make_client(stub, timeout=5.0) as client, pytest.raises(APITimeoutError):
        client.models(timeout=0.05)
    assert len(stub.hits) == 1


def test_models_per_call_timeout_none_keeps_constructor_default(stub) -> None:
    # An explicit per-call timeout=None must NOT be forwarded to httpx (where
    # it would mean "no timeout"): the constructor default still fires.
    stub.set_delay(0.5)
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
    with _make_client(stub, timeout=0.05) as client, pytest.raises(APITimeoutError):
        client.models(timeout=None)
    assert len(stub.hits) == 1


def test_models_request_headers_merge_with_defaults(stub) -> None:
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
    with _make_client(stub) as client:
        client.models(request_headers={"X-Experiment": "models-a"})
    headers = stub.hits[-1]["headers"]
    assert headers["x-experiment"] == "models-a"
    assert headers["authorization"] == "Bearer test-key"
    assert headers["content-type"] == "application/json"


def test_models_requires_get_json_capable_transport(stub) -> None:
    # The Transport protocol only promises post_json/close; model listing
    # additionally needs get_json and fails loudly without it, while ask
    # keeps working on the very same transport.
    from daf_jev._http import HttpxTransport

    class PostOnlyTransport:
        def __init__(self) -> None:
            self._inner = HttpxTransport(base_url=stub.base_url, timeout=5.0)

        def post_json(
            self,
            path: str,
            json_body: dict,
            headers: dict[str, str],
            *,
            timeout: float | None = None,
        ) -> httpx.Response:
            return self._inner.post_json(path, json_body, headers, timeout=timeout)

        def close(self) -> None:
            self._inner.close()

    client = daf_jev.JevClient(
        api_key="test-key", transport=PostOnlyTransport(), retry=RetryPolicy(jitter=0.0)
    )
    try:
        with pytest.raises(TypeSafeError) as excinfo:
            client.models()
        assert "get_json" in str(excinfo.value)
        stub.enqueue(body=_answers_body())
        resp = client.ask("state", {"billing": NoulQuestion(instructions="q")})
    finally:
        client.close()
    assert "billing" in resp.answers


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


def test_ask_raw_dict_question_passes_through_verbatim(stub) -> None:
    # Raw dicts ride alongside Question dataclasses: posted exactly as given,
    # without to_wire() rewriting them.
    stub.enqueue(
        body={
            "model": "jev-latest",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {"q": {"type": "noul", "noul": 0.5}},
        }
    )
    raw_question = {
        "type": "noul",
        "instructions": "raw dict",
        "criteria": {"true": "yes", "false": None},
    }
    with _make_client(stub) as client:
        resp = client.ask("state", {"q": raw_question})
    hit = stub.hits[0]
    assert hit["json"]["questions"] == {"q": raw_question}
    assert resp.nouls["q"].noul == 0.5


def test_ask_empty_questions_raises_without_hitting_the_wire(stub) -> None:
    with _make_client(stub) as client, pytest.raises(TypeSafeError) as excinfo:
        client.ask("state", {})
    assert len(stub.hits) == 0  # rejected before any request is sent
    assert "nonempty" in str(excinfo.value)


def test_double_close_is_idempotent_and_guarded_afterwards(stub) -> None:
    client = _make_client(stub)
    client.close()
    client.close()  # second close is a no-op, never an exception
    with pytest.raises(TypeSafeError) as excinfo:
        client.ask("state", {"billing": NoulQuestion(instructions="q")})
    assert "closed" in str(excinfo.value)
    assert len(stub.hits) == 0


def test_transport_close_releases_connection(stub) -> None:
    from daf_jev._http import HttpxTransport

    stub.enqueue(body=_answers_body())
    transport = HttpxTransport(base_url=stub.base_url, timeout=5.0, headers={})
    transport.post_json("/v1/systemone", {}, {"Authorization": "Bearer test-key"})
    transport.close()
    # A closed httpx.Client refuses further requests.
    with pytest.raises(RuntimeError):
        transport.post_json("/v1/systemone", {}, {})
    assert len(stub.hits) == 1


def test_httpx_transport_get_json_via_context_manager(stub) -> None:
    from daf_jev._http import HttpxTransport

    stub.enqueue(
        body={
            "models": [
                {
                    "name": "jev-latest",
                    "description": "current",
                    "release_date": "2026-01-01",
                }
            ]
        },
        headers={"x-typesafe-request-id": "req-get"},
    )
    with HttpxTransport(base_url=stub.base_url, timeout=5.0) as transport:
        response = transport.get_json("/v1/models", {"Authorization": "Bearer k"})
    assert response.status_code == 200
    assert response.json()["models"][0]["name"] == "jev-latest"
    assert stub.hits[0]["method"] == "GET"
    assert stub.hits[0]["headers"]["authorization"] == "Bearer k"
    assert response.headers["x-typesafe-request-id"] == "req-get"


def test_httpx_transport_default_timeout_is_60_seconds(stub) -> None:
    # httpx's own default is 5s; the transport must substitute the explicit
    # 60s default instead of letting slow LLM calls be capped silently.
    from daf_jev._http import DEFAULT_TIMEOUT_SECONDS, HttpxTransport

    transport = HttpxTransport(base_url=stub.base_url)
    try:
        assert transport._client.timeout == httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)
    finally:
        transport.close()


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

