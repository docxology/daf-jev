"""Triage router: one choice question dispatched with confidence gating.

Demonstrates:
- ``tiered_gate``: three-way automate/review/escalate routing on confidence
- ``route``: dispatch on the chosen label with a fallback handler
- the two-threshold confidence-routing scheme from the docs

Run: python examples/triage_router.py [--model NAME]
"""

from __future__ import annotations

import argparse

from daf_jev import JevClient, choice, load_settings

try:
    from daf_jev.compose import route, tiered_gate
except ImportError as exc:  # mid-build: compose helpers not landed yet
    raise SystemExit(
        "This example needs daf_jev.compose.route and .tiered_gate; they "
        f"are not importable in this checkout ({exc})"
    ) from exc

STATE = (
    "Support email: 'You charged me twice this month, please refund the "
    "duplicate.'"
)

QUESTION = choice(
    "Classify the message intent.",
    {
        "billing": "payments, charges, refunds",
        "technical": "bugs and outages",
        "other": "anything else",
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Confidence-routed triage.")
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
        response = client.ask(STATE, {"intent": QUESTION})

    answer = response.answers["intent"]
    label = tiered_gate(answer, high=0.85, low=0.6)
    print(
        f"tiered_gate: {label} (choice={answer.choice}, "
        f"confidence={answer.confidence:.2f})"
    )

    handlers = {
        "billing": lambda: "auto-refund the duplicate charge",
        "technical": lambda: "attach diagnostics and open an incident",
    }
    action = route(
        answer,
        handlers,
        min_confidence=0.6,
        fallback=lambda: "send to the general support queue",
    )
    print(f"route: {action}")


if __name__ == "__main__":
    main()
