"""Async batch evaluation: run a question set on a single-use async client.

Demonstrates:
- constructing an ``AsyncJevClient`` with an injected canned transport
- ``await evaluator.evaluate_async()`` with explicit ``(state_id, state)``
  tuples and bounded concurrency
- per-state error capture: one failing state records an error, the batch
  still completes
- single-use session semantics: the ``Evaluator`` closes the async session
  at batch end, so a further ``ask`` raises ``TypeSafeError``
- the aggregate ``summary()`` after the batch

Run: python examples/evaluate_async.py [--model NAME] [--concurrency N]
"""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx

from daf_jev import (
    AsyncJevClient,
    Evaluator,
    RetryPolicy,
    TypeSafeError,
    choice,
    load_settings,
)

STATES = [
    ("sms_1", "SMS: 'Your package arrives tomorrow between 2-4pm.'"),
    ("sms_2", "SMS: 'URGENT: your account is suspended, click http://bit.ly/abc now'"),
    ("sms_3", "SMS: 'Lunch tomorrow at noon, same place?'"),
    ("sms_4", "SMS: 'Final notice: pay invoice #8812 or service stops today.'"),
]

QUESTIONS = {
    "spam": choice(
        "Is this message spam or phishing?",
        {"spam": "unwanted marketing or phishing", "legit": "a normal message"},
    ),
}


class CannedAsyncTransport:
    """Minimal AsyncTransport with per-state canned replies (no network)."""

    async def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        state = json_body["state"]
        if "Lunch tomorrow" in state:
            # One designated failure: 500 is non-retryable (retryable set
            # is {429, 529}), so with max_attempts=1 the state records an
            # error instead of stalling the batch.
            return httpx.Response(
                500, json={"error": "simulated provider error"}
            )
        label, confidence, p_spam = _canned_answer(state)
        payload = {
            "model": "canned-latest",
            "answers": {
                "spam": {
                    "type": "choice",
                    "choice": label,
                    "probabilities": {
                        "spam": p_spam,
                        "legit": round(1.0 - p_spam, 4),
                    },
                    "confidence": confidence,
                },
            },
            "usage": {"input_tokens": 42, "output_tokens": 7},
        }
        # A FRESH Response per call: a Response body can be consumed once.
        return httpx.Response(
            200,
            json=payload,
            headers={"x-typesafe-request-id": "canned-0000"},
        )

    async def close(self) -> None:
        return None


def _canned_answer(state: str) -> tuple[str, float, float]:
    """(choice, confidence, p_spam) varied per state for a lively demo."""
    if "suspended" in state:
        return ("spam", 0.95, 0.95)
    if "Final notice" in state:
        return ("spam", 0.60, 0.60)
    return ("legit", 0.90, 0.10)


async def run(api_key: str, model: str, concurrency: int) -> None:
    client = AsyncJevClient(
        api_key=api_key,
        model=model,
        transport=CannedAsyncTransport(),
        retry=RetryPolicy(max_attempts=1),
    )
    evaluator = Evaluator(client, QUESTIONS, concurrency=concurrency)
    records = await evaluator.evaluate_async(STATES)

    for record in records:
        if record.error is not None:
            print(f"{record.state_id}: ERROR {record.error}")
        else:
            answer = record.response.answers["spam"]
            print(f"{record.state_id}: {answer.choice} ({record.latency_s:.2f}s)")

    print("summary:")
    print(json.dumps(evaluator.summary(), indent=2))

    # Single-use proof: evaluate_async() closed the async session in its
    # finally block, so a post-batch ask must fail rather than hang.
    try:
        await client.ask(STATES[0][1], QUESTIONS)
        print("single-use: UNEXPECTED ask succeeded after the batch")
    except TypeSafeError as exc:
        print(f"single-use: TypeSafeError after the batch: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Async batch evaluation on a single-use AsyncJevClient."
    )
    parser.add_argument("--model", default=None, help="model name override")
    parser.add_argument("--concurrency", type=int, default=2, help="parallel states")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    asyncio.run(run(settings.api_key, args.model or settings.model, args.concurrency))


if __name__ == "__main__":
    main()
