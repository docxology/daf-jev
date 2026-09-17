"""Corpus evaluation: run one question set over many states with ``Evaluator``.

Demonstrates:
- constructing an ``Evaluator`` over a sync ``JevClient``
- evaluating an inline corpus with bounded concurrency
- per-state records (choice or captured error) plus the aggregate summary

Run: python examples/evaluate_corpus.py [--model NAME] [--concurrency N]
"""

from __future__ import annotations

import argparse

from daf_jev import Evaluator, JevClient, choice, load_settings

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch corpus evaluation.")
    parser.add_argument("--model", default=None, help="model name override")
    parser.add_argument("--concurrency", type=int, default=2, help="parallel states")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    with JevClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=args.model or settings.model,
    ) as client:
        evaluator = Evaluator(client, QUESTIONS, concurrency=args.concurrency)
        records = evaluator.evaluate(STATES)

    for record in records:
        if record.error is not None:
            print(f"{record.state_id}: ERROR {record.error}")
        else:
            answer = record.response.answers["spam"]
            print(f"{record.state_id}: {answer.choice} ({record.latency_s:.2f}s)")

    print(evaluator.summary())


if __name__ == "__main__":
    main()
