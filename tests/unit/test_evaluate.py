"""Unit tests for daf_jev.evaluate.Evaluator over the real local HTTP stub.

Same no-mock convention as the rest of the suite: the Evaluator drives real
JevClient / AsyncJevClient instances against the stub server from conftest.py
(no patching of daf_jev internals). Bulk evaluation pops queued stub programs
per request, so content-asserting tests pin ``concurrency=1`` for
deterministic program consumption; the concurrency tests use identical
programs so ordering cannot matter.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from daf_jev import (
    AsyncJevClient,
    ChoiceQuestion,
    JevClient,
    NoulQuestion,
    QuestionSet,
    RetryPolicy,
    ScoreQuestion,
)
from daf_jev._errors import TypeSafeError
from daf_jev.evaluate import Evaluator

# ------------------------------------------------------------- primitives ----


def _questions() -> dict:
    return {
        "billing": NoulQuestion(instructions="Is this about billing?"),
        "tone": ChoiceQuestion(
            instructions="What is the tone?", criteria={"calm": None, "angry": "hostile"}
        ),
        "severity": ScoreQuestion(instructions="Rate severity", criteria=["low", "high"]),
    }


def _body(
    *,
    noul: float = 0.9,
    choice: str = "calm",
    conf_c: float = 0.8,
    score: float = 0.5,
    conf_s: float = 0.7,
    inp: int = 10,
    outp: int = 5,
    model: str = "jev-latest",
) -> dict:
    return {
        "model": model,
        "usage": {"input_tokens": inp, "output_tokens": outp},
        "answers": {
            "billing": {"type": "noul", "noul": noul},
            "tone": {
                "type": "choice",
                "choice": choice,
                "probabilities": {"calm": 1.0, "angry": 0.0},
                "confidence": conf_c,
            },
            "severity": {
                "type": "score",
                "score": score,
                "legend": {"0": "low", "1": "high"},
                "probabilities": {"0": 0.5, "1": 0.5},
                "confidence": conf_s,
            },
        },
    }


def _sync_client(stub, **overrides):
    kwargs = {
        "api_key": "test-key",
        "base_url": stub.base_url,
        "retry": RetryPolicy(jitter=0.0),
        "sleep": lambda _seconds: None,  # injected no-op sleep; never patch internals
    }
    kwargs.update(overrides)
    return JevClient(**kwargs)


def _async_client(stub, **overrides):
    kwargs = {
        "api_key": "test-key",
        "base_url": stub.base_url,
        "retry": RetryPolicy(jitter=0.0),
    }
    kwargs.update(overrides)
    return AsyncJevClient(**kwargs)


# ---------------------------------------------------- construction/validation


def test_evaluator_rejects_nonpositive_concurrency() -> None:
    with pytest.raises(ValueError, match=r"concurrency must be >= 1, got 0"):
        Evaluator(object(), _questions(), concurrency=0)


def test_evaluate_rejects_malformed_state_input() -> None:
    # A bare non-str, non-tuple item fails fast, naming its input index.
    evaluator = Evaluator(object(), _questions())
    with pytest.raises(TypeError, match=r"at index 0, got int"):
        evaluator.evaluate([42])


def test_evaluate_rejects_foreign_client() -> None:
    evaluator = Evaluator(object(), _questions())
    with pytest.raises(TypeError, match="client must be"):
        evaluator.evaluate(["s0"])


# ------------------------------------------------------------ sync happy path


def test_sync_evaluate_ids_order_and_states(stub) -> None:
    states = ["first", ("custom-1", {"k": "v"}), "third", "fourth"]
    for i, noul in enumerate((0.2, 0.5, 0.8, 0.9)):
        stub.enqueue(body=_body(noul=noul, inp=10 * (i + 1), outp=i + 1))
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(states)

    assert [r.state_id for r in records] == [
        "state_0000",
        "custom-1",
        "state_0002",
        "state_0003",
    ]
    assert [r.state for r in records] == [
        "first",
        {"k": "v"},
        "third",
        "fourth",
    ]
    assert all(r.error is None for r in records)
    assert [r.response.nouls["billing"].noul for r in records] == [
        pytest.approx(0.2),
        pytest.approx(0.5),
        pytest.approx(0.8),
        pytest.approx(0.9),
    ]
    # every request carried its own state, in input order
    assert [h["json"]["state"] for h in stub.hits] == [
        "first",
        {"k": "v"},
        "third",
        "fourth",
    ]
    assert all(r.latency_s >= 0 for r in records)


def test_evaluate_accepts_questionset_mapping(stub) -> None:
    stub.enqueue(body=_body())
    questions = QuestionSet().noul("billing", "Is this about billing?")
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, questions)  # default concurrency
        records = evaluator.evaluate(["s0"])
    assert records[0].error is None
    assert records[0].response.nouls["billing"].noul == pytest.approx(0.9)
    assert stub.hits[0]["json"]["questions"]["billing"]["type"] == "noul"


def test_evaluator_model_override_reaches_request(stub) -> None:
    stub.enqueue(body=_body(model="jev-x"))
    with _sync_client(stub) as client:
        evaluator = Evaluator(
            client,
            {"billing": NoulQuestion(instructions="q")},
            model="jev-x",
        )
        records = evaluator.evaluate(["s0"])
    assert stub.hits[0]["json"]["model"] == "jev-x"
    assert records[0].error is None


def test_concurrency_caps_in_flight_sync(stub) -> None:
    for _ in range(4):
        stub.enqueue(body=_body())  # identical programs: order cannot matter
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=2)
        records = evaluator.evaluate(["s0", "s1", "s2", "s3"])
    assert len(records) == 4
    assert all(r.error is None for r in records)
    assert {r.state_id for r in records} == {
        "state_0000",
        "state_0001",
        "state_0002",
        "state_0003",
    }
    assert {h["json"]["state"] for h in stub.hits} == {"s0", "s1", "s2", "s3"}


# ------------------------------------------------------------ async happy path


def test_async_evaluate_path(stub) -> None:
    for i in range(3):
        stub.enqueue(body=_body(noul=0.1 * (i + 1), inp=5 * (i + 1)))
    client = _async_client(stub)
    evaluator = Evaluator(client, _questions(), concurrency=2)
    records = evaluator.evaluate(["a", "b", "c"])
    # The Evaluator drives the async client on a private event loop and
    # closes the session when the batch completes (the client is single-use
    # through evaluate()), so a later close is a no-op, not a dead-loop crash.
    asyncio.run(client.close())

    assert [r.state_id for r in records] == [
        "state_0000",
        "state_0001",
        "state_0002",
    ]
    assert all(r.error is None for r in records)
    summary = evaluator.summary(records)
    assert summary["n_states"] == 3
    assert summary["n_errors"] == 0
    assert summary["total_input_tokens"] == 5 + 10 + 15


def test_evaluate_works_inside_running_event_loop(stub) -> None:
    # The async path runs on a private event loop, so a synchronous
    # evaluate() call made from inside a running loop still works.
    stub.enqueue(body=_body())
    client = _async_client(stub)
    evaluator = Evaluator(client, _questions(), concurrency=1)

    async def scenario():
        return evaluator.evaluate(["inside-loop"])

    records = asyncio.run(scenario())
    assert [r.state_id for r in records] == ["state_0000"]
    assert records[0].error is None
    # The single-use async session was closed when the batch ended.
    with pytest.raises(TypeSafeError, match="client is closed"):
        asyncio.run(client.ask("inside-loop", _questions()))


def test_async_session_closed_after_batch(stub) -> None:
    # The async client is single-use through evaluate(): the Evaluator closes
    # the session when the batch completes.
    stub.enqueue(body=_body())
    client = _async_client(stub)
    assert client._closed is False
    evaluator = Evaluator(client, _questions(), concurrency=1)
    evaluator.evaluate(["s0"])
    assert client._closed is True


def test_async_session_closed_even_when_gather_is_cancelled(stub) -> None:
    # Pins the documented finally contract: the session also closes when the
    # gather is cancelled (or a task fails) mid-batch.
    stub.enqueue(body=_body(), delay=0.5)
    stub.enqueue(body=_body(), delay=0.5)

    async def scenario():
        client = _async_client(stub)
        evaluator = Evaluator(client, _questions(), concurrency=1)
        batch = asyncio.ensure_future(
            evaluator._evaluate_async([("s0", "a"), ("s1", "b")], client)
        )
        await asyncio.sleep(0.1)  # first ask is in flight against the slow stub
        batch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await batch
        return client

    client = asyncio.run(scenario())
    assert client._closed is True


# ------------------------------------------------------------ error handling --


def test_per_state_error_keeps_batch_alive(stub) -> None:
    stub.enqueue(body=_body(noul=0.1))
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    stub.enqueue(body=_body(noul=0.3))
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(["s0", "s1", "s2"])

    assert [r.state_id for r in records] == [
        "state_0000",
        "state_0001",
        "state_0002",
    ]
    assert records[0].error is None
    assert records[2].error is None
    assert records[1].response is None
    assert records[1].error  # non-empty error description
    assert all(r.latency_s >= 0 for r in records)

    summary = evaluator.summary(records)
    assert summary["n_states"] == 3
    assert summary["n_errors"] == 1
    # aggregates exclude the errored record
    assert summary["questions"]["billing"]["mean"] == pytest.approx(0.2)
    assert summary["total_input_tokens"] == 20


def test_async_per_state_error_keeps_batch_alive(stub) -> None:
    # The async path captures per-state failures the same way the sync
    # thread pool does: a 401 among 200s becomes one error record and the
    # batch stays alive.
    stub.enqueue(body=_body(noul=0.1))
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    stub.enqueue(body=_body(noul=0.3))
    client = _async_client(stub)
    evaluator = Evaluator(client, _questions(), concurrency=1)
    records = evaluator.evaluate(["s0", "s1", "s2"])

    assert [r.state_id for r in records] == [
        "state_0000",
        "state_0001",
        "state_0002",
    ]
    assert records[0].error is None
    assert records[2].error is None
    assert records[1].response is None
    assert records[1].error  # non-empty error description

    summary = evaluator.summary(records)
    assert summary["n_states"] == 3
    assert summary["n_errors"] == 1
    # aggregates exclude the errored record
    assert summary["questions"]["billing"]["mean"] == pytest.approx(0.2)
    assert summary["total_input_tokens"] == 20


def test_question_aggregates_omitted_without_healthy_records(stub) -> None:
    stub.enqueue(status=401, body={"error": {"message": "bad key"}})
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(["only"])
    summary = evaluator.summary(records)
    assert summary["n_errors"] == 1
    assert "billing" not in summary["questions"]
    assert summary["total_input_tokens"] == 0


# ----------------------------------------------------------------- summary ----


def test_summary_aggregates_by_question_kind(stub) -> None:
    bodies = [
        _body(noul=0.2, choice="calm", conf_c=0.6, score=0.4, conf_s=0.8, inp=10, outp=1),
        _body(noul=0.5, choice="calm", conf_c=0.7, score=0.5, conf_s=0.9, inp=20, outp=2),
        _body(noul=0.8, choice="angry", conf_c=0.8, score=0.6, conf_s=1.0, inp=30, outp=3),
    ]
    for body in bodies:
        stub.enqueue(body=body)
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(["a", "b", "c"])
    summary = evaluator.summary(records)

    assert summary["n_states"] == 3
    assert summary["n_errors"] == 0
    assert summary["total_input_tokens"] == 60
    assert summary["total_output_tokens"] == 6

    billing = summary["questions"]["billing"]
    assert billing["kind"] == "noul"
    assert billing["mean"] == pytest.approx(0.5)
    assert billing["min"] == pytest.approx(0.2)
    assert billing["max"] == pytest.approx(0.8)

    tone = summary["questions"]["tone"]
    assert tone["kind"] == "choice"
    assert tone["counts"] == {"calm": 2, "angry": 1}
    assert tone["mode"] == "calm"
    assert tone["mean_confidence"] == pytest.approx(0.7)

    severity = summary["questions"]["severity"]
    assert severity["kind"] == "score"
    assert severity["mean"] == pytest.approx(0.5)
    assert severity["mean_confidence"] == pytest.approx(0.9)

    assert summary["mean_latency_s"] >= 0
    assert summary["p95_latency_s"] >= 0


def test_summary_defaults_to_last_evaluate_result(stub) -> None:
    stub.enqueue(body=_body())
    stub.enqueue(body=_body())
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(["a", "b"])
        assert evaluator.summary() == evaluator.summary(records)


def test_summary_before_evaluate_raises() -> None:
    evaluator = Evaluator(object(), _questions())
    with pytest.raises(ValueError, match="no evaluation records: call evaluate"):
        evaluator.summary()


def test_raw_dict_question_passes_through_but_is_skipped_from_aggregates(stub) -> None:
    # Raw dicts are accepted alongside Question dataclasses on the wire, and
    # a question with no recognized declared type is skipped in aggregation.
    questions = _questions()
    questions["extra_raw"] = {"type": "mystery", "instructions": "raw passthrough"}
    stub.enqueue(body=_body())
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, questions, concurrency=1)
        records = evaluator.evaluate(["s0"])
    assert records[0].error is None
    assert stub.hits[0]["json"]["questions"]["extra_raw"]["type"] == "mystery"
    summary = evaluator.summary(records)
    assert set(summary["questions"]) == {"billing", "tone", "severity"}


def test_summary_latency_spans_failed_records(stub) -> None:
    # Latency aggregates deliberately include failed records: a failed
    # attempt still cost wall time, and that is the ops signal.
    stub.enqueue(body=_body(inp=10))
    stub.enqueue(status=401, body={"error": {"message": "bad key"}}, delay=0.4)
    stub.enqueue(body=_body(inp=10))
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(["fast", "slow-fail", "fast"])

    assert records[1].error
    assert records[1].latency_s >= 0.4
    summary = evaluator.summary(records)
    assert summary["n_errors"] == 1
    # p95 over 3 records is the maximum, i.e. the failed record's latency.
    assert summary["p95_latency_s"] >= 0.4
    assert summary["mean_latency_s"] >= 0.4 / 3


# ------------------------------------------------------------------ to_json ---


def test_to_json_is_json_safe(stub) -> None:
    stub.enqueue(body=_body(model="jev-x", inp=3, outp=4))
    stub.enqueue(status=401, body={"error": {"message": "nope"}})
    with _sync_client(stub) as client:
        evaluator = Evaluator(client, _questions(), concurrency=1)
        records = evaluator.evaluate(["ok", "bad"])

    payload = evaluator.to_json(records)
    text = json.dumps(payload)  # must not raise
    assert json.loads(text) == payload

    assert set(payload[0]) == {"state_id", "state", "response", "error", "latency_s"}
    ok = payload[0]
    assert ok["state_id"] == "state_0000"
    assert ok["state"] == "ok"
    assert ok["error"] is None
    assert ok["response"]["model"] == "jev-x"
    assert ok["response"]["usage"] == {"input_tokens": 3, "output_tokens": 4}
    assert ok["response"]["answers"]["billing"]["noul"] == pytest.approx(0.9)

    bad = payload[1]
    assert bad["response"] is None
    assert bad["error"]
    assert bad["latency_s"] >= 0
