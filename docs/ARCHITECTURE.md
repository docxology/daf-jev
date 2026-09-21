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
  honoring `Retry-After` when present: the `Retry-After-ms` header wins when set, then
  the numeric `Retry-After` form — both clamped to [0, 300] seconds; the HTTP-date form
  is intentionally unsupported and falls back to exponential backoff.
- Models listing exists in the official SDK (Models resource). Exact HTTP path/shape:
  read `docs/reference/sdk/python/api/clients/sync/models.md` and `.../client.md`
  before implementing; if the snapshot gives a path, use it. If no explicit path is
  documented, implement `models()` as `GET /v1/models` and note the assumption in code.

## Environment

- `JEV_API_KEY` preferred; fall back to `TYPESAFE_API_KEY` (official SDK's name).
- `JEV_BASE_URL` optional override (default `https://api.typesafe.ai`).
- `.env` in the working directory (`Path(".env")` default) is auto-loaded by a tiny
  built-in loader (NO python-dotenv dep). Values are stripped before use, so
  whitespace-only values count as unset at every layer (injected env > process env >
  `.env`). `.env` is gitignored and MUST never be read into tests; tests inject `env={...}`.

## Package layout (src/daf_jev/)

- `_types.py` — wire dataclasses. No I/O.
  - `JSONContent = Union[str, list, dict]` (values inside dicts may be None; state itself may not)
  - `NoulQuestion(instructions: JSONContent, criteria: Optional[dict] = None)`,
    `ChoiceQuestion(instructions, criteria: Mapping[str, str | None])`,
    `ScoreQuestion(instructions, criteria: Sequence[str])` — all frozen dataclasses,
    class attr `type`, method `to_wire() -> dict` producing exactly the documented shape
    (omit `criteria` when None for noul; score criteria MUST be a list of >= 2 strings —
    raise `ValueError` otherwise; choice criteria MUST be a non-empty `Mapping` whose
    values are `str | None` — `ValueError` otherwise).
  - `Question = Union[NoulQuestion, ChoiceQuestion, ScoreQuestion]`
  - Answers (frozen dataclasses): `NoulAnswer(noul: float)`,
    `ChoiceAnswer(choice: str, probabilities: dict[str, float], confidence: float)`,
    `ScoreAnswer(score: float, legend: dict[str, str], probabilities: dict[str, float],
    confidence: float)` — each with `type` attr; `answer_from_wire(payload) -> Answer`.
  - `Usage(input_tokens: int = 0, output_tokens: int = 0)`
  - `SystemOneResponse(model: str, answers: dict[str, Answer], usage: Usage,
    request_id: Optional[str] = None)` with cached `nouls` / `choices` / `scores`
    dict views filtered by answer type.
  - `parse_response(payload: dict, request_id: Optional[str] = None) -> SystemOneResponse`
    (strict: unknown answer type or missing keys raise `ValueError`).
  - Strict parsing (hardened): numeric wire fields reject `bool` and numeric strings
    (int/float only); `choice`/`model` require an actual `str`; malformed
    `probabilities`/`legend`/`usage` shapes raise `ValueError`, never
    `TypeError`/`AttributeError`. `Usage` token counts follow the same numeric
    contract: an `int` passes as-is (`bool` never does), a float only when
    integral (`100.0` -> `100`), and numeric strings raise `ValueError`
    ("input_tokens must be an integer number"). `legend` values must already be
    strings (`ValueError` "legend values must be strings" — `None`/bool/int are
    never `str()`-coerced; level keys stay stringified).
- `_errors.py` — exception hierarchy (mirror the JS SDK classes):
  `TypeSafeError` base; `APIConnectionError`, `APITimeoutError`;
  `APIStatusError` (carries `status_code`, `body`, `request_id`) with subclasses
  `BadRequestError(400)`, `AuthenticationError(401)`, `PermissionDeniedError(403)`,
  `NotFoundError(404)`, `UnprocessableEntityError(422)`, `RateLimitError(429)`,
  `OverloadedError(529)`, `InternalServerError(5xx)`;
  `error_from_status(status_code, body=None, request_id=None) -> APIStatusError | None`.
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
  Both httpx transports also expose `get_json(path, headers, *, timeout=None)`
  (models listing) under the same per-call timeout rule.
  `timeout=None` keeps the transport's configured default; a per-call value
  overrides it for that single request (explicit `None` is never forwarded to
  httpx, which would disable timeouts entirely). A transport constructed
  without a timeout passes `DEFAULT_TIMEOUT_SECONDS = 60.0` to httpx instead of
  httpx's own 5-second default; `_normalize_base_url` ensures a base URL with a
  path component ends with `/`.
- `client.py` —
  - `JevClient(api_key=None, *, base_url=None, model=None, transport=None,
    retry=None, sleep=time.sleep, timeout=None, env=None)`:
    resolves key via `config.resolve_api_key(env)`; `model=None` resolves via
    `config.resolve_model(env)` (`JEV_MODEL` / `TYPESAFE_DEFAULT_MODEL`, then
    `jev-latest`); empty/whitespace `api_key` or `model` raises `ValueError`;
    raises `TypeSafeError` when no key found and no transport injected. When
    `retry` / `timeout` are not passed they resolve from the environment via
    `config.resolve_retry(env)` / `config.resolve_timeout(env)` (that timeout
    may be None → the transport's 60.0 s default); explicit arguments always
    win.
  - `ask(state, questions: Mapping[str, Question], *, model=None,
    timeout=None, request_headers=None) -> SystemOneResponse`
    — single POST; retries per policy; maps errors. `timeout` overrides the
    client default for this call only; `request_headers` are merged over the
    default headers for this call only (per-call entries win, stored defaults
    never mutated).
  - `models(*, timeout=None, request_headers=None) -> list[ModelCard]` — a
    GET retried per the same policy as `ask` (shared send/retry path);
    per-call `timeout`/`request_headers` semantics identical to `ask`
    (explicit `None` never forwarded — constructor/env default applies;
    per-call header entries win, stored defaults never mutated).
    `ModelCard` is a dataclass per snapshot shape.
  - `close()`; context-manager support. `close()` sets the closed flag only
    after the transport close completes; `ask`/`models` after close raise
    `TypeSafeError("client is closed")`.
  - `AsyncJevClient` — same surface, `async def ask/models`, `async close`.
  - httpx exception mapping (checked in order): `httpx.TimeoutException` →
    `APITimeoutError` FIRST; then `httpx.HTTPError` (TransportError +
    RequestError, incl. `DecodingError`/`TooManyRedirects`) and
    `httpx.StreamError` → `APIConnectionError`.
- `primitives.py` — ergonomic builders + composition container. No I/O.
  - `noul(instructions, *, true_desc=None, false_desc=None) -> NoulQuestion`
  - `choice(instructions, options: Mapping[str, str | None]) -> ChoiceQuestion`
  - `score(instructions, levels: Sequence[str]) -> ScoreQuestion`
    (every builder validates `instructions` is str/list/dict — `ValueError`
    otherwise)
  - `QuestionSet(Mapping[str, Question])` — `QuestionSet()`, `.add(id, q)`,
    `.merge(other)`, `to_wire()`, plus builder methods mirroring the free functions.
- `compose.py` — composable decision patterns (docs: /patterns/*). Pure logic
  over answers; no I/O and no client dependency.
  - `composite_score(answer: ScoreAnswer, weights: Optional[Sequence[float]] = None)
    -> float` — weighted (default uniform) expected value over level indices.
    Probabilities validated once on a shared canonical path: keys parsed via
    `int()` (`ValueError` "probability keys must be integer level indices"
    otherwise), values must be finite and non-negative (`ValueError` naming
    key/value); duplicate integer spellings of one level ('1', '01')
    accumulate onto that level, and both weighting paths iterate the canonical
    sorted indices. With weights: length must match the level count, weights
    finite, sum positive, weighted mass non-zero (each `ValueError`). The
    `[min index, max index]` range guarantee holds for non-negative weights;
    negative weights are accepted deliberately (scale-invariant reweighting)
    but void it.
  - `confidence_gate(answer, *, threshold: float, below: str = "review") -> str`
    — returns the primary value when confidence >= threshold else `below`;
    a Score answer's level maps via `round` (nearest, ties to even) clamped
    to the probable level range; a non-finite score raises `ValueError`.
  - `route(answer: ChoiceAnswer, handlers: Mapping[str, Callable[[], T]],
    *, min_confidence: float = 0.0, fallback: Callable[[], T] | None = None) -> T`
    — NaN confidence fails the `>= min_confidence` comparison and routes to
    the fallback (fail-closed; `ValueError` when no fallback is provided).
  - `tiered_gate(answer, *, high=0.85, low=0.6, high_label="automate",
    middle_label="review", low_label="escalate") -> str` — two-threshold
    routing: confidence >= high → high_label, >= low → middle_label, else
    low_label; non-finite thresholds, `low > high`, or empty labels raise
    `ValueError`; a NaN confidence compares False against both thresholds and
    escalates; answers without a `confidence` field raise `TypeError`.
  - `pick(actions: Mapping[str, Callable], choices: Mapping[str, ChoiceAnswer | Answer])`
    convenience wrapper; isinstance-narrows to `ChoiceAnswer` and silently
    skips other answers (unchanged).
- `models.py` — pure selection over the models listing; no I/O.
  - `pick_model(cards, *, contains=None, prefer="latest") -> ModelCard`
    — case-insensitive substring filter on `name` (`contains`); `prefer`
    `latest` = max `release_date` (None dates sort last, ties → first in
    input order), `first`/`last` = input order. `ValueError` on empty input,
    no match after filtering, or unknown `prefer`.
- `evaluate.py` — concurrent evaluation of a fixed question set over many
  states. `Evaluator(client, questions, *, concurrency=4, model=None)` with
  `client` typed `JevClient | AsyncJevClient` (a foreign client raises
  `TypeError` from `evaluate()`); thread pool for the sync client,
  `asyncio.Semaphore` for the async one. The public
  `async def evaluate_async(items)` is the ONE async path: it takes the
  normalized `(state_id, state)` items, requires an `AsyncJevClient`
  (`TypeError` otherwise), runs the semaphore path on the caller's event
  loop, and stores records so `summary()`/`to_json()` work exactly like
  after `evaluate()`; `evaluate()` normalizes raw states, then drives that
  same method on a private event loop (worker thread when called from
  inside a running loop) so it stays synchronous. Per-state failures are
  captured into `EvaluationRecord.error`, never aborting the batch. The
  async session is closed in a `finally`, so a cancelled gather still
  closes it (an `AsyncJevClient` is single-use through one evaluation).
  `summary()` latency mean/p95 span ALL records, failed included — a
  deliberate ops signal; token totals and per-question aggregates cover
  successful records only. Aggregation keys off the question's DECLARED
  type with per-type `isinstance` narrowing; an unknown declared type is
  skipped.
- `calibration.py` — pure confidence-calibration statistics over
  (confidence, correct) pairs: `bucket_index`, `reliability_table`,
  `expected_calibration_error`, `brier_score`. Every entry point validates
  each confidence in [0, 1] through the shared `_check_confidence` (NaN fails
  the chained comparison) — `ValueError` otherwise; `brier_score` also
  rejects empty `pairs`.
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
  - `resolve_model(env=None) -> str` (`JEV_MODEL` / `TYPESAFE_DEFAULT_MODEL`
    or default `jev-latest`).
  - `Settings` frozen dataclass (`api_key, base_url, model, retry=RetryPolicy(),
    timeout=None`) + `load_settings(env=None)` — reads `.env` exactly once and
    shares the parsed mapping across the private resolvers (the public
    `resolve_*` signatures are unchanged).
- `ledger.py` — thread-safe usage accounting across call loops (no I/O):
  `UsageLedger.record(Usage | SystemOneResponse | None) -> None` (None is a
  silent no-op for error paths; anything else raises `TypeError`);
  `snapshot()` / `reset()` (returns pre-reset
  totals, then zeroes) return a frozen `UsageSnapshot` (`requests`,
  `input_tokens`, `output_tokens`, `total_tokens` property, JSON-safe
  `to_dict()`). Complements `Evaluator.summary()`, which aggregates usage
  per evaluation batch.
- `resilience.py` — opt-in client-side failure isolation:
  `CircuitState` (closed / open / half_open), `CircuitOpenError(TypeSafeError)`
  (carries `remaining_seconds`), `CircuitBreaker(failure_threshold=5,
  cooldown_seconds=30.0, clock=time.monotonic)` with `call(fn, *args,
  **kwargs)`, `record_success()` / `record_failure()`, pure-read `state` /
  `consecutive_failures`, and a JSON-safe `to_dict()`. N consecutive
  failures open the circuit for the cooldown; a single probe is admitted
  after it (probe failure reopens with a fresh stamp). `call()` records a
  failure on any `BaseException` (KeyboardInterrupt, SystemExit,
  CancelledError included) and always re-raises, so a HALF_OPEN probe can
  never wedge the breaker; `CircuitOpenError.remaining_seconds` is always a
  float >= 0 (`0.0` for the probe-rejection race). The wrapped callable
  always runs outside the lock and the breaker never sleeps — the same
  pure-computation philosophy as `RetryPolicy`. Default OFF: `JevClient`
  is not wired to it.
- `decider.py` — decision-point decider: the observe -> compose -> ask ->
  gate -> fail-open -> act loop as one reusable class. Pure orchestration
  over injected I/O; `decide()` never raises (the fallback hook is the
  floor and must not raise).
  - `DecisionEvent(source, reason, error, latency_s, usage, request_id)`
    frozen dataclass with a JSON-safe `to_dict()`; `source` is
    `"model"` / `"cache"` / `"fallback"`, `reason` follows the closed
    fallback taxonomy: `not_asked`, `no_key` (latched for the Decider's
    lifetime), `client_error` (latched), `latched`
    (`max_consecutive_failures` reached), `budget`, `breaker`,
    `compose_error`, `ask_error` (counts toward the latch), `gate`,
    `mapping_error` (counts toward the latch), `error` LAST (belt-and-suspenders:
    any unexpected exception inside `decide()` that no earlier guard catches —
    a raising `cache_key`, a raising cache mapping operation, or a raising
    `should_ask`/gate hook).
  - `ConfidenceGate(answer_id, threshold)` — frozen; threshold validated
    in [0, 1] else `ValueError`. Returns None to accept, a rejection
    reason otherwise; noul answers (no confidence attr) are not gated.
  - `Budget(max_calls=None, max_input_tokens=None, max_output_tokens=None,
    max_total_tokens=None, attempts=0)` — at least one threshold required, and
    every provided threshold must be >= 0 (`max_calls=0` stays valid — a
    deliberate "no calls" budget), else `ValueError`; `charge()` once per ask
    attempt (success or
    failure); `exceeded(usage: UsageSnapshot)` returns a human-readable
    reason when any limit is met/passed; JSON-safe `to_dict()`.
  - `Decider(Generic[S, T])(client=None, *, render_state, questions,
    map_answers, fallback, gate=None, should_ask=None, budget=None,
    cache=None, cache_key=None, ledger=None, breaker=None, timeout=None,
    max_consecutive_failures=3, client_factory=None, env=None,
    clock=time.monotonic, on_event=None)` — `client`/`client_factory`
    mutually exclusive, `cache`/`cache_key` together, latch >= 1,
    timeout > 0 (else `ValueError`). `decide()` order: cache hit (the
    `cache_key` is computed once per decide and reused by the final store) ->
    `should_ask` -> client resolution (latching: injected client;
    factory called once — an exception OR a None return latches
    `client_error`; default path
    resolves the key — None latches `no_key`, else
    `JevClient(env=env, retry=RetryPolicy(max_attempts=1))`, single
    attempt per ask so worst-case blocking is one timeout) -> budget gate
    -> compose (`compose_error`) -> one ask behind the optional breaker
    (`CircuitOpenError` -> `breaker`; other exceptions count toward the
    latch, reason `ask_error`) -> ledger record + failure-counter reset ->
    gate (`gate`) -> map (`mapping_error`, counts toward the latch) ->
    cache store + `"model"` event. Extra surface: `last_event`,
    `usage_snapshot()`, `calibration_pairs()` (declared-confidence /
    gate-accepted pairs when the gate is a `ConfidenceGate` — a
    self-consistency proxy, NOT correctness), `dead` property.
- `cli.py` — argparse (stdlib), thin. `main(argv=None) -> int`. Common flags:
  `--base-url` (ask/models/evaluate) and `--json`/`--pretty` (mutually
  exclusive; compact is the default).
  - `daf-jev ask --state-file FILE | --state TEXT [--question ID=SPEC ...] [--model M]
    [--json | --pretty]` where SPEC is `noul:<instructions>` |
    `choice:<instructions>:opt1=desc,opt2=…` | `score:<instructions>:level1,level2,…`
    (option/level descriptions may be empty → None for choice; `\,` `\:` `\\`
    escape the delimiters inside a SPEC). Duplicate `--question` ids are
    rejected; `--state-file` content parses only as dict/list JSON (scalar
    JSON such as `123` stays raw text). Usage errors — malformed `--question`,
    unreadable `--state-file`, zero questions, duplicate ids — exit 2 with
    `{"error": "UsageError", ...}` on stderr; runtime errors exit 1 with the
    exception class name in the JSON.
  - `daf-jev models [--pick latest|first|last] [--contains STR]` — list or
    pick models.
  - `daf-jev evaluate --questions-file PATH --states-file PATH
    [--concurrency N] [--model M] [--include-records]` — YAML questions (SPEC
    strings or native `{type, instructions, criteria}` mappings; duplicate
    keys rejected, nested included), states one per line or a JSON array of
    strings; prints the summary JSON (`--include-records` adds per-state
    records).
  - `daf-jev docs-verify [--manifest PATH]` — delegates to
    `daf_jev.docs_verify.verify_manifest` (default: the absolute
    repo-root-anchored `docs/reference/MANIFEST.json`, independent of the
    CWD); prints `{manifest, pages, missing, drifted, added, ok}` where
    `added` lists extra `.md` files the manifest does not list; exit 1 when
    `ok` is False.
  - `daf-jev serve [--transport stdio]` — runs the MCP server (stdio only);
    a missing `mcp` extra prints a `uv sync --extra mcp` hint (exit 1).
  - All output JSON to stdout; exit 0 ok, 2 usage, 1 runtime error.
- `__init__.py` — eager imports only (no ImportError guards). Public exports
  (46 names incl. `__version__`): the original 41-name list plus five
  intentional additions — `ModelCard`, `Answer`, `JSONContent`,
  `answer_from_wire`, `parse_response` — i.e.:
  `JevClient, AsyncJevClient, NoulQuestion, ChoiceQuestion, ScoreQuestion, Question,
  Answer, JSONContent, NoulAnswer, ChoiceAnswer, ScoreAnswer, Usage, SystemOneResponse,
  ModelCard, RetryPolicy, TypeSafeError, RateLimitError, OverloadedError, APITimeoutError,
  APIConnectionError, noul, choice, score, QuestionSet, composite_score, confidence_gate,
  route, Settings, load_settings, resolve_retry, resolve_timeout, pick_model,
  Evaluator, EvaluationRecord, UsageLedger, UsageSnapshot, CircuitBreaker,
  CircuitOpenError, CircuitState, Budget, ConfidenceGate, DecisionEvent,
  Decider, answer_from_wire, parse_response, __version__`.
- `scripts/scrape_docs.py` — standalone (stdlib urllib) re-scraper: reads llms.txt,
  fetches every page into `docs/reference/` preserving `.md` paths, rewrites
  `MANIFEST.json` with per-page sha256 + `snapshot_id` (sha256 of concatenated page
  hashes, first 16 hex). CLI: `--check` mode exits 1 on drift, 0 on match (no
  writes); `--timeout` must be > 0; a derived page path containing `..` raises
  `ValueError` (a hostile index must not write outside the output dir);
  unrecognized llms.txt lines are skipped with a stderr warning.
- `scripts/generate_figures.py` — thin orchestrator over `figures.py` (needs
  the `figures` extra): renders the registry (or `--only NAME`, exit 2 on an
  unknown name) and ALWAYS writes `figure_registry.json` — `--only` runs
  included — because template validation requires it; exit 1 on unexpected
  error (missing benchmark data names the file), 0 on success.
- `scripts/z_generate_manuscript_variables.py` — thin orchestrator over
  `manuscript_variables.py`: writes `output/data/manuscript_variables.json`
  and (inside a template checkout) injects `{{TOKEN}}`s; strict mode (default)
  exits 1 with a `FileNotFoundError` naming the missing analysis output rather
  than fabricating values; `--allow-draft` emits `N/A` sentinels instead.
- `questions.py` — shared native question-mapping builder (no I/O):
  `question_from_mapping(value, *, context="question") -> Question` builds a
  `NoulQuestion`/`ChoiceQuestion`/`ScoreQuestion` from a
  `{type, instructions, criteria}` mapping with strict validation and
  actionable `ValueError` messages; the CLI (`evaluate --questions-file`) and
  the MCP server route native mappings through it so validation is defined
  exactly once.
- `docs_verify.py` — shared verifier for a docs snapshot manifest (read-only):
  `verify_manifest(manifest_path)` re-hashes every listed page (sha256 + byte
  length), flags `url`→path mismatches as `drifted`, and reports extra `.md`
  files as `added`; report schema `{manifest, pages, missing, drifted, added,
  ok}` with `ok` True only when all three finding lists are empty (the CLI
  treats `added` as failure, mirroring `scrape_docs.py --check`);
  `DEFAULT_MANIFEST` is anchored to the repo root this module is installed
  in, not the process CWD.
- `mcp_server.py` — FastMCP server (`build_server()`,
  `main(transport="stdio")`): 7 tools — `jev_ask` (state widened to
  str|dict|list; questions are SPEC strings or native dicts routed through
  `question_from_mapping`), `jev_evaluate` (async: `AsyncJevClient` +
  `Evaluator.evaluate_async()` on the serving loop; empty `states` →
  `ValueError`),
  `jev_models` (async; `pick` is a Literal schema; `contains=""` = no
  filter), `jev_composite_score` (finite/non-negative probability validation
  via `composite_score`), `jev_confidence_gate`, `jev_tiered_gate`,
  `jev_docs_verify` (error shape `{"error", "message", "ok": False}`) — plus
  the `jev://docs/snapshot` resource via `docs_verify` (CWD-independent).
  Every return is JSON-safe (`dataclasses.asdict`); stdio transport only;
  `mcp` imports at module level (optional extra — never from core modules);
  client/compose/evaluate import lazily inside the tools.

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
  (exit codes, JSON out, `docs-verify` against a temp fixture manifest),
  decider loop end-to-end over the stub server (`tests/unit/test_decider.py`:
  happy path, cache, budget, breaker, consecutive-failure latch, gate,
  mapping/compose errors, no-key/client-error latching, event receipts).
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
