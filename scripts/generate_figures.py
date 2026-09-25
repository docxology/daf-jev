#!/usr/bin/env python3
"""Thin orchestrator: render the daf-jev figure registry to PNGs.

Renders every figure in ``src/daf_jev/figures`` (or a single one via
``--only NAME``) into the output figures directory, then writes
``figure_registry.json`` alongside the PNGs on every run — including
``--only`` runs — because template validation requires the registry to
accompany the figures. It also always writes the sibling ``architecture.mmd``
(byte-deterministic mermaid source emitted by the pure
``figures.architecture_mermaid()``; deliberately NOT a registry entry —
``figure_registry.json`` keeps its template-validation schema). The
``--only`` choices are derived from the figure
registry itself so the help text can never drift. Data-driven figures
read the latest benchmark JSONs from ``output/benchmarks/`` at generation
time; missing data raises a clear error naming the missing file (the
architecture, primitives, and confidence figures are data-free and always
render).

All drawing lives in ``src/daf_jev/figures``; this script only wires
arguments, project paths, and exit codes.

Requires the ``figures`` optional-dependency group (matplotlib):
``uv sync --extra figures``.

Options:
    --out-dir DIR   destination directory (default: output/figures)
    --only NAME     render a single figure (see --help for the valid names,
                    derived from the figure registry)

Exit codes:
    0   all requested figures written, plus figure_registry.json
    1   unexpected error (missing benchmark data, matplotlib absent, ...)
    2   unknown --only NAME
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _candidate in (_PROJECT_ROOT, _PROJECT_ROOT / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _registry_names() -> str:
    """Sorted registered figure names, or a hint when matplotlib is absent."""
    try:
        from daf_jev.figures import FIGURE_FILENAMES
    except ImportError:
        return "install the `figures` extra to list the valid names"
    return ", ".join(sorted(FIGURE_FILENAMES))


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate daf-jev manuscript figures")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_PROJECT_ROOT / "output" / "figures",
        help="Destination directory for PNGs (default: output/figures)",
    )
    parser.add_argument(
        "--only",
        default=None,
        metavar="NAME",
        help=f"Render a single figure instead of the full registry (one of: {_registry_names()})",
    )
    args = parser.parse_args()

    try:
        from daf_jev.figures import (
            architecture_mermaid,
            generate_all,
            generate_one,
            write_figure_registry,
        )
    except ImportError as exc:
        print(
            f"error: figure generation requires matplotlib — install with `uv sync --extra figures` ({exc})",
            file=sys.stderr,
        )
        return 1

    try:
        if args.only is not None:
            written = [generate_one(args.only, args.out_dir, _PROJECT_ROOT)]
        else:
            written = generate_all(args.out_dir, _PROJECT_ROOT)
        # The registry must accompany the figures on every path, including
        # --only runs; it mirrors the full static registry metadata either way.
        write_figure_registry(args.out_dir, _PROJECT_ROOT)
        # The .mmd sibling is written on every path too — including --only
        # runs — and is deliberately NOT part of figure_registry.json (whose
        # schema is the template-validation contract).
        mmd_path = args.out_dir / "architecture.mmd"
        mmd_path.write_text(architecture_mermaid() + "\n", encoding="utf-8")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(path)
    print(mmd_path)
    print(f"wrote {len(written)} figure(s) to {args.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
