# daf-jev examples

Eight runnable scripts showing the core patterns of the toolkit. Each script:

- resolves credentials with `daf_jev.load_settings()` — from `JEV_API_KEY`
  or `TYPESAFE_API_KEY` (env or a `.env` file in the current directory);
- prints `SKIP: JEV_API_KEY not set` and exits 0 when no key is found
  (the `.env` key is never printed);
- accepts `--model NAME` to override the model (default: provider-resolved
  — for the default `jev` provider: `JEV_MODEL`, then
  `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`);
- writes nothing to disk and prints its results (the one exception:
  `asia_bayes.py`, which writes `asia_graphspec.json`);

## Scripts

### `quickstart.py`

One mixed `ask` call with a noul (yes/no), a choice, and a score question;
pretty-prints every answer plus usage and request id.

```sh
python examples/quickstart.py [--model NAME]
```

### `triage_router.py`

One choice question routed two ways: `tiered_gate` assigns
automate/review/escalate from the answer's confidence (two thresholds),
then `route` dispatches to a label handler with a fallback.

```sh
python examples/triage_router.py [--model NAME]
```

### `composite_scoring.py`

One score question: `composite_score` computes the expected level value,
re-weighted by custom weights; `confidence_gate` then decides act vs.
escalate from the answer's confidence.

```sh
python examples/composite_scoring.py [--model NAME]
```

### `evaluate_corpus.py`

`Evaluator` runs a fixed question set over an inline four-state SMS corpus
with bounded concurrency (`--concurrency N`, default 2), printing each
state's choice or captured error plus the aggregate summary.

```sh
python examples/evaluate_corpus.py [--model NAME] [--concurrency N]
```

### `gated_fallback.py`

Heuristic-first triage: a deterministic keyword lexicon scores each demo
message as `(label, confidence)` over the same labels a `choice` question
uses. Confident heuristic results are used with no model call at all;
unsure messages fall back to `client.ask()`, whose answer then passes
through `confidence_gate` (`below="escalate"`) as the final escalation
lane. `UsageLedger` totals the requests and tokens the run actually spent.

```sh
python examples/gated_fallback.py [--model NAME]
```

### `decider_loop.py`

The decision-point loop as one `Decider`: typed hooks
(`render_state` / `questions` / `map_answers` / `fallback`), a
`ConfidenceGate` that rejects low-confidence answers into the fallback, a
`Budget(max_calls=...)` bounding the ask attempts, and a JSON `on_event`
receipt per decision (`model` / `cache` / `fallback` with a classified
reason). The floor action is a deterministic keyword-majority label over
the same lexicons the choice question uses. Prints each demo message's
action, the event log, and the usage snapshot.

```sh
python examples/decider_loop.py [--model NAME]
```

### `providers_example.py`

Multi-provider dispatch: prints the registered provider list
(`list_providers()`), resolves per-provider settings with
`load_settings(provider=...)`, registers a third-party `ProviderSpec` with
`register_provider`, then runs one ask through `open_client(...)` over an
in-process canned `Transport` — no server and no network call even when a
key is present. The canned response carries kev's extra top-level
`latency_ms` field to show strict-parse tolerance.

```sh
python examples/providers_example.py [--model NAME]
```

### `asia_bayes.py`

Jev as a factor source for a graphical model: builds the 8-variable Asia
net from `Variable` objects, runs `propose_structure` (one batched ask
over all 28 variable pairs; the proposed edges print for comparison with
the reference structure), then `elicit_cpts` over the reference Asia
structure — all 18 CPT rows in one batched ask — walks the posterior
trajectory from the Jev+GTSAM Asia experiment (priors, then
`asia=false`, then `+xray=true`, then `+dysp=true`, printing the
P(tub)/P(lung)/P(bronc) marginals at each step), and writes the elicited
net as GraphSpec (`dafjev.bayesnet/1`) to `asia_graphspec.json` in the
current directory. No network beyond the selected provider's endpoint.

```sh
python examples/asia_bayes.py [--provider KEY] [--model NAME]
```

## Notes

- Optional helpers are imported defensively, so a checkout mid-build that
  lacks them fails with a clear message instead of a raw traceback.
- Network calls go to the selected provider's base URL (for the default
  `jev` provider: `JEV_BASE_URL` / `TYPESAFE_BASE_URL`, default
  `https://api.typesafe.ai`). All eight scripts are offline-safe: without
  a key they do nothing but print the SKIP line;
  `providers_example.py` makes no network call even with one.
