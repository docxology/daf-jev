#!/usr/bin/env python3
"""Thin orchestrator: render the daf-jev figure registry to PNGs.

Renders every figure in ``src/daf_jev/figures`` (or a single one via
``--only NAME``) into the output figures directory. Data-driven figures
read the latest benchmark JSONs from ``output/benchmarks/`` at generation
time; missing data raises a clear error naming the missing file
(figures 1, 2, and 5 are data-free and always render).

All drawing lives in ``src/daf_jev/figures``; this script only wires
arguments, project paths, and exit codes.

Requires the ``figures`` optional-dependency group (matplotlib):
``uv sync --extra figures``.

Options:
    --out-dir DIR   destination directory (default: output/figures)
    --only NAME     render a single figure (one of: architecture,
                    primitives, batching, latency, confidence)

Exit codes:
    0   all requested figures written
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
        help="Render a single figure instead of the full registry",
    )
    args = parser.parse_args()

    try:
        from daf_jev.figures import generate_all, generate_one
    except ImportError as exc:
        print(f"error: figure generation requires matplotlib — install with `uv sync --extra figures` ({exc})", file=sys.stderr)
        return 1

    if args.only is not None:
        try:
            written = [generate_one(args.only, args.out_dir, _PROJECT_ROOT)]
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        written = generate_all(args.out_dir, _PROJECT_ROOT)

    for path in written:
        print(path)
    print(f"wrote {len(written)} figure(s) to {args.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
