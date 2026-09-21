#!/usr/bin/env python3
"""End-to-end latency of two daf_jev decision patterns over the live API.

- composite-score pipeline: one Score call -> composite_score -> confidence_gate
  (docs/reference/patterns/composite-scoring.md + confidence-routing.md)
- intent routing: one Choice call -> route() to a trivial handler
  (docs/reference/patterns/confidence-routing.md)

Reports p50/p95 wall seconds over --runs repetitions of each pipeline. With
--async the same runs execute concurrently through AsyncJevClient +
asyncio.gather and the total wall time is compared against the sequential run.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path
from time import perf_counter

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _util import latency_summary, settings_or_skip, write_result  # noqa: E402

from daf_jev import (  # noqa: E402
    AsyncJevClient,
    JevClient,
    choice,
    composite_score,
    confidence_gate,
    route,
    score,
)

TICKET_STATE = (
    "Support ticket #4821 from Dana Okafor (workspace: Northwind Logistics, plan: "
    "Pro). 'Our weekly KPI export has failed since Tuesday with error code EXP-412. "
    "We present these numbers to the board on Monday, so this is urgent. Billing "
    "renewal already went through on the 3rd and our two new analysts are still "
    "waiting on seat invitations from last week.'"
)

QUALITY_ID = "export_quality"
QUALITY_QUESTION = {QUALITY_ID: score(
    "How would you rate the customer's message as input for a support triage "
    "workflow: how specific, complete, and actionable is it?",
    [
        "Poor: vague complaint, no specifics.",
        "Fair: some detail but missing key facts.",
        "Good: clear and mostly complete.",
        "Excellent: specific, complete, and actionable.",
    ],
)}

INTENT_STATE = (
    "Voice command from account 7731: 'I placed an order last Thursday and was "
    "charged twice. I also can't log in after the site update. Can you look into "
    "the duplicate charge first?'"
)

INTENT_ID = "intent"
INTENT_QUESTION = {INTENT_ID: choice(
    "What is the customer's primary request?",
    {
        "billing": "Charges, invoices, refunds, subscriptions.",
        "account": "Login, permissions, profile, security.",
        "feature": "The customer is requesting new functionality.",
        "other": "Something else entirely.",
    },
)}

HANDLERS = {
    "billing": lambda: "handler:billing",
    "account": lambda: "handler:account",
    "feature": lambda: "handler:feature",
}
FALLBACK = lambda: "handler:human"  # noqa: E731


def pipeline_composite(client: JevClient) -> tuple[float, int, dict]:
    """One Score call -> composite_score -> confidence_gate."""
    started = perf_counter()
    response = client.ask(TICKET_STATE, QUALITY_QUESTION)
    answer = response.answers[QUALITY_ID]
    composite = composite_score(answer)
    verdict = confidence_gate(answer, threshold=0.6)
    wall = perf_counter() - started
    tokens = response.usage.input_tokens + response.usage.output_tokens
    return wall, tokens, {"composite": round(composite, 4), "gate": verdict}


def pipeline_routing(client: JevClient) -> tuple[float, int, dict]:
    """One Choice call -> route() to a trivial handler."""
    started = perf_counter()
    response = client.ask(INTENT_STATE, INTENT_QUESTION)
    answer = response.answers[INTENT_ID]
    outcome = route(answer, HANDLERS, min_confidence=0.6, fallback=FALLBACK)
    wall = perf_counter() - started
    tokens = response.usage.input_tokens + response.usage.output_tokens
    return wall, tokens, {"choice": answer.choice, "routed": outcome}


def measure(pipeline, client, runs: int) -> dict:
    walls, tokens, last = [], 0, {}
    for _ in range(runs):
        wall, tok, info = pipeline(client)
        walls.append(wall)
        tokens += tok
        last = info
    return {**latency_summary(walls), "tokens": tokens, "last_decision": last}


def run_async(settings, model: str, runs: int) -> tuple[float, int]:
    """All runs of both pipelines concurrently via AsyncJevClient + gather."""

    async def a_composite(client):
        response = await client.ask(TICKET_STATE, QUALITY_QUESTION)
        answer = response.answers[QUALITY_ID]
        composite_score(answer)
        confidence_gate(answer, threshold=0.6)
        return response.usage.input_tokens + response.usage.output_tokens

    async def a_routing(client):
        response = await client.ask(INTENT_STATE, INTENT_QUESTION)
        answer = response.answers[INTENT_ID]
        route(answer, HANDLERS, min_confidence=0.6, fallback=FALLBACK)
        return response.usage.input_tokens + response.usage.output_tokens

    async def gather_all():
        client = AsyncJevClient(api_key=settings.api_key, base_url=settings.base_url,
                                model=model)
        try:
            started = perf_counter()
            tokens = await asyncio.gather(
                *(a_composite(client) for _ in range(runs)),
                *(a_routing(client) for _ in range(runs)),
            )
            return perf_counter() - started, sum(tokens)
        finally:
            await client.close()

    return asyncio.run(gather_all())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=10,
                        help="repetitions per pipeline (default 10)")
    parser.add_argument("--model", default="jev-latest",
                        help="model id (default jev-latest)")
    parser.add_argument("--async", dest="use_async", action="store_true",
                        help="also run all repetitions concurrently via "
                             "AsyncJevClient + asyncio.gather and compare")
    args = parser.parse_args(argv)

    settings = settings_or_skip()
    if settings is None:
        return 0

    composite: dict = {}
    routing: dict = {}
    with JevClient(api_key=settings.api_key, base_url=settings.base_url,
                   model=args.model) as client:
        composite = measure(pipeline_composite, client, args.runs)
        routing = measure(pipeline_routing, client, args.runs)

    payload = {
        "name": "patterns",
        "date": date.today().isoformat(),
        "model": args.model,
        "runs": args.runs,
        "composite_score_pipeline": composite,
        "intent_routing": routing,
    }

    async_concurrency = None
    if args.use_async:
        wall, tokens = run_async(settings, args.model, args.runs)
        sequential_wall = composite["mean_s"] * args.runs + routing["mean_s"] * args.runs
        async_concurrency = {
            "wall_s": round(wall, 4),
            "sequential_wall_s": round(sequential_wall, 4),
            "speedup_ratio": round(sequential_wall / wall, 3),
            "total_tokens": tokens,
        }
        payload["async_concurrency"] = async_concurrency

    path = write_result("patterns", payload)

    print(f"patterns: model={args.model} runs={args.runs}")
    print(f"{'pipeline':<26}{'runs':>5}  {'mean_s':>8}  {'p50_s':>8}  {'p95_s':>8}  {'tok':>8}")
    for label, row in (("composite_score", composite), ("intent_routing", routing)):
        print(f"{label:<26}{row['runs']:>5}  {row['mean_s']:>8.4f}  "
              f"{row['p50_s']:>8.4f}  {row['p95_s']:>8.4f}  {row['tokens']:>8,}")
    if async_concurrency is not None:
        print(
            f"async concurrency: wall={async_concurrency['wall_s']:.4f}s  "
            f"sequential={async_concurrency['sequential_wall_s']:.4f}s  "
            f"speedup={async_concurrency['speedup_ratio']:.2f}x  "
            f"tok={async_concurrency['total_tokens']:,}"
        )
    print(f"results: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
