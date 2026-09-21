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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from daf_jev._errors import TypeSafeError
from daf_jev._types import (
    ChoiceAnswer,
    JSONContent,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
)
from daf_jev.client import AsyncJevClient, JevClient

__all__ = ["EvaluationRecord", "Evaluator"]

StateInput = str | tuple[str, JSONContent]


@dataclasses.dataclass
class EvaluationRecord:
    """Outcome of one evaluated state."""

    state_id: str
    state: JSONContent
    response: SystemOneResponse | None
    error: str | None
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
        client: JevClient | AsyncJevClient,
        questions: Mapping[str, Any],
        *,
        concurrency: int = 4,
        model: str | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {concurrency}")
        self._client = client
        self._questions = dict(questions)
        self._concurrency = concurrency
        self._model = model
        self._records: list[EvaluationRecord] | None = None

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
            records = self._run_async(self._evaluate_async(items, self._client))
        elif isinstance(self._client, JevClient):
            records = self._evaluate_sync(items, self._client)
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

    def _record_of(
        self, client: JevClient, state_id: str, state: JSONContent
    ) -> EvaluationRecord:
        start = time.perf_counter()
        try:
            response = client.ask(state, self._questions, model=self._model)
        except Exception as exc:  # per-state failure: never aborts the batch
            return EvaluationRecord(
                state_id, state, None, _error_text(exc), time.perf_counter() - start
            )
        return EvaluationRecord(
            state_id, state, response, None, time.perf_counter() - start
        )

    async def _evaluate_async(
        self,
        items: Sequence[tuple[str, JSONContent]],
        client: AsyncJevClient,
    ) -> list[EvaluationRecord]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(state_id: str, state: JSONContent) -> EvaluationRecord:
            async with semaphore:
                start = time.perf_counter()
                try:
                    response = await client.ask(
                        state, self._questions, model=self._model
                    )
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

        try:
            return list(
                await asyncio.gather(
                    *(run(state_id, state) for state_id, state in items)
                )
            )
        finally:
            # evaluate() drives the async client on a private event loop, so
            # its pooled keep-alive connections are bound to a loop that dies
            # with this batch; close the async session cleanly here rather
            # than leaving the caller with a poisoned client. Running in a
            # finally also closes the session when the gather is cancelled
            # or a task fails mid-batch.
            await client.close()

    def _evaluate_sync(
        self,
        items: Sequence[tuple[str, JSONContent]],
        client: JevClient,
    ) -> list[EvaluationRecord]:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._concurrency
        ) as pool:
            futures = [
                pool.submit(self._record_of, client, state_id, state)
                for state_id, state in items
            ]
            return [future.result() for future in futures]

    # ------------------------------------------------------------ analysis

    def _records_or_last(
        self, records: Sequence[EvaluationRecord] | None
    ) -> Sequence[EvaluationRecord]:
        if records is None:
            if self._records is None:
                raise ValueError("no evaluation records: call evaluate() first")
            return self._records
        return records

    def summary(
        self, records: Sequence[EvaluationRecord] | None = None
    ) -> dict[str, Any]:
        """Aggregate records (default: the last :meth:`evaluate` result).

        Latency aggregates (``mean_latency_s`` and ``p95_latency_s``) span
        every record, failed ones included: failed attempts still cost wall
        time, and that is the ops signal this summary reports. Token totals
        and the per-question aggregates cover successful records only.
        """
        records = self._records_or_last(records)
        responses = [
            record.response
            for record in records
            if record.error is None and record.response is not None
        ]
        latencies = [record.latency_s for record in records]
        return {
            "n_states": len(records),
            "n_errors": len(records) - len(responses),
            "total_input_tokens": sum(
                response.usage.input_tokens for response in responses
            ),
            "total_output_tokens": sum(
                response.usage.output_tokens for response in responses
            ),
            "mean_latency_s": _mean(latencies) if latencies else 0.0,
            "p95_latency_s": _p95(latencies) if latencies else 0.0,
            "questions": self._question_summary(responses),
        }

    def _question_summary(
        self, responses: Sequence[SystemOneResponse]
    ) -> dict[str, Any]:
        # Aggregate by the question's DECLARED type, not the answer's; a
        # response whose answer type disagrees with the declaration is
        # skipped for that question.
        aggregates: dict[str, Any] = {}
        for qid, question in self._questions.items():
            qtype = getattr(question, "type", None)
            if qtype == "noul":
                noul_answers = [
                    answer
                    for answer in (
                        response.answers.get(qid) for response in responses
                    )
                    if isinstance(answer, NoulAnswer)
                ]
                if not noul_answers:
                    continue
                values = [answer.noul for answer in noul_answers]
                aggregates[qid] = {
                    "kind": "noul",
                    "mean": _mean(values),
                    "min": min(values),
                    "max": max(values),
                }
            elif qtype == "choice":
                choice_answers = [
                    answer
                    for answer in (
                        response.answers.get(qid) for response in responses
                    )
                    if isinstance(answer, ChoiceAnswer)
                ]
                if not choice_answers:
                    continue
                counts = Counter(answer.choice for answer in choice_answers)
                aggregates[qid] = {
                    "kind": "choice",
                    "counts": dict(counts),
                    "mode": counts.most_common(1)[0][0],
                    "mean_confidence": _mean(
                        [answer.confidence for answer in choice_answers]
                    ),
                }
            elif qtype == "score":
                score_answers = [
                    answer
                    for answer in (
                        response.answers.get(qid) for response in responses
                    )
                    if isinstance(answer, ScoreAnswer)
                ]
                if not score_answers:
                    continue
                aggregates[qid] = {
                    "kind": "score",
                    "mean": _mean([answer.score for answer in score_answers]),
                    "mean_confidence": _mean(
                        [answer.confidence for answer in score_answers]
                    ),
                }
        return aggregates

    def to_json(
        self, records: Sequence[EvaluationRecord] | None = None
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
