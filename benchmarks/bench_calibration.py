#!/usr/bin/env python3
"""Confidence calibration and noul stability of the live model.

For each of N short distinct states, the same three-option choice question
(sentiment/urgency classification) is asked R times — one call per repeat,
so each repeat yields an independent answer. Per state, the modal choice
across repeats acts as a self-consistency correctness proxy (agreement with
the majority choice, not ground truth); the (confidence, correct) pairs feed
the expected calibration error, the Brier score, and a reliability table
from daf_jev.calibration. A noul question is repeated the same way; its
stability metric is the mean pairwise |Δnoul| across repeats per state,
averaged over states.

Writes output/benchmarks/calibration_<YYYYMMDD>.json and prints a compact
per-state table. Skips gracefully (exit 0) when JEV_API_KEY is not set; a
failing call drops that state's repeats and is counted in ``n_errors``.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from itertools import combinations
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _util import settings_or_skip, write_result  # noqa: E402
from daf_jev import JevClient, choice, noul  # noqa: E402
from daf_jev.calibration import (  # noqa: E402
    brier_score,
    expected_calibration_error,
    reliability_table,
)

STATES: tuple[str, ...] = (
    "The login page returns a 500 error for every user since this morning's deploy.",
    "Customers praise the new dashboard layout in this quarter's feedback round.",
    "The export button spins for a while and then produces an empty CSV file.",
    "Invoice totals are off by one cent whenever the cart holds more than five items.",
    "The team finished the database migration ahead of schedule and with no downtime.",
    "A handful of users report slow search results during peak hours only.",
)

CHOICE_ID = "sentiment"
CHOICE_OPTIONS = {
    "praise": "positive feedback; nothing is broken",
    "urgent_issue": "a blocking defect needing prompt attention",
    "minor_issue": "a small defect or annoyance with a workaround",
}
NOUL_ID = "resolved"
NOUL_INSTRUCTIONS = "Is the situation described in the report already fully resolved?"


def choice_questions() -> dict[str, object]:
    """The single three-option classification question for one state call."""
    return {
        CHOICE_ID: choice(
            "Classify the overall sentiment and urgency of this report.",
            CHOICE_OPTIONS,
        )
    }


def noul_questions() -> dict[str, object]:
    """The single yes/no question for one state call."""
    return {NOUL_ID: noul(NOUL_INSTRUCTIONS)}


def collect_answers(
    client: JevClient, repeats: int
) -> tuple[dict[int, list], dict[int, list], int]:
    """Run R independent calls per state for both question kinds.

    Returns per-state answer lists for the choice and noul questions plus an
    error count. On the first failing call for a state, that state's repeats
    are dropped entirely from both metrics.
    """
    choice_answers: dict[int, list] = {i: [] for i in range(len(STATES))}
    noul_answers: dict[int, list] = {i: [] for i in range(len(STATES))}
    n_errors = 0
    for repeat in range(repeats):
        for i, state in enumerate(STATES):
            if i not in choice_answers:
                continue  # state already dropped after an earlier error
            try:
                choice_answers[i].append(
                    client.ask(state, choice_questions()).answers[CHOICE_ID]
                )
                noul_answers[i].append(
                    client.ask(state, noul_questions()).answers[NOUL_ID]
                )
            except Exception as exc:  # graceful: drop the state, keep benching
                choice_answers.pop(i, None)
                noul_answers.pop(i, None)
                n_errors += 1
                print(f"  state {i}: call failed ({type(exc).__name__}: {exc}); "
                      f"its repeats are excluded")
    return choice_answers, noul_answers, n_errors


def choice_metrics(choice_answers: dict[int, list]) -> dict:
    """ECE, Brier score, and reliability table over modal-agreement pairs."""
    pairs: list[tuple[float, bool]] = []
    for answers in choice_answers.values():
        modal = Counter(a.choice for a in answers).most_common(1)[0][0]
        pairs.extend((a.confidence, a.choice == modal) for a in answers)
    return {
        "ece": round(expected_calibration_error(pairs), 4),
        "brier": round(brier_score(pairs), 4),
        "buckets": reliability_table(pairs),
    }


def mean_pairwise_gap(noul_answers: dict[int, list]) -> float | None:
    """Mean pairwise |Δnoul| per state, averaged over states."""
    per_state = []
    for answers in noul_answers.values():
        values = [a.noul for a in answers]
        gaps = [abs(x - y) for x, y in combinations(values, 2)]
        if gaps:
            per_state.append(mean(gaps))
    return round(mean(per_state), 4) if per_state else None


def print_table(
    choice_answers: dict[int, list], noul_answers: dict[int, list]
) -> None:
    """Compact per-state summary: modal choice, agreement, mean confidence."""
    print(f"{'state':>5}  {'n':>3}  {'modal choice':<14}  {'agree':>6}  "
          f"{'mean conf':>9}  {'mean noul':>9}  {'gap':>7}")
    for i in sorted(choice_answers):
        answers = choice_answers[i]
        modal = Counter(a.choice for a in answers).most_common(1)[0][0]
        agree = sum(a.choice == modal for a in answers) / len(answers)
        noul_mean = mean(a.noul for a in noul_answers[i])
        values = [a.noul for a in noul_answers[i]]
        gaps = [abs(x - y) for x, y in combinations(values, 2)]
        gap = mean(gaps) if gaps else 0.0
        print(f"{i:>5}  {len(answers):>3}  {modal:<14}  {agree:>6.2f}  "
              f"{mean(a.confidence for a in answers):>9.3f}  {noul_mean:>9.3f}  "
              f"{gap:>7.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--states", type=int, default=6,
                        help="number of distinct states to classify (default 6)")
    parser.add_argument("--repeats", type=int, default=5,
                        help="independent repeats per state (default 5)")
    parser.add_argument("--model", default="jev-latest",
                        help="model id (default jev-latest)")
    args = parser.parse_args(argv)
    if not 1 <= args.states <= len(STATES):
        parser.error(f"--states must be between 1 and {len(STATES)}")

    settings = settings_or_skip()
    if settings is None:
        return 0

    states = STATES[: args.states]
    with JevClient(api_key=settings.api_key, base_url=settings.base_url,
                   model=args.model) as client:
        print(f"calibration: model={args.model} states={args.states} "
              f"repeats={args.repeats}")
        choice_answers, noul_answers, n_errors = collect_answers(
            client, args.repeats
        )

    if not choice_answers:
        print("all states failed; no calibration metrics computed")
        return 1

    choice_summary = choice_metrics(choice_answers)
    gap = mean_pairwise_gap(noul_answers)
    payload = {
        "name": "calibration",
        "date": date.today().isoformat(),
        "model": args.model,
        "states": args.states,
        "repeats": args.repeats,
        "choice": choice_summary,
        "noul_stability": {"mean_pairwise_gap": gap},
        "n_errors": n_errors,
        "notes": "correctness proxy = agreement with modal choice "
                 "(self-consistency), not ground truth",
    }

    print_table(choice_answers, noul_answers)
    print(f"choice calibration: ECE={choice_summary['ece']:.4f}  "
          f"Brier={choice_summary['brier']:.4f}")
    print(f"noul stability: mean_pairwise_gap={gap if gap is not None else 'N/A'}")
    if n_errors:
        print(f"errors: {n_errors} state(s) excluded after failing calls")
    path = write_result("calibration", payload)
    print(f"results: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
