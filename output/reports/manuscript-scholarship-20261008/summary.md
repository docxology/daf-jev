# Expanded working manuscript and hosted test improvements

The [26-page working manuscript](../../pdf/modular-methods-scholarship-20261008-final.pdf) expands the decision-model methods, scholarship and selected empirical figures. This is a local source and manuscript result. The full local/hosted comparative study remains incomplete. Nothing was pushed or published, and this continuation made no provider inference calls, authenticated hosted requests or model process starts.

The bibliography contains 29 entries, with 25 cited in this render. The manuscript retains ten sections, 52 headings, thirteen numbered figures and three tables. Its theoretical treatment covers proper scoring, calibration and sharpness, selective prediction, adaptive threshold selection, orchestration, constrained decoding, dataset provenance and contamination, grouped validation, ordinal target loss, exact graphical inference and distinct billing evidence.

Six new empirical figures and the revised overview consume exact selected public study aggregates. PNG and vector PDF copies are retained; each selected study figure has a plotted-data JSON companion. Fixed-prediction bootstrap intervals, leakage-filtered refits, validation gates, sparse Wine bins and execution coverage have distinct interpretations. Unsupported combinations supply no invented estimate. The thirteen-figure path is opt-in; the seven-figure legacy API remains available.

## Software verification and hosted testing

The selected verification records 1590 passing unit tests with 93.11% combined line/branch coverage. Ruff, Mypy over 47 modules, the 111-page documentation snapshot and diff checks passed. The two live tests were collected and were not executed. Fresh independent review covers source, statistics, accounting and credential handling; final all-page presentation and interpretation reviews are retained privately with fingerprints in [summary.json](summary.json).

Thirty-three new diagnostic cases comprise 27 real-loopback HTTP cases and six pure receipt/accounting cases. They cover malformed/non-JSON replies, oversized or interrupted response bodies, independently valid billing/usage, bounded identifiers, reflected request/credential rejection and cancellation. Thirty-eight selected-evidence/figure cases cover source selection, denominator consistency, malformed metrics and intervals, optional interfaces, deterministic rendering and adversarial caller styles. These are software regression results and do not establish hosted inference success.

The adapter retains only a bounded decoded-body hash/count, fixed media/parse classifications and validated receipt fields. The 1 MiB retained-body cap is not a bound on decompression, wire bytes or total memory. Each actual request remains separately admitted and finalized; hidden retries, endpoint substitution and unknown-billing continuation remain prohibited. Historical malformed replies are not backfilled with guessed content or costs.

## Retained execution evidence

| Cohort | Planned | Completed | Unsupported | Failed | Unresolved | Unattempted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU comparators | 93046 | 68894 | 24152 | 0 | 0 | 0 |
| Older partial native | 2792 | 2005 | 495 | 3 | 1 | 288 |
| Hosted pilot | 18065 | 0 | 19 | 1 | 0 | 18045 |

Completion includes capability work. Cohorts and source identities differ; these denominators cannot establish a common model ranking. CPU quality predictions number 68870. Canonical supervised text accuracies are 87.69% for BANKING77 and 79.84% for CLINC150/OOS. Wine bin-index scalar MAE is 0.2770 versus 0.3319 for the training-frequency reference. These values describe CPU comparators, not native or chat-model performance. See the selected [CPU report](../full-offline-20261008/full-offline-comparison.json) and [hosted continuation summary](../hosted-pilot-20261008/summary.json) for their original identities and limitations.

The hosted pilot retains one failed transport attempt with unknown billing. Further hosted admission is stopped under the same USD 25 allocation, `first-authorized-hosted-usd25`. The unexecuted full hosted proposal contains 376155 cells; it is neither a funded run nor a completed study. Native continuation additionally requires verified cumulative runtime admission and sufficient available memory. Changed software requires a new frozen execution manifest; it cannot reset the budget or local clock. Per-attempt hosted billing reconciliation is required before further calls, and spending beyond USD 25 needs a new authorization.

## Reproduce the manuscript

The final source revision is `450a49a3731c794cc6138707c2100ac48854a471`. In a separate checkout at that revision, with the documented local toolchain and fonts:

```bash
uv sync --extra dev --extra figures --extra benchmark
uv run python scripts/generate_figures.py --include-study
uv run python scripts/z_generate_manuscript_variables.py
uv run python scripts/render_pdf.py \
    --output output/pdf/reproduced-scholarship-new.pdf \
    --artifacts-dir .benchmarks/reproduced-scholarship-build-new
```

Choose fresh output paths. Planning, selected-evidence consumption and reporting perform no inference. The selected verification and study hashes are recorded in `manuscript/evidence.json`; altered or stale inputs fail. The variable map contains 66 tokens, including 17 selected-study values. A later artifact-only commit records generated outputs; reproduce from the source revision above so the build epoch remains 1791487963.

Two render invocations on this host produced byte-identical PDFs: SHA-256 `a75ae2379f0a39071057e1a426af10b1b595bd010aa037719b10636d7b3599a3`. All four renderer gates are zero, and all 26 pages passed bounds/full-text/visual checks with resolved citations, references, safe links and complete figures/tables. The percent units and one clipped command identified in the preserved initial rendering were corrected in a fresh final PDF. [Reproduction metadata](reproduction.json) records the toolchain and scope; cross-platform byte identity and scientific/live acceptance are not claimed.
