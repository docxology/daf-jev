"""Gated fallback: a keyword heuristic answers first; the model is called
only when the heuristic is not confident enough.

Demonstrates:
- a deterministic lexicon heuristic producing ``(label, confidence)`` pairs
  over the same option labels a ``choice`` question uses
- ``confidence_gate`` with ``below="escalate"`` as the final escalation lane
  when the model's own confidence is below the gate
- ``UsageLedger`` accounting every model call the fallback actually makes

Run: python examples/gated_fallback.py [--model NAME]
"""

from __future__ import annotations

import argparse

from daf_jev import JevClient, choice, load_settings

try:
    from daf_jev.compose import confidence_gate
    from daf_jev.ledger import UsageLedger
except ImportError as exc:  # mid-build: helpers not landed yet
    raise SystemExit(
        "This example needs daf_jev.compose.confidence_gate and "
        "daf_jev.ledger.UsageLedger; they are not importable in this "
        f"checkout ({exc})"
    ) from exc

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
    "The payment went through, but the dashboard shows an error since.",
)

QUESTION = choice(
    "Classify the message intent.",
    {
        "billing": "payments, charges, refunds",
        "technical": "bugs and outages",
        "other": "anything else",
    },
)


def heuristic_guess(message: str) -> tuple[str | None, float]:
    """Score ``message`` against the keyword lexicons.

    Returns ``(label, confidence)``. When exactly one lexicon matches, its
    label comes back with confidence ``0.7 + 0.1`` per extra keyword,
    capped at ``0.9``. When several lexicons match or none do, the
    lexicons disagree or say nothing, so ``(None, 0.0)`` is returned and
    the caller should fall back to the model.
    """
    lowered = message.lower()
    matches = [
        (label, sum(1 for keyword in keywords if keyword in lowered))
        for label, keywords in LEXICON.items()
    ]
    matches = [(label, hits) for label, hits in matches if hits > 0]
    if len(matches) == 1:
        label, hits = matches[0]
        return label, min(0.9, 0.7 + 0.1 * (hits - 1))
    return None, 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Heuristic-first triage with a gated model fallback."
    )
    parser.add_argument("--model", default=None, help="model name override")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    ledger = UsageLedger()
    heuristic_answers = 0
    with JevClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=args.model or settings.model,
    ) as client:
        for message in MESSAGES:
            print(f"\nmessage: {message!r}")
            label, confidence = heuristic_guess(message)
            if confidence >= GATE:
                heuristic_answers += 1
                print(
                    f"heuristic: {label} (confidence={confidence:.2f}) -> "
                    "at or above the gate, no model call"
                )
                continue
            print(f"heuristic unsure (confidence={confidence:.2f}) -> asking the model")
            response = client.ask(message, {"intent": QUESTION})
            ledger.record(response)
            answer = response.answers["intent"]
            final = confidence_gate(answer, threshold=GATE, below="escalate")
            print(
                f"model: {final} (choice={answer.choice}, "
                f"confidence={answer.confidence:.2f})"
            )

    print(
        f"\nusage: {ledger.snapshot().to_dict()} "
        f"({heuristic_answers}/{len(MESSAGES)} messages answered by the "
        "heuristic alone)"
    )


if __name__ == "__main__":
    main()
