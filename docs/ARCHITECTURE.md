# daf-jev — Architecture Contract (v1, 2026-09-16)

Single source of truth for the package build. All workers MUST match these signatures
exactly. Wire facts below are verified against the local docs snapshot
(`docs/reference/`, snapshot `b79c9cd6008489f1`); per-module workers MUST also read
their listed snapshot pages for details and keep this contract accurate if they find
contradictions (report the delta; do not silently deviate).

## Wire facts (verified)

- Endpoint: `POST https://api.typesafe.ai/v1/systemone`
  - Headers: `Authorization: Bearer <API_KEY>`, `Content-Type: application/json`
  - Response header of record: `x-typesafe-request-id`
- Body: `{"state": <str|obj|arr>, "model": "jev-latest", "questions": {<id>: Question}}`
- Question (discriminated by `type`):
  - `noul`: `instructions` (required), optional `criteria: {"true": str?, "false": str?}`
  - `choice`: `instructions`, required `criteria: {option: str|null}`
  - `score`: `instructions`, required `criteria: [levels...]` (ordered, >= 2)
- Answer:
  - `noul`: `{type, noul: float}` (0=no, 1=yes)
  - `choice`: `{type, choice: str, probabilities: {option: float} (sum 1), confidence: float}`
  - `score`: `{type, score: float (probability-weighted, may be fractional),
    legend: {level_index_str: desc}, probabilities: {level_index_str: float}, confidence: float}`
- Top response: `{model, answers: {id: Answer}, usage: {input_tokens, output_tokens}}`
- Errors: 401 auth, 403 permission, 404 not found, 400 bad request, 422 validation,
  429 rate limit, 529 overloaded, 5xx internal. Retry 429/529 with exponential backoff,
  honor `Retry-After` when present.
- Models listing exists in the official SDK (Models resource). Exact HTTP path/shape:
  read `docs/reference/sdk/python/api/clients/sync/models.md` and `.../client.md`
  before implementing; if the snapshot gives a path, use it. If no explicit path is
  documented, implement `models()` as `GET /v1/models` and note the assumption in code.

## Environment

