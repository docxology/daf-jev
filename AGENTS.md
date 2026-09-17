# AGENTS.md — daf-jev

Agent-facing notes. For the human-facing overview see `README.md`; for the
authoritative design contract see `docs/ARCHITECTURE.md` (v1, 2026-09-16 —
single source of truth; workers must match its signatures exactly and report
any contradiction rather than silently deviating).

This is a local-only sidecar project under `projects/ongoing/`. Repo-wide
lane policy (never commit/push, symlink topology, doc standard) lives in
`../../AGENTS.md` (the `ongoing/` root) and `../AGENTS.md` (Code_Tools
category) — do not restate it here.

## Layout

- `src/daf_jev/` — the package (src layout, uv-managed):
  - `_types.py` — frozen wire dataclasses (`NoulQuestion` / `ChoiceQuestion` /
    `ScoreQuestion`, answers, `Usage`, `SystemOneResponse` with `nouls` /
    `choices` / `scores` views), `parse_response` (strict).
  - `_errors.py` — exception hierarchy mirroring the official SDK
    (`TypeSafeError` base, `APIStatusError` subclasses per status code,
    `error_from_status`).
  - `_retry.py` — `RetryPolicy` (429/529, exponential backoff + jitter,
    `Retry-After` aware); pure `next_delay`, sleeping happens in the client.
  - `_http.py` — `Transport` / `AsyncTransport` protocols +
    `HttpxTransport` / `AsyncHttpxTransport`.
  - `client.py` — `JevClient` / `AsyncJevClient` (`ask`, `models`, `close`,
    context-manager support), `ModelCard`.
  - `primitives.py` — `noul()` / `choice()` / `score()` builders and
    `QuestionSet` (no I/O).
  - `compose.py` — `composite_score`, `confidence_gate`, `route`, `pick`
    (pure logic; multi-call helpers take an injected client).
  - `config.py` — `load_dotenv`, `resolve_api_key` (injected env >
    process env > `.env`; `JEV_API_KEY` then `TYPESAFE_API_KEY`),
    `resolve_base_url`, `Settings` / `load_settings`.
  - `cli.py` — stdlib argparse: `ask`, `models`, `docs-verify`; JSON to
    stdout, exit 0/1/2.
  - `__init__.py` — public exports listed in `docs/ARCHITECTURE.md`.
- `tests/` — `conftest.py` (stub-server fixtures, see below), `tests/unit/`
  (10 files, 136 tests collected — per module plus CLI and scraper),
  `tests/live/test_live_api.py` (2 tests, `@pytest.mark.live`).
- `scripts/scrape_docs.py` — standalone stdlib re-scraper for the docs
  snapshot; CLI: `--index-url`, `--out-dir`, `--check`, `--manifest PATH`
  (or positional MANIFEST; `--manifest` requires `--check`), `--timeout`.
- `benchmarks/` — live-API benchmark scripts with their own `README.md`;
  `_util.py` holds shared SKIP/percentile/JSON-writer helpers.
- `docs/ARCHITECTURE.md` — contract (see `docs/README.md`).
- `docs/reference/` — hashed docs snapshot (see `docs/README.md`).
- `output/benchmarks/` — benchmark result JSONs (`batching_<date>.json`,
  `patterns_<date>.json`); build output, not documentation.
- `pyproject.toml` — setuptools build, `httpx` + `pyyaml` runtime deps,
  `dev` (pytest, pytest-cov, pytest-timeout) and `bench` (rich) extras,
  console script `daf-jev = daf_jev.cli:main`, coverage gate config.

## Invariants and gotchas

- **Local-only lane** — never commit, push, or publish; see
  `../../AGENTS.md` and `../AGENTS.md`.
- **`.env` is gitignored and holds the real key.** Never print, copy, or
  commit its value. Tests MUST never read it: unit config tests pass
  explicit env mappings; live tests read `os.environ["JEV_API_KEY"]` only.
  `.env.example` documents the shape.
- **No-mock test convention.** Never patch or monkeypatch `daf_jev`
  internals. The network stand-in is a REAL local HTTP server
  (`ThreadingHTTPServer` on 127.0.0.1, ephemeral port, fixtures in
  `tests/conftest.py`) with programmable queued responses and per-request
  hit recording; tests drive the real `HttpxTransport`/`JevClient` through
  it — including retry (429 once with `Retry-After: 0` then 200, assert 2
  hits), error mapping (401/422/529), and timeout (slow handler).
- **Live marker.** `tests/live/test_live_api.py` carries
  `pytest.mark.live` + `pytest.mark.skipif(not os.environ.get("JEV_API_KEY"))`
  — the `live` marker is registered in `pyproject.toml`
  (`--strict-markers`); live tests are skipped, not failed, without a key.
- **Coverage gate: >= 90% on `src/`** (`fail_under = 90`,
  branch coverage, `source = ["src"]`). Current on-disk `.coverage` data:
  95.30%.
- **`composite_score` weights re-weight the probability distribution** —
  `q_i = p_i * w_i / sum(p_j * w_j)`, expected value `sum(q_i * i)` over
  sorted level indices; scale-invariant (only weight ratios matter),
  result always in `[min index, max index]`, `ValueError` on length
  mismatch, non-finite weights, non-positive weight sum, or zero weighted
  mass. Deliberate orchestrator ruling — details in
  `docs/ARCHITECTURE.md` (`compose.py`) and the `compose.py` docstring.
- **`pick` returns a dict** `{question_id: routed_result}` and silently
  skips answers without a `choice` field (noul, score); unmapped choices
  raise `KeyError` from `route` (use `route` with `fallback=` when a
  default is wanted). Deliberate orchestrator ruling — see
  `docs/ARCHITECTURE.md`.
- Score question criteria MUST be a list of >= 2 strings; choice criteria
  non-empty — both raise `ValueError` in `to_wire()`.
- Python >= 3.10, stdlib + `httpx` (+ `pyyaml`) only; the `.env` loader is
  a tiny built-in in `config.py`, no python-dotenv dependency.

## Verification commands

```bash
uv sync --extra dev --extra bench
uv run pytest tests/unit --cov=src          # 136 tests, coverage gate >= 90%
JEV_API_KEY=... uv run pytest tests/live    # 2 live tests; skipped without key
uv run python benchmarks/bench_batching.py --runs 3
uv run python benchmarks/bench_patterns.py --runs 10
uv run daf-jev docs-verify                  # snapshot drift check, exit 1 on mismatch
python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json  # offline
```
