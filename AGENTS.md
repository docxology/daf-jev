# AGENTS.md — daf-jev

Agent-facing notes. For the human-facing overview see `README.md`; for the
authoritative design contract see `docs/ARCHITECTURE.md` (single source of
truth; workers must match its current signatures exactly and report any
contradiction rather than silently deviating).

This is a **self-versioned** git repo at
`projects/platform/hum-docxology/repos/public/daf-jev` — a managed Docxology
checkout (each checkout there owns its own git history and upstream; the
hum-docxology worktree intentionally ignores nested checkouts). Container
rules live in `../../AGENTS.md` (the `repos/` checkout container) — do not
restate them here; there is no `../AGENTS.md` in this location.

## Layout

- `src/daf_jev/` — the package (src layout, uv-managed):
  - `_types.py` — frozen wire dataclasses (`NoulQuestion` / `ChoiceQuestion` /
    `ScoreQuestion`, answers, `Usage`, `SystemOneResponse` with `nouls` /
    `choices` / `scores` views), `parse_response` (strict).
  - `_errors.py` — exception hierarchy mirroring the official SDK
    (`TypeSafeError` base, `APIStatusError` subclasses per status code,
    `error_from_status`).
  - `_retry.py` — `RetryPolicy` (429/529, exponential backoff + jitter,
    `Retry-After` aware); pure `next_delay`, sleeping happens in the client.
  - `_json.py` — `strict_json_loads`: preserves insertion order, rejects
    duplicate object keys at every depth, nonstandard NaN/Infinity literals and
    numbers overflowing the selected float/Decimal parser. Finite Decimal
    currency values retain their exact digits; consumers enforce numeric bounds.
    Decoder recursion failures become `ValueError` for the malformed-response
    path; no fixed nesting limit is imposed by this helper.
  - `_yaml.py` — `strict_yaml_loads`: a private safe loader for literal frozen
    benchmark/manuscript configuration. Duplicate mapping keys, including
    collisions after merge expansion, aliases, unsafe tags and nonfinite numbers
    fail before planning or generation; global PyYAML behavior is unchanged.
  - `_cancellation.py` — private recovery of explicitly owned cancellation
    evidence through task/timeout exception chaining. It stops at the current
    owned origin and rejects unrelated handled exception context. It does not
    change cancellation state or infer usage, billing or transport arrival.
  - `_http.py` — `Transport` / `AsyncTransport` protocols +
    `HttpxTransport` / `AsyncHttpxTransport`.
  - `client.py` — `JevClient` / `AsyncJevClient` (`ask`, `models`, `close`,
    context-manager support), `ModelCard`. `ask` takes per-call `timeout` /
    `request_headers` (per-call entries win); retry policy and default
    timeout resolve from env (`config.resolve_retry` / `resolve_timeout`)
    unless passed explicitly. Provider dispatch: `for_provider`
    classmethods + `open_client` / `open_async_client` (see
    `providers.py`). Strict decoder failures on successful HTTP responses
    propagate as `ValueError`; malformed error bodies retain raw text (or None
    when empty) and the HTTP status exception taxonomy.
  - `primitives.py` — `noul()` / `choice()` / `score()` builders and
    `QuestionSet` (no I/O).
  - `compose.py` — `composite_score`, `confidence_gate`, `route`,
    `tiered_gate`, `pick` (pure logic, no I/O).
  - `evaluate.py` — `Evaluator` / `EvaluationRecord`: concurrent evaluation
    of a fixed question set over many states (thread pool for the sync
    client, `asyncio.Semaphore` for the async client); per-state failures
    captured in `EvaluationRecord.error`, never aborting the batch.
    `evaluate()` / `summary()` / `to_json()`; `evaluate_async()` awaits on the
    caller's loop. Both evaluation entry points close an async client at batch
    end, including cancellation; this legacy single-use lifecycle is intentional.
  - `models.py` — `pick_model(cards, *, contains=None, prefer="latest")`;
    pure selection over the models listing (no I/O); `ValueError` on empty
    input, no match after filtering, or unknown `prefer`.
  - `benchmark_allocation.py` — explicit shared hosted allowance, exact
    `LegacyRunBinding` imports, cross-run reservation/reconciliation and
    allocation execution lease. Hosted runner manifests must bind an existing
    allocation; planning/reporting never initialize or import one. Unknown
    billing remains stopped even for zero-tariff attempts. See
    `docs/shared_allocations.md` and the authoritative benchmark contract.
  - `figures.py` — matplotlib figure registry: 8 core named figures
    (`architecture`, `primitives`, `batching`, `latency`, `confidence`,
    `calibration`, `graphical_abstract`, `admission`) plus six opt-in empirical
    study figures and `figure_registry.json` emission;
    data-driven figures read the exact receipts selected and hash-verified by
    `manuscript/evidence.json` through `evidence.py`, never an independently
    chosen newest file.
  - `manuscript_variables.py` — `generate_variables` / `save_variables`: 66
    `{{TOKEN}}` manuscript variables derived from pyproject, docs MANIFEST,
    test counts, benchmark JSONs, and the `manuscript/config.yaml`
    experiment knobs (`BATCHING_RUNS`, `CALIBRATION_STATES`,
    `CALIBRATION_REPEATS`; `CONFIG_BATCHING_N<n>` token names derive from
    the configured batch widths); zero hardcoded result values. Benchmark inputs
    use the same explicit `manuscript/evidence.json` selection as figures.
    Verification inputs must match the source and tests being described; see
    the coverage and manuscript invariants below. Optional selected native
    verification exports supply recorded counts/coverage/environment without
    running pytest collection or reading raw coverage during regeneration.
  - `config.py` — `load_dotenv`, `resolve_api_key` (injected env >
    process env > `.env`; `JEV_API_KEY` then `TYPESAFE_API_KEY`),
    `resolve_base_url`, `resolve_model`, `resolve_retry` /
    `resolve_timeout` (env overrides, see README table), `Settings` /
    `load_settings` (optional `provider=` selection).
  - `providers.py` — provider registry (no I/O): frozen `ProviderSpec`,
    `register_provider` / `get_provider` / `list_providers`, per-provider
    api-key/base-URL/model resolvers delegating to `config._lookup`;
    built-ins registered at import in order: jev, jeff, kev, localjev,
    openthai-systemone, openrouter. Provider keys are stable API (see
    invariants).
  - `ledger.py` — thread-safe usage accounting: `UsageLedger.record(
    Usage | SystemOneResponse | None)` (None is a silent no-op; anything
    else raises `TypeError`), `snapshot()` / `reset()` returning a frozen
    JSON-safe `UsageSnapshot` (incl. `total_tokens`).
  - `resilience.py` — opt-in `CircuitBreaker` (closed/open/half_open);
    `call()` and awaited `call_async()` record a failure on any `BaseException`
    and always re-raise, including cancellation; async success is recorded only
    after completion, so a HALF_OPEN probe cannot wedge the breaker;
    `CircuitOpenError.remaining_seconds` is always a float >= 0 (`0.0` for
    the probe-rejection race). Not wired into `JevClient` by default.
  - `decider.py` — `Decider` observe -> compose -> ask -> gate -> fail-open
    -> act loop (`decide()` never raises), `DecisionEvent` (JSON-safe
    `to_dict()`), `ConfidenceGate` (finite non-bool thresholds/confidences in
    `[0,1]`), `Budget` (thresholds validated >= 0, `max_calls=0` stays valid);
    11-reason closed fallback taxonomy with
    `error` LAST (belt-and-suspenders); a client factory that raises OR
    returns None latches `client_error`; `cache_key` computed once per
    decide. Paid usage/request IDs survive mapping and gate fallbacks; the
    mapping-failure latch resets only after a full successful pipeline.
  - `cli.py` — stdlib argparse: `ask`, `models` (`--pick latest|first|last`,
    `--contains STR`), `evaluate` (`--questions-file`, `--states-file`,
    `--concurrency`, `--model`, `--include-records`), `docs-verify`, `serve`
    (`--transport stdio` — the only choice), `posteriors-load` (FILE +
    optional `--graphspec`; validates a `dafjev.bayesnet-posteriors/1` or
    `gnn.marginals/1` sidecar, keyless), `posteriors-reask` (FILE +
    optional `--graphspec` + repeatable `--asked VAR`; prints the
    max-entropy re-ask plan JSON, `dafjev.bayesnet-posteriors/1` sidecars
    only, keyless), `providers` (registry listing;
    global `--provider` flag); JSON to stdout, exit 0/1/2.
  - `mcp_server.py` — FastMCP server (`build_server` / `main`): tools
    `jev_ask`, `jev_evaluate`, `jev_models`, `jev_composite_score`,
    `jev_confidence_gate`, `jev_tiered_gate`, `jev_docs_verify`,
    `jev_posteriors_load`, `jev_reask_plan` + the `jev://docs/snapshot`
    resource; stdio transport only; `jev_evaluate` / `jev_models` /
    `jev_posteriors_load` / `jev_reask_plan` are async;
    `jev_composite_score` validates finite non-negative probabilities
    (`ValueError`); imports `mcp` at module import (optional `mcp` extra
    — never import from core modules); every tool but
    `jev_posteriors_load` (sidecar ingest, no API call) and
    `jev_reask_plan` (posteriors sidecar re-ask plan, no API call) takes
    an optional `provider` argument (default `jev`).
  - `questions.py` — shared native question-mapping builder (no I/O):
    `question_from_mapping(value, *, context="question")` builds
    `NoulQuestion` / `ChoiceQuestion` / `ScoreQuestion` from a
    `{type, instructions, criteria}` mapping with strict validation and
    actionable `ValueError` messages; the CLI (`evaluate
    --questions-file`) and the MCP server (`jev_ask` / `jev_evaluate`)
    route native mappings through it (spec strings keep using
    `cli.parse_question_spec`).
  - `docs_verify.py` — shared read-only docs-snapshot manifest verifier:
    `verify_manifest(manifest_path)` re-hashes every listed page (sha256 +
    byte length), flags url→path mismatches as `drifted` and extra `.md`
    files as `added`; report `{manifest, pages, missing, drifted, added,
    ok}`. Routed through by `daf-jev docs-verify` and MCP
    `jev_docs_verify`; `DEFAULT_MANIFEST` is module-anchored to the repo
    checkout (installed copies fail — see the docs-verify battery note).
  - `calibration.py` — pure calibration statistics over `(confidence,
    correct)` pairs: `bucket_index`, `reliability_table`,
    `expected_calibration_error`, `brier_score`; no I/O.
  - `jaggedness.py` — model-jaggedness statistics (pure stdlib `math`):
    how far repeated answers to stochastic prompts stray from the stated
    uniform distribution. Fixtures `COIN` / `COIN_NOUL` / `D6`;
    `uniform_chi2` (chi-square + df + p via `chi2_sf`),
    `uniform_deviation` (max |Δp| from 1/k + total variation),
    `runs_test_z` / `max_streak` (serial structure), `position_slope`
    (order-rotation position bias), `noul_choice_delta` (same coin,
    noul vs choice). Entry `run_battery(client, fixtures, *, repeats=50,
    concurrent=32, timeout=None)` drives a duck-typed `ask` client and
    returns `{fixture: battery}` (floats rounded to 6 decimals);
    degeneracy is a reported finding, not an error. No I/O beyond the
    injected client. Live battery: `benchmarks/bench_jaggedness.py`.
  - `graphical.py` — discrete Bayes nets (`Variable`, `Edge`, `CPT`,
    `BayesNet`): graph helpers + deterministic `topological_order`,
    `validate()`, exact inference (`posterior` / `query`, pure-stdlib
    variable elimination, no numpy; zero-probability evidence —
    including partially and fully observed impossible evidence — raises),
    decision methods
    (`most_probable_explanation`, `sample`, `conditional_scenarios`),
    plus public `decompose_single_parent` (joint-preserving aux-chain
    decomposition; single-parent scoped to ORIGINAL nodes — the RxInfer
    5.5.x multi-parent `DiscreteTransition` stall mitigation),
    and the `dafjev.bayesnet/1` GraphSpec JSON round-trip — a
    cross-repo contract with the GNN bridge (see invariants).
  - `graphical_elicitation.py` — `elicit_cpts` (every CPT row of a net
    in one batched `choice` ask; deterministic ids, chunking via
    `max_questions_per_request`) and `propose_structure` (one batched
    ask over all variable pairs -> DAG proposal, edges only); both take
    any object with `.ask(state, questions)`. Await `elicit_cpts_async` /
    `propose_structure_async` on the caller's loop for caller-owned lifecycle;
    cancellation propagates without closing the client. The sync compatibility
    bridge closes a fresh async client after use. CPT rows remain as answered
    and must satisfy strict mass validation; no renormalization occurs. Structure
    search scores edge log-probability gain against the no-edge baseline; its
    intentional exact/greedy semantics are specified in the contract.
  - `graphical_viz.py` — `to_mermaid` (zero-dependency `graph TD`
    diagram), `plot_network` (layered topological-layout PNG),
    `plot_posterior_trajectory` (grouped P(true) bars across cumulative
    evidence steps; "true" = last state); matplotlib imports lazily
    inside the plotters (`figures` extra).
  - `graphical_animation.py` — `animate_posterior(net, query_keys,
    evidence_steps, path, *, labels=None, fps=1, dpi=110)` (grouped
    P(true) bars growing per cumulative evidence step; same
    P(true)-is-last-state convention as `plot_posterior_trajectory`)
    and `animate_network(net, evidence_steps, path, *, fps=1)`
    (layered network layout mirroring `plot_network`'s coordinate
    scheme, node fill color = P(true) at the step, coolwarm 0..1);
    GIF via PillowWriter; lazy matplotlib import with the
    figures-extra hint; fail-closed validation before any figure
    (`figures` extra).
  - `bayesnet_posteriors.py` — fail-closed ingest of GNN-emitted
    posterior sidecars: `load_posteriors(path, graphspec=None) ->
    PosteriorsSidecar` over the two sibling variants
    (`dafjev.bayesnet-posteriors/1` `{format, evidence, posteriors}` —
    raw Float64 rows, flat `1e-6` per-row row-sum budget, one-hot
    evidence rule; `gnn.marginals/1` `{format, marginals, source_model}`
    — 6-digit-rounded rows with the length-widened budget), optionally
    cross-checked against a `dafjev.bayesnet/1` GraphSpec;
    `pair_for_calibration(sidecar, assignments) -> CalibrationPairing`
    (calibration target pairing: `(confidence, correct)` pairs matching
    the `daf_jev.calibration` convention + per-variable soft multiclass
    Brier scores); `row_sum_deviations(sidecar)`. Exported at package
    root; surfaced as `daf-jev posteriors-load` and MCP
    `jev_posteriors_load`.
  - `reask.py` — max-entropy re-ask policy over posterior sidecars (pure
    compute, no I/O): `entropy_bits` (Shannon entropy in BITS/log2;
    negative or non-finite probabilities raise; rows drifting beyond the
    `ROW_SUM_TOLERANCE` budget raise with the deviation in the message
    and are never renormalized), `reask_plan` / `next_question`
    (max-entropy not-yet-asked variable over a
    `dafjev.bayesnet-posteriors/1` sidecar's posterior rows, ties by
    sidecar insertion order, `None` when exhausted; variant-B
    `gnn.marginals/1` sidecars rejected with both format strings named —
    no evidence to replay). The `ReAskPlan` frozen dataclass carries the
    sidecar's `evidence` verbatim; it never constructs Jev calls — the
    example layer (`examples/reask_policy.py`) wires the plan into the
    ask. Exported at package root; surfaced as `daf-jev
    posteriors-reask` and MCP `jev_reask_plan`.
  - `decision_backends.py` — frozen provider-neutral requests, predictions,
    capabilities and per-attempt receipts; sync/async protocols, explicit native
    System One/chat/letter HTTP adapters, priors and a threaded async bridge.
    Caller-owned lifecycle; generated labels have no invented beliefs or
    confidence. Probability source, meaning and correctness are distinct.
  - `benchmark_datasets.py` — prepared dataset validation, explicit public
    fetch/prepare, deterministic synthetic generation, grouped splits and pilot
    pools. Version-three synthetic inputs bind ordered presentations and
    complete matched Choice groups; controls are quality-only.
  - `benchmark_sampling.py` — exact shared timing sample packs, default `cohort`
    scope and explicit legacy `per_dataset` scope. The timing selector uses no
    targets conditional on the frozen supplied pools; upstream pilot
    stratification can use class/grade labels.
  - `benchmark_models.py` — train-only priors and optional sklearn comparators,
    plus exact synthetic rule references. Hard rule labels have no one-hot
    beliefs; analytical Bayes probabilities carry explicit formula provenance.
  - `benchmark_metrics.py` — quality, calibration, repeatability, grouped
    uncertainty and dataset audits over supplied rows, retaining all planned
    outcomes and unknown probability meaning/cost.
  - `benchmark_policies.py` — validation-only gate fitting, descriptive offline
    policy replay and bounded synthetic entropy controls. Replay is not an
    executed cascade or measured end-to-end policy latency.
  - `benchmark_store.py` — immutable manifests, hash-linked journal/head,
    executor leases and durable hosted reservation/reconciliation. Unresolved
    liability blocks admission; copied evidence is inspected read-only.
  - `benchmark_runner.py` — explicit plan/run/resume/report, catalog snapshots,
    frozen cohorts/settings and phase barriers. Unresolved starts are never
    automatically replayed; failed/unsupported/unattempted remain denominators.
    Graphical summaries use the same journal-derived status as main cells.
    Reports bind dataset configuration ID/index/prepared SHA separately from the
    family name and retain all frozen arms, including wholly unavailable arms.
    Attempted-outcome coverage and planned-decision coverage remain distinct.
  - `benchmark_workflows.py` — actual weak/gate/strong cascade execution through
    injected backends and retained child receipts; supplied backends stay
    caller-owned and enclosing cells measure execution latency.
  - `benchmark_resources.py` — hardware identity and scoped sampled process RSS
    and elapsed time. Serving PID/create-time is explicit; no process launch or
    signal. Sampled RSS is not continuous or true Metal allocator peak memory.
  - `benchmark_graphical.py` — injected async reference-graph reconstruction,
    structure proposal and coupled oracle evidence acquisition/re-asks. Genuine
    beliefs are required; normalized surrogate factors do not establish CPT
    truth, causal discovery or calibrated probability meaning.
  - `benchmark_publication.py` — exclusive offline Markdown/PDF exports from
    frozen benchmark reports, preserving identities and partial outcomes.
    Export success does not establish execution or publication acceptance.
  - `benchmark_cli.py` — thin `benchmark` argparse dispatcher for dataset,
    catalog, plan, run, resume and report commands; no implicit fetch.
  - `evidence.py` — confined, nonsymlink, SHA-256-bound historical publication
    input selection shared by figures and manuscript variables. The private
    helper name `_latest_benchmark` does not mean date-based discovery.
    `selected_benchmark_bytes` consumes the exact bytes it verifies; path-based
    compatibility helpers do not provide that single-read guarantee.
    `verification_inputs`, `VerificationStatistics` and `selected_verification`
    bind retained unit/JUnit/coverage/live-collection evidence to the exact
    source/test/script/config inventory; malformed/stale explicit selection
    fails even in draft mode. Live collection does not execute live tests.
  - `__init__.py` — public exports listed in `docs/ARCHITECTURE.md`.
