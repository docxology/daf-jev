"""Decision-point decider loop: observe -> compose -> ask -> gate -> fail-open.

Demonstrates:
- typed hooks: ``render_state`` / ``questions`` / ``map_answers`` / ``fallback``
- a deterministic keyword lexicon as the floor action the Decider falls
  back to whenever the model is unavailable, unconfident, or over budget
- ``ConfidenceGate`` rejecting low-confidence answers into the fallback
- ``Budget`` bounding the ask attempts
- ``on_event`` JSON receipts for every decision (model / cache / fallback)

Run: python examples/decider_loop.py [--model NAME]
"""

from __future__ import annotations

import argparse
import json

from daf_jev import (
    Budget,
    ConfidenceGate,
    Decider,
    JevClient,
    choice,
    load_settings,
)

GATE = 0.75

LEXICON = {
    "billing": ("refund", "charged", "charge", "invoice", "payment", "billing"),
    "technical": ("error", "crash", "bug", "outage", "broken", "500"),
    "other": ("feedback", "suggestion", "compliment", "complaint"),
}

MESSAGES = (
    "You charged me twice this month, please refund the duplicate.",
    "The app crashes with a 500 error on every page load.",
    "Something seems off with my account, can you take a look?",
)

QUESTION = choice(
    "Classify the message intent.",
    {
        "billing": "payments, charges, refunds",
        "technical": "bugs and outages",
        "other": "anything else",
    },
)


def lexicon_label(message: str) -> str:
    """Deterministic floor action: keyword-majority label or ``other``."""
    lowered = message.lower()
    counts = {
        label: sum(1 for keyword in keywords if keyword in lowered)
        for label, keywords in LEXICON.items()
    }
    best = max(counts, key=lambda label: counts[label])
    return best if counts[best] > 0 else "other"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decision-point decider loop over a small demo corpus."
    )
    parser.add_argument("--model", default=None, help="model name override")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    events: list[dict] = []
    with JevClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=args.model or settings.model,
    ) as client:
        decider = Decider(
            client,
            render_state=str,
            questions=lambda message: {"intent": QUESTION},
            map_answers=lambda message, resp: resp.choices["intent"].choice,
            fallback=lexicon_label,
            gate=ConfidenceGate("intent", threshold=GATE),
            budget=Budget(max_calls=10),
            on_event=lambda event: events.append(event.to_dict()),
        )
        for message in MESSAGES:
            label = decider.decide(message)
            last = decider.last_event
            print(f"\nmessage: {message!r}")
            print(
                f"  -> {label} (source={last.source}, "
                f"reason={last.reason}, latency={last.latency_s:.3f}s)"
            )

    print(f"\nevents: {json.dumps(events, indent=2)}")
    print(f"usage: {decider.usage_snapshot().to_dict()}")


if __name__ == "__main__":
    main()
