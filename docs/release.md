# Package and archival release

The release describes software and selected evidence. It does not certify every
provider, complete a proposed full study, reconcile an unknown invoice or
establish calibrated decision probabilities. The current expansion separates
typed native distributions, generated labels and scores, CPU references,
validation-selected policies, exact graphical inference and execution coverage.

## Version and citation contract

Synchronize `pyproject.toml`, `daf_jev.__version__`, `CITATION.cff` and
`.zenodo.json`. The concept DOI
[10.5281/zenodo.22816187](https://doi.org/10.5281/zenodo.22816187) identifies the
software family. The published
[v0.6.0 record](https://zenodo.org/records/22921974) remains historical.
Until a new version record is created and verified, use the concept citation;
do not invent a version DOI or describe a draft as published. After publication,
bind the new version citation, release date, remote tag and exact asset hashes.

`.zenodo.json` is the repository's descriptive metadata mirror, not an API
request template. The publisher must use the actual API's resource, creator,
license and versioning schema. Create a new version in the existing concept
family and retain the prior published files. Zenodo's
[record-management guide](https://help.zenodo.org/docs/deposit/manage-records/)
and [API documentation](https://developers.zenodo.org/) define the remote
operations; successful local preparation is not proof those operations succeeded.

## Package scope

The wheel contains the `daf_jev` source package, its `py.typed` marker, license,
metadata and `daf-jev` entry point. Core dependencies remain separate from
optional `benchmark`, `figures` and `mcp` extras. Python support declarations
must match actual checks; the CI matrix declares remote checks but does not
substitute for a completed run on the release commit.

The wheel does not bundle datasets, model weights, serving environments,
documentation snapshots, manuscripts or private run directories. The default
documentation verifier is checkout-anchored; an installed caller can explicitly
supply a manifest to `verify_manifest`. Benchmark execution requires its
documented Git-source-checkout identity. Figure and manuscript reproduction
require the source tree and selected evidence. These are intentional boundaries,
not installed-model acceptance.

Package metadata includes its Markdown description, repository/documentation
links and SPDX license expression. Setuptools' minimum version supports that
license format. See the [PyPA metadata guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
and [PEP 561](https://peps.python.org/pep-0561/) for the package and typing seams.

## Candidate checks

Build into a fresh directory. Build inputs and archive contents must agree with
the intended source commit; unrelated ignored files must remain outside it.

```bash
uv build --out-dir .benchmarks/release-new/dist
uv venv --python 3.10 .benchmarks/release-new/core
uv pip install --python .benchmarks/release-new/core/bin/python \
    .benchmarks/release-new/dist/daf_jev-0.7.0-py3-none-any.whl
uv run python scripts/check_release_package.py \
    --source-root . \
    --wheel .benchmarks/release-new/dist/daf_jev-0.7.0-py3-none-any.whl \
    --sdist .benchmarks/release-new/dist/daf_jev-0.7.0.tar.gz \
    --python .benchmarks/release-new/core/bin/python \
    --output .benchmarks/release-new/package-check.json
```

The checker installs nothing. It compares every package module and the typed
marker with the wheel/sdist, every declared core and optional dependency,
provided extra, project URL, classifier and entry-point group with `pyproject.toml`.
Literal requirement normalization covers package names, specifier ordering and
quoted marker strings; unsupported declaration syntax fails rather than being
approximated. Dependencies are compared without evaluating markers or importing
their packages.

The wheel allowlist contains the exact package files and six supported
setuptools metadata files; `RECORD` must bind every member's bytes and size.
The sdist allowlist contains the required package/readme/license/project files,
generated `PKG-INFO` and `setup.cfg`, the six supported egg-info files, and any
included current test `.py` files with matching source bytes. Mirrored package
metadata, dependency and entry-point declarations, package names and the
`SOURCES.txt` inventory are checked too. Arbitrary metadata-directory files,
extra source-root payloads, undeclared commands or dependencies, and empty
undeclared directories fail. Generated INI comments are refused too, rather than
being ignored as an unvalidated place to store additional content. The receipt enumerates the actual accepted members;
the sdist is not the comprehensive research-source archive.

It also rejects duplicate, escaping or linked archive members, and optionally imports
the installed core outside the checkout. That installed check makes one sync
and two persistent async requests to its owned loopback fixture, using explicit
fake credentials. It makes no hosted request or model inference. The receipt
path is exclusive; failure must be retained and investigated. A source-only
unit pass cannot replace the installed-artifact check.

Also build a wheel from the sdist in isolation, compare source bytes and inspect
the installed CLI. Check optional extras separately. Wheel byte identity across
builds requires control of build tools/timestamps; equal package source bytes
alone do not prove reproducible archive bytes. Run the full repository gates
after all release source/test/config inputs settle. Capture fresh retained
verification and select it explicitly before generating variables, figures and
a new PDF. Preserve historical inference source identities.

## Public asset allowlist

Freeze a manifest before upload, with each exact filename, size and SHA256.
Recommended release files are:

| Asset | Permitted contents |
| --- | --- |
| `daf_jev-0.7.0-py3-none-any.whl` | Checked installed core package and typing metadata |
| `daf_jev-0.7.0.tar.gz` | Checked package sdist, source/readme/license |
| `daf-jev-0.7.0-source.zip` | Reviewed release-commit projection of source, tests, scripts, guides, examples, recipes and manuscript inputs |
| `daf-jev-0.7.0-manuscript.pdf` | Fresh reviewed release-version PDF with resolved citations, figures, tables and complete page text |
| `daf-jev-0.7.0-evidence.zip` | Explicit public projection of selected summaries, historical receipts, figure registry, token map and portable verification inputs |
| `SHA256SUMS` and `release-manifest.json` | Exact asset hashes, source/tag identity, selection provenance and acceptance limits |

The filenames are a proposed contract until the publisher freezes actual assets.
The source/evidence projections must enumerate members; do not zip a working
tree or upload every file under `output/`. Wheel/sdist and research-source
archives serve different purposes. Any source archive exclusions must be
disclosed, especially when they affect offline regeneration. If a projection
cannot regenerate the manuscript, say which inputs are unavailable.

Exclude `.env`, credentials, `.benchmarks`, private runtime/process records,
account/billing details, model weights, caches, failed diagnostic PDFs and
unselected builds. Hash the preserved originals. Historical verification logs
can contain personal absolute paths: do not silently edit them and retain their
old hashes. Prefer a fresh genuine capture from a neutral release checkout with
portable relative evidence references; otherwise publish a clearly identified
derived privacy projection that does not claim to be the original receipt.
`scripts/project_verification.py --capture ORIGINAL --out-dir FRESH_DIRECTORY`
creates that declared derivative: it relocates project/interpreter display and
removes JUnit hostname attributes while retaining results, coverage and source
identities. It binds original and emitted file hashes, preserves the original
capture and refuses unknown private path display. Review the resulting archive
and its selected-evidence references before publishing; the transformation is
privacy preparation, not a new test execution or runtime acceptance.
Public summaries can retain unavailable private-evidence references with an
explicit verification limit; those paths are not downloadable artifacts.

The documentation snapshot has its own provenance and upstream rights; the
software's MIT license must not be asserted as a relicensing of third-party
documentation, datasets or model weights. Keep dataset/model source links and
their original licensing terms. No prepared real corpus or model is part of
the default release allowlist.

## Remote acceptance

Before publication, independently check the release asset list, metadata,
privacy boundary and every-page PDF completeness. Verify zero unresolved tokens,
citations/references, missing images and overfull vertical boxes, and check
horizontal text bounds: successful compiler gates alone can miss a clipped
command. Confirm that the cover's package version and concept DOI match.

The authorized publisher pushes the reviewed commit/tag and verifies their
actual remote identities. GitHub releases should attach the reviewed assets,
not rely on an unreviewed generated working-tree archive. On Zenodo, verify the
new record belongs to the existing family, uploaded file checksums/lengths match,
publication completed and the public version DOI/metadata/files resolve. Record
local package, CI, remote, archival and scientific evidence separately. This
workflow does not authorize a PyPI upload or a new model/billing allocation.
