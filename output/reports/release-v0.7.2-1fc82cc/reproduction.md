# Reproducing the v0.7.2 manuscript

The executable source build is commit `1fc82cc427cb4300985d3738bfff95f3550ae300`, with Git timestamp / `SOURCE_DATE_EPOCH` `1791578224`. The later release commit adds selected verification and generated publication artifacts; its timestamp is not the build timestamp. Use the source commit and explicitly restore the selected verification inputs from tag `v0.7.2` to reproduce the recorded PDF bytes.

```bash
git clone https://github.com/docxology/daf-jev.git daf-jev-v072
cd daf-jev-v072
git switch --detach 1fc82cc427cb4300985d3738bfff95f3550ae300
git restore --source v0.7.2 --worktree -- manuscript/evidence.json output/verification/v0.7.2-public-mac310-1fc82cc
uv sync --extra dev --extra figures --extra benchmark
uv run python scripts/generate_figures.py --include-study
uv run python scripts/z_generate_manuscript_variables.py
uv run python scripts/render_pdf.py --output output/pdf/reproduced-v072.pdf --artifacts-dir output/reports/fresh-v072-render
```

Planning, figure generation, variable generation and rendering make no inference requests. The selected native hosted evidence is the completed capability cut; the full quality study and prospective two-provider comparison require their own terminal evidence. Historical benchmark and partial local evidence retain their original interpretation and missing provenance.

The recorded PDF SHA-256 is `c5b3f5d21eee2a0b4ef7d44378eed85eb3e2af5a2c64888081ea9823bde4c7b6`. Two subsequent fresh renders were byte-identical, including a render after correcting the generated figure inventory. All 40 named figure/registry/data/Mermaid files also reproduced byte for byte in a fresh output directory. The completed final variable map includes all 15 figures and equals strict regeneration from its exact selected evidence.

The verified render used macOS, Python 3.14.4, Pandoc 3.12, XeTeX from TeX Live 2026, BibTeX 0.99e, Times New Roman, Menlo and Latin Modern Math. Cross-platform PDF byte identity is unverified. Native unit verification describes Python 3.10.20 and 3.14.4 separately. The five public files in each verification directory are declared privacy projections of retained original exports; exact hashes and transformation metadata remain in their records.

`package-acceptance.json` and `package-reproduction.json` bind the separately built wheel and sdist to the same source commit. Installed core API/CLI acceptance and the byte-identical sdist-to-wheel rebuild do not establish optional serving runtime acceptance. Benchmark planning and execution require a Git-backed source checkout.
