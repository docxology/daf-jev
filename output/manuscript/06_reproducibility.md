# Reproducibility Certification {#sec:reproducibility}

Every artifact behind this manuscript — figures, tables, token values, and the documentation snapshot the model claims rest on — is regenerable from the repository with the commands below, and every generated value reaches the prose through the token pipeline rather than hand transcription.

## Artifact inventory and hashing

- **Figures.** The five figures of this manuscript are generated into `output/figures/` by `src/daf_jev/figures.py` (one `generate_<name>()` function per figure plus `generate_all(out_dir)`), orchestrated by `scripts/generate_figures.py`:

  ```bash
  uv run python scripts/generate_figures.py            # all figures
  uv run python scripts/generate_figures.py --only batching_speedup
  ```

  The data-driven figures read `output/benchmarks/batching_*.json` and `output/benchmarks/patterns_*.json`, resolving "latest" by filename date; a missing benchmark file is reported as a clear error naming the missing file rather than silently producing an empty chart. The two schematic figures and the parametric confidence-band illustration require no data and no network.

- **Manuscript variables.** All dynamic values reach the prose as double-brace token placeholders, computed by `src/daf_jev/manuscript_variables.py::generate_variables(project_root)` and written to `output/data/manuscript_variables.json` by the thin orchestrator `scripts/z_generate_manuscript_variables.py`, which then renders substituted copies of every section into `output/manuscript/`. Running in strict mode fails if analysis outputs are missing; the `--allow-draft` flag substitutes draft sentinels instead of failing, for early-stage renders only.

- **Documentation snapshot.** The bundled snapshot of the TypeSafe documentation comprises 108 pages (1014.8 KiB) under `docs/reference/`, scraped on 2026-09-16 and identified as snapshot b79c9cd6008489f1. The manifest records a content hash per page plus the snapshot identifier; drift is detectable at any time with:

  ```bash
  uv run daf-jev docs-verify                 # re-hash the tree, exit non-zero on drift
  uv run python scripts/scrape_docs.py --check   # same check without rewriting
  ```

## Test suite and coverage

The test suite follows the no-mock convention: unit tests drive the real transport against a real local HTTP server fixture, and live tests hit the real API only when a key is present in the environment (they skip with a notice otherwise). The suite comprises 15 test files — 214 unit tests and 2 live tests — collected with:

```bash
uv run pytest tests/unit --cov=src     # unit suite under the coverage gate
JEV_API_KEY=... uv run pytest tests/live   # live tests against the real API
```

Measured coverage over the package source stands at 94.05, enforced by the coverage gate configured in `pyproject.toml`. Test and collection counts are computed at variable-generation time by collecting the suite; if collection is unavailable in a given environment, the corresponding values are reported as draft sentinels rather than fabricated.

## Provenance chain

The certification chain is: benchmark scripts write dated JSON payloads → figure generators read those payloads and render `output/figures/*.png` → the variable generator reads the same payloads plus `manuscript/config.yaml`, `pyproject.toml`, the test suite, and the docs manifest to compute the token mapping → the injection step substitutes tokens into `output/manuscript/*.md` → the renderer consumes the substituted copies. No numeric fact in this paper has a hand-maintained copy; the environment of record is `macOS-26.6.2-arm64-arm-64bit-Mach-O` under 3.14.6, and the rendered edition is version 0.2.0 of this manuscript, generated at 2026-09-17T00:04:14Z.
