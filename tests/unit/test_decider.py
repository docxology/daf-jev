"""Unit tests for daf_jev.decider over the real local HTTP stub.

The Decider is exercised through a real JevClient bound to the conftest
stub server — no patching of daf_jev internals anywhere. The no-key path
uses only the sanctioned hermeticity tools: env-var monkeypatch plus a
tmp_path chdir so the .env lookup finds nothing.
"""

from __future__ import annotations

import json

import pytest

from daf_jev import (
    Budget,
    ChoiceAnswer,
    ChoiceQuestion,
    CircuitBreaker,
    ConfidenceGate,
    Decider,
    JevClient,
    NoulAnswer,
    RetryPolicy,
    UsageLedger,
    UsageSnapshot,
)


def _questions() -> dict:
    return {
        "route": ChoiceQuestion(
            instructions="Pick an action.", criteria={"act": None, "hold": "wait"}
        ),
    }


def _body(
    confidence: float = 0.9,
    choice: str = "act",
    input_tokens: int = 100,
    output_tokens: int = 20,
    noul_only: bool = False,
) -> dict:
    if noul_only:
        answers: dict = {"route": {"type": "noul", "noul": 0.8}}
    else:
        answers = {
            "route": {
                "type": "choice",
                "choice": choice,
                "probabilities": {"act": 0.7, "hold": 0.3},
                "confidence": confidence,
            }
        }
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "answers": answers,
    }


def _stub_client(stub) -> JevClient:
    return JevClient(
        api_key="test",
        base_url=stub.base_url,
        retry=RetryPolicy(max_attempts=1),
    )


def _decider(stub, **overrides) -> Decider:
    kwargs = {
        "client": _stub_client(stub),
        "render_state": str,
        "questions": lambda state: _questions(),
        "map_answers": lambda state, resp: resp.choices["route"].choice,
        "fallback": lambda state: "hold",
    }
    kwargs.update(overrides)
    return Decider(**kwargs)


def test_happy_path_model_action(stub) -> None:
    stub.enqueue(body=_body(), headers={"x-typesafe-request-id": "req-1"})
    ledger = UsageLedger()
    budget = Budget(max_calls=5)
    decider = _decider(stub, ledger=ledger, budget=budget)

    assert decider.decide("state one") == "act"
    assert len(stub.hits) == 1
    event = decider.last_event
    assert event.source == "model"
    assert event.reason is None and event.error is None
    assert event.request_id == "req-1"
    assert event.usage.input_tokens == 100 and event.usage.output_tokens == 20
    assert ledger.snapshot() == UsageSnapshot(
        requests=1, input_tokens=100, output_tokens=20
    )
    assert budget.attempts == 1


def test_cache_second_decide_makes_no_new_hit(stub) -> None:
    stub.enqueue(body=_body())
    cache: dict = {}
    decider = _decider(stub, cache=cache, cache_key=lambda state: state)

    assert decider.decide("s1") == "act"
    assert decider.decide("s1") == "act"
    assert len(stub.hits) == 1
    assert cache == {"s1": "act"}
    assert decider.last_event.source == "cache"
    assert decider.last_event.usage is None
    assert decider.last_event.request_id is None


def test_budget_max_calls_falls_back_without_new_hit(stub) -> None:
    stub.enqueue(body=_body())
    decider = _decider(stub, budget=Budget(max_calls=1))

    assert decider.decide("s1") == "act"
    assert decider.decide("s2") == "hold"
    assert len(stub.hits) == 1
    assert decider.last_event.source == "fallback"
    assert decider.last_event.reason == "budget"
    assert decider.last_event.error == "max_calls reached (1/1)"


def test_budget_token_limits(stub) -> None:
    stub.enqueue(body=_body(input_tokens=100, output_tokens=20))
    decider = _decider(stub, budget=Budget(max_input_tokens=50))

    assert decider.decide("s1") == "act"
    assert decider.decide("s2") == "hold"
    assert len(stub.hits) == 1
    assert decider.last_event.reason == "budget"


def test_budget_exceeded_thresholds() -> None:
    output_budget = Budget(max_output_tokens=10)
    assert output_budget.exceeded(UsageSnapshot(0, 0, 9)) is None
    assert output_budget.exceeded(UsageSnapshot(0, 0, 11)) is not None
    total_budget = Budget(max_total_tokens=30)
    assert total_budget.exceeded(UsageSnapshot(0, 10, 20)) is not None
    calls_budget = Budget(max_calls=100)
    assert calls_budget.exceeded(UsageSnapshot(0, 500, 500)) is None
    assert calls_budget.to_dict() == {
        "max_calls": 100,
        "max_input_tokens": None,
        "max_output_tokens": None,
        "max_total_tokens": None,
        "attempts": 0,
    }
    calls_budget.charge()
    assert calls_budget.attempts == 1