- `tests/` — `conftest.py` (stub-server fixtures, see below), `tests/unit/`
  (per module plus CLI, scraper, and the evaluate/models/figures/
  manuscript_variables, calibration, and mcp_server modules, plus
  test_graphical.py, test_graphical_elicitation.py,
  test_graphical_viz.py, test_graphical_methods.py,
  test_graphical_animation.py, test_bayesnet_posteriors.py, and
  test_reask.py),
  `tests/live/test_live_api.py` (2 tests, `@pytest.mark.live`). Generated
  counts live in `output/data/manuscript_variables.json` (test_count /
  coverage, refresh via `scripts/z_generate_manuscript_variables.py`).
- `scripts/scrape_docs.py` — standalone stdlib re-scraper for the docs
  snapshot; CLI: `--index-url`, `--out-dir`, `--check`, `--manifest PATH`
  (or positional MANIFEST; `--manifest` requires `--check`), `--timeout`.
  Plain mode prunes snapshot pages the fresh manifest does not list
  (`prune_orphans`; receipt under `"pruned"` in the summary line) — the
  snapshot dir stays an exact manifest mirror. `--check` alone fetches remotely
  and writes nothing; `--check --manifest PATH` (or positional manifest)
  re-hashes local pages without network or writes.
- `scripts/generate_figures.py` — thin orchestrator over `figures.py`;
  CLI: `--out-dir DIR` (default `output/figures`), `--only NAME`; needs the
  `figures` extra (`uv sync --extra figures`). Exit 0 ok, 2 unknown
  `--only`, 1 unexpected error.
