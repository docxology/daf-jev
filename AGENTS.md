# AGENTS.md — daf-jev

Agent-facing notes. For the human-facing overview see `README.md`; for the
authoritative design contract see `docs/ARCHITECTURE.md` (v1, 2026-09-16 —
single source of truth; workers must match its signatures exactly and report
any contradiction rather than silently deviating).

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
  - `_http.py` — `Transport` / `AsyncTransport` protocols +
    `HttpxTransport` / `AsyncHttpxTransport`.
  - `client.py` — `JevClient` / `AsyncJevClient` (`ask`, `models`, `close`,
    context-manager support), `ModelCard`. `ask` takes per-call `timeout` /
    `request_headers` (per-call entries win); retry policy and default
    timeout resolve from env (`config.resolve_retry` / `resolve_timeout`)
    unless passed explicitly. Provider dispatch: `for_provider`
    classmethods + `open_client` / `open_async_client` (see
    `providers.py`).
  - `primitives.py` — `noul()` / `choice()` / `score()` builders and
    `QuestionSet` (no I/O).
  - `compose.py` — `composite_score`, `confidence_gate`, `route`,
    `tiered_gate`, `pick` (pure logic, no I/O).
  - `evaluate.py` — `Evaluator` / `EvaluationRecord`: concurrent evaluation
    of a fixed question set over many states (thread pool for the sync
    client, `asyncio.Semaphore` for the async client); per-state failures
    captured in `EvaluationRecord.error`, never aborting the batch.
    `evaluate()` / `summary()` / `to_json()`; an `AsyncJevClient` is
    single-use through `evaluate()` — the async session is closed at batch
    end.
  - `models.py` — `pick_model(cards, *, contains=None, prefer="latest")`;
    pure selection over the models listing (no I/O); `ValueError` on empty
    input, no match after filtering, or unknown `prefer`.
  - `figures.py` — matplotlib figure registry: 7 named figures
    (`architecture`, `primitives`, `batching`, `latency`, `confidence`,
    `calibration`, `graphical_abstract`) + `figure_registry.json` emission;
    data-driven figures read the newest `output/benchmarks/*.json`.
  - `manuscript_variables.py` — `generate_variables` / `save_variables`: 49
    `{{TOKEN}}` manuscript variables derived from pyproject, docs MANIFEST,
    test counts, benchmark JSONs, and the `manuscript/config.yaml`
    experiment knobs (`BATCHING_RUNS`, `CALIBRATION_STATES`,
    `CALIBRATION_REPEATS`; `CONFIG_BATCHING_N<n>` token names derive from
    the configured batch widths); zero hardcoded result values.
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
    `call()` records a failure on any `BaseException` and always re-raises,
    so a HALF_OPEN probe cannot wedge the breaker;
    `CircuitOpenError.remaining_seconds` is always a float >= 0 (`0.0` for
    the probe-rejection race). Not wired into `JevClient` by default.
  - `decider.py` — `Decider` observe -> compose -> ask -> gate -> fail-open
    -> act loop (`decide()` never raises), `DecisionEvent` (JSON-safe
    `to_dict()`), `ConfidenceGate`, `Budget` (thresholds validated >= 0,
    `max_calls=0` stays valid); 11-reason closed fallback taxonomy with
    `error` LAST (belt-and-suspenders); a client factory that raises OR
    returns None latches `client_error`; `cache_key` computed once per
    decide.
  - `cli.py` — stdlib argparse: `ask`, `models` (`--pick latest|first|last`,
    `--contains STR`), `evaluate` (`--questions-file`, `--states-file`,
    `--concurrency`, `--model`, `--include-records`), `docs-verify`, `serve`
    (`--transport stdio` — the only choice), `providers` (registry listing;
    global `--provider` flag); JSON to stdout, exit 0/1/2.
  - `mcp_server.py` — FastMCP server (`build_server` / `main`): tools
    `jev_ask`, `jev_evaluate`, `jev_models`, `jev_composite_score`,
    `jev_confidence_gate`, `jev_tiered_gate`, `jev_docs_verify` + the
    `jev://docs/snapshot` resource; stdio transport only; `jev_evaluate` /
    `jev_models` are async; `jev_composite_score` validates finite
    non-negative probabilities (`ValueError`); imports `mcp` at module
    import (optional `mcp` extra — never import from core modules); every
    tool takes an optional `provider` argument (default `jev`).
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
    including the fully-observed case — raises), decision methods
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
    any object with `.ask(state, questions)`.
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
  - `__init__.py` — public exports listed in `docs/ARCHITECTURE.md`.
