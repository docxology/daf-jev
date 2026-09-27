"""Calibration walkthrough: Decider calibration_pairs() into calibration stats.

Demonstrates:
- ``Decider`` wired with a ``ConfidenceGate`` so each ``decide()`` records a
  ``(declared confidence, gate-accepted)`` pair (``decider.calibration_pairs()``)
- feeding those pairs into ``daf_jev.calibration``: ``bucket_index``,
  ``reliability_table``, ``expected_calibration_error``, ``brier_score``
- the injected-transport seam: canned choice answers with deterministic
  per-call confidences, so both accepted and gate-rejected pairs exist and
  the whole run performs NO network

NOTE: these pairs are a self-consistency proxy, NOT ground-truth
correctness. ``gate-accepted`` means "declared confidence >= threshold",
not "the answer was right". ECE and Brier here measure agreement between
the model's confidence and the gate, not real accuracy calibration.

Run: python examples/calibration_walkthrough.py [--model NAME]
     [--threshold FLOAT] [--buckets INT]
"""

from __future__ import annotations

import argparse
import json

import httpx

from daf_jev import (
    ConfidenceGate,
    Decider,
    JevClient,
    RetryPolicy,
    choice,
    load_settings,
)

CONFIDENCES = [0.93, 0.88, 0.81, 0.72, 0.65, 0.58]

CAVEAT = (
    "NOTE: pairs are (declared confidence, gate-accepted) — a self-consistency"
    " proxy, NOT ground-truth correctness."
)


class CannedTransport:
    """Minimal Transport returning canned choice answers (no network)."""

    def __init__(self, confidences: list[float]) -> None:
        self._confidences = confidences
        self._call = 0

    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        confidence = self._confidences[self._call % len(self._confidences)]
        self._call += 1
        payload = {
            "model": "canned-model",
            "answers": {
                "intent": {
                    "type": "choice",
                    "choice": "refund",
                    "probabilities": {"refund": 0.7, "escalate": 0.3},
                    "confidence": confidence,
                }
            },
            "usage": {"input_tokens": 42, "output_tokens": 7},
        }
        return httpx.Response(
            200,
            json=payload,
            headers={"x-typesafe-request-id": "canned-0000"},
        )

    def close(self) -> None:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decider calibration_pairs() into calibration statistics."
    )
    parser.add_argument("--model", default=None, help="model name override")
    parser.add_argument(
        "--threshold", type=float, default=0.75, help="gate confidence threshold"
    )
    parser.add_argument(
        "--buckets", type=int, default=4, help="reliability-table bucket count"
    )
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    client = JevClient(
        api_key=settings.api_key,
        model=args.model or settings.model,
        transport=CannedTransport(CONFIDENCES),
        retry=RetryPolicy(max_attempts=1),
    )
    decider = Decider(
        client,
        render_state=json.dumps,
        questions=lambda _state: {
            "intent": choice("What should we do?", {"refund": "send money back"})
        },
        map_answers=lambda _state, response: response.answers["intent"].choice,
        fallback=lambda _state: "unsure",
        gate=ConfidenceGate("intent", threshold=args.threshold),
    )

    for i in range(len(CONFIDENCES) * 2):
        state = {"ticket": f"T-{1000 + i}", "body": "customer wants a refund"}
        print(f"decide({state['ticket']}) -> {decider.decide(state)}")

    pairs = decider.calibration_pairs()
    print(f"\ncollected {len(pairs)} calibration pairs: {pairs}")
    print(CAVEAT)

    from daf_jev.calibration import (
        brier_score,
        bucket_index,
        expected_calibration_error,
        reliability_table,
    )

    print(f"\nbucket_index(0.93, n_buckets={args.buckets}) ="
          f" {bucket_index(0.93, n_buckets=args.buckets)}")
    print("\nreliability table:")
    print("  bucket range      n  mean_confidence  accuracy")
    for row in reliability_table(pairs, n_buckets=args.buckets):
        print(
            f"  [{row['bucket_lo']:.2f}, {row['bucket_hi']:.2f})"
            f"  {row['n']:>3}  {row['mean_confidence']:.3f}"
            f"           {row['accuracy']:.3f}"
        )
    ece = expected_calibration_error(pairs, n_buckets=args.buckets)
    brier = brier_score(pairs)
    print(f"\nexpected_calibration_error = {ece:.4f}")
    print(f"brier_score = {brier:.4f}")
    print(f"\nusage: {decider.usage_snapshot().to_dict()}")


if __name__ == "__main__":
    main()
