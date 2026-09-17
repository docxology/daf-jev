"""Unit tests for daf_jev.ledger: usage accumulation across call loops."""

from __future__ import annotations

import dataclasses
import json
import threading

from daf_jev._types import (
    Answer,
    NoulAnswer,
    SystemOneResponse,
    Usage,
    parse_response,
)
from daf_jev.ledger import UsageLedger, UsageSnapshot


def _response(
    input_tokens: int, output_tokens: int, request_id: str = "req-1"
) -> SystemOneResponse:
    """Build a real wire response through the parser (no mocks)."""
    payload = {
        "model": "system-one",
        "answers": {"q1": {"type": "noul", "noul": 0.7}},
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    return parse_response(payload, request_id=request_id)


def _direct_response(
    input_tokens: int, output_tokens: int
) -> SystemOneResponse:
    """Build a response by direct dataclass construction."""
    answers: dict[str, Answer] = {"q1": NoulAnswer(noul=0.3)}
    return SystemOneResponse(
        model="system-one",
        answers=answers,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_zero_state_snapshot() -> None:
    ledger = UsageLedger()
    assert ledger.snapshot() == UsageSnapshot()


def test_record_usage_dataclass() -> None:
    ledger = UsageLedger()
    ledger.record(Usage(input_tokens=10, output_tokens=4))
    assert ledger.snapshot() == UsageSnapshot(
        requests=1, input_tokens=10, output_tokens=4
    )
    assert ledger.snapshot().total_tokens == 14


def test_record_parsed_response() -> None:
    ledger = UsageLedger()
    ledger.record(_response(7, 3))
    assert ledger.snapshot() == UsageSnapshot(
        requests=1, input_tokens=7, output_tokens=3
    )


def test_record_directly_constructed_response() -> None:
    ledger = UsageLedger()
    ledger.record(_direct_response(5, 9))
    assert ledger.snapshot() == UsageSnapshot(
        requests=1, input_tokens=5, output_tokens=9
    )


def test_record_none_is_silent_noop() -> None:
    ledger = UsageLedger()
    ledger.record(None)
    assert ledger.snapshot() == UsageSnapshot()


def test_record_returns_none() -> None:
    ledger = UsageLedger()
    assert ledger.record(None) is None
    assert ledger.record(Usage()) is None


def test_mixed_accumulation_exact_totals() -> None:
    ledger = UsageLedger()
    ledger.record(_response(11, 4))
    ledger.record(None)  # error path: no usage produced
    ledger.record(Usage(input_tokens=2, output_tokens=6))
    ledger.record(_direct_response(1, 1))
    ledger.record(_response(100, 200, request_id="req-2"))
    assert ledger.snapshot() == UsageSnapshot(
        requests=4, input_tokens=114, output_tokens=211
    )
    assert ledger.snapshot().total_tokens == 325


def test_snapshot_does_not_mutate_ledger() -> None:
    ledger = UsageLedger()
    ledger.record(Usage(input_tokens=3, output_tokens=3))
    before = ledger.snapshot()
    after = ledger.snapshot()
    assert before == after
    assert after.requests == 1


def test_snapshot_is_frozen() -> None:
    snapshot = UsageSnapshot(requests=1, input_tokens=2, output_tokens=3)
    try:
        snapshot.requests = 5  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("UsageSnapshot must be frozen")


def test_reset_returns_pre_reset_totals_and_zeroes() -> None:
    ledger = UsageLedger()
    ledger.record(Usage(input_tokens=10, output_tokens=5))
    ledger.record(_response(4, 6))
    prior = ledger.reset()
    assert prior == UsageSnapshot(
        requests=2, input_tokens=14, output_tokens=11
    )
    assert ledger.snapshot() == UsageSnapshot()


def test_reset_on_empty_ledger() -> None:
    ledger = UsageLedger()
    assert ledger.reset() == UsageSnapshot()
    assert ledger.snapshot() == UsageSnapshot()


def test_to_dict_is_json_safe() -> None:
    ledger = UsageLedger()
    ledger.record(Usage(input_tokens=12, output_tokens=8))
    data = ledger.snapshot().to_dict()
    assert data == {
        "requests": 1,
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }
    assert json.loads(json.dumps(data)) == data


def test_zero_state_to_dict() -> None:
    data = UsageSnapshot().to_dict()
    assert json.loads(json.dumps(data)) == {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def test_thread_safety_smoke_exact_totals() -> None:
    """8 threads x 250 mixed-shape records must yield exact totals."""
    ledger = UsageLedger()
    threads_count = 8
    records_per_thread = 250
    # Per 250 records: 63 None, 63 Usage(2,1), 62 parsed(3,2),
    # 62 direct(3,1) => 187 requests, 498 input, 249 output tokens.
    per_thread_requests = 187
    per_thread_input = 63 * 2 + 62 * 3 + 62 * 3
    per_thread_output = 63 * 1 + 62 * 2 + 62 * 1
    assert per_thread_input == 498
    assert per_thread_output == 249

    def worker() -> None:
        for i in range(records_per_thread):
            if i % 4 == 0:
                ledger.record(None)
            elif i % 4 == 1:
                ledger.record(Usage(input_tokens=2, output_tokens=1))
            elif i % 4 == 2:
                ledger.record(_response(3, 2))
            else:
                ledger.record(_direct_response(3, 1))

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snapshot = ledger.snapshot()
    assert snapshot.requests == threads_count * per_thread_requests
    assert snapshot.input_tokens == threads_count * per_thread_input
    assert snapshot.output_tokens == threads_count * per_thread_output
    assert snapshot.total_tokens == snapshot.input_tokens + snapshot.output_tokens
    # reset() under the same contention returns exactly these totals.
    assert ledger.reset() == snapshot
