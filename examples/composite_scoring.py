"""Composite scoring: expected value of a score answer with custom weights.

Demonstrates:
- ``score`` questions returning a probability distribution over levels
- ``composite_score`` re-weighting that distribution with custom weights
- ``confidence_gate`` deciding act vs. escalate on the answer's confidence

Run: python examples/composite_scoring.py [--model NAME]
"""

from __future__ import annotations

import argparse

from daf_jev import (
    JevClient,
    composite_score,
    confidence_gate,
    load_settings,
    score,
)

STATE = (
    "Deployment candidate: migration script touches the orders table "
    "during peak traffic."
)

QUESTION = score(
    "How risky is deploying this change right now?",
    ["safe", "mildly risky", "risky", "reckless"],
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weighted composite scoring.")
    parser.add_argument("--model", default=None, help="model name override")
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
        response = client.ask(STATE, {"risk": QUESTION})

    answer = response.answers["risk"]
    print(f"raw score: {answer.score:.3f}  confidence: {answer.confidence:.2f}")
    print(f"probabilities: {answer.probabilities}")

    # Weights re-weight the distribution: the last (reckless) level counts most.
    weights = [0.05, 0.15, 0.3, 0.5]
    composite = composite_score(answer, weights=weights)
    print(f"weighted composite (weights={weights}): {composite:.3f}")

    decision = confidence_gate(answer, threshold=0.7, below="escalate to a human")
    print(f"confidence_gate(threshold=0.7): {decision}")


if __name__ == "__main__":
    main()
