#!/usr/bin/env bash
# Offline package gate; live API tests require separate explicit execution.
set -euo pipefail
# Keep the declared profile fixed even in a developer shell with pytest defaults.
unset PYTEST_ADDOPTS
if [ "$#" -ne 0 ]; then
    printf 'usage: bash scripts/gate.sh (no test-selection overrides)\n' >&2
    exit 2
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# The suite asserts the benchmark runtime and figure paths, so the gate selects the
# same extras as CI. With `--extra dev` alone a fresh environment failed the
# benchmark-runtime test; only a venv synced earlier with more extras passed.
exec uv run --locked --extra dev --extra figures --extra benchmark python -m pytest tests/ -m 'not live' --cov=src --cov-branch --cov-fail-under=90
