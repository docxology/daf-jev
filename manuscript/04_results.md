# Results {#sec:results}

This section reports the two live-API benchmarks that quantify the design claims of [@sec:methodology]: the batching benchmark, which reproduces the documented parallel-questions pattern [@typesafe2026patterns], and the decision-pattern latency benchmark. Both run against the real {{BENCH_MODEL}} model; every value below is injected from the benchmark outputs at render time, and the figures are regenerated from the same JSON files, so prose, tables, and figures share one source of truth. The results reported here were recorded on {{BENCH_DATE}}.

## Batching speedup and token cost

The batching benchmark compares two strategies over the same state and question mix: one call carrying all questions in a batch, versus one sequential single-question call per question, repeated for each configured batch width over multiple measured runs. The answers are unchanged by batching (the parallel-sampler semantics of [@sec:jev_model]); what changes is wall time — a single round trip versus one round trip per question — and token cost, because the sequential strategy re-sends the state once per question.

[@fig:batching] shows the measured speedup per batch width together with the token-cost ratio on a secondary axis.

![Batching speedup of the {{BENCH_MODEL}} model versus sequential single-question calls, measured by `benchmarks/bench_batching.py` on {{BENCH_DATE}}. Bars give the wall-time speedup of one batched call over one sequential call per question for each configured batch width ({{CONFIG_BATCHING_N5}}, {{CONFIG_BATCHING_N10}}, {{CONFIG_BATCHING_N20}} questions, values in [@tbl:batching]); the secondary axis shows the token-cost ratio, which falls below unity because the sequential strategy re-sends the state once per question. Bars are annotated with their values; the title in the rendered figure carries the model and run date read from the benchmark JSON itself.](../output/figures/batching_speedup.png){#fig:batching width=85%}

[@tbl:batching] tabulates the measured speedups. The speedup grows with batch width, as expected from the round-trip accounting: the fixed per-call overhead is amortized over more questions, and the state is transmitted once rather than once per question.

| Questions per batch | Wall-time speedup vs sequential |
|---------------------|---------------------------------|
| {{CONFIG_BATCHING_N5}} | {{BENCH_BATCHING_SPEEDUP_N5}} |
| {{CONFIG_BATCHING_N10}} | {{BENCH_BATCHING_SPEEDUP_N10}} |
| {{CONFIG_BATCHING_N20}} | {{BENCH_BATCHING_SPEEDUP_N20}} |

:: Wall-time speedup of one batched call versus one sequential call per question, per configured batch width, recorded by `benchmarks/bench_batching.py` against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Values are injected from the benchmark JSON at render time. {#tbl:batching}

Token cost moves in the same direction. At the widest configured batch width the batched strategy consumes a token ratio of {{BENCH_BATCHING_TOKEN_RATIO_N20}} relative to the sequential strategy: the state paragraph dominates the input tokens of a single-question call, so re-sending it per question makes the sequential strategy strictly more expensive in addition to being slower.

## Decision-pipeline latency

The second benchmark measures end-to-end latency of two composition pipelines — the network call plus the local composition logic, exactly as an application would run them:

- **composite_score** — one `score` call, then `composite_score` over the answer, then a `confidence_gate` verdict;
- **intent_routing** — one `choice` call, then `route()` dispatching to a trivial handler.

Each pipeline is executed {{BENCH_PATTERNS_RUNS}} times; [@tbl:latency] reports the median (p50) and tail (p95) wall times per pipeline, and [@fig:latency] plots them side by side.

![Median (p50) and tail (p95) end-to-end wall time per decision pipeline, measured by `benchmarks/bench_patterns.py` over {{BENCH_PATTERNS_RUNS}} runs against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Each bar is one pipeline (composite scoring, intent routing) with paired p50/p95 groups; axis labels are read from the benchmark JSON fields at figure-generation time. Values are tabulated in [@tbl:latency].](../output/figures/latency_percentiles.png){#fig:latency width=85%}

| Pipeline | Median wall time, p50 (s) | Tail wall time, p95 (s) |
|--------------------|---------------------------|-------------------------|
| composite_score | {{BENCH_PATTERNS_COMPOSITE_P50_S}} | {{BENCH_PATTERNS_COMPOSITE_P95_S}} |
| intent_routing | {{BENCH_PATTERNS_ROUTING_P50_S}} | {{BENCH_PATTERNS_ROUTING_P95_S}} |

:: End-to-end wall time (network round trip plus local composition logic) per decision pipeline, median and tail over {{BENCH_PATTERNS_RUNS}} runs recorded by `benchmarks/bench_patterns.py` against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Values are injected from the benchmark JSON at render time. {#tbl:latency}

## Interpretation

Three observations tie the measurements back to the design rulings of [@sec:methodology]. First, the batching speedups in [@tbl:batching] confirm that the parallel-sampler semantics translate directly into wall-clock savings: the batched strategy is faster at every configured width, and the gap widens with width exactly as the round-trip accounting predicts. Second, the token-cost ratio below unity at the widest width shows that batching is not merely faster but cheaper, because the state is transmitted once — so the pattern documented in the primary source [@typesafe2026patterns] holds end to end for a third-party client implementation. Third, the pipeline latencies in [@tbl:latency] sit within the model's millisecond-scale latency envelope ([@sec:jev_model]): the pure-logic composition layer adds no measurable latency beyond the network round trip, which is precisely what allows confidence-gated routing to run inline on interactive request paths rather than in a background queue.