- `JEV_API_KEY` preferred; fall back to `TYPESAFE_API_KEY` (official SDK's name).
- `JEV_BASE_URL` optional override (default `https://api.typesafe.ai`).
- `.env` at project root is auto-loaded by a tiny built-in loader (NO python-dotenv dep).
  `.env` is gitignored and MUST never be read into tests; tests inject `env={...}`.

## Package layout (src/daf_jev/)

- `_types.py` — wire dataclasses. No I/O.
  - `JSONContent = Union[str, list, dict]` (values inside dicts may be None; state itself may not)
  - `NoulQuestion(instructions: JSONContent, criteria: Optional[dict] = None)`,
    `ChoiceQuestion(instructions, criteria: Mapping[str, str | None])`,
    `ScoreQuestion(instructions, criteria: Sequence[str])` — all frozen dataclasses,
    class attr `type`, method `to_wire() -> dict` producing exactly the documented shape
    (omit `criteria` when None for noul; score criteria MUST be a list of >= 2 strings —
    raise `ValueError` otherwise; choice criteria MUST be non-empty).
  - `Question = Union[NoulQuestion, ChoiceQuestion, ScoreQuestion]`
  - Answers (frozen dataclasses): `NoulAnswer(noul: float)`,
    `ChoiceAnswer(choice: str, probabilities: dict[str, float], confidence: float)`,
    `ScoreAnswer(score: float, legend: dict[str, str], probabilities: dict[str, float],
    confidence: float)` — each with `type` attr; `answer_from_wire(payload) -> Answer`.
  - `Usage(input_tokens: int = 0, output_tokens: int = 0)`
  - `SystemOneResponse(model: str, answers: dict[str, Answer], usage: Usage,
    request_id: Optional[str] = None)` with cached `nouls` / `choices` / `scores`
    dict views filtered by answer type.
  - `parse_response(payload: dict, request_id: Optional[str]) -> SystemOneResponse`
    (strict: unknown answer type or missing keys raise `ValueError`).
- `_errors.py` — exception hierarchy (mirror the JS SDK classes):
  `TypeSafeError` base; `APIConnectionError`, `APITimeoutError`;
  `APIStatusError` (carries `status_code`, `body`, `request_id`) with subclasses
  `BadRequestError(400)`, `AuthenticationError(401)`, `PermissionDeniedError(403)`,
  `NotFoundError(404)`, `UnprocessableEntityError(422)`, `RateLimitError(429)`,
  `OverloadedError(529)`, `InternalServerError(5xx)`;
  `error_from_status(status_code, body, request_id) -> APIStatusError | None`.
  Read `docs/reference/sdk/python/api/exceptions.md` for messages/details.
- `_retry.py` — `RetryPolicy` frozen dataclass:
  `max_attempts=3, retryable_statuses=frozenset({429, 529}), backoff_base=0.5,
  backoff_max=8.0, jitter=0.1, respect_retry_after=True` and PURE method
  `next_delay(attempt: int, retry_after: Optional[float]) -> float`
  (exponential `backoff_base * 2**(attempt-1)` capped at `backoff_max`, plus uniform
  `±jitter/2`; `retry_after` wins when `respect_retry_after` and provided; >= 0).
  Sleep happens in the client (injectable clock/sleep for tests).
- `_http.py` — `Transport` protocol: `post_json(path: str, json_body: dict,
  headers: dict[str, str], *, timeout=None) -> httpx.Response` (+ `close()`).
  `HttpxTransport(base_url, timeout, headers)` implements it with `httpx`.
  Also `AsyncTransport` / `AsyncHttpxTransport` with `async` signature.
  `timeout=None` keeps the transport's configured default; a per-call value
  overrides it for that single request (explicit `None` is never forwarded to
  httpx, which would disable timeouts entirely).
- `client.py` —
  - `JevClient(api_key=None, *, base_url=None, model="jev-latest", transport=None,
    retry=None, sleep=time.sleep, timeout=None, env=None)`:
    resolves key via `config.resolve_api_key(env)`; raises `TypeSafeError` (or
    `ValueError`) when no key found and no transport injected. When `retry`
    / `timeout` are not passed they resolve from the environment via
    `config.resolve_retry(env)` / `config.resolve_timeout(env)`; explicit
    arguments always win.
  - `ask(state, questions: Mapping[str, Question], *, model=None,
    timeout=None, request_headers=None) -> SystemOneResponse`
    — single POST; retries per policy; maps errors. `timeout` overrides the
    client default for this call only; `request_headers` are merged over the
    default headers for this call only (per-call entries win, stored defaults
    never mutated).
  - `models() -> list[ModelCard]` (`ModelCard` dataclass per snapshot shape).
  - `close()`; context-manager support.
  - `AsyncJevClient` — same surface, `async def ask/models`, `async close`.
- `primitives.py` — ergonomic builders + composition container. No I/O.
  - `noul(instructions, *, true_desc=None, false_desc=None) -> NoulQuestion`
  - `choice(instructions, options: Mapping[str, str | None]) -> ChoiceQuestion`
  - `score(instructions, levels: Sequence[str]) -> ScoreQuestion`
  - `QuestionSet(Mapping[str, Question])` — `QuestionSet()`, `.add(id, q)`,
    `.merge(other)`, `to_wire()`, plus builder methods mirroring the free functions.
- `compose.py` — composable decision patterns (docs: /patterns/*). Pure logic over
  answers; network only via an injected client for the multi-call helpers.
  - `composite_score(answer: ScoreAnswer, weights: Optional[Sequence[float]] = None)
    -> float` — weighted (default uniform) expected value over level indices.
  - `confidence_gate(answer, *, threshold: float, below: str = "review") -> str`
    — returns the primary value when confidence >= threshold else `below`.
  - `route(answer: ChoiceAnswer, handlers: Mapping[str, Callable[[], T]],
    *, min_confidence: float = 0.0, fallback: Callable[[], T] | None = None) -> T`
  - `pick(actions: Mapping[str, Callable], choices: Mapping[str, ChoiceAnswer | Answer])`
    convenience wrapper.
- `models.py` — pure selection over the models listing; no I/O.
  - `pick_model(cards, *, contains=None, prefer="latest") -> ModelCard`
    — case-insensitive substring filter on `name` (`contains`); `prefer`
    `latest` = max `release_date` (None dates sort last, ties → first in
    input order), `first`/`last` = input order. `ValueError` on empty input,
    no match after filtering, or unknown `prefer`.
- `config.py` —
  - `load_dotenv(path: Path = Path(".env")) -> dict[str, str]` (KEY=VALUE, ignore
    comments/blank, no quoting gymnastics needed; never raise on missing file).
  - `resolve_api_key(env: Optional[Mapping[str, str]] = None) -> Optional[str]`
    — precedence: injected env mapping > process env > `.env` file
    (`JEV_API_KEY` then `TYPESAFE_API_KEY`).
  - `resolve_base_url(env=None) -> str` (JEV_BASE_URL or default).
  - `resolve_retry(env=None) -> RetryPolicy` — per-field overrides from
    `JEV_MAX_ATTEMPTS` (int >= 1), `JEV_BACKOFF_BASE` (float > 0),
    `JEV_BACKOFF_MAX`, `JEV_JITTER` (float >= 0); unset/invalid keeps the
    `RetryPolicy()` default for that field.
  - `resolve_timeout(env=None) -> float | None` — `JEV_TIMEOUT` seconds
    (positive float); unset/invalid → None.
  - `Settings` frozen dataclass (`api_key, base_url, model, retry=RetryPolicy(),
    timeout=None`) + `load_settings(env=None)` (populates retry/timeout via the
    new resolvers).
- `cli.py` — argparse (stdlib), thin. `main(argv=None) -> int`.
  - `daf-jev ask --state-file FILE | --state TEXT [--question ID=SPEC ...] [--model M]
    [--json | --pretty]` where SPEC is `noul:<instructions>` |
    `choice:<instructions>:opt1=desc,opt2=…` | `score:<instructions>:level1,level2,…`
    (option/level descriptions may be empty → None for choice).
  - `daf-jev models` — list models.
  - `daf-jev docs-verify [--manifest docs/reference/MANIFEST.json]` — re-hash
    `docs/reference/**` and report drift vs manifest (exit 1 on mismatch).
  - All output JSON to stdout; exit 0 ok, 2 usage, 1 runtime error.
- `__init__.py` — public exports:
  `JevClient, AsyncJevClient, NoulQuestion, ChoiceQuestion, ScoreQuestion, Question,
  NoulAnswer, ChoiceAnswer, ScoreAnswer, Usage, SystemOneResponse, RetryPolicy,
  TypeSafeError, RateLimitError, OverloadedError, APITimeoutError, APIConnectionError,
  noul, choice, score, QuestionSet, composite_score, confidence_gate, route,
  Settings, load_settings, resolve_retry, resolve_timeout, pick_model,
  Evaluator, EvaluationRecord, __version__`.
- `scripts/scrape_docs.py` — standalone (stdlib urllib) re-scraper: reads llms.txt,
  fetches every page into `docs/reference/` preserving `.md` paths, rewrites
  `MANIFEST.json` with per-page sha256 + `snapshot_id` (sha256 of concatenated page
  hashes, first 16 hex). CLI: `--check` mode exits 1 on drift, 0 on match (no writes).

## Tests (tests/) — template "no-mock" convention

- NEVER patch internal functions or monkeypatch client internals. The network
  stand-in is a REAL local HTTP server (`http.server` on 127.0.0.1, ephemeral port,
  fixture in `tests/conftest.py`) serving canned `/v1/systemone` and `/v1/models`
  responses; tests drive the real `HttpxTransport`/`JevClient` through it, including
  retry (server returns 429 once with `Retry-After: 0`, then 200 — assert 2 hits),
  error mapping (401/422/529), and timeout (client timeout < 0.05s against a slow
  handler).
- `tests/unit/` — per module: types round-trip + validation errors, retry `next_delay`
  math (deterministic via injected jitter seed or jitter=0), errors from status,
  client ask/models/response parsing + views, primitives builders, compose functions,
  config precedence (injected env > os.environ > .env fixture file), CLI via capsys
  (exit codes, JSON out, `docs-verify` against a temp fixture manifest).
- `tests/live/test_live_api.py` — `@pytest.mark.live` +
  `pytest.mark.skipif(not os.environ.get("JEV_API_KEY"), reason="JEV_API_KEY not set")`.
  Real API: mixed noul/choice/score call over a small state, assert shape and
  probability sums; models listing. MUST read the key from env only.
- Deterministic, isolated, full-suite-safe: live tests skipped without the key;
  no test reads the real `.env` (unit config tests pass explicit env mappings).

## Benchmarks (benchmarks/) — live API, graceful skip without key

- `bench_batching.py` — reproduce docs' parallel-questions claim: 1 call with N
  questions vs N calls with 1 question (N in {5, 10, 20}); report wall time, tokens,
  and speedup to stdout and `output/benchmarks/batching_<date>.json`.
- `bench_patterns.py` — latency of composite-score pipeline and confidence routing
  decisions end-to-end (1 call each); report p50/p95 over >= 10 runs.
- Both: argparse `--runs`, exit 0 with "SKIP: JEV_API_KEY not set" when key absent.

## Conventions (template_code_project)

- uv-managed; thin scripts; logic in src; >= 90% coverage gate on src.
- Python >= 3.10, stdlib + httpx (+ pyyaml) only.
- Every source dir carries README.md/AGENTS.md accurate to disk (docs pass later).
- Workers: NO linting/formatting/test-running/gate-running. Edit only.