- `tests/` — `conftest.py` (stub-server fixtures, see below), `tests/unit/`
  (per module plus CLI, scraper, and the evaluate/models/figures/
  manuscript_variables, calibration, and mcp_server modules, plus
  test_graphical.py, test_graphical_elicitation.py,
  test_graphical_viz.py, test_graphical_methods.py, and
  test_graphical_animation.py),
  `tests/live/test_live_api.py` (2 tests, `@pytest.mark.live`). Generated
  counts live in `output/data/manuscript_variables.json` (test_count /
  coverage, refresh via `scripts/z_generate_manuscript_variables.py`).
- `scripts/scrape_docs.py` — standalone stdlib re-scraper for the docs
  snapshot; CLI: `--index-url`, `--out-dir`, `--check`, `--manifest PATH`
  (or positional MANIFEST; `--manifest` requires `--check`), `--timeout`.
- `scripts/generate_figures.py` — thin orchestrator over `figures.py`;
  CLI: `--out-dir DIR` (default `output/figures`), `--only NAME`; needs the
  `figures` extra (`uv sync --extra figures`). Exit 0 ok, 2 unknown
  `--only`, 1 unexpected error.
- `scripts/z_generate_manuscript_variables.py` — thin orchestrator over
  `manuscript_variables.py`; writes `output/data/manuscript_variables.json`
  and (inside the template checkout) substitutes `{{TOKEN}}`s into
  `output/manuscript/`. `--allow-draft` permits `N/A` fallbacks when
  analysis outputs are missing.
- `scripts/render_pdf.py` — in-repo PDF render (pandoc --natbib over the
  generated token map; inputs `manuscript/render/{preamble,cover}.tex`);
  runs the render gates (zero unresolved bibtex entries / undefined refs /
  unloadable images; `SOURCE_DATE_EPOCH` pinned from HEAD); `--install`
  also replaces the root PDF.
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
- `examples/` — twelve runnable walkthroughs (`quickstart.py`,
  `triage_router.py`, `composite_scoring.py`, `evaluate_corpus.py`,
  `gated_fallback.py`, `decider_loop.py`, `providers_example.py`,
  `asia_bayes.py`, `decider_resilience.py`, `evaluate_async.py`,
  `calibration_walkthrough.py`, `retry_policies.py`) + `README.md`; each
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
  (13 entries). Prose only: every measured number is a `{{TOKEN}}`
  placeholder (see invariants).
- `manuscript/render/` — render inputs for the in-repo PDF fallback
  (`preamble.tex`, `cover.tex`), consumed by `scripts/render_pdf.py`.
- `benchmarks/` — live-API benchmark scripts with their own `README.md`;
  `_util.py` holds shared SKIP/percentile/JSON-writer helpers.
- `docs/ARCHITECTURE.md` — contract (see `docs/README.md`); it now covers
  the newer modules (evaluate, calibration, ledger, resilience, decider,
  questions, docs_verify, mcp_server, providers, graphical,
  graphical_elicitation, graphical_viz) and the figure/variables/experiment
  scripts, plus the manuscript-pipeline module internals (`figures.py`,
  `manuscript_variables.py`) — the contract now documents both; the map
  above remains the quick on-disk map for those.
- `docs/models.md` — sourced model technical reference (see `docs/README.md`).
- `docs/reference/` — hashed docs snapshot (see `docs/README.md`).
- `output/` — build artifacts, not documentation: `benchmarks/` (result
  JSONs), `figures/` (7 PNGs + `figure_registry.json`), `data/`
  (`manuscript_variables.json`), `manuscript/` (token-substituted sections),
  `pdf/` (`daf-jev_combined.pdf`), `reports/` (template validation reports,
  rendered provenance), `experiments/` (Asia run:
  `output/experiments/asia/` — `asia_graphspec.json`, `network.png`,
  `posterior_trajectory.png`, `mermaid.txt`, `receipts.json`; the
  cross-repo artifacts, see Cross-repo pipeline below). `web/` —
  `_combined_manuscript.md`, the template-render combined manuscript
  (tracked in git, not gitignored; verified 2026-09-24).
- `pyproject.toml` — setuptools build, version 0.6.0, `httpx` + `pyyaml`
  runtime deps, `dev` (pytest, pytest-cov, pytest-timeout, matplotlib, mcp,
  mypy, types-PyYAML, ruff), `figures` (matplotlib), and `mcp` (`mcp>=1.2,<2`, for
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
5. **Feed back** — posteriors re-enter daf-jev (calibration, evidence
   queries, trajectory re-walk).

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
  local `main` @ `22be3ac` is 2 commits ahead of `origin/main` (`5591d31`):
  jaggedness `0f342cf` + `22be3ac`, unpushed as of 2026-09-24).
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
  (currently 0.6.0) and the deposit DOIs above.
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
  gate via `exclude_also`). Don't hardcode counts here: generated
  test_count / coverage live in `output/data/manuscript_variables.json`
  (refresh via `scripts/z_generate_manuscript_variables.py`). Raw
  `.coverage` data is not retained on disk.
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
  render.
