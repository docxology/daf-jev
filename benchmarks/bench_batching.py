#!/usr/bin/env python3
"""Reproduce the parallel-questions batching claim from the TypeSafe docs.

Docs: docs/reference/cookbooks/parallel_questions.md — one call with N questions
vs N sequential single-question calls over the same state. The answers are the
same either way; what changes is wall time (one round trip vs N) and tokens
(the state is re-sent N times). This script measures both for N in {5, 10, 20}
over a short state and reports speedup / token-cost ratios.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from statistics import mean
from time import perf_counter

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _util import settings_or_skip, write_result  # noqa: E402

from daf_jev import JevClient, choice, noul, score  # noqa: E402

STATE = (
    "Acme Analytics is a cloud dashboard product. The Starter plan costs $9 per "
    "user per month and keeps 30 days of history. The Pro plan costs $29 per user "
    "per month, keeps 12 months of history, adds SSO, and includes email support "
    "with a 24-hour response target. Data is encrypted in transit and at rest, and "
    "customers in the EU are served from the Frankfurt region. The free trial lasts "
    "14 days and does not require a credit card. Acme reported 99.9% uptime over "
    "the past year, and scheduled maintenance is announced at least 48 hours in "
    "advance."
)


def build_questions() -> list[tuple[str, object]]:
    """20 real questions over STATE, interleaved so any prefix of 5/10/20
    spans all three kinds (noul / choice / score)."""
    nouls = [
        ("trial_card", noul("Can a customer start the free trial without a credit card?")),
        ("pro_sso", noul("Does the Pro plan include SSO?")),
        ("encrypted", noul("Is customer data encrypted both in transit and at rest?")),
        ("eu_region", noul("Are EU customers served from the Frankfurt region?")),
        ("maintenance_notice", noul("Is scheduled maintenance announced at least 48 hours in advance?")),
        ("starter_sso", noul("Does the Starter plan include SSO?")),
        ("starter_history_30d", noul("Does the Starter plan keep 30 days of history?")),
    ]
    choices = [
        ("trial_length", choice("How long is the free trial?", {
            "14 days": "The trial runs for 14 days.",
            "7 days": "The trial runs for 7 days.",
            "30 days": "The trial runs for 30 days.",
            "No trial": "There is no free trial.",
        })),
        ("pro_price", choice("What does the Pro plan cost per user per month?", {
            "$29": "Pro costs $29 per user per month.",
            "$9": "Pro costs $9 per user per month.",
            "$49": "Pro costs $49 per user per month.",
            "Custom": "Pro pricing is negotiated per customer.",
        })),
        ("starter_history", choice("How much history does the Starter plan keep?", {
            "30 days": "Starter keeps 30 days of history.",
            "12 months": "Starter keeps 12 months of history.",
            "6 months": "Starter keeps 6 months of history.",
            "Unlimited": "Starter keeps history indefinitely.",
        })),
        ("uptime", choice("What uptime did Acme report over the past year?", {
            "99.9%": "Reported uptime was 99.9%.",
            "99.99%": "Reported uptime was 99.99%.",
            "99.0%": "Reported uptime was 99.0%.",
            "95.0%": "Reported uptime was 95.0%.",
        })),
        ("eu_region_name", choice("Which region serves customers in the EU?", {
            "Frankfurt": "EU customers are served from Frankfurt.",
            "Ireland": "EU customers are served from Ireland.",
            "Virginia": "EU customers are served from Virginia.",
            "Sydney": "EU customers are served from Sydney.",
        })),
        ("support_target", choice("What is the support response target on the Pro plan?", {
            "24 hours": "Pro support responds within 24 hours.",
            "1 hour": "Pro support responds within 1 hour.",
            "72 hours": "Pro support responds within 72 hours.",
            "None": "Pro has no stated response target.",
        })),
        ("history_plan", choice("Which plan keeps 12 months of history?", {
            "Pro": "The Pro plan keeps 12 months of history.",
            "Starter": "The Starter plan keeps 12 months of history.",
            "Both": "Both plans keep 12 months of history.",
            "Neither": "No plan keeps 12 months of history.",
        })),
    ]
    scores = [
        ("trial_generosity", score("How generous is the free trial offering?", [
            "Harsh: very short and requires payment details.",
            "Modest: short trial, friction to start.",
            "Good: reasonable length, no card needed.",
            "Very generous: long trial with full features.",
        ])),
        ("security_posture", score("How strong is the described security posture?", [
            "Weak: no security claims.",
            "Basic: one measure mentioned.",
            "Strong: encryption in transit and at rest.",
            "Comprehensive: encryption plus regional isolation and attestations.",
        ])),
        ("pricing_transparency", score("How transparent is the pricing as described?", [
            "Opaque: no prices disclosed.",
            "Vague: rough ranges only.",
            "Clear: exact per-plan prices.",
            "Exhaustive: prices plus every included feature.",
        ])),
        ("enterprise_readiness", score("How ready is the product for large enterprises?", [
            "Not ready: consumer-grade only.",
            "Emerging: some features enterprises need.",
            "Ready: SSO, support targets, and history depth.",
            "Fully ready: adds compliance and dedicated support.",
        ])),
        ("maintenance_communication", score("How well is maintenance communicated to customers?", [
            "Not communicated: customers find out during downtime.",
            "Somewhat: ad hoc notices.",
            "Reliable: advance notice with a fixed lead time.",
        ])),
        ("plan_flexibility", score("How much choice do customers have between plans?", [
            "None: a single offering.",
            "Limited: plans differ only in price.",
            "Good: plans differ in price, history, and features.",
        ])),
    ]
    pool: list[tuple[str, object]] = []
    for i in range(20):
        source = (nouls, choices, scores)[i % 3]
        pool.append(source[i // 3])
    return pool


def run_batched(client: JevClient, questions: dict, runs: int) -> tuple[list[float], int, int]:
    walls, in_tok, out_tok = [], 0, 0
    for _ in range(runs):
        started = perf_counter()
        response = client.ask(STATE, questions)
        walls.append(perf_counter() - started)
        in_tok += response.usage.input_tokens
        out_tok += response.usage.output_tokens
    return walls, in_tok, out_tok


def run_singles(client: JevClient, questions: dict, runs: int) -> tuple[list[float], int, int]:
    """N sequential single-question calls per run; wall is the full round."""
    round_walls, in_tok, out_tok = [], 0, 0
    for _ in range(runs):
        started = perf_counter()
        for qid, question in questions.items():
            response = client.ask(STATE, {qid: question})
            in_tok += response.usage.input_tokens
            out_tok += response.usage.output_tokens
        round_walls.append(perf_counter() - started)
    return round_walls, in_tok, out_tok


def bench_n(client: JevClient, questions: dict, runs: int) -> dict:
    b_walls, b_in, b_out = run_batched(client, questions, runs)
    s_walls, s_in, s_out = run_singles(client, questions, runs)
    b_wall = mean(b_walls)
    s_wall = mean(s_walls)
    return {
        "n": len(questions),
        "batched": {
            "mean_wall_s": round(b_wall, 4),
            "input_tokens": b_in,
            "output_tokens": b_out,
        },
        "single": {
            "mean_total_wall_s": round(s_wall, 4),
            "input_tokens": s_in,
            "output_tokens": s_out,
        },
        "speedup_ratio": round(s_wall / b_wall, 3),
        "token_cost_ratio": round((s_in + s_out) / (b_in + b_out), 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3,
                        help="repeats per strategy per N (default 3)")
    parser.add_argument("--model", default="jev-latest",
                        help="model id (default jev-latest)")
    args = parser.parse_args(argv)

    settings = settings_or_skip()
    if settings is None:
        return 0

    pool = build_questions()
    rows = []
    with JevClient(api_key=settings.api_key, base_url=settings.base_url,
                   model=args.model) as client:
        for n in (5, 10, 20):
            rows.append(bench_n(client, dict(pool[:n]), args.runs))

    payload = {
        "name": "batching",
        "date": date.today().isoformat(),
        "model": args.model,
        "runs": args.runs,
        "state_chars": len(STATE),
        "results": rows,
    }
    path = write_result("batching", payload)

    print(f"batching: model={args.model} runs={args.runs} state={len(STATE)} chars")
    header = f"{'N':>3}  {'batched_s':>10}  {'single_s':>10}  {'speedup':>7}  {'batched_toks':>12}  {'single_toks':>12}  {'tok_ratio':>9}"
    print(header)
    for row in rows:
        print(
            f"{row['n']:>3}  {row['batched']['mean_wall_s']:>10.4f}  "
            f"{row['single']['mean_total_wall_s']:>10.4f}  "
            f"{row['speedup_ratio']:>7.2f}x  "
            f"{row['batched']['input_tokens'] + row['batched']['output_tokens']:>12,}  "
            f"{row['single']['input_tokens'] + row['single']['output_tokens']:>12,}  "
            f"{row['token_cost_ratio']:>9.2f}x"
        )
    print(f"results: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
