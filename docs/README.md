# docs/

Documentation for daf-jev.

## Contents

**Docs:**

- [ARCHITECTURE.md](ARCHITECTURE.md) — the design contract:
  [Wire facts](ARCHITECTURE.md#wire-facts-verified) ·
  [Environment](ARCHITECTURE.md#environment) ·
  [Package layout](ARCHITECTURE.md#package-layout-srcdaf_jev) ·
  [Provider dispatch](ARCHITECTURE.md#provider-dispatch) ·
  [Graphical models](ARCHITECTURE.md#graphical-models) ·
  [End-to-end pipeline](ARCHITECTURE.md#end-to-end-pipeline) ·
  [Tests](ARCHITECTURE.md#tests-tests--template-no-mock-convention) ·
  [Benchmarks](ARCHITECTURE.md#benchmarks-benchmarks--live-api-graceful-skip-without-key) ·
  [Conventions](ARCHITECTURE.md#conventions-template_code_project)
- [models.md](models.md) — sourced model reference; a contents list at the
  top of the page links every section. Ecosystem + graphical-models
  sections: [10. Sibling System One servers: jeff and kev](models.md#10-sibling-system-one-servers-jeff-and-kev) ·
  [11. Sibling ecosystem (second tier)](models.md#11-sibling-ecosystem-second-tier) ·
  [12. Jev as a factor source for graphical models](models.md#12-jev-as-a-factor-source-for-graphical-models)
- [reference/](reference/) — the hashed TypeSafe docs snapshot
  ([MANIFEST.json](reference/MANIFEST.json)); details below.

**Elsewhere in the repo:**

- [README.md](../README.md) — project overview, quickstart, and the
  cross-repo pipeline story
- [AGENTS.md](../AGENTS.md) — repo-wide agent contract
- [examples/README.md](../examples/README.md) — per-example walkthroughs
- [benchmarks/README.md](../benchmarks/README.md) — benchmark commands and receipts
- [skills/daf-jev/SKILL.md](../skills/daf-jev/SKILL.md) — the agent skill

## Release metadata

`CITATION.cff` (CFF 1.2.0 citation metadata) and `.zenodo.json` (Zenodo
deposit metadata) live at the repo root. Releases are archived as version
deposits on the stable concept DOI `10.5281/zenodo.22816187`, which always
resolves to the latest published version (API-verified 2026-09-24): v0.3.0
(<https://zenodo.org/records/22817425>), v0.4.0
(<https://zenodo.org/records/22884305>), v0.4.1
(<https://zenodo.org/records/22884676>, published 2026-09-21), v0.4.2
(<https://zenodo.org/records/22921823>, 2026-09-22), v0.5.0
(<https://zenodo.org/records/22921963>, 2026-09-22), and v0.6.0
(<https://zenodo.org/records/22921974>, 2026-09-23, latest), with the
public repository at <https://github.com/docxology/daf-jev>.

## ARCHITECTURE.md — the contract

`docs/ARCHITECTURE.md` (v1, 2026-09-16) is the **single source of truth**
for the package build: wire facts (endpoint, question/answer shapes, error
statuses, retry semantics), environment variables (including the v0.2
`resolve_retry` / `resolve_timeout` overrides — `JEV_MAX_ATTEMPTS`,
`JEV_BACKOFF_BASE`, `JEV_BACKOFF_MAX`, `JEV_JITTER`, `JEV_TIMEOUT`),
module-by-module signatures (including the v0.2 additions `models.py` /
`pick_model`, per-call `timeout` / `request_headers` on `ask`, and the
`Evaluator` exports), the no-mock test convention, and benchmark
conventions. All workers must match its signatures exactly; on
contradiction, report the delta — do not silently deviate.

Gap note: the contract now also covers the newer modules — `evaluate.py`,
`calibration.py`, `jaggedness.py` (model-jaggedness statistics and the
`run_battery` battery driver over stochastic prompts), `questions.py`,
`docs_verify.py`, `mcp_server.py`, the
decision-loop trio (`ledger.py`, `resilience.py`, `decider.py`), and the
figure/variables scripts (`scripts/generate_figures.py`,
`scripts/z_generate_manuscript_variables.py`), the live-API benchmark
battery (`benchmarks/` — `bench_jaggedness.py` measures uniformity
deviation, choice degeneracy, runs/streak, order rotation, concurrent
wobble, and the noul-vs-choice delta; see `benchmarks/README.md`), the
provider-dispatch
registry (`providers.py`), and the graphical-models stack
(`graphical.py`, `graphical_elicitation.py`, `graphical_viz.py`,
`scripts/bayes_experiment.py`) — plus the post-wave-A hardening semantics
(client timeout/error mapping, strict wire parsing, compose validation,
decider taxonomy). The remaining gap is the manuscript-pipeline module
internals (`figures.py`, `manuscript_variables.py`), covered by the
contract only through their script entry points; the root `AGENTS.md`
module map stays the detailed on-disk truth for those, and the contract
should be extended rather than contradicted. The Graphical models section
now carries the [end-to-end pipeline](ARCHITECTURE.md#end-to-end-pipeline) —
the signature-exact two-repo command sequence and the five experiment
artifacts.

## models.md — sourced model reference

`docs/models.md` is a technical reference on System One models and Jev:
what the models are, how Jev is built and trained, how calibration works,
and where the vendor's claims have (and have not) been corroborated. Every
factual claim carries a source link and an access date; primary (TypeSafe
docs snapshot) and third-party claims are flagged distinctly. Its cite-key
crosswalk matches the BibTeX keys in `manuscript/references.bib`
(`typesafe2026systemone`, `register2026jev`, …). A contents list at the
top of the page links every section; sections 10-12 cover the
sibling-server ecosystem and Jev as a factor source for graphical models
([Section 12](models.md#12-jev-as-a-factor-source-for-graphical-models)).
Documentation, not a benchmark — do not quote its numbers in code or tests.

## reference/ — TypeSafe docs snapshot

`docs/reference/` is a **108-page** hashed snapshot of
<https://docs.typesafe.ai> (fetched via its `llms.txt` index), preserving
the docs' `.md` URL paths: `introduction/`, `concepts/`, `primitives/`,
`patterns/`, `cookbooks/`, `demos/`, `sdk/` (JS and Python), etc.

`MANIFEST.json` schema:

```json
{
  "source": "...", "base_url": "...", "index_url": "...",
  "scraped_at_utc": "...", "index_sha256": "...",
  "page_count": 108,
  "pages": {"<rel-path>.md": {"title", "url", "sha256", "bytes"}},
  "snapshot_id": "b79c9cd6008489f1"
}
```

The current snapshot was scraped 2026-09-16T21:19:06Z and has
`snapshot_id` **`b79c9cd6008489f1`** (first 16 hex chars of the sha256 over
the concatenated per-page hashes, in page order). The per-page `sha256`
values are what `daf-jev docs-verify` re-checks.

### Regenerate / verify

```bash
# Full re-scrape (network): fetches every page and rewrites MANIFEST.json
python scripts/scrape_docs.py

# Offline drift check against the current snapshot (no network, no writes)
python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json

# Online check: fresh scrape compared against disk, exit 1 on drift
python scripts/scrape_docs.py --check

# Equivalent check from the installed CLI
uv run daf-jev docs-verify
```

Snapshot pages are the source of record for API behavior questions — read
them (e.g. `sdk/python/api/exceptions.md`) before changing wire-facing
code. Do not hand-edit pages: changes are detected as drift by
`docs-verify`.

## skills/ — agent skill

`skills/daf-jev/SKILL.md` is the agent-facing skill document (when-to-use,
install, Python API surface, CLI, MCP server, pitfalls); to install it into
an agent, copy the whole `skills/daf-jev/` directory into the agent's skills
location — see `skills/README.md`. Documentation only, never imported by
code.

## examples/ — runnable walkthroughs

`examples/` holds eight runnable scripts (quickstart, triage router,
composite scoring, corpus evaluation, gated fallback, decider loop,
providers example, Asia Bayes — see `examples/README.md`); each
prints `SKIP: JEV_API_KEY not set` and exits 0 when no API key resolves.

## calibration

`src/daf_jev/calibration.py` is pure confidence-calibration statistics
(`bucket_index`, `reliability_table`, `expected_calibration_error`,
`brier_score`) over `(confidence, correct)` pairs.
`benchmarks/bench_calibration.py` feeds it live-API pairs where "correct"
means agreement with the modal choice across repeats — a self-consistency
correctness proxy, never ground-truth accuracy; results land in
`output/benchmarks/calibration_<YYYYMMDD>.json`.