- **`{{TOKEN}}` no-hardcode manuscript protocol.** Every measured number in
  `manuscript/*.md` is a `{{TOKEN}}` placeholder; the 49 tokens live in
  `output/data/manuscript_variables.json` (generated by
  `scripts/z_generate_manuscript_variables.py` from pyproject, the docs
  MANIFEST, test collection counts, and the benchmark JSONs — no hardcoded
  results in the generator either). After any analysis/benchmark/test-count
  change, re-run the variables script before re-rendering. NEVER hardcode
  results into manuscript prose; strict mode (default) fails on missing
  inputs instead of fabricating values (`--allow-draft` emits `N/A`
  sentinels for drafts only).
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
- Python >= 3.10, stdlib + `httpx` (+ `pyyaml`) only; the `.env` loader is
  a tiny built-in in `config.py`, no python-dotenv dependency. `matplotlib`
  is required only for the `figures` extra.
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

```bash
uv sync --extra dev --extra figures
uv run pytest tests/unit --cov=src          # coverage gate >= 90%; generated counts in
                                            # output/data/manuscript_variables.json —
                                            # refresh via scripts/z_generate_manuscript_variables.py
                                            # (bare `...` protocol stubs excluded via exclude_also)
JEV_API_KEY=... uv run pytest tests/live    # 2 live tests; skipped without key
uv run ruff check .
uv run mypy src/daf_jev
uv run python benchmarks/bench_batching.py --runs 3
uv run python benchmarks/bench_patterns.py --runs 10
uv run python benchmarks/bench_calibration.py   # live; SKIP + exit 0 without a key
uv run python benchmarks/bench_jaggedness.py    # live; per-provider SKIP lines; global
                                                # "SKIP: no provider keys set" + exit 0 when
                                                # none of JEV/JEFF/KEV_API_KEY is set
                                                # flags: --providers 'jeff,kev,jev', --fixtures,
                                                # --repeats 50, --concurrent 32, --timeout, --model
uv run daf-jev docs-verify                  # snapshot drift check, exit 1 on mismatch
                                            # repo-checkout only: docs/reference/ is not
                                            # packaged into wheels (module-anchored
                                            # manifest path); installed copies fail
uv run python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json  # --check re-fetches every linked page (live network, NOT offline); exit 1 on drift
uv run daf-jev serve --help                     # serve subcommand smoke; --transport stdio only
uv sync --extra figures
uv run python scripts/generate_figures.py   # 7 PNGs + figure_registry.json -> output/figures/
uv run python scripts/z_generate_manuscript_variables.py   # 49 tokens + injection
uv run python scripts/bayes_experiment.py --animate   # keyless: prints SKIP and
                                                      # exits 0 before any network
                                                      # use (no artifacts written);
                                                      # with a key: the five
                                                      # artifacts +
                                                      # posterior_animation.gif +
                                                      # network_animation.gif

# Render the PDF manually (the template checkout render is currently
# blocked: the leaf symlink was removed 2026-09-18 — see the render-path
# invariant above). The in-repo fallback reproduces the template render via
# pandoc --natbib; inputs are manuscript/render/{preamble,cover}.tex and the
# generated token map; gates: zero unresolved bibtex entries / undefined
# refs / unloadable images; SOURCE_DATE_EPOCH pinned from HEAD.
uv run python scripts/render_pdf.py            # render + gates
uv run python scripts/render_pdf.py --install  # also replace the root PDF

# Template-pipeline path (for reference; currently blocked):
cd /Volumes/external_drive/Git/template && \
  uv run python scripts/pipeline/stage_03_render.py --project ongoing/daf-jev
cd /Volumes/external_drive/Git/template && \
  uv run python scripts/pipeline/stage_04_validate.py --project ongoing/daf-jev
# -> output/pdf/daf-jev_combined.pdf; 9 validation checks

# MCP server full handshake needs the mcp extra (mcp>=1.2,<2 — already
# carried by the `dev` extra, so `uv sync --extra dev` suffices; the
# separate `mcp` extra only matters for a minimal env): connect any MCP
# client to `daf-jev serve` over stdio.
uv run python examples/quickstart.py   # keyless check: prints SKIP: JEV_API_KEY not set, exit 0
uv run python examples/providers_example.py   # keyless check: SKIP + exit 0; no network even with a key
```
