# docs/

Documentation for daf-jev.

## Release metadata

`CITATION.cff` (CFF 1.2.0 citation metadata) and `.zenodo.json` (Zenodo
deposit metadata) live at the repo root. The v0.3.0 release is archived on
Zenodo under the stable concept DOI `10.5281/zenodo.22816187` (v0.3.0
version record: <https://zenodo.org/records/22817425>), with the public
repository at <https://github.com/docxology/daf-jev>.

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
`calibration.py`, `questions.py`, `docs_verify.py`, `mcp_server.py`, the
decision-loop trio (`ledger.py`, `resilience.py`, `decider.py`), and the
figure/variables scripts (`scripts/generate_figures.py`,
`scripts/z_generate_manuscript_variables.py`) — plus the post-wave-A
hardening semantics (client timeout/error mapping, strict wire parsing,
compose validation, decider taxonomy). The remaining gap is the
manuscript-pipeline module internals (`figures.py`,
`manuscript_variables.py`), covered by the contract only through their
script entry points; the root `AGENTS.md` module map stays the detailed
on-disk truth for those, and the contract should be extended rather than
contradicted.

## models.md — sourced model reference

`docs/models.md` is a technical reference on System One models and Jev:
what the models are, how Jev is built and trained, how calibration works,
and where the vendor's claims have (and have not) been corroborated. Every
factual claim carries a source link and an access date; primary (TypeSafe
docs snapshot) and third-party claims are flagged distinctly. Its cite-key
crosswalk matches the BibTeX keys in `manuscript/references.bib`
(`typesafe2026systemone`, `register2026jev`, …). Documentation, not a
benchmark — do not quote its numbers in code or tests.

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

`examples/` holds six runnable scripts (quickstart, triage router,
composite scoring, corpus evaluation, gated fallback, decider loop — see
`examples/README.md`); each
prints `SKIP: JEV_API_KEY not set` and exits 0 when no API key resolves.

## calibration

`src/daf_jev/calibration.py` is pure confidence-calibration statistics
(`bucket_index`, `reliability_table`, `expected_calibration_error`,
`brier_score`) over `(confidence, correct)` pairs.
`benchmarks/bench_calibration.py` feeds it live-API pairs where "correct"
means agreement with the modal choice across repeats — a self-consistency
correctness proxy, never ground-truth accuracy; results land in
`output/benchmarks/calibration_<YYYYMMDD>.json`.
