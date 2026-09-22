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
  uv run python scripts/render_pdf.py            # render to a temp dir, gates
  uv run python scripts/render_pdf.py --install  # also replace the repo-root
                                                 # daf-jev_combined.pdf

Render gates (fail with exit 2): zero unresolved bibtex entries, zero
undefined LaTeX references, zero unloadable images. bibtex's exit code is
tolerated when it still wrote out.bbl (its 3 known header-comment parse
errors and unknown-@online-type warnings are pre-existing and benign); the
gate counters above are the real contract. SOURCE_DATE_EPOCH is pinned from
HEAD so identical inputs render byte-identical PDFs.
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile

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


def build(install: bool) -> int:
    vars = json.load(open(REPO / 'output/data/manuscript_variables.json'))
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

    build_dir = pathlib.Path(tempfile.mkdtemp(prefix='dafjev_render_'))
    man = build_dir / 'manuscript'
    man.mkdir()
    (man / 'combined.md').write_text(combined)
    shutil.copy(REPO / 'manuscript/render/preamble.tex', man / 'preamble.tex')
    shutil.copy(REPO / 'manuscript/render/cover.tex', man / 'cover.tex')
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
        benign = argv[0] == 'bibtex' and (man / 'out.bbl').exists()
        if r.returncode != 0 and not benign:
            print(f"FAIL ({r.returncode}): {' '.join(argv[:3])}...")
            print(((r.stdout or '') + (r.stderr or ''))[-1200:])
            shutil.rmtree(build_dir, ignore_errors=True)
            return 1

    blg = (man / 'out.blg').read_text()
    log = (man / 'out.log').read_text()
    missing = blg.count("didn't find a database entry")
    undef = len(re.findall(r'Reference .* undefined', log))
    noload = log.count('Unable to load picture')
    pages = re.search(r'\((\d+) pages', log)
    print(f'GATE bibtex-missing={missing} (must be 0)')
    print(f'GATE undefined-refs={undef} (must be 0)')
    print(f'GATE unloadable-images={noload} (must be 0)')
    print(f'pages={pages.group(1) if pages else "?"}')
    if missing or undef or noload:
        print(f'artifacts kept in {build_dir}')
        return 2

    if install:
        dest = REPO / 'daf-jev_combined.pdf'
        shutil.copy(man / 'out.pdf', dest)
        print(f'installed -> {dest}')
    shutil.rmtree(build_dir, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(build('--install' in sys.argv))
