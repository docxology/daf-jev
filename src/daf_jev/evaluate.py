"""Batch evaluation harness over the TypeSafe Jev (System One) API.

Runs a fixed question set against many states through either a sync
:class:`~daf_jev.client.JevClient` (thread pool) or an async
:class:`~daf_jev.client.AsyncJevClient` (``asyncio`` + semaphore), never
aborting the batch: per-state failures are captured into
:class:`EvaluationRecord.error`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import math
import time
from collections import Counter
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from daf_jev._errors import TypeSafeError
from daf_jev._types import (
    ChoiceAnswer,
    ChoiceQuestion,
    JSONContent,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneResponse,
)
from daf_jev.client import AsyncJevClient, JevClient

__all__ = ["EvaluationRecord", "Evaluator"]

StateInput = Union[str, tuple[str, JSONContent]]


@dataclasses.dataclass
class EvaluationRecord:
    """Outcome of one evaluated state."""

    state_id: str
    state: JSONContent
    response: Optional[SystemOneResponse]
    error: Optional[str]
    latency_s: float


def _error_text(exc: Exception) -> str:
    if isinstance(exc, TypeSafeError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


class Evaluator:
    """Evaluate a fixed question set over many states, concurrently.

    ``client`` is a :class:`~daf_jev.client.JevClient` (thread-pool
    concurrency) or an :class:`~daf_jev.client.AsyncJevClient`
    (``asyncio.Semaphore`` concurrency); ``questions`` is any mapping of
    question id to a ``daf_jev`` question object (a ``QuestionSet``
    included).

    The async path runs on a private event loop so ``evaluate()`` stays
    synchronous; because the pooled keep-alive connections of an async
    client are bound to that loop, the Evaluator closes the async
    session when its batch completes — an ``AsyncJevClient`` is single
    use through ``evaluate()``.
    """

    def __init__(
        self,
        client: Any,
        questions: Mapping[str, Any],
        *,
        concurrency: int = 4,
        model: Optional[str] = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {concurrency}")
        self._client = client
        self._questions = dict(questions)
        self._concurrency = concurrency
        self._model = model
        self._records: Optional[list[EvaluationRecord]] = None

    # ------------------------------------------------------------- driving

    def evaluate(self, states: Iterable[StateInput]) -> list[EvaluationRecord]:
        """Run every state through the question set, in input order.

        Bare ``str`` states are assigned ids ``state_0000``-style from
        their input index; tuples carry an explicit id. Per-state errors
        are captured into :attr:`EvaluationRecord.error` (response
        ``None``) — the batch is never aborted. Results are stored and
        become the default for :meth:`summary` / :meth:`to_json`.
        """
        items: list[tuple[str, JSONContent]] = []
        for index, item in enumerate(states):
            if isinstance(item, str):
                items.append((f"state_{index:04d}", item))
            elif isinstance(item, tuple) and len(item) == 2:
                items.append((str(item[0]), item[1]))
            else:
                raise TypeError(
                    f"expected str or (state_id, state) tuple at index "
                    f"{index}, got {type(item).__name__}"
                )

        if isinstance(self._client, AsyncJevClient):
            records = self._run_async(self._evaluate_async(items))
        elif isinstance(self._client, JevClient):
            records = self._evaluate_sync(items)
        else:
            raise TypeError(
                "client must be a JevClient or AsyncJevClient, got "
                f"{type(self._client).__name__}"
            )
        self._records = records
        return records

    @staticmethod
    def _run_async(coro: Any) -> Any:
        """Drive the async path from the sync API, even inside a loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # Called from within a running event loop (e.g. an async harness):
        # execute the evaluation loop on a private thread so the public
        # evaluate() stays synchronous.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    def _ask(self, state: JSONContent) -> SystemOneResponse:
        return self._client.ask(state, self._questions, model=self._model)

    def _record_of(self, state_id: str, state: JSONContent) -> EvaluationRecord:
        start = time.perf_counter()
        try:
            response = self._ask(state)
        except Exception as exc:  # per-state failure: never aborts the batch
            return EvaluationRecord(
                state_id, state, None, _error_text(exc), time.perf_counter() - start
            )
        return EvaluationRecord(
            state_id, state, response, None, time.perf_counter() - start
        )

    async def _evaluate_async(
        self, items: Sequence[tuple[str, JSONContent]]
    ) -> list[EvaluationRecord]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(state_id: str, state: JSONContent) -> EvaluationRecord:
            async with semaphore:
                start = time.perf_counter()
                try:
                    response = await self._ask(state)
                except Exception as exc:
                    return EvaluationRecord(
                        state_id,
                        state,
                        None,
                        _error_text(exc),
                        time.perf_counter() - start,
                    )
                return EvaluationRecord(
                    state_id, state, response, None, time.perf_counter() - start
                )

        records = list(
            await asyncio.gather(
                *(run(state_id, state) for state_id, state in items)
            )
        )
        # evaluate() drives the async client on a private event loop, so
        # its pooled keep-alive connections are bound to a loop that dies
        # with this batch; close the async session cleanly here rather
        # than leaving the caller with a poisoned client.
        await self._client.close()
        return records

    def _evaluate_sync(
        self, items: Sequence[tuple[str, JSONContent]]
    ) -> list[EvaluationRecord]:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._concurrency
        ) as pool:
            futures = [
                pool.submit(self._record_of, state_id, state)
                for state_id, state in items
            ]
            return [future.result() for future in futures]

    # ------------------------------------------------------------ analysis

    def _records_or_last(
        self, records: Optional[Sequence[EvaluationRecord]]
    ) -> Sequence[EvaluationRecord]:
        if records is None:
            if self._records is None:
                raise ValueError("no evaluation records: call evaluate() first")
            return self._records
        return records

    def summary(
        self, records: Optional[Sequence[EvaluationRecord]] = None
    ) -> dict[str, Any]:
        """Aggregate records (default: the last :meth:`evaluate` result)."""
        records = self._records_or_last(records)
        ok = [
            record
            for record in records
            if record.error is None and record.response is not None
        ]
        latencies = [record.latency_s for record in records]
        return {
            "n_states": len(records),
            "n_errors": len(records) - len(ok),
            "total_input_tokens": sum(
                record.response.usage.input_tokens for record in ok
            ),
            "total_output_tokens": sum(
                record.response.usage.output_tokens for record in ok
            ),
            "mean_latency_s": _mean(latencies) if latencies else 0.0,
            "p95_latency_s": _p95(latencies) if latencies else 0.0,
            "questions": self._question_summary(ok),
        }

    def _question_summary(self, ok: Sequence[EvaluationRecord]) -> dict[str, Any]:
        # Aggregate by the question's DECLARED type, not the answer's; a
        # response whose answer type disagrees with the declaration is
        # skipped for that question.
        expected = {
            "noul": NoulAnswer,
            "choice": ChoiceAnswer,
            "score": ScoreAnswer,
        }
        aggregates: dict[str, Any] = {}
        for qid, question in self._questions.items():
            qtype = getattr(question, "type", None)
            answer_cls = expected.get(qtype)
            if answer_cls is None:
                continue
            answers = [
                record.response.answers[qid]
                for record in ok
                if qid in record.response.answers
                and isinstance(record.response.answers[qid], answer_cls)
            ]
            if not answers:
                continue
            if qtype == "noul":
                values = [answer.noul for answer in answers]  # type: ignore[attr-defined]
                aggregates[qid] = {
                    "kind": "noul",
                    "mean": _mean(values),
                    "min": min(values),
                    "max": max(values),
                }
            elif qtype == "choice":
                counts = Counter(answer.choice for answer in answers)  # type: ignore[attr-defined]
                aggregates[qid] = {
                    "kind": "choice",
                    "counts": dict(counts),
                    "mode": counts.most_common(1)[0][0],
                    "mean_confidence": _mean(
                        [answer.confidence for answer in answers]  # type: ignore[attr-defined]
                    ),
                }
            else:  # score
                aggregates[qid] = {
                    "kind": "score",
                    "mean": _mean(
                        [answer.score for answer in answers]  # type: ignore[attr-defined]
                    ),
                    "mean_confidence": _mean(
                        [answer.confidence for answer in answers]  # type: ignore[attr-defined]
                    ),
                }
        return aggregates

    def to_json(
        self, records: Optional[Sequence[EvaluationRecord]] = None
    ) -> list[dict[str, Any]]:
        """JSON-safe view of records (default: the last :meth:`evaluate`)."""
        records = self._records_or_last(records)
        return [
            {
                "state_id": record.state_id,
                "state": record.state,
                "response": None
                if record.response is None
                else {
                    "model": record.response.model,
                    "usage": dataclasses.asdict(record.response.usage),
                    "answers": {
                        qid: {**dataclasses.asdict(answer), "type": answer.type}
                        for qid, answer in record.response.answers.items()
                    },
                },
                "error": record.error,
                "latency_s": record.latency_s,
            }
            for record in records
        ]
