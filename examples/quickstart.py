"""Quickstart: one mixed ask (noul + choice + score) against the TypeSafe
Jev (System One) API.

Demonstrates:
- resolving credentials and defaults via ``daf_jev.load_settings()``
- building questions with the ``noul``/``choice``/``score`` helpers
- reading answers, usage, and request id off a ``SystemOneResponse``

Run: python examples/quickstart.py [--model NAME]
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from daf_jev import JevClient, choice, load_settings, noul, score

STATE = {
    "ticket": "T-1042",
    "summary": "Checkout button returns HTTP 500 on Safari for saved cards.",
}

QUESTIONS = {
    "is_bug": noul("Is this report a software bug?"),
    "severity": choice(
        "Which queue should own this ticket?",
        {"billing": "payments or refunds", "technical": "product defects"},
    ),
    "urgency": score(
        "Rate the urgency to fix this.", ["later", "next sprint", "hotfix now"]
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="One mixed ask call.")
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
        response = client.ask(STATE, QUESTIONS)

    print(f"model={response.model}  request_id={response.request_id}")
    for qid, answer in response.answers.items():
        print(f"{qid}: {json.dumps(dataclasses.asdict(answer), sort_keys=True)}")
    print(
        f"usage: {response.usage.input_tokens} input / "
        f"{response.usage.output_tokens} output tokens"
    )


if __name__ == "__main__":
    main()
