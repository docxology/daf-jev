#!/usr/bin/env python3
"""Thin orchestrator: generate and inject manuscript variables.

Reads project metadata and analysis outputs, writes
``output/data/manuscript_variables.json``, and substitutes
``{{TOKEN}}`` markers in manuscript sections into
``output/manuscript/`` for PDF rendering.

All computation lives in ``src/daf_jev/manuscript_variables``;
all injection lives in ``infrastructure.rendering.manuscript_injection``
(available only when this project sits inside the template repository —
standalone checkouts skip the injection step).

Exit codes:
    0   variables written (and injected, when inside a template repo)
    1   unexpected error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _candidate in (_PROJECT_ROOT, _PROJECT_ROOT / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _template_repo_root(project_root: Path) -> Path | None:
    """Return the template repository root when this project is inside one."""
    for parent in project_root.parents:
        if (parent / "infrastructure").is_dir() and (parent / "pyproject.toml").is_file():
            return parent
        # Sidecar layout: the project lives under `<git>/projects/...` with the
        # template engine checked out as the sibling `<git>/template` — probe it
        # explicitly so injection works from the sidecar real path too.
        sibling = parent / "template"
        if (sibling / "infrastructure").is_dir() and (sibling / "pyproject.toml").is_file():
            return sibling
    return None


_REPO_ROOT = _template_repo_root(_PROJECT_ROOT)
if _REPO_ROOT is not None and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate manuscript variables for daf-jev")
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Allow N/A fallbacks when analysis outputs are missing (non-pipeline draft mode)",
    )
    args = parser.parse_args()

    from daf_jev.manuscript_variables import generate_variables, save_variables

    variables = generate_variables(
        _PROJECT_ROOT,
        require_analysis_outputs=not args.allow_draft,
    )
    out_path = _PROJECT_ROOT / "output" / "data" / "manuscript_variables.json"
    save_variables(variables, out_path)

    if _REPO_ROOT is not None:
        from infrastructure.rendering.manuscript_injection import write_resolved_manuscript_tree

        write_resolved_manuscript_tree(_PROJECT_ROOT, variables)
    else:
        print("note: not inside a template repository — skipping {{TOKEN}} injection", file=sys.stderr)

    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
