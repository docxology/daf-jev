"""Providers: multi-provider dispatch through the provider registry.

Demonstrates:
- listing the registered providers (``list_providers()``)
- per-provider settings resolution via ``load_settings(provider=...)``
- the extension story: registering a third-party ``ProviderSpec``
- the Transport injection seam: one ask over an in-process canned
  transport, so this script performs NO server call and NO network even
  when a key is present (the canned response carries kev's extra
  top-level ``latency_ms`` field to show strict-parse tolerance)

Run: python examples/providers_example.py [--model NAME]
"""

from __future__ import annotations

import argparse
import dataclasses
import json

import httpx

from daf_jev import (
    ProviderSpec,
    choice,
    list_providers,
    load_settings,
    noul,
    open_client,
    register_provider,
    score,
)

STATE = {
    "ticket": "T-1042",
    "summary": "Checkout button returns HTTP 500 on Safari for saved cards.",
}

QUESTIONS = {
    "is_bug": noul("Is this report a software bug?"),
    "queue": choice(
        "Which queue should own this ticket?",
        {"billing": "payments or refunds", "technical": "product defects"},
    ),
    "severity": score(
        "Rate the urgency to fix this.", ["minor", "noticeable", "blocking"]
    ),
}


class CannedTransport:
    """Minimal Transport returning a canned kev-shaped payload (no network)."""

    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        payload = {
            "model": "kev-latest",
            "answers": {
                "is_bug": {"type": "noul", "noul": 0.9},
                "queue": {
                    "type": "choice",
                    "choice": "technical",
                    "probabilities": {"billing": 0.2, "technical": 0.8},
                    "confidence": 0.8,
                },
                "severity": {
                    "type": "score",
                    "score": 2.0,
                    "legend": {
                        "0": "minor",
                        "1": "noticeable",
                        "2": "blocking",
                    },
                    "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0},
                    "confidence": 1.0,
                },
            },
            "usage": {"input_tokens": 42, "output_tokens": 0},
            # kev adds a top-level latency_ms field; parse_response
            # tolerates (and ignores) unknown top-level fields.
            "latency_ms": 123,
        }
        return httpx.Response(
            200,
            json=payload,
            headers={"x-typesafe-request-id": "canned-0000"},
        )

    def close(self) -> None:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Provider registry walkthrough.")
    parser.add_argument("--model", default=None, help="model name override")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    print("registered providers:")
    for spec in list_providers():
        print(
            f"  {spec.key}: {spec.display_name} @ {spec.default_base_url}"
            f" (model={spec.default_model}, key var={spec.api_key_vars[0]})"
        )

    kev_settings = load_settings(provider="kev")
    print(
        "load_settings(provider='kev') ->"
        f" provider={kev_settings.provider}"
        f" base_url={kev_settings.base_url} model={kev_settings.model}"
    )

    register_provider(
        ProviderSpec(
            key="acme",
            display_name="Acme (third-party example)",
            default_base_url="http://localhost:9000",
            api_key_vars=("ACME_API_KEY", "TYPESAFE_API_KEY"),
            base_url_vars=("ACME_BASE_URL", "TYPESAFE_BASE_URL"),
            default_model="acme-latest",
            model_vars=("ACME_MODEL",),
            notes=(
                "Registered by examples/providers_example.py to demo the"
                " extension API."
            ),
        )
    )
    print(
        "after register_provider:"
        f" {', '.join(spec.key for spec in list_providers())}"
    )

    # The injected transport removes the key requirement entirely; the ask
    # below never leaves this process.
    with open_client(
        "kev",
        api_key=kev_settings.api_key,
        model=args.model or kev_settings.model,
        transport=CannedTransport(),
    ) as client:
        response = client.ask(STATE, QUESTIONS)

    print(f"model={response.model}  request_id={response.request_id}")
    for qid, answer in response.answers.items():
        print(f"  {qid}: {json.dumps(dataclasses.asdict(answer), sort_keys=True)}")
    print("extra top-level 'latency_ms' was parsed and ignored")
    print(
        f"usage: {response.usage.input_tokens} input /"
        f" {response.usage.output_tokens} output tokens"
    )


if __name__ == "__main__":
    main()