def test_breaker_opens_after_failure(stub) -> None:
    stub.enqueue(status=500, body={"error": "boom"})
    decider = _decider(
        stub, breaker=CircuitBreaker(failure_threshold=1, cooldown_seconds=999.0)
    )

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "ask_error"
    assert len(stub.hits) == 1
    assert decider.decide("s2") == "hold"
    assert decider.last_event.reason == "breaker"
    assert len(stub.hits) == 1  # fail fast: no new hit while the circuit is open


def test_consecutive_failure_latch(stub) -> None:
    for _ in range(3):
        stub.enqueue(status=500, body={"error": "boom"})
    decider = _decider(stub, max_consecutive_failures=3)

    for _ in range(3):
        assert decider.decide("s") == "hold"
        assert decider.last_event.reason == "ask_error"
    assert decider.dead is True

    stub.enqueue(body=_body())
    assert decider.decide("healthy") == "hold"
    assert decider.last_event.reason == "latched"
    assert len(stub.hits) == 3  # the healthy program was never consumed


def test_confidence_gate(stub) -> None:
    stub.enqueue(body=_body(confidence=0.3))
    decider = _decider(stub, gate=ConfidenceGate("route", 0.5))

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "gate"
    assert decider.last_event.error == "confidence 0.300 < threshold 0.500"

    stub.enqueue(body=_body(confidence=0.9))
    accepted = _decider(stub, gate=ConfidenceGate("route", 0.5))
    assert accepted.decide("s2") == "act"
    assert accepted.last_event.source == "model"


def test_noul_answers_are_not_gated(stub) -> None:
    stub.enqueue(body=_body(noul_only=True))
    decider = _decider(
        stub,
        gate=ConfidenceGate("route", 0.5),
        map_answers=lambda state, resp: "acted",
    )

    assert decider.decide("s1") == "acted"
    assert decider.last_event.source == "model"
    assert decider.calibration_pairs() == []  # no confidence to record


def test_confidence_gate_missing_answer_and_validation() -> None:
    gate = ConfidenceGate("route", 0.5)
    answer = ChoiceAnswer(
        choice="act", probabilities={"act": 1.0}, confidence=0.9
    )
    assert gate({"other": answer}) == "missing answer 'route'"
    assert gate({"route": NoulAnswer(noul=0.8)}) is None
    assert gate({"route": answer}) is None
    with pytest.raises(ValueError):
        ConfidenceGate("route", 1.5)
    with pytest.raises(ValueError):
        ConfidenceGate("route", -0.1)


def test_mapping_error_counts_toward_latch(stub) -> None:
    stub.enqueue(body=_body())
    stub.enqueue(status=500, body={"error": "boom"})
    stub.enqueue(status=500, body={"error": "boom"})

    def map_answers(state, resp):
        raise ValueError("unusable answers")

    decider = _decider(stub, map_answers=map_answers, max_consecutive_failures=3)

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "mapping_error"
    assert decider.decide("s2") == "hold"
    assert decider.last_event.reason == "ask_error"
    assert decider.decide("s3") == "hold"
    assert decider.last_event.reason == "ask_error"
    assert decider.dead is True  # mapping failures count toward the latch

    stub.enqueue(body=_body())
    assert decider.decide("s4") == "hold"
    assert decider.last_event.reason == "latched"
    assert len(stub.hits) == 3


def test_not_asked_short_circuits_before_any_hit(stub) -> None:
    decider = _decider(stub, should_ask=lambda state: False)

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "not_asked"
    assert len(stub.hits) == 0


def test_client_factory_error_latches(stub) -> None:
    def factory():
        raise RuntimeError("factory down")

    decider = _decider(stub, client=None, client_factory=factory)

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "client_error"
    assert decider.last_event.error == "factory down"
    assert decider.dead is True
    assert decider.decide("s2") == "hold"
    assert decider.last_event.reason == "client_error"
    assert len(stub.hits) == 0


def test_client_error_text_falls_back_to_class_name(stub) -> None:
    def factory():
        raise ValueError()

    decider = _decider(stub, client=None, client_factory=factory)
    assert decider.decide("s1") == "hold"
    assert decider.last_event.error == "ValueError"


