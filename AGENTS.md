# AGENTS.md — daf-jev

Agent-facing notes. For the human-facing overview see `README.md`; for the
authoritative design contract see `docs/ARCHITECTURE.md` (v1, 2026-09-16 —
single source of truth; workers must match its signatures exactly and report
any contradiction rather than silently deviating).

This is a sidecar project under `projects/ongoing/`, now **self-versioned**
(see invariants). Repo-wide lane policy (symlink topology, never `git add`
lane paths into an outer repo, doc standard) lives in `../../AGENTS.md` (the
`ongoing/` root) and `../AGENTS.md` (Code_Tools category) — do not restate it
here.

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
    unless passed explicitly.
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
    `load_settings`.
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
    (`--transport stdio` — the only choice); JSON to stdout, exit 0/1/2.
  - `mcp_server.py` — FastMCP server (`build_server` / `main`): tools
    `jev_ask`, `jev_evaluate`, `jev_models`, `jev_composite_score`,
    `jev_confidence_gate`, `jev_tiered_gate`, `jev_docs_verify` + the
    `jev://docs/snapshot` resource; stdio transport only; `jev_evaluate` /
    `jev_models` are async; `jev_composite_score` validates finite
    non-negative probabilities (`ValueError`); imports `mcp` at module
    import (optional `mcp` extra — never import from core modules).
  - `calibration.py` — pure calibration statistics over `(confidence,
    correct)` pairs: `bucket_index`, `reliability_table`,
    `expected_calibration_error`, `brier_score`; no I/O.
  - `__init__.py` — public exports listed in `docs/ARCHITECTURE.md`.
- `tests/` — `conftest.py` (stub-server fixtures, see below), `tests/unit/`
  (per module plus CLI, scraper, and the evaluate/models/figures/
  manuscript_variables, calibration, and mcp_server modules),
  `tests/live/test_live_api.py` (2 tests, `@pytest.mark.live`). Generated
  counts live in `output/data/manuscript_variables.json` (test_count /
  coverage, refresh via `scripts/z_generate_manuscript_variables.py`; last
  full run: 316 passing unit tests).
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
- `examples/` — six runnable walkthroughs (`quickstart.py`,
  `triage_router.py`, `composite_scoring.py`, `evaluate_corpus.py`,
  `gated_fallback.py`, `decider_loop.py`) + `README.md`; each prints
  `SKIP: JEV_API_KEY not set` and exits 0 without a key (see invariants).
- `skills/` — agent-facing skill docs: `daf-jev/SKILL.md` (frontmatter +
  Markdown skill) + `README.md` (install notes). Documentation only — never
  imported by code.
- `manuscript/` — 10 sections (`00_abstract.md` …
  `08_scope_and_related_work.md`, `99_references.md`) + `preamble.md` +
  `config.yaml` + `references.bib`
  (13 entries). Prose only: every measured number is a `{{TOKEN}}`
  placeholder (see invariants).
- `benchmarks/` — live-API benchmark scripts with their own `README.md`;
  `_util.py` holds shared SKIP/percentile/JSON-writer helpers.
- `docs/ARCHITECTURE.md` — contract (see `docs/README.md`); it now covers
  the newer modules (evaluate, calibration, ledger, resilience, decider,
  questions, docs_verify, mcp_server) and the figure/variables scripts.
  The manuscript-pipeline module internals (`figures.py`,
  `manuscript_variables.py`) are the one remaining gap — the map above is
  the detailed on-disk truth for those.
- `docs/models.md` — sourced model technical reference (see `docs/README.md`).
- `docs/reference/` — hashed docs snapshot (see `docs/README.md`).
- `output/` — build artifacts, not documentation: `benchmarks/` (result
  JSONs), `figures/` (7 PNGs + `figure_registry.json`), `data/`
  (`manuscript_variables.json`), `manuscript/` (token-substituted sections),
  `pdf/` (`daf-jev_combined.pdf`), `reports/` (template validation reports,
  rendered provenance).