- `scripts/z_generate_manuscript_variables.py` — thin orchestrator over
  `manuscript_variables.py`; writes `output/data/manuscript_variables.json`
  and (inside the template checkout) substitutes `{{TOKEN}}`s into
  `output/manuscript/`. `--allow-draft` permits `N/A` fallbacks when
  analysis outputs are missing.
- `scripts/capture_verification.py` — genuine unit coverage/JUnit + live
  collection capture into `--out-dir FRESH_INSIDE_ROOT`. Retains native exports,
  logs, before/after inventories and failed captures; removes only its owned
  private raw coverage. Does not execute live tests or select publication inputs.
- `scripts/render_pdf.py` — in-repo PDF render (pandoc --natbib over the
  generated token map; inputs `manuscript/render/{preamble,cover}.tex`);
  runs the render gates (zero unresolved bibtex entries / undefined refs /
  unloadable images / overfull vertical boxes; `SOURCE_DATE_EPOCH` pinned from
  HEAD). `--output FILE` selects a fresh standalone PDF; `--artifacts-dir DIR`
  exclusively retains intermediate Markdown/TeX/log inputs in a fresh directory.
  `--install` also replaces the root PDF and requires publication-scope
  authorization. Inspect all headings/prose and page layout after the gates.
- `scripts/bayes_experiment.py` — thin orchestrator over `graphical` +
  `graphical_elicitation` + `graphical_viz` + `graphical_animation`;
  CLI: `--provider`, `--model`, `--edge-penalty FLOAT` (default 1.0),
  `--propose-structure` (prints the proposal, continues with the
  reference edges), `--animate` (writes `posterior_animation.gif` +
  `network_animation.gif` into `--out-dir` after the five artifacts and
  records them under `animations` in `receipts.json`), `--out-dir`
  (default `output/experiments/asia`); writes `asia_graphspec.json`,
  `network.png`, `posterior_trajectory.png`, `mermaid.txt`, and
  `receipts.json` (per-run provenance: provider/model, proposed edges,
  elicited CPTs, posterior trajectory); keyless SKIP.
