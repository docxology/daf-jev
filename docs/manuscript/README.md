# DAF-JEV manuscript

The numbered Markdown files are the maintained paper. [`config.yaml`](config.yaml)
defines paper metadata, [`references.bib`](references.bib) holds the citations,
and [`evidence.json`](evidence.json) binds each selected result to its SHA-256.
See the [documentation index](../README.md) and [reproducibility guide](../reproducibility.md)
for the project and its evidence requirements.

## Standalone PDF

From a clean DAF-JEV checkout, install Pandoc 3.11, XeLaTeX, BibTeX, the packages
listed in [`render/preamble.tex`](render/preamble.tex), the Latin Modern Roman
and Math fonts, and DejaVu Sans Mono. Install the Python dependencies with
`uv sync --locked --extra dev --extra figures --extra benchmark`.

When validating the layout, use the checked-in, previously validated token map
and figures. For current source statistics, first capture and select
[verification evidence](../reproducibility.md#retained-verification-for-exact-offline-regeneration)
and regenerate the token map and figures from the selected inputs.

```bash
uv run --locked --no-sync python scripts/render_pdf.py \
  --output output/pdf/reproduction-new.pdf \
  --artifacts-dir .benchmarks/reproduction-build-new
```

Use fresh output paths. Review the renderer's bibliography and LaTeX checks,
then open the PDF and verify its sections, references, figures, and text across
all pages. The saved map used for layout checks retains its original source and
test statistics.

## Pinned template PDF

The [template exemplar](https://github.com/docxology/template/tree/87704feae0a4490ef7dad9c931d268e8c30273c2/projects/templates/template_code_project/manuscript)
defines the Markdown, configuration, preamble, and bibliography layout. The
[template source resolver](https://github.com/docxology/template/blob/87704feae0a4490ef7dad9c931d268e8c30273c2/infrastructure/core/project_paths.py#L59-L75)
reads `docs/manuscript/`. Use a disposable checkout of the same JEV commit as a
[template working project](https://github.com/docxology/template/blob/87704feae0a4490ef7dad9c931d268e8c30273c2/projects/README.md#L208-L223)
so generated copies stay separate from the retained artifacts in your checkout.

Install Python 3.14 or newer, Pandoc 3.11, `pandoc-crossref` v0.3.25a built for
Pandoc 3.11, and the TeX packages and fonts from the standalone instructions.
Run the following from the clean DAF-JEV checkout.

```bash
jev_source="$PWD"
render_workspace="$(mktemp -d)"
git clone https://github.com/docxology/template.git "$render_workspace/template"
cd "$render_workspace/template"
git checkout --detach 87704feae0a4490ef7dad9c931d268e8c30273c2
uv sync --locked --no-dev
mkdir -p projects/working
git clone --no-local "$jev_source" projects/working/daf-jev
git -C projects/working/daf-jev checkout --detach "$(git -C "$jev_source" rev-parse HEAD)"

uv run --locked --no-sync python - <<'PY'
import json
import shutil
from pathlib import Path

from infrastructure.rendering.manuscript_injection import write_resolved_manuscript_tree

project = Path("projects/working/daf-jev").resolve()
variables = json.loads((project / "output/data/manuscript_variables.json").read_text())
write_resolved_manuscript_tree(project, variables)

# The template resolves rendered LaTeX figure paths under output/figures.
matrix = project / "output/reports/hosted-expansion-20261008/admission-matrix.pdf"
figures = project / "output/figures"
shutil.copyfile(matrix, figures / matrix.name)
registry = figures / "figure_registry.json"
entries = json.loads(registry.read_text())
entries["fig:hosted_admission"] = {
    "label": "fig:hosted_admission",
    "filename": matrix.name,
    "generated_by": "daf-jev hosted expansion report",
    "alt_text": "Admission decisions by model, backend, and requested study arm.",
}
registry.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
PY

uv run --locked --no-sync python scripts/pipeline/stage_03_render.py \
  --project working/daf-jev --skip-manuscript-hydration
uv run --locked --no-sync python scripts/pipeline/stage_04_validate.py \
  --project working/daf-jev
```

Inspect the combined PDF in `projects/working/daf-jev/output/pdf/` and the
validation reports in `projects/working/daf-jev/output/reports/`. Use the
[template stage guide](https://github.com/docxology/template/blob/87704feae0a4490ef7dad9c931d268e8c30273c2/docs/RUN_GUIDE.md#L563-L574)
for stage options. Rendering is separate from publication acceptance.