- `pyproject.toml` — setuptools build, version 0.4.1, `httpx` + `pyyaml`
  runtime deps, `dev` (pytest, pytest-cov, pytest-timeout, matplotlib, mcp),
  `figures` (matplotlib), and `mcp` (`mcp>=1.2,<2`, for
  `mcp_server.py` / `daf-jev serve`) extras, console script
  `daf-jev = daf_jev.cli:main`, coverage gate config.

## Invariants and gotchas

- **Self-versioned git repo, canonical checkout in the flat mirror**
  (branch `main`; remote `origin` → https://github.com/docxology/daf-jev;
  local `main` last recorded in sync with `origin/main` @ `7c4db8e`
  (2026-09-21).
  Commit meaningful changes locally — the template's provenance validation
  requires git-tracked worktree files — and push to `origin` for
  owner-approved publication (2026-09-18). Never `git add` any path under
  this lane into an OUTER repo (`../../AGENTS.md`, `../AGENTS.md`).
- **Zenodo deposits (v0.4.1 published 2026-09-21).** The v0.4.1 release is
  archived as Zenodo deposit id **22884676** (version DOI
  `10.5281/zenodo.22884676`, record
  <https://zenodo.org/records/22884676>; source zip from tag `v0.4.1` +
  the rendered PDF); v0.4.0 remains deposit **22884305** (version DOI
  `10.5281/zenodo.22884305`);
  v0.3.0 remains deposit **22817425** (version DOI
  `10.5281/zenodo.22817425`); the concept DOI
  `10.5281/zenodo.22816187` is stable across versions and always resolves
  to the latest published version. Deposit **22816188** is the earlier
  superseded deposit in the same concept family — never cite or pin it. New
  releases MUST be new version deposits on the same concept via the Zenodo
  deposits API (`POST /api/records/<latest-id>/versions`, then PUT metadata
  — this build wants RDM shapes: `person_or_org` creators with
  `family_name`/`given_names`, `resource_type {"id": "software"}`, license
  via the `rights` field, and a `publisher` string for DataCite DOI
  registration — never a fresh deposit, which would mint a new concept
  DOI). Files of a PUBLISHED record are immutable (the edit-draft bucket
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
  (currently 0.4.1) and the deposit DOIs above.
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
- **Live marker.** `tests/live/test_live_api.py` carries
  `pytest.mark.live` + `pytest.mark.skipif(not os.environ.get("JEV_API_KEY"))`
  — the `live` marker is registered in `pyproject.toml`
  (`--strict-markers`); live tests are skipped, not failed, without a key.
- **Coverage gate: >= 90% on `src/`** (`fail_under = 90`, branch coverage,
  `source = ["src"]`; bare `...` protocol-stub lines are excluded from the
  gate via `exclude_also`). Don't hardcode counts here: generated
  test_count / coverage live in `output/data/manuscript_variables.json`
  (refresh via `scripts/z_generate_manuscript_variables.py`); last
  full-suite measurement 93.50%. Raw `.coverage` data is not retained on
  disk.
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
uv run daf-jev docs-verify                  # snapshot drift check, exit 1 on mismatch
python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json  # offline
uv run daf-jev serve --help                     # serve subcommand smoke; --transport stdio only
uv sync --extra figures
uv run python scripts/generate_figures.py   # 7 PNGs + figure_registry.json -> output/figures/
uv run python scripts/z_generate_manuscript_variables.py   # 49 tokens + injection

# Render + validate from the template checkout (currently blocked: the leaf
# symlink was removed 2026-09-18 — see the render-path invariant above):
cd /Volumes/external_drive/Git/template && \
  uv run python scripts/pipeline/stage_03_render.py --project ongoing/daf-jev
cd /Volumes/external_drive/Git/template && \
  uv run python scripts/pipeline/stage_04_validate.py --project ongoing/daf-jev
# -> output/pdf/daf-jev_combined.pdf; 9 validation checks

# MCP server full handshake needs the mcp extra: uv sync --extra mcp, then
# connect any MCP client to `daf-jev serve` over stdio.
python examples/quickstart.py   # keyless check: prints SKIP: JEV_API_KEY not set, exit 0
```
