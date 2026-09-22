#!/usr/bin/env python3
"""Asia Bayes experiment: Jev factors -> structure -> CPTs -> trajectory.

Thin orchestrator over ``daf_jev.graphical`` (the net engine),
``daf_jev.graphical_elicitation`` (batched Jev asks) and
``daf_jev.graphical_viz`` (mermaid + PNG artifacts) — ALL logic lives in
the src modules; this script only wires arguments, the provider client,
stdout output, and exit codes.

Steps:
  1. build the eight Asia variables (the canonical binary fixture text)
  2. structure step: the reference Asia edge list — or, with
     ``--propose-structure``, a ``propose_structure`` run whose proposal
     is printed against the reference edges; either way the mermaid
     diagram of the resulting structure goes to stdout and the CPT step
     continues with the REFERENCE edges (the reproducible choice,
     matching examples/asia_bayes.py)
  3. CPT step: ``elicit_cpts`` over the reference edges — one batched ask
  4. posterior walkthrough: ``priors`` -> ``asia=false`` ->
     ``+xray=true`` -> ``+dysp=true``, printed as a P(true) table for
     tub/lung/bronc ("true" = the last state of each variable's states
     tuple — the same binary convention ``plot_posterior_trajectory``
     charts)
  5. artifacts into ``--out-dir`` (default ``output/experiments/asia``):
     ``asia_graphspec.json`` (GraphSpec ``dafjev.bayesnet/1``),
     ``network.png`` (``plot_network``), ``posterior_trajectory.png``
     (``plot_posterior_trajectory``), and ``mermaid.txt`` (the mermaid
     source of the net the experiment actually used — the reference
     edges)

Keyless: prints ``SKIP: JEV_API_KEY not set`` and exits 0 BEFORE any
network use (checked via ``load_settings(provider=...)``). Plotting needs
the ``figures`` extra (matplotlib): ``uv sync --extra figures``.

Options:
    --provider KEY          daf-jev provider key (default: jev)
    --model NAME            optional model override
    --edge-penalty FLOAT    structure-proposal penalty (default 1.0;
                            only used with --propose-structure)
    --propose-structure     run propose_structure and print the proposal
                            against the reference edges (CPTs still use
                            the reference edges)
    --out-dir PATH          artifact directory (default output/experiments/asia)

Exit codes:
    0   success (including the keyless SKIP run)
    1   real error (the exception propagates; its traceback is the only
        stderr output)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _candidate in (_PROJECT_ROOT, _PROJECT_ROOT / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

# Canonical Asia fixture text (same strings as examples/asia_bayes.py and
# the unit tests; binary states, Lauritzen-Spiegelhalter reference edges).
_ASIA_STATES = ("false", "true")
ASIA_VARIABLE_SPECS = (
    ("asia", "Recently visited Asia?"),
    ("tub", "Has tuberculosis"),
    ("smoke", "Is a smoker"),
    ("lung", "Has lung cancer"),
    ("bronc", "Has bronchitis"),
    ("either", "Has tuberculosis or lung cancer"),
    ("xray", "Abnormal X-ray result"),
    ("dysp", "Has dyspnoea (shortness of breath)"),
)
ASIA_EDGE_SPECS = (
    ("asia", "tub"),
    ("smoke", "lung"),
    ("smoke", "bronc"),
    ("lung", "either"),
    ("tub", "either"),
    ("either", "xray"),
    ("either", "dysp"),
    ("bronc", "dysp"),
)
WALKTHROUGH = (
    ("priors", {}),
    ("asia=false", {"asia": "false"}),
    ("asia=false, xray=true", {"asia": "false", "xray": "true"}),
    (
        "asia=false, xray=true, dysp=true",
        {"asia": "false", "xray": "true", "dysp": "true"},
    ),
)
QUERY_KEYS = ("tub", "lung", "bronc")


def main() -> int:
    """Parse args, run the experiment, write artifacts; exit 0."""
    from daf_jev import (
        BayesNet,
        Edge,
        Variable,
        elicit_cpts,
        load_settings,
        open_client,
        propose_structure,
    )
    from daf_jev.graphical_viz import (
        plot_network,
        plot_posterior_trajectory,
        to_mermaid,
    )

    parser = argparse.ArgumentParser(
        description="Asia Bayes experiment from Jev factors (graphical models)."
    )
    parser.add_argument(
        "--provider", default="jev", help="daf-jev provider key (default: jev)"
    )
    parser.add_argument("--model", default=None, help="model name override")
    parser.add_argument(
        "--edge-penalty",
        type=float,
        default=1.0,
        help="edge penalty for --propose-structure (default: 1.0)",
    )
    parser.add_argument(
        "--propose-structure",
        action="store_true",
        help="propose the topology via pairwise choices and print it against "
        "the reference edges (CPTs are still elicited over the reference edges)",
    )
    parser.add_argument(
        "--out-dir",
        default="output/experiments/asia",
        help="artifact directory (default: output/experiments/asia)",
    )
    args = parser.parse_args()

    # Provider precedence mirrors the CLI: --provider flag > DAF_JEV_PROVIDER
    # env > "jev" (falsy env values are skipped, same truthiness as config).
    provider = args.provider
    if provider == "jev":
        from daf_jev.config import load_dotenv

        env_hint = {**load_dotenv(), **os.environ}
        provider = env_hint.get("DAF_JEV_PROVIDER") or "jev"

    settings = load_settings(provider=provider)
    if settings.api_key is None:
        from daf_jev import get_provider

        spec = get_provider(provider)
        print(f"SKIP: {spec.api_key_vars[0]} not set")
        return 0

    variables = tuple(
        Variable(key, description, _ASIA_STATES)
        for key, description in ASIA_VARIABLE_SPECS
    )
    edges = tuple(Edge(parent, child) for parent, child in ASIA_EDGE_SPECS)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open_client(
        provider,
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=args.model or settings.model,
    ) as client:
        print(f"provider={provider}  model={args.model or settings.model}")

        structure_edges = edges
        if args.propose_structure:
            proposed = propose_structure(
                variables, client=client, edge_penalty=args.edge_penalty
            )
            print(
                f"\npropose_structure: {len(proposed.edges)} edges proposed "
                f"({len(variables) * (len(variables) - 1) // 2} pair questions, "
                f"edge_penalty={args.edge_penalty})"
            )
            print("proposal vs reference edges:")
            for edge in proposed.edges:
                print(f"  proposed  {edge.parent}->{edge.child}")
            for edge in edges:
                print(f"  reference {edge.parent}->{edge.child}")
            print("continuing with the reference edges for CPT elicitation")
            structure_edges = proposed.edges
            proposed_edges = [[e.parent, e.child] for e in proposed.edges]
        else:
            print(f"\nstructure: reference Asia edges ({len(edges)} edges)")
            proposed_edges = []

        structure = BayesNet(variables=variables, edges=structure_edges, cpts={})
        print(
            f"\nmermaid diagram of the "
            f"{'proposed' if args.propose_structure else 'reference'} structure:"
        )
        print(to_mermaid(structure))

        net = elicit_cpts(variables, edges, client=client)
        rows = sum(len(cpt.table) for cpt in net.cpts.values())
        print(f"\nelicit_cpts: {len(net.cpts)} CPTs, {rows} rows, one batched ask")

        width = max(len(label) for label, _evidence in WALKTHROUGH)
        header = "step".ljust(width) + "  " + "  ".join(
            f"{key:>5}" for key in QUERY_KEYS
        )
        print("\nP(true) trajectory (true = last state):")
        print(header)
        for label, evidence in WALKTHROUGH:
            marginals = net.posterior(evidence)
            cells = "  ".join(
                f"{marginals[key][-1]:.3f}" for key in QUERY_KEYS
            )
            print(label.ljust(width) + "  " + cells)

        spec_path = out_dir / "asia_graphspec.json"
        with open(spec_path, "w", encoding="utf-8") as fh:
            json.dump(net.to_json(), fh, indent=2)
        network_path = plot_network(net, out_dir / "network.png")
        trajectory_path = plot_posterior_trajectory(
            net,
            QUERY_KEYS,
            [evidence for _label, evidence in WALKTHROUGH],
            out_dir / "posterior_trajectory.png",
            labels=[label for label, _evidence in WALKTHROUGH],
        )
        mermaid_path = out_dir / "mermaid.txt"
        mermaid_path.write_text(to_mermaid(net) + "\n", encoding="utf-8")

        receipts_path = out_dir / "receipts.json"
        with receipts_path.open("w", encoding="utf-8") as fh:
            json.dump(
                {
                    "provider": provider,
                    "model": args.model or settings.model,
                    "proposed_structure_used": args.propose_structure,
                    "proposed_edges": proposed_edges,
                    "cpts_elicited": sorted(net.cpts),
                    "posterior_trajectory": {
                        label: {
                            key: net.query(key, dict(evidence))[-1]
                            for key in QUERY_KEYS
                        }
                        for label, evidence in WALKTHROUGH
                    },
                },
                fh,
                indent=2,
            )
            fh.write("\n")

        print(f"\nwrote {receipts_path}")
        print(f"wrote {spec_path} (format dafjev.bayesnet/1)")
        print(f"wrote {network_path}")
        print(f"wrote {trajectory_path}")
        print(f"wrote {mermaid_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())