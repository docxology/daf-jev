"""Asia Bayes net: Jev as a factor source for graphical models.

Demonstrates:
- building the 8-variable Asia net from ``Variable`` objects
- ``propose_structure``: the topology from one batched ask over all 28
  variable pairs (printed for comparison with the reference structure)
- ``elicit_cpts``: every CPT of the whole network — all 18 parent-assignment
  rows — in ONE batched ask against the selected provider
- exact local inference: the posterior walkthrough from the Jev+GTSAM Asia
  experiment — priors, then ``asia=false``, then ``+xray=true``, then
  ``+dysp=true`` — printing the tub/lung/bronc trajectory
- ``BayesNet.to_json()``: the GraphSpec interchange (``dafjev.bayesnet/1``),
  written to ``asia_graphspec.json``

No network beyond the selected provider's System One endpoint.

Run: python examples/asia_bayes.py [--provider KEY] [--model NAME]
"""

from __future__ import annotations

import argparse
import json

from daf_jev import (
    BayesNet,
    Edge,
    Variable,
    elicit_cpts,
    load_settings,
    open_client,
    propose_structure,
)

# The reference Asia structure (Lauritzen-Spiegelhalter); each child's
# parent set matches the CPTs the posterior walkthrough conditions on.
ASIA_EDGES = [
    Edge("asia", "tub"),
    Edge("smoke", "lung"),
    Edge("smoke", "bronc"),
    Edge("lung", "either"),
    Edge("tub", "either"),
    Edge("either", "xray"),
    Edge("either", "dysp"),
    Edge("bronc", "dysp"),
]

# Short clinical phrases; they drive the elicitation's state text.
ASIA_VARIABLES = [
    Variable("asia", "Recently visited Asia?", ("false", "true")),
    Variable("tub", "Has tuberculosis", ("false", "true")),
    Variable("smoke", "Is a smoker", ("false", "true")),
    Variable("lung", "Has lung cancer", ("false", "true")),
    Variable("bronc", "Has bronchitis", ("false", "true")),
    Variable("either", "Has tuberculosis or lung cancer", ("false", "true")),
    Variable("xray", "Abnormal X-ray result", ("false", "true")),
    Variable("dysp", "Has dyspnoea (shortness of breath)", ("false", "true")),
]

WALKTHROUGH = [
    ("priors", {}),
    ("asia=false", {"asia": "false"}),
    ("asia=false, xray=true", {"asia": "false", "xray": "true"}),
    (
        "asia=false, xray=true, dysp=true",
        {"asia": "false", "xray": "true", "dysp": "true"},
    ),
]


def print_marginals(label: str, evidence: dict[str, str], net: BayesNet) -> None:
    print(f"\nevidence [{label}]")
    for key in ("tub", "lung", "bronc"):
        marginal = net.query(key, evidence)
        print(f"  P({key}=true) = {marginal[1]:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Asia Bayes net from Jev factors.")
    parser.add_argument("--provider", default="jev", help="provider key (default: jev)")
    parser.add_argument("--model", default=None, help="model name override")
    args = parser.parse_args()

    settings = load_settings(provider=args.provider)
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    pairs = len(ASIA_VARIABLES) * (len(ASIA_VARIABLES) - 1) // 2
    with open_client(
        args.provider,
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=args.model or settings.model,
    ) as client:
        print(f"provider={args.provider}  model={args.model or settings.model}")

        proposed = propose_structure(ASIA_VARIABLES, client=client)
        print(f"\npropose_structure: {len(proposed.edges)} edges proposed "
              f"({pairs} pair questions)")
        for edge in proposed.edges:
            print(f"  {edge.parent}->{edge.child}")
        print("(propose_structure returns edges only; elicit_cpts fills the CPTs)")

        net = elicit_cpts(ASIA_VARIABLES, ASIA_EDGES, client=client)
        rows = sum(len(cpt.table) for cpt in net.cpts.values())
        print(f"\nelicit_cpts: {len(net.cpts)} CPTs, {rows} rows, one batched ask")

        for label, evidence in WALKTHROUGH:
            print_marginals(label, evidence, net)

        with open("asia_graphspec.json", "w", encoding="utf-8") as fh:
            json.dump(net.to_json(), fh, indent=2)
        print("\nwrote asia_graphspec.json (format dafjev.bayesnet/1)")


if __name__ == "__main__":
    main()