- `examples/` — thirteen runnable walkthroughs (`quickstart.py`,
  `triage_router.py`, `composite_scoring.py`, `evaluate_corpus.py`,
  `gated_fallback.py`, `decider_loop.py`, `providers_example.py`,
  `asia_bayes.py`, `decider_resilience.py`, `evaluate_async.py`,
  `calibration_walkthrough.py`, `retry_policies.py`, `reask_policy.py`) +
  `README.md`; each
  prints `SKIP: JEV_API_KEY not set`
  and exits 0 without a key (see invariants); `providers_example.py` makes
  no network call even with a key (injected transport); `asia_bayes.py`
  builds the Asia net from Jev factors (elicit + propose against the
  selected provider), walks the posterior trajectory, and writes
  `asia_graphspec.json`.
- `skills/` — agent-facing skill docs: `daf-jev/SKILL.md` (frontmatter +
  Markdown skill) + `daf-jev/README.md` (per-skill install + pointers) +
  `README.md` (skill-tree install notes). Documentation only — never
  imported by code.
- `manuscript/` — 10 sections (`00_abstract.md` …
  `08_scope_and_related_work.md`, `99_references.md`) + `preamble.md` +
  `config.yaml` + `references.bib`
  (31 entries). Prose only: every measured number is a `{{TOKEN}}`
  placeholder (see invariants).
