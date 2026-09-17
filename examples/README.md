# daf-jev examples

Five runnable scripts showing the core patterns of the toolkit. Each script:

- resolves credentials with `daf_jev.load_settings()` — from `JEV_API_KEY`
  or `TYPESAFE_API_KEY` (env or a `.env` file in the current directory);
- prints `SKIP: JEV_API_KEY not set` and exits 0 when no key is found
  (the `.env` key is never printed);
- accepts `--model NAME` to override the model (default: `JEV_MODEL`,
  then `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`);
- writes nothing to disk and prints its results.

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

## Notes

- Optional helpers are imported defensively, so a checkout mid-build that
  lacks them fails with a clear message instead of a raw traceback.
- Network calls go to `JEV_BASE_URL` / `TYPESAFE_BASE_URL`
  (default `https://api.typesafe.ai`). All five scripts are offline-safe:
  without a key they do nothing but print the SKIP line.
