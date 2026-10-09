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
  [Decision backends and benchmark contracts](ARCHITECTURE.md#decision-backends-and-benchmark-contracts) ·
  [Conventions](ARCHITECTURE.md#conventions-template_code_project)
- [models.md](models.md) — sourced model reference; a contents list at the
  top of the page links every section. Ecosystem + graphical-models
  sections: [10. Sibling System One servers: jeff and kev](models.md#10-sibling-system-one-servers-jeff-and-kev) ·
  [11. Sibling ecosystem (second tier)](models.md#11-sibling-ecosystem-second-tier) ·
  [12. Jev as a factor source for graphical models](models.md#12-jev-as-a-factor-source-for-graphical-models)
- [reference/](reference/) — the hashed TypeSafe docs snapshot
  ([MANIFEST.json](reference/MANIFEST.json)); details below.
- [providers.md](providers.md) — legacy dispatch and explicit local/hosted
  benchmark adapters, output semantics, capability evidence and accounting.
- [local_serving.md](local_serving.md) — isolated Mac runtimes, full-input
  admission, resident model ownership, counterbalanced passes and resource limits.
- [decision_benchmarking.md](decision_benchmarking.md) — plan/run/resume/report,
  quality/timing/cost metrics, policies and partial-run interpretation.
- [datasets.md](datasets.md) — deterministic synthetic controls, pinned public
  datasets, leakage groups, splits, labels and sampling.
- [full_study.md](full_study.md) — full-fold selection, final training views,
  executable cohort admission, the first hosted probe's accounting hold and
  the complete comparative-study acceptance.
- [hosted_expansion.md](hosted_expansion.md) — full-cohort hosted obligations,
  refreshed model discovery, bounded progressive spending and incomplete runs.
- [benchmark_comparisons.md](benchmark_comparisons.md) — matched arm identities,
  paired group bootstrap differences and semantic comparison limits.
- [release.md](release.md) — exact installed artifacts, public privacy projections,
  release asset allowlists and GitHub/Zenodo acceptance.
- [reproducibility.md](reproducibility.md) — exact source/input/result identities,
  historical receipt limits, verification, rendering and publication gates.
- [methods_review.md](methods_review.md) — reproduced defects, repaired contracts,
  corrected claims and remaining scientific acceptance.

**Elsewhere in the repo:**

- [README.md](../README.md) — project overview, quickstart, and the
  cross-repo pipeline story
- [AGENTS.md](../AGENTS.md) — repo-wide agent contract
- [examples/README.md](../examples/README.md) — per-example walkthroughs
- [benchmarks/README.md](../benchmarks/README.md) — benchmark commands and receipts
- [benchmarks/configs/](../benchmarks/configs/) — offline comparator, synthetic
  reference, local serving and hosted pilot preparation recipes
- [skills/daf-jev/SKILL.md](../skills/daf-jev/SKILL.md) — the agent skill

## Release metadata

`CITATION.cff` (CFF 1.2.0 citation metadata) and `.zenodo.json` (Zenodo
deposit metadata) live at the repo root. Releases are archived as version
deposits on the stable concept DOI `10.5281/zenodo.22816187`, which always
resolves to the latest published version. The recorded release inventory was
verified on 2026-09-24: v0.3.0
(<https://zenodo.org/records/22817425>), v0.4.0
(<https://zenodo.org/records/22884305>), v0.4.1
(<https://zenodo.org/records/22884676>, published 2026-09-21), v0.4.2
(<https://zenodo.org/records/22921823>, 2026-09-22), v0.5.0
(<https://zenodo.org/records/22921963>, 2026-09-22), and v0.6.0
(<https://zenodo.org/records/22921974>, 2026-09-23), with the
public repository at <https://github.com/docxology/daf-jev>.
This dated inventory does not claim the current working tree has been released.

## ARCHITECTURE.md — the contract

`docs/ARCHITECTURE.md` is the **single source of truth** for current signatures,
wire validation, lifecycle/error semantics, environment resolution, pure
composition, graphical/posterior interchange, CLI/MCP and the no-mock convention.
All workers must match the current contract; report contradictions rather than
silently deviating. [AGENTS.md](../AGENTS.md) is the quick on-disk module map.

The [benchmark contracts](ARCHITECTURE.md#decision-backends-and-benchmark-contracts)
cover native/chat/letter adapters, prepared datasets, train-only comparators,
metrics/gates, executed cascades, durable accounting, resources, graphical
controls and offline exports. The [sampling contract](ARCHITECTURE.md#benchmark_samplingpy)
defines exact global timing packs and explicit legacy scope. Its label-free
selection is conditional on the supplied frozen pool; upstream pilot pools
can be label-stratified. Version-three synthetic inputs bind ordered
presentations and complete matched groups, with quality controls excluded from
ordinary timing. Probability meaning is separate from provenance and independent
calibration evidence. The [cross-repo pipeline](ARCHITECTURE.md#end-to-end-pipeline)
retains its declared GraphSpec/posterior seams and verification limits.

## Verification and reproduction entry points

From a prepared checkout, `uv run daf-jev docs-verify` verifies local snapshot
bytes, sizes and URL-to-path mapping without network or writes. Source checks
use the commands in [AGENTS.md](../AGENTS.md#verification-commands). Passed-test
and coverage results must come from a completed gate bound to the exact inputs;
do not infer current results from prose counts or an older generated map.

Figures and measured manuscript variables share the explicit, hash-verified
selection in [manuscript/evidence.json](../manuscript/evidence.json). They do not
select the newest benchmark file. Prefer the genuine
`scripts/capture_verification.py --out-dir FRESH_INSIDE_ROOT` capture and optional
hash-bound `verification` selection for exact offline regeneration. It runs unit
coverage/JUnit and only collects live tests; generation reads those native
exports without pytest/raw coverage. Malformed/stale explicit selections fail
even in draft mode. The legacy raw path remains available; retain fresh ephemeral
`.coverage` until token/evidence custody closes. See the
[reproduction contract](reproducibility.md#retained-verification-for-exact-offline-regeneration)
for the record and selection format.
Missing or stale evidence cannot be repaired by hand-editing measured values.

A layout-only rerender may consume an unchanged, already validated saved map.
Choose fresh paths to preserve previous outputs and retain diagnostic inputs:

```bash
uv run python scripts/render_pdf.py --output output/pdf/reproduction-new.pdf \
    --artifacts-dir .benchmarks/reproduction-build-new
```

Rendering also requires Pandoc, XeLaTeX, BibTeX, the preamble's TeX packages,
Times New Roman, Menlo and Latin Modern Math. The release reproduction record
identifies the source-build commit and fixed epoch; overlay its retained
evidence, figures and saved variables for exact same-host reproduction. A later
artifact commit's HEAD timestamp defines a different build.

The renderer requires zero unresolved citations, undefined references,
unloadable images and overfull vertical boxes. Review all source headings/prose
and every PDF page as well: marker/bounds checks alone cannot detect absent or
clipped text. The reproducible build timestamp is distinct from actual render
and experiment times. `--install` also replaces the root PDF and is an explicit
publication-scope action.

Source verification, declared capabilities, actual model/runtime probes,
execution receipts, accounting closure and scientific/publication acceptance
are separate evidence. A later source gate does not upgrade historical model
receipts. Partial reports retain failed, unsupported, unresolved and unattempted
cells; a started cell without a terminal outcome remains unresolved. Unknown
cost is not zero. Read [local serving](local_serving.md) and
[benchmarking](decision_benchmarking.md) before model execution; preparation
recipes do not constitute runtime acceptance or authorize additional funding.

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

`docs/reference/` is a hashed snapshot of
<https://docs.typesafe.ai> (fetched via its `llms.txt` index), preserving
the docs' `.md` URL paths: `introduction/`, `concepts/`, `primitives/`,
`patterns/`, `cookbooks/`, `demos/`, `sdk/` (JS and Python), etc.

`MANIFEST.json` records source/base/index URLs, scrape UTC time, index SHA-256,
page count, snapshot ID and per-path `title`, `url`, `sha256` and `bytes`.
Read its `page_count` and verifier output for the frozen inventory instead of
maintaining a separate current count in prose.

The current snapshot was scraped 2026-09-24T22:55:05Z and has
`snapshot_id` **`708902db9820d9d8`** (first 16 hex chars of the sha256 over
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

# Shared verifier (offline); default snapshot belongs to this checkout
uv run daf-jev docs-verify

# Explicit snapshot for a CLI installed without repository docs
daf-jev docs-verify --manifest /path/to/snapshot/MANIFEST.json
```

The scraper's explicit-manifest mode checks local hashes/sizes/extra pages;
`docs-verify` also checks URL-to-path drift. Neither verifies the live website.
Wheel installs do not bundle `docs/reference/`; the module-anchored default
requires a checkout, while `--manifest` can select separately supplied pages.

Snapshot pages are dated source material for API behavior questions — read
them (e.g. `sdk/python/api/exceptions.md`) before changing wire-facing
code, then distinguish their date from current hosted behavior. Do not hand-edit
pages: changes are detected as drift by `docs-verify`.

## skills/ — agent skill

`skills/daf-jev/SKILL.md` is the agent-facing skill document (when-to-use,
install, Python API surface, CLI, MCP server, pitfalls); to install it into
an agent, copy the whole `skills/daf-jev/` directory into the agent's skills
location — see `skills/README.md`. Documentation only, never imported by
code.

## examples/ — runnable walkthroughs

`examples/` holds thirteen runnable scripts (quickstart, triage router,
composite scoring, corpus evaluation, gated fallback, decider loop,
decider resilience, async evaluation, calibration walkthrough, retry
policies, providers example, Asia Bayes, posterior re-ask policy — see
`examples/README.md`); each
prints `SKIP: JEV_API_KEY not set` and exits 0 when no API key resolves.

## calibration

`src/daf_jev/calibration.py` is pure confidence-calibration statistics
(`bucket_index`, `reliability_table`, `expected_calibration_error`,
`brier_score`) over `(confidence, correct)` pairs.
`benchmarks/bench_calibration.py` feeds it live-API pairs where "correct"
means agreement with the modal choice across repeats — a self-consistency
correctness proxy, never ground-truth accuracy; results land in
unique `output/benchmarks/calibration_<UTC>_<UUID>.json` receipts. The retained
dated September receipt remains unchanged.