- `manuscript/render/` — render inputs for the in-repo PDF fallback
  (`preamble.tex`, `cover.tex`), consumed by `scripts/render_pdf.py`.
- `benchmarks/` — historical/live-API scripts plus explicit frozen benchmark
  recipes in `configs/`, documented in `benchmarks/README.md`;
  `_util.py` holds shared SKIP/percentile/JSON-writer helpers. Planning and
  reporting are inference-free; fetch/catalog and actual execution are explicit.
- `docs/ARCHITECTURE.md` — contract (see `docs/README.md`); it now covers
  clients, composition, provider dispatch, graphical methods, posterior
  interchange, decision backends, datasets/sampling, accounting, benchmarks
  and publication/reproduction scripts. The map above is a quick inventory;
  authoritative signatures and failure semantics live in the contract.
- `docs/models.md` — sourced model technical reference (see `docs/README.md`).
- `docs/reference/` — hashed docs snapshot (see `docs/README.md`).
- `output/` — build artifacts, not documentation: `benchmarks/` (result
  JSONs), `figures/` (8 core PNGs, opt-in study figures, vector PDF companions
  and `figure_registry.json`), `data/`
  (`manuscript_variables.json`), `manuscript/` (token-substituted sections),
  `pdf/` (`daf-jev_combined.pdf`), `reports/` (template validation reports,
  rendered provenance), `experiments/` (Asia run:
  `output/experiments/asia/` — `asia_graphspec.json`, `network.png`,
  `posterior_trajectory.png`, `mermaid.txt`, `receipts.json`; the
  cross-repo artifacts, see Cross-repo pipeline below). `web/` —
  `_combined_manuscript.md`, the template-render combined manuscript
  (tracked in git, not gitignored; verified 2026-09-24).
- `pyproject.toml` — setuptools build, version 0.7.0, `httpx` + `pyyaml`
  and conditional `tomli` on Python 3.10
  runtime deps, `dev` (pytest, pytest-cov, pytest-timeout, matplotlib, mcp,
  mypy, types-PyYAML, ruff, pypdf), `figures` (matplotlib/Pillow), `benchmark`
  (scikit-learn/psutil), and `mcp` (`mcp>=1.2,<2`, for
  `mcp_server.py` / `daf-jev serve`) extras, console script
  `daf-jev = daf_jev.cli:main`, coverage gate config.

## Cross-repo pipeline

