# Tests

Run from the repository root with a Python version configured in the
[CI workflow](../.github/workflows/ci.yml). Install the locked extras first.
The offline gate checks lint, types, the documentation snapshot, and the
non-live tests. It measures branches and enforces a 90% total coverage floor.

```bash
uv sync --locked --extra dev --extra figures --extra benchmark
UV_NO_SYNC=1 UV_OFFLINE=1 bash scripts/gate.sh
```

[`unit/`](unit/) covers the package and its offline integrations using local
HTTP fixtures and real files. To check the publication verification inputs,
run this focused test after preparing the environment.

```bash
uv run --locked --no-sync python -m pytest tests/unit/test_project_verification.py
```

[`live/`](live/) contains tests marked `live` that require an API key and
network access. CI checks their collection with this command.

```bash
uv run --locked --no-sync python -m pytest --collect-only tests/live
```

See [verification and reproduction](../docs/reproducibility.md#retained-verification-for-exact-offline-regeneration)
for the native receipt format and how manuscript builds select evidence.
