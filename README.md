# daf-jev

Modular, composable Python client and decision toolkit for the **TypeSafe Jev
(System One) API**. One HTTP endpoint, three question primitives, and a set of
pure-logic composition patterns built on top of the answers.

## What it provides

- **Primitives** — `noul` (yes/no), `choice` (pick an option from a
  probability distribution), `score` (rated on ordered levels). Build
  questions with `noul()` / `choice()` / `score()` and group them in a
  `QuestionSet`; batch any number of questions into a single API call.
- **Client** — `JevClient` / `AsyncJevClient` wrapping
  `POST https://api.typesafe.ai/v1/systemone`, with retries (429/529,
  exponential backoff, `Retry-After`), typed error mapping, and a
  `models()` listing.
- **Composition patterns** — pure functions over answers:
  `composite_score` (probability-weighted expected value over score levels),
  `confidence_gate` (auto-escalate low-confidence answers), `route` /
  `pick` (intent routing by choice).

Dependencies: Python >= 3.10, `httpx`, `pyyaml`. Managed with `uv`.

## Quickstart

```bash
uv sync
export JEV_API_KEY="sk-..."   # or TYPESAFE_API_KEY, or put it in .env
```

`.env` at the project root is auto-loaded (there is a `.env.example` to copy
from; `.env` itself is gitignored).

```python
from daf_jev import JevClient, choice, noul, score

with JevClient() as client:  # api_key resolved from env / .env
    resp = client.ask(
        "Customer message: I was charged twice this month and nobody has responded.",
        {
            "billing": noul("Is this about a billing problem?"),
            "tone": choice("What is the tone?", {"calm": None, "frustrated": "annoyed but civil"}),
            "severity": score("How severe?", ["minor", "noticeable", "blocking"]),
        },
    )

print(resp.nouls["billing"].noul)          # 0.0 (no) .. 1.0 (yes)
print(resp.choices["tone"].choice, resp.choices["tone"].confidence)
print(resp.scores["severity"].score)       # probability-weighted, may be fractional
```

Composing decisions:

```python
from daf_jev import confidence_gate, composite_score

value = composite_score(resp.scores["severity"])   # expected value over level indices
verdict = confidence_gate(resp.choices["tone"], threshold=0.6, below="review")
```

## CLI

```bash
uv run daf-jev ask \
  --state "I was charged twice this month." \
  --question billing=noul:Is this about a billing problem? \
  --question tone=choice:What is the tone?:calm=,angry=hostile \
  --question severity=score:How severe?:minor,noticeable,blocking \
  --pretty

uv run daf-jev models          # list available models

uv run daf-jev docs-verify     # re-hash docs/reference/ against MANIFEST.json
```

All commands print JSON to stdout; exit 0 on success, 2 on usage error, 1 on
runtime error.

## Tests and benchmarks

```bash
uv sync --extra dev --extra bench
uv run pytest tests/unit --cov=src          # 136 unit tests; coverage gate >= 90%
JEV_API_KEY=... uv run pytest tests/live    # 2 live tests against the real API
```

Unit tests need no key: they run against a real local HTTP stub server
(`tests/conftest.py`). Live tests and benchmarks hit the real API and are
skipped with a `SKIP:` message when `JEV_API_KEY` is absent.

```bash
uv run python benchmarks/bench_batching.py --runs 3   # 1 call with N questions vs N calls
uv run python benchmarks/bench_patterns.py --runs 10  # composite-score / routing latency
```

Latest recorded results (2026-09-16, `output/benchmarks/`): batching is
3.5x–20.5x faster (N=5→20) and 2.8x–4.2x cheaper in tokens; decision-pattern
pipelines run at ~0.12 s p50.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the authoritative design
  contract (wire facts, module signatures, test and benchmark conventions).
- [`docs/`](docs/README.md) — index, including the 108-page hashed snapshot
  of docs.typesafe.ai in `docs/reference/`.
