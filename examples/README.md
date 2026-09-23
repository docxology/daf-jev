# daf-jev examples

Eight runnable scripts showing the core patterns of the toolkit. Each script:

- resolves credentials with [`daf_jev.load_settings()`](../src/daf_jev/config.py) — from
  `JEV_API_KEY` or `TYPESAFE_API_KEY` (env or a `.env` file in the current
  directory);
- prints `SKIP: JEV_API_KEY not set` and exits 0 when no key is found
  (the `.env` key is never printed);
- accepts `--model NAME` to override the model (default: provider-resolved
  — for the default `jev` provider: `JEV_MODEL`, then
  `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`);
- writes nothing to disk and prints its results (the one exception:
  [`asia_bayes.py`](asia_bayes.py), which writes `asia_graphspec.json`).

## At a glance

| Example | What it teaches |
|---|---|
| [`quickstart.py`](quickstart.py) | One mixed `ask` call — noul, choice, and score questions, plus usage and request id. |
| [`triage_router.py`](triage_router.py) | Routing a choice answer by confidence: [`tiered_gate`](../src/daf_jev/compose.py) thresholds, then [`route`](../src/daf_jev/compose.py) dispatch with a fallback. |
| [`composite_scoring.py`](composite_scoring.py) | Scoring a score answer: [`composite_score`](../src/daf_jev/compose.py) with custom weights, then [`confidence_gate`](../src/daf_jev/compose.py) for act vs. escalate. |
| [`evaluate_corpus.py`](evaluate_corpus.py) | [`Evaluator`](../src/daf_jev/evaluate.py) over many states with bounded concurrency and per-state error capture. |
| [`gated_fallback.py`](gated_fallback.py) | Heuristic-first triage: spend no model call when confident, fall back to [`ask`](../src/daf_jev/client.py) plus [`confidence_gate`](../src/daf_jev/compose.py) when unsure. |
| [`decider_loop.py`](decider_loop.py) | The full [`Decider`](../src/daf_jev/decider.py) decision-point loop: hooks, gate, [`Budget`](../src/daf_jev/decider.py), and a JSON event receipt. |
| [`providers_example.py`](providers_example.py) | Multi-provider dispatch through the [`provider registry`](../src/daf_jev/providers.py) and a canned in-process `Transport`. |
| [`asia_bayes.py`](asia_bayes.py) | Jev as a factor source for a graphical model: structure proposal, one-ask CPT elicitation, exact inference, GraphSpec export. |

## Scripts

### [`quickstart.py`](quickstart.py)

One mixed `ask` call with a noul (yes/no), a choice, and a score question —
built with the [`primitives`](../src/daf_jev/primitives.py) builders;
pretty-prints every answer plus usage and request id.

```sh
python examples/quickstart.py [--model NAME]
```

### [`triage_router.py`](triage_router.py)

One choice question routed two ways: `tiered_gate` assigns
automate/review/escalate from the answer's confidence (two thresholds),
then `route` dispatches to a label handler with a fallback. Both live in
[`compose`](../src/daf_jev/compose.py).

```sh
python examples/triage_router.py [--model NAME]
```

### [`composite_scoring.py`](composite_scoring.py)

One score question: [`composite_score`](../src/daf_jev/compose.py) computes
the expected level value, re-weighted by custom weights;
[`confidence_gate`](../src/daf_jev/compose.py) then decides act vs.
escalate from the answer's confidence.

```sh
python examples/composite_scoring.py [--model NAME]
```

### [`evaluate_corpus.py`](evaluate_corpus.py)

[`Evaluator`](../src/daf_jev/evaluate.py) runs a fixed question set over an
inline four-state SMS corpus with bounded concurrency
(`--concurrency N`, default 2), printing each state's choice or captured
error plus the aggregate summary.

```sh
python examples/evaluate_corpus.py [--model NAME] [--concurrency N]
```

### [`gated_fallback.py`](gated_fallback.py)

Heuristic-first triage: a deterministic keyword lexicon scores each demo
message as `(label, confidence)` over the same labels a `choice` question
uses. Confident heuristic results are used with no model call at all;
unsure messages fall back to `client.ask()`, whose answer then passes
through [`confidence_gate`](../src/daf_jev/compose.py)
(`below="escalate"`) as the final escalation lane.
[`UsageLedger`](../src/daf_jev/ledger.py) totals the requests and tokens
the run actually spent.

```sh
python examples/gated_fallback.py [--model NAME]
```

### [`decider_loop.py`](decider_loop.py)

The decision-point loop as one [`Decider`](../src/daf_jev/decider.py):
typed hooks (`render_state` / `questions` / `map_answers` / `fallback`), a
`ConfidenceGate` that rejects low-confidence answers into the fallback, a
`Budget(max_calls=...)` bounding the ask attempts, and a JSON `on_event`
receipt per decision (`model` / `cache` / `fallback` with a classified
reason). The floor action is a deterministic keyword-majority label over
the same lexicons the choice question uses. Prints each demo message's
action, the event log, and the usage snapshot.

