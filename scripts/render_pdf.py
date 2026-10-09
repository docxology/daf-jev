#!/usr/bin/env python3
"""Render daf-jev_combined.pdf from the substituted manuscript.

The template render pipeline (stage_03_render from the template checkout) is
currently unavailable — the leaf symlink was removed 2026-09-18 (owner
decision). This script is the documented manual fallback: it reproduces the
same render via pandoc --natbib (see docs/README.md and the manuscript's own
99_references.md note):

  tokens -> citation-form cross-refs to \\ref -> pandoc --natbib
         -> xelatex / bibtex / xelatex x2.

Inputs (all in-repo):
  output/data/manuscript_variables.json   generated token map (z_generate)
  manuscript/*.md                         substituted section sources
  manuscript/render/preamble.tex          render preamble (fence minus the two
                                          environment-conditional blocks)
  manuscript/render/cover.tex             cover page (title, author, DOI,
                                          version)
  manuscript/references.bib               bibliography

Usage:
  uv run python scripts/render_pdf.py --output output/pdf/new-report.pdf
  uv run python scripts/render_pdf.py --install  # also replace the repo-root
                                                 # daf-jev_combined.pdf

Render gates (fail with exit 2): successful BibTeX with zero warnings or
unresolved entries, zero undefined LaTeX references, zero unloadable images,
zero overfull vertical boxes. Use --artifacts-dir with a fresh directory to
retain TeX/log inputs for content-completeness review. A generated out.bbl
does not excuse a failed or warning-producing BibTeX run. SOURCE_DATE_EPOCH
is pinned from HEAD so identical inputs render byte-identical PDFs.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
ORDER = ['00_abstract', '01_introduction', '02_the_jev_model', '03_methodology',
         '04_integration_surfaces', '05_results', '06_experimental_setup',
         '07_reproducibility', '08_scope_and_related_work', '99_references']

PANDOC = ['pandoc', 'combined.md', '-o', 'out.tex', '--standalone', '--natbib',
          '--number-sections', '-H', 'preamble.tex', '-B', 'cover.tex',
          '-V', 'documentclass=article',
          '-V', 'mainfont=Times New Roman',
          '-V', 'monofont=Menlo',
          '--pdf-engine=xelatex']


def bibtex_succeeded(returncode: int, log: str) -> bool:
    """Require native BibTeX success without suppressing style/data warnings."""
    return returncode == 0 and 'Warning--' not in log


def build(install: bool, output: pathlib.Path | None = None,
          artifacts_dir: pathlib.Path | None = None) -> int:
    output = output or REPO / 'output/pdf/daf-jev_combined.pdf'
    output = output.resolve()
    if output.exists():
        print(f'FAIL: output already exists: {output}; select a fresh --output path')
        return 1
    if artifacts_dir is not None:
        artifacts_dir = artifacts_dir.resolve()
        if artifacts_dir.exists():
            print(f'FAIL: artifacts directory already exists: {artifacts_dir}')
            return 1
    with (REPO / 'output/data/manuscript_variables.json').open() as fh:
        vars = json.load(fh)
    parts = []
    for name in ORDER:
        text = (REPO / 'manuscript' / f'{name}.md').read_text()
        for k, v in vars.items():
            text = text.replace('{{' + k + '}}', v)
        assert '{{' not in text, f'unresolved token in {name}'
        parts.append(text)
    combined = '\n\n'.join(parts)

    # Citation-form cross-refs must become LaTeX \ref: pandoc --natbib would
    # otherwise turn [@sec:x] into \citep{sec:x} and feed it to bibtex.
    combined, n = re.subn(r'\[@((?:sec|fig|tbl):[A-Za-z0-9_-]+)\]', r'\\ref{\1}', combined)
    print(f'cross-refs converted: {n}')
    bib_keys = re.findall(r'^@\w+\{([^,]+),', (REPO / 'manuscript' / 'references.bib').read_text(), re.M)
    pattern = '|'.join(re.escape(k) for k in bib_keys)
    leftover = [c for c in re.findall(r'\[(@[^\]]*)\]', combined)
                if not re.fullmatch(f'@(?:{pattern})(?:\\s*;\\s*@(?:{pattern}))*', c)]
    print(f'leftover non-bib [@...] cites: {leftover if leftover else "none"}')
    assert not leftover, 'non-bib cross-refs survived conversion'

    combined += '\n\n\\bibliography{' + str((REPO / 'manuscript' / 'references').resolve()) + '}\n'

    build_dir = artifacts_dir or pathlib.Path(tempfile.mkdtemp(prefix='dafjev_render_'))
    if artifacts_dir is not None:
        build_dir.mkdir(parents=True, exist_ok=False)
    man = build_dir / 'manuscript'
    man.mkdir()
    (man / 'combined.md').write_text(combined)
    shutil.copy(REPO / 'manuscript/render/preamble.tex', man / 'preamble.tex')
    cover = (REPO / 'manuscript/render/cover.tex').read_text()
    for key, value in vars.items():
        cover = cover.replace('{{' + key + '}}', value)
    assert '{{' not in cover, 'unresolved cover token'
    (man / 'cover.tex').write_text(cover)
    (build_dir / 'output').symlink_to(REPO / 'output')

    epoch = subprocess.run(['git', 'show', '-s', '--format=%ct', 'HEAD'], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    env = {**os.environ, 'SOURCE_DATE_EPOCH': epoch}
    runs = [PANDOC,
            ['xelatex', '-interaction=nonstopmode', 'out.tex'],
            ['bibtex', 'out'],
            ['xelatex', '-interaction=nonstopmode', 'out.tex'],
            ['xelatex', '-interaction=nonstopmode', 'out.tex']]
    for argv in runs:
        r = subprocess.run(argv, cwd=man, capture_output=True, text=True, env=env)
        failed_bibtex = (argv[0] == 'bibtex' and not bibtex_succeeded(
            r.returncode, (man / 'out.blg').read_text() if (man / 'out.blg').exists() else ''
        ))
        if r.returncode != 0 or failed_bibtex:
            print(f"FAIL ({r.returncode}): {' '.join(argv[:3])}...")
            print(((r.stdout or '') + (r.stderr or ''))[-1200:])
            if artifacts_dir is None:
                shutil.rmtree(build_dir, ignore_errors=True)
            else:
                print(f'artifacts kept in {build_dir}')
            return 2 if argv[0] == 'bibtex' else 1

    blg = (man / 'out.blg').read_text()
    log = (man / 'out.log').read_text()
    missing = blg.count("didn't find a database entry")
    bibtex_warnings = blg.count('Warning--')
    undef = len(re.findall(r'Reference .* undefined', log))
    noload = log.count('Unable to load picture')
    overfull_vboxes = log.count('Overfull \\vbox')
    pages = re.search(r'\((\d+) pages', log)
    print(f'GATE bibtex-missing={missing} (must be 0)')
    print(f'GATE bibtex-warnings={bibtex_warnings} (must be 0)')
    print(f'GATE undefined-refs={undef} (must be 0)')
    print(f'GATE unloadable-images={noload} (must be 0)')
    print(f'GATE overfull-vboxes={overfull_vboxes} (must be 0)')
    print(f'pages={pages.group(1) if pages else "?"}')
    if missing or bibtex_warnings or undef or noload or overfull_vboxes:
        print(f'artifacts kept in {build_dir}')
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    with (man / 'out.pdf').open('rb') as source, output.open('xb') as destination:
        shutil.copyfileobj(source, destination)
    print(f'rendered -> {output}')
    print(f'PDF SHA256={hashlib.sha256(output.read_bytes()).hexdigest()}')
    if install:
        dest = REPO / 'daf-jev_combined.pdf'
        shutil.copy(man / 'out.pdf', dest)
        print(f'installed -> {dest}')
    if artifacts_dir is None:
        shutil.rmtree(build_dir, ignore_errors=True)
    else:
        print(f'artifacts kept in {build_dir}')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path,
                        help='fresh standalone PDF path; existing output is preserved')
    parser.add_argument('--install', action='store_true',
                        help='also replace the repository-root PDF')
    parser.add_argument('--artifacts-dir', type=pathlib.Path,
                        help='fresh directory retaining intermediate TeX and logs')
    args = parser.parse_args()
    sys.exit(build(args.install, args.output, args.artifacts_dir))