def test_client_factory_success_path(stub) -> None:
    stub.enqueue(body=_body())
    decider = _decider(stub, client=None, client_factory=lambda: _stub_client(stub))

    assert decider.decide("s1") == "act"
    assert decider.last_event.source == "model"


def test_default_client_resolution_success_then_budget(stub) -> None:
    decider = _decider(
        stub,
        client=None,
        env={"JEV_API_KEY": "k"},
        budget=Budget(max_calls=0),
    )

    # Resolution succeeds (no network at construction), then the budget
    # gate short-circuits before any ask.
    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "budget"
    assert len(stub.hits) == 0


def test_no_key_latches(stub, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # load_dotenv finds no .env here
    decider = _decider(stub, client=None)

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "no_key"
    assert decider.dead is True
    assert decider.decide("s2") == "hold"
    assert decider.last_event.reason == "no_key"
    assert len(stub.hits) == 0


def test_compose_error(stub) -> None:
    def questions(state):
        raise ValueError("bad questions")

    decider = _decider(stub, questions=questions)

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "compose_error"
    assert len(stub.hits) == 0


def test_decide_never_raises_on_mapping_runtime_error(stub) -> None:
    stub.enqueue(body=_body())

    def map_answers(state, resp):
        raise RuntimeError("unexpected")

    decider = _decider(
        stub, map_answers=map_answers, fallback=lambda state: ("floor", state)
    )

    assert decider.decide("s1") == ("floor", "s1")
    assert decider.last_event.reason == "mapping_error"


def test_error_reason_via_broken_cache_key(stub) -> None:
    def cache_key(state):
        raise RuntimeError("bad key")

    decider = _decider(stub, cache={}, cache_key=cache_key)

    assert decider.decide("s1") == "hold"
    assert decider.last_event.reason == "error"
    assert len(stub.hits) == 0


def test_calibration_pairs(stub) -> None:
    stub.enqueue(body=_body(confidence=0.3))
    stub.enqueue(body=_body(confidence=0.9))
    decider = _decider(stub, gate=ConfidenceGate("route", 0.5))

    assert decider.decide("s1") == "hold"  # gated
    assert decider.decide("s2") == "act"  # accepted
    assert decider.calibration_pairs() == [(0.3, False), (0.9, True)]


def test_calibration_pairs_empty_without_gate(stub) -> None:
    stub.enqueue(body=_body())
    decider = _decider(stub)

    decider.decide("s1")
    assert decider.calibration_pairs() == []


def test_event_hook_and_json_roundtrip(stub) -> None:
    stub.enqueue(body=_body())
    events: list = []
    decider = _decider(stub, budget=Budget(max_calls=1), on_event=events.append)

    assert decider.decide("s1") == "act"
    assert decider.decide("s2") == "hold"
    assert [event.source for event in events] == ["model", "fallback"]
    assert [event.reason for event in events] == [None, "budget"]
    payload = json.dumps([event.to_dict() for event in events])
    parsed = json.loads(payload)
    assert parsed[0]["usage"] == {"input_tokens": 100, "output_tokens": 20}
    assert parsed[0]["request_id"] is None
    assert parsed[1]["usage"] is None


def test_raising_on_event_does_not_break_decide(stub) -> None:
    stub.enqueue(body=_body())

    def on_event(event):
        raise RuntimeError("observer down")

    decider = _decider(stub, on_event=on_event)

    assert decider.decide("s1") == "act"
    assert decider.last_event.source == "model"


def test_usage_snapshot_passthrough(stub) -> None:
    stub.enqueue(body=_body())
    decider = _decider(stub)

    decider.decide("s1")
    assert decider.usage_snapshot() == UsageSnapshot(
        requests=1, input_tokens=100, output_tokens=20
    )


def test_construction_validation(stub) -> None:
    with pytest.raises(ValueError):  # client and client_factory together
        _decider(stub, client_factory=lambda: None)
    with pytest.raises(ValueError):  # cache without cache_key
        _decider(stub, cache={})
    with pytest.raises(ValueError):  # cache_key without cache
        _decider(stub, cache_key=lambda state: state)
    with pytest.raises(ValueError):  # no thresholds
        Budget()
    with pytest.raises(ValueError):
        _decider(stub, max_consecutive_failures=0)
    with pytest.raises(ValueError):
        _decider(stub, timeout=0.0)
