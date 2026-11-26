#!/usr/bin/env python3
"""Generate the token map consumed by the manuscript renderers.

Read project metadata and reviewed analysis outputs and write
``output/data/manuscript_variables.json``. See ``docs/manuscript/README.md``
for using that map with the standalone and pinned template renderers.

Exit codes:
    0   variables written
    1   missing analysis outputs (strict mode) or unexpected error
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
    parser = argparse.ArgumentParser(description="Generate manuscript variables for daf-jev")
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Allow N/A fallbacks when analysis outputs are missing (non-pipeline draft mode)",
    )
    args = parser.parse_args()

    out_path = _PROJECT_ROOT / "output" / "data" / "manuscript_variables.json"
    try:
        from daf_jev.manuscript_variables import generate_variables, save_variables

        variables = generate_variables(
            _PROJECT_ROOT,
            require_analysis_outputs=not args.allow_draft,
        )
        save_variables(variables, out_path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