```sh
python examples/decider_loop.py [--model NAME]
```

### [`providers_example.py`](providers_example.py)

Multi-provider dispatch: prints the registered provider list
([`list_providers()`](../src/daf_jev/providers.py)), resolves per-provider
settings with [`load_settings(provider=...)`](../src/daf_jev/config.py),
registers a third-party `ProviderSpec` with
[`register_provider`](../src/daf_jev/providers.py), then runs one ask
through [`open_client(...)`](../src/daf_jev/client.py) over an in-process
canned `Transport` — no server and no network call even when a key is
present. The canned response carries kev's extra top-level `latency_ms`
field to show strict-parse tolerance.

```sh
python examples/providers_example.py [--model NAME]
```

### [`asia_bayes.py`](asia_bayes.py)

Jev as a factor source for a graphical model: builds the 8-variable Asia
net from [`Variable`](../src/daf_jev/graphical.py) objects, runs
[`propose_structure`](../src/daf_jev/graphical_elicitation.py) (one batched
ask over all 28 variable pairs; the proposed edges print for comparison
with the reference structure), then
[`elicit_cpts`](../src/daf_jev/graphical_elicitation.py) over the reference
Asia structure — all 18 CPT rows in one batched ask — walks the posterior
trajectory from the Jev+GTSAM Asia experiment (priors, then
`asia=false`, then `+xray=true`, then `+dysp=true`, printing the
P(tub)/P(lung)/P(bronc) marginals at each step), and writes the elicited
net as GraphSpec (`dafjev.bayesnet/1`) to `asia_graphspec.json` in the
current directory. No network beyond the selected provider's endpoint.

```sh
python examples/asia_bayes.py [--provider KEY] [--model NAME]
```

The elicited net's method-level what-if surfaces live in
[`graphical.py`](../src/daf_jev/graphical.py):
`most_probable_explanation(evidence)` (most probable joint assignment
consistent with the evidence; deterministic lexicographic tiebreak),
`sample(n, rng=None)` (ancestral sampling in topological order), and
`conditional_scenarios(variable, evidence=None, targets=None)`
(per-state posterior marginals of the targets).

#### Committed experiment artifacts

The committed artifact set in `output/experiments/asia/` was produced by the
thin experiment runner [`scripts/bayes_experiment.py`](../scripts/bayes_experiment.py)
(default `--out-dir output/experiments/asia`) with `--propose-structure`
against the `openrouter` provider — see the run's
[`receipts.json`](../output/experiments/asia/receipts.json). All five
artifacts:

| Artifact | What it is |
|---|---|
| [`asia_graphspec.json`](../output/experiments/asia/asia_graphspec.json) | The elicited net as GraphSpec (`dafjev.bayesnet/1`) — the interchange input for the GNN/RxInfer.jl bridge. |
| [`network.png`](../output/experiments/asia/network.png) | Layered layout of the net ([`plot_network`](../src/daf_jev/graphical_viz.py)). |
| [`posterior_trajectory.png`](../output/experiments/asia/posterior_trajectory.png) | Grouped P(true) bars across the evidence walkthrough ([`plot_posterior_trajectory`](../src/daf_jev/graphical_viz.py)). |
| [`mermaid.txt`](../output/experiments/asia/mermaid.txt) | `graph TD` source of the net the experiment actually used (the reference edges). |
| [`receipts.json`](../output/experiments/asia/receipts.json) | The live receipt: provider, model, proposed edges, elicited CPTs, and the posterior trajectory. |

The trajectory under cumulative evidence — priors → `asia=false` →
`+xray=true` → `+dysp=true` — moves P(tub) 0.120 → 0.371 → 0.434
(values from [`receipts.json`](../output/experiments/asia/receipts.json);
P(lung) 0.131 → 0.389 → 0.460, P(bronc) 0.227 → 0.244 → 0.322).
For animation, the thin runner
[`scripts/bayes_experiment.py`](../scripts/bayes_experiment.py) takes
`--animate`: after the five artifacts it writes `posterior_animation.gif`
and `network_animation.gif` into `--out-dir` and records them under
`animations` in `receipts.json`.

The GraphSpec hand-off continues in the GNN repo's RxInfer bridge
([PR #165](https://github.com/ActiveInferenceInstitute/Generalized_Notation_Notation/pull/165))
— see the root [`README.md`](../README.md#jev-to-rxinferjl-pipeline) for
the end-to-end pipeline. (The bridge repo is a separate checkout; its paths
are not relative links from here.)

## Notes

- Optional helpers are imported defensively, so a checkout mid-build that
  lacks them fails with a clear message instead of a raw traceback.
- Network calls go to the selected provider's base URL (for the default
  `jev` provider: `JEV_BASE_URL` / `TYPESAFE_BASE_URL`, default
  `https://api.typesafe.ai`). All eight scripts are offline-safe: without
  a key they do nothing but print the SKIP line;
  [`providers_example.py`](providers_example.py) makes no network call even
  with one.
