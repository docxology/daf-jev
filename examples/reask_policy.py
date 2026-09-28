"""Re-ask policy: sidecar posteriors drive the next question (pipeline
step 5 as a decision-policy input).

Demonstrates:
- ingesting a ``dafjev.bayesnet-posteriors/1`` sidecar written by the
  GNN bridge (the Julia ``--out`` artifact re-entering daf-jev)
- building a :class:`~daf_jev.reask.ReAskPlan`: next variable =
  max Shannon entropy (bits) among not-yet-asked variables, ties broken
  by sidecar insertion order
- feeding the plan into a decision step: the max-entropy variable
  becomes the ``choice`` question the ticket loop asks next, and the
  answer routes through ``route`` with a fallback -- the ask wiring
  lives HERE, the plan itself never constructs Jev calls
- the injected-transport seam: a scripted canned transport, zero network
- the SKIP contract: exits 0 with no JEV_API_KEY before any network use

Run: python examples/reask_policy.py [--model NAME]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import httpx

from daf_jev import (
    ChoiceAnswer,
    JevClient,
    RetryPolicy,
    choice,
    load_settings,
)
from daf_jev.bayesnet_posteriors import load_posteriors
from daf_jev.compose import route
from daf_jev.reask import next_question, reask_plan

# The GNN bridge's --out sidecar: posteriors over the triage dimensions,
# evidence observed so far (the replay context). Written to a temp file
# and ingested through the real loader -- the same fail-closed path the
# CLI and MCP seams use.
SIDECAR = {
    "format": "dafjev.bayesnet-posteriors/1",
    # Evidence rows must be one-hot (the loader's rule), so the observed
    # variable carries a degenerate posterior row alongside the live ones.
    "evidence": {"customer_tier": "enterprise"},
    "posteriors": {
        "customer_tier": {"enterprise": 1.0, "consumer": 0.0},
        "category": {"billing": 0.25, "technical": 0.25, "account": 0.25, "other": 0.25},
        "urgency": {"low": 0.7, "high": 0.3},
        "sentiment": {"calm": 0.5, "frustrated": 0.5},
    },
}


class ScriptedTransport:
    """Canned Transport serving one queued choice response per ask."""

    def __init__(self) -> None:
        self.queue: list[dict] = []

    def enqueue(self, payload: dict) -> None:
        self.queue.append(payload)

    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        payload = self.queue.pop(0)
        return httpx.Response(
            200,
            json=payload,
            headers={"x-typesafe-request-id": "canned-reask-0000"},
        )

    def close(self) -> None:
        return None


def _answers_payload(variable: str, choice_label: str) -> dict:
    """A wire-shaped SystemOneResponse answering the plan's question."""
    return {
        "model": "kev-latest",
        "answers": {
            variable: {
                "type": "choice",
                "choice": choice_label,
                "probabilities": {choice_label: 0.9},
                "confidence": 0.9,
            },
        },
        "usage": {"input_tokens": 42, "output_tokens": 7},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Max-entropy re-ask policy over a posterior sidecar."
    )
    parser.add_argument("--model", default=None, help="model name override")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    with tempfile.TemporaryDirectory() as tmp:
        sidecar_path = Path(tmp) / "sidecar.json"
        sidecar_path.write_text(json.dumps(SIDECAR), encoding="utf-8")
        sidecar = load_posteriors(sidecar_path)

        asked: set[str] = set()
        transport = ScriptedTransport()
        transport.enqueue(_answers_payload("category", "billing"))
        transport.enqueue(_answers_payload("sentiment", "frustrated"))
        transport.enqueue(_answers_payload("urgency", "low"))
        transport.enqueue(_answers_payload("customer_tier", "enterprise"))

        with JevClient(
            api_key=settings.api_key,
            model=args.model or settings.model,
            transport=transport,
            retry=RetryPolicy(max_attempts=1),
        ) as client:
            while True:
                # Pipeline step 5: the sidecar's posterior rows decide the
                # NEXT question -- max entropy among not-yet-asked rows.
                plan = reask_plan(sidecar, asked=asked)
                variable = plan.next_question
                if variable is None:
                    break
                entropy = plan.entropy
                print(
                    f"re-ask: {variable} (entropy {entropy:.3f} bits, "
                    f"evidence replayed: {json.dumps(plan.evidence)})"
                )

                # The decision-policy input becomes a real Jev ask HERE
                # (example-layer wiring; the plan never builds calls).
                response = client.ask(
                    f"support ticket; observed evidence: "
                    f"{json.dumps(dict(plan.evidence))}",
                    {
                        variable: choice(
                            f"Which {variable} fits this ticket best?",
                            dict.fromkeys(sidecar.posteriors[variable]),
                        )
                    },
                )
                answer = response.answers[variable]
                if not isinstance(answer, ChoiceAnswer):
                    raise TypeError(f"expected a choice answer for {variable}")
                asked.add(variable)

                # Dispatch on the answer with a confidence fallback --
                # the re-ask loop's action step.
                action = route(
                    answer,
                    {
                        "billing": lambda: "route to billing on-call",
                        "technical": lambda: "attach diagnostics",
                        "frustrated": lambda: "escalate to human triage",
                        "calm": lambda: "continue automated triage",
                        "low": lambda: "batch for the next triage run",
                        "high": lambda: "page the on-call owner",
                    },
                    min_confidence=0.6,
                    fallback=lambda: "general queue",
                )
                print(f"  -> choice={answer.choice} action={action}")

        # Exhausted: every posterior variable has been asked.
        final = reask_plan(sidecar, asked=asked)
        print(f"queue exhausted: next_question={final.next_question}")
        assert next_question(sidecar, asked=asked) is None


if __name__ == "__main__":
    main()