The graphical-models story crosses repos: Jev elicits the Bayes net, the
GNN repo's `rxinfer_bridge` turns the GraphSpec into an RxInfer.jl
`@model`, Julia computes marginals, and posteriors feed back into
daf-jev. Format seam: GraphSpec `dafjev.bayesnet/1` (invariant below;
emitter/parser in [`src/daf_jev/graphical.py`](src/daf_jev/graphical.py) and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#graphical-models)).

1. **Elicit** — [`scripts/bayes_experiment.py`](scripts/bayes_experiment.py)
   runs `propose_structure` + `elicit_cpts` (two batched asks) against the
   selected provider.
2. **Artifacts** — five files land in `output/experiments/asia/`:
   [`asia_graphspec.json`](output/experiments/asia/asia_graphspec.json)
   (interchange), [`network.png`](output/experiments/asia/network.png),
   [`posterior_trajectory.png`](output/experiments/asia/posterior_trajectory.png),
   [`mermaid.txt`](output/experiments/asia/mermaid.txt), and
   [`receipts.json`](output/experiments/asia/receipts.json) (per-run
   provenance: provider/model, proposed edges, elicited CPTs, posterior
   trajectory; live openrouter run: tub `0.120 -> 0.371 -> 0.434` under
   cumulative evidence `asia=false` → `+xray=true` → `+dysp=true`).
3. **Bridge** — GNN `rxinfer_bridge`
   ([PR #165](https://github.com/ActiveInferenceInstitute/Generalized_Notation_Notation/pull/165),
   branch `feat/rxinfer-bridge`) reads the GraphSpec (`dafjev.bayesnet/1`),
   parses `.gnn` subsets, emits a deterministic RxInfer.jl `@model`.
4. **Infer** — `julia --project=examples/rxinfer examples/rxinfer/asia_model.jl
   examples/rxinfer/asia_graphspec.json` — the committed 8-node Asia spec
   currently stalls at the multi-parent `DiscreteTransition` nodes (Known
   gap below); single-parent specs print exact marginals end-to-end.
   `--out FILE` writes a `dafjev.bayesnet-posteriors/1` sidecar for
   re-asking Jev.
5. **Feed back** — posteriors re-enter daf-jev through
   [`src/daf_jev/bayesnet_posteriors.py`](src/daf_jev/bayesnet_posteriors.py)
   (`load_posteriors` + `pair_for_calibration`; surfaced as
   `daf-jev posteriors-load` and MCP `jev_posteriors_load`) —
   calibration, evidence queries, trajectory re-walk.

Known gap: single-parent nets run end-to-end with exact posteriors on
both RxInfer 5.5.0 and 5.5.2; multi-parent `DiscreteTransition` nodes
stall in RxInfer 5.5.x VMP (upstream limitation; full gap matrix in the
GNN-side `examples/rxinfer/README.md`).

GNN-side verification (run from the GNN checkout, branch
`feat/rxinfer-bridge`):

```bash
uv run mypy src/gnn/rxinfer_bridge.py
uv run pytest tests/gnn/test_rxinfer_bridge.py
julia --project=examples/rxinfer examples/rxinfer/asia_model.jl \
    examples/rxinfer/asia_graphspec.json      # full Asia spec: stalls at multi-parent
                                              # DiscreteTransition (Known gap above);
                                              # single-parent specs print exact marginals
```

GNN-side paths are relative to that repo and not clickable from this repo
on GitHub; note `examples/rxinfer/` there carries no committed
`Project.toml` (RxInfer 5.5.x lives in a project-local depot; the committed
fallback environment is `src/gnn/execute/rxinfer/`).

## Invariants and gotchas

- **Self-versioned git repo, canonical checkout in the flat mirror**
  (branch `main`; remote `origin` → https://github.com/docxology/daf-jev;
  local `main` carries the improvement-campaign commits (jaggedness, waves 1-3
  folds, battery housekeeping) and is ahead of `origin/main` (`5591d31`, which
  predates the campaign); the campaign lands upstream exclusively via PR
  branches — `campaign-wave-1` → PR #1 — never direct pushes to `main`; the
  ahead count and tip move with every fold, so read them from git, not here.
  Commit meaningful changes locally — the template's provenance validation
  requires git-tracked worktree files — and push to `origin` for
  owner-approved publication (2026-09-18). Never `git add` any path under
  this lane into an OUTER repo (the hum-docxology worktree; container
  rules in `../../AGENTS.md`).
- **Zenodo deposits (v0.6.0 published 2026-09-23; family re-verified
  against the live API 2026-09-24).** The stable concept DOI
  `10.5281/zenodo.22816187` always resolves to the latest published
  version. Version deposits: v0.3.0 = **22817425**, v0.4.0 = **22884305**,
  v0.4.1 = **22884676** (published 2026-09-21; source zip from tag
  `v0.4.1` + the rendered PDF), v0.4.2 = **22921823** (2026-09-22),
  v0.5.0 = **22921963** (2026-09-22), v0.6.0 = **22921974** (2026-09-23,
  latest; version DOI `10.5281/zenodo.22921974`, record
  <https://zenodo.org/records/22921974>). Deposit **22816188** is the
  earlier superseded deposit in the same concept family — never cite or
  pin it. New releases MUST be new version deposits
  on the same concept via the Zenodo
  deposits API (`POST /api/records/<latest-id>/versions`, then PUT metadata
  — this build wants (re-verified 2026-09-23 against the live API; the
  older flat-shape note below was wrong): creators in the RDM nested form
  `{"person_or_org": {"type": "personal", "family_name": "Friedman",
  "given_name": "Daniel Ari", "identifiers": [{"scheme": "orcid",
  "identifier": "0000-0001-6232-9096"}]}, "affiliations": [{"name":
  "Active Inference Institute"}]}` — publish-time validation REQUIRES the
  explicit `type: "personal"` + `family_name`/`given_name` inside
  `person_or_org` (`type` absent → the PUT silently strips the name;
  `family_name` blank at publish → 400), `resource_type {"id":
  "software"}` (the `{"title","type"}` form is silently dropped), license
  via the `rights` field, and a `publisher` string for DataCite DOI
  registration — never a fresh deposit, which would mint a new concept
  DOI). The v0.4.0/v0.4.1 deposits currently project authorless
  creators (pre-fix metadata); fix their metadata via the edit-draft when
  touching them again. If a deposit fails mid-flight (e.g. publish 400),
  DELETE the orphaned new-version draft (`DELETE /api/records/<id>/draft`
  → 204) before re-running — a second `versions` POST while a draft
  exists 400s. BEFORE publishing a version deposit, verify the rendered PDF text (pymupdf over every page:
  zero `??`, zero `{{`, cover shows the release version and the concept
  DOI) — the v0.4.1 PDF shipped with four unresolved citations because
  this check was missing. Files of a PUBLISHED record are immutable (the
  edit-draft bucket
  is locked: content PUTs 403) — the ONLY way to add/change files is a new
  version deposit. File uploads: POST the files URL with an ARRAY body
  (`[{"key": ...}]`), PUT the content link with
  `Content-Type: application/octet-stream` (a pdf content-type 415s),
  then POST the commit link. The Zenodo API token lives in the template checkout's `.env` as
  `ZENODO_PROD_TOKEN`: never echo it, never print it in logs or
  transcripts, never copy it into the lane repo or commit it anywhere.
- **Public release remote.** <https://github.com/docxology/daf-jev>
  (`docxology/daf-jev`) is the release remote for the published code and
  repo landing page; the local lane git repo (branch `main`) remains the
  source of truth. Publishing to the public
  repo is the owner's call; the lane invariant against `git add`-ing lane
  paths into outer repos stands.
- **Release metadata files.** `CITATION.cff` (CFF 1.2.0, concept DOI) and
  `.zenodo.json` (Zenodo mirror, `upload_type: software`, `license: mit`)
  live at the repo root and MUST stay in sync with the pyproject version
  and the deposit DOIs above. GitHub releases and published Zenodo versions
  are separate evidence; a package-version update does not establish a new DOI.
- **`.env` is gitignored and holds the real key.** Never print, copy, or
  commit its value. Tests MUST never read it: unit config tests pass
  explicit env mappings; live tests read `os.environ["JEV_API_KEY"]` only.
  `.env.example` documents the shape.
- **No-mock test convention.** Never patch or monkeypatch `daf_jev`
  internals. The network stand-in is a REAL local HTTP server
  (`ThreadingHTTPServer` on 127.0.0.1, ephemeral port, fixtures in
  `tests/conftest.py`) with programmable queued responses and per-request
  hit recording; tests drive the real `HttpxTransport`/`JevClient` through
  it — including retry (429 once with `Retry-After: 0` then 200, assert 2
  hits), error mapping (401/422/529), and timeout (slow handler).
  Carve-out: the rule bans patching daf-jev behavior. Relocating INPUTS
  is not patching — point parameterized seams (e.g.
  `docs_verify.verify_manifest(manifest_path=...)`,
  `mcp_server._snapshot_summary(manifest_path=...)`) at fixture paths
  instead of setattr-ing module globals; env-relocation monkeypatch
  (setenv/delenv/chdir) remains sanctioned.
- **Live marker.** `tests/live/test_live_api.py` carries
  `pytest.mark.live` + `pytest.mark.skipif(not os.environ.get("JEV_API_KEY"))`
  — the `live` marker is registered in `pyproject.toml`
  (`--strict-markers`); live tests are skipped, not failed, without a key.
- **Coverage gate: >= 90% on `src/`** (`fail_under = 90`, branch coverage,
  `source = ["src"]`; bare `...` protocol-stub lines are excluded from the
  gate via `exclude_also`). Don't hardcode passed-test or coverage results here:
  bind them to a completed gate for the exact source/test/config inputs and
  generate `output/data/manuscript_variables.json` through
  `scripts/z_generate_manuscript_variables.py`. When using the raw-coverage
  generation path, retain ephemeral `.coverage` until token generation and
  evidence/render custody close, then remove it. Missing/stale inputs never
  authorize hand-edited results or reuse as current measurements; an `N/A`
  sentinel is unavailable evidence. Consult the current architecture and
  reproduction guide for the accepted verification-input path. Prefer a genuine
  `scripts/capture_verification.py` capture and explicit hash-bound `verification`
  selection in `manuscript/evidence.json` for exact offline regeneration from
  retained native JSON/JUnit/collection outputs. Before, after and current
  source/test/script/config inventories must agree; no new pytest collection or
  raw data is needed when reading the selected completed capture.
- **Render path (no leaf alias).** The former managed lifecycle leaf symlink
  `template/projects/ongoing/daf-jev -> .../Code_Tools/daf-jev` was removed
  2026-09-18 by owner decision. The template's project-path confinement
  rejects intermediate symlinks (e.g. resolving through
  `ongoing/Code_Tools`) by design, so `--project ongoing/daf-jev`
  render/validate via the template pipeline is currently blocked.
  Re-create a leaf symlink only with owner say-so; never substitute a
  non-leaf alias.
- **`figure_registry.json` must be emitted with the figures.**
  `figures.generate_all()` always writes it into the figures directory
  after the PNGs (`scripts/generate_figures.py` inherits this); template
  validation (`stage_04_validate.py`) checks the registry, so a figures
  rebuild that omits it fails validation. Data-driven figures (`batching`,
  `latency`, `calibration`, `graphical_abstract`) raise `FileNotFoundError`
  naming the missing benchmark JSON rather than fabricating data;
  `architecture`, `primitives`, and `confidence` are data-free and always
  render. Data-driven inputs must match the explicit `manuscript/evidence.json`
  selection used by manuscript variables; adding a newer file does not select it.
- **`{{TOKEN}}` no-hardcode manuscript protocol.** Every measured number in
  `manuscript/*.md` is a `{{TOKEN}}` placeholder; the 66 tokens live in
  `output/data/manuscript_variables.json` (generated by
  `scripts/z_generate_manuscript_variables.py` from pyproject, the docs
  MANIFEST, test collection counts, and the benchmark JSONs — no hardcoded
  results in the generator either). After any analysis/benchmark/test-count
  change, re-run the variables script before re-rendering. NEVER hardcode
  results into manuscript prose; strict mode (default) fails on missing
  analysis inputs instead of fabricating values (`--allow-draft` emits `N/A`
  sentinels for drafts only; unavailable verification results are not measurements).
  A layout/prose-only rerender may reuse an unchanged, already validated token
  map through the renderer's normal saved-token substitution, without rerunning
  analysis or coverage. Preserve that map's exact identity and prior PDFs.
  `GENERATION_TIMESTAMP` is the reproducible build timestamp, not necessarily
  the actual render time or experiment time.
- **Render completeness.** Use a fresh `--output` and, for reviewable builds,
  a fresh `--artifacts-dir`. All four renderer gates must pass, followed by
  all-page section/prose completeness and layout review against the substituted
  source. Absence of unresolved markers or out-of-bounds extracted words alone
  cannot detect missing/clipped content. A successful render is local artifact
  evidence, not scientific acceptance or permission to publish.
- **Benchmark acceptance boundaries.** Freeze exact source/config/input/catalog
  identities before execution; retain every attempt and planned cell status.
  A start without a terminal cell outcome is `unresolved`, even when its HTTP
  attempt has a receipt; a never-started cell is `unattempted`. Source tests,
  declared capabilities, actual runtime probes, model predictions, cost/billing
  closure and scientific/publication acceptance are separate evidence tiers.
  A later source gate does not upgrade historical inference receipts. Unknown
  hosted charge retains liability; unknown local compute cost is not free.
  The same authorized total allocation and cumulative profile allowance must
  carry across replacement plans; no automatic retry, refund or cap reset.
- **`composite_score` weights re-weight the probability distribution** —
  `q_i = p_i * w_i / sum(p_j * w_j)`, expected value `sum(q_i * i)` over
  sorted level indices; scale-invariant (only weight ratios matter); for
  non-negative weights the result lies within `[min index, max index]`
  (negative weights are accepted deliberately but void that guarantee);
  probabilities are validated on both paths (finite, non-negative;
  integer-index keys accumulated canonically — duplicate spellings like
  '1'/'01' merge onto one level); `ValueError` on length mismatch,
  non-finite weights, non-positive weight sum, or zero weighted mass.
  Deliberate orchestrator ruling — details in
  `docs/ARCHITECTURE.md` (`compose.py`) and the `compose.py` docstring.
- **`pick` returns a dict** `{question_id: routed_result}` and silently
  skips answers without a `choice` field (noul, score); unmapped choices
  raise `KeyError` from `route` (use `route` with `fallback=` when a
  default is wanted). Deliberate orchestrator ruling — see
  `docs/ARCHITECTURE.md`.
- Score question criteria MUST be a list of >= 2 strings; choice criteria
  non-empty — both raise `ValueError` in `to_wire()`.
- Python >= 3.10; core dependencies are `httpx`, `pyyaml` and `tomli` on
  Python 3.10 (`tomllib` is built in on newer Python). The `.env` loader is
  a tiny built-in in `config.py`, no python-dotenv dependency. `matplotlib`
  is optional through the `figures` extra; benchmark classifiers/resources use
  their own optional extra.
- **MCP tools are JSON-safe across the wire.** Every `mcp_server` tool
  returns plain dict/list/str/float only — dataclasses are converted with
  `dataclasses.asdict` before returning; nothing non-JSON-serializable may
  cross the MCP boundary. FastMCP runs over **stdio only** (other transports
  are unsupported by design; the CLI exposes `--transport stdio` as the sole
  choice). The `mcp` package is an optional extra — never import
  `daf_jev.mcp_server` (or `mcp`) from core modules; only `mcp_server.py`
  imports `mcp` (at module level), reached lazily from `cli.py`'s `serve`.
- **Calibration proxy semantics.** `bench_calibration.py`'s correctness
  signal is agreement with the modal choice across repeats (self-consistency
  proxy), NOT ground truth. Never present its ECE/Brier/reliability figures
  as ground-truth accuracy calibration in prose, docs, or figure captions;
  the JSON's `notes` field and the `fig:calibration` caption carry the
  caveat.
- **Examples skip without a key.** Every `examples/` script prints
  `SKIP: JEV_API_KEY not set` and exits 0 when no API key resolves (process
  env, then project `.env`); keep new examples to this contract.
- **Provider keys are stable API.** The provider registry
  (`src/daf_jev/providers.py`) is public surface: provider keys never
  change or get removed, and adding a built-in provider requires README
  (Providers section) + `docs/ARCHITECTURE.md` (Provider dispatch) +
  `skills/daf-jev/SKILL.md` (provider quick reference) sync in the same
  commit.
- **GraphSpec `dafjev.bayesnet/1` is a cross-repo contract.** The format
  string emitted by `BayesNet.to_json()` / `from_json()` is consumed and
  produced by the GNN bridge (GeneralizedNotationNotation): changing it
  (or its row/shape semantics) requires both repos to land in the same
  wave. Do not bump it unilaterally. The full pipeline and GNN-side
  verification commands are in the
  [Cross-repo pipeline](#cross-repo-pipeline) section.
- **`skills/` is documentation.** `skills/daf-jev/SKILL.md` is agent-facing
  documentation, never imported by code; keep it consistent with
  `README.md` and `docs/ARCHITECTURE.md` facts.

## Verification commands

Prepare the environment through the repository toolchain (`uv sync --extra dev
--extra figures`, and `--extra benchmark` for optional comparators/resources).
Dependency resolution can use the network. After preparation, these checkout
checks need no API key or remote service:

```bash
uv run pytest tests/unit --cov=src           # completed source gate; do not hardcode results
uv run ruff check .
uv run mypy src/daf_jev
uv run daf-jev docs-verify                  # local SHA/size/path verification
uv run python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json
                                            # offline manifest check; no writes/network
uv run daf-jev serve --help                 # stdio surface only; does not start serving
uv run daf-jev benchmark --help             # dispatcher only; no fetch/model call
```

`docs-verify` defaults to the module-anchored repository snapshot. Wheel installs
do not include `docs/reference/`; use `docs-verify --manifest PATH` with a supplied
snapshot outside the checkout rather than claiming the default is installed data.
The shared verifier also detects URL-to-path drift.

Reproduction builds write artifacts and must use the reviewed evidence selection.
Capture native verification exports first, then deliberately select the receipt's
relative path and SHA-256 in `manuscript/evidence.json`; retain historical
benchmark selections. Captures execute unit tests and only collect live tests.
With the selection, regeneration reads exact retained outputs without new
pytest collection/raw coverage. The legacy raw path remains available; retain
fresh raw data until token/evidence custody closes. A layout-only rerender reuses
the unchanged validated map and needs no new test/model run:

```bash
uv run python scripts/generate_figures.py   # selected inputs + figure_registry.json
uv run python scripts/capture_verification.py --out-dir .benchmarks/verification-new
# Select verification.json path/hash deliberately before regeneration.
uv run python scripts/z_generate_manuscript_variables.py
uv run python scripts/render_pdf.py --output output/pdf/reproduction-new.pdf \
    --artifacts-dir .benchmarks/reproduction-build-new
```

Choose fresh paths for each build. The renderer uses Pandoc/TeX and the saved
map; zero unresolved citations, undefined references, unloadable images and
overfull vertical boxes are required. Review every heading/prose section and
page layout too. `SOURCE_DATE_EPOCH` pins the reproducible build timestamp from
HEAD. `--install` additionally replaces the root PDF and is a separately
scope-authorized action. The external template path remains subject to the
render-path invariant above; do not recreate aliases to bypass it.

The following commands can contact live services or models when credentials
resolve. Execute them only within the authorized experiment/network scope;
keyless SKIP is not a runtime acceptance result:

```bash
uv run pytest tests/live                    # process-env key; otherwise skipped
uv run python benchmarks/bench_batching.py --runs 3
uv run python benchmarks/bench_patterns.py --runs 10
uv run python benchmarks/bench_calibration.py
uv run python benchmarks/bench_jaggedness.py
uv run python scripts/bayes_experiment.py --animate
uv run python examples/quickstart.py
uv run python scripts/scrape_docs.py --check # remote fetch, read-only disk comparison
```

Plain `scripts/scrape_docs.py` additionally rewrites the snapshot and prunes
orphans. Benchmark `dataset fetch` / `catalog` are explicit network operations;
`plan` and `report` are inference-free; `run` / `resume` execute the frozen arms.
Read `docs/decision_benchmarking.md`, `docs/local_serving.md` and the relevant
`benchmarks/configs/` recipe before execution. Preparation examples and declared
capabilities are not accepted model runtimes. Preserve credential, budget,
resident-model ownership, source/custody and unresolved-attempt boundaries.

MCP full handshake needs the optional `mcp` package (also in `dev`); connect a
client to `daf-jev serve` over stdio. `examples/providers_example.py` uses an
injected transport and makes no network call even with a key. Other examples
keep the keyless SKIP contract described above.
