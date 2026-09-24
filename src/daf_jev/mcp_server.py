"""MCP server for the daf-jev toolkit.

Exposes the TypeSafe Jev (System One) client and decision toolkit as MCP
tools over the official SDK (:mod:`mcp.server.fastmcp`). Every tool returns
a JSON-safe dict/list/float/str and takes an optional ``provider``
argument (default ``jev``) validated against :mod:`daf_jev.providers`;
keys, base URL and default model resolve once per call via
:func:`daf_jev.config.load_settings` for that provider (a missing API
key raises ``ValueError``, which MCP surfaces as a tool error). Client,
compose and evaluate modules are imported lazily inside the tools, mirroring
:mod:`daf_jev.cli`; native question mappings and docs verification route
through the shared :mod:`daf_jev.questions` / :mod:`daf_jev.docs_verify`
modules.

Run with ``daf-jev serve`` (stdio transport, the default and only
supported transport).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from daf_jev import config
from daf_jev._types import JSONContent
from daf_jev.docs_verify import DEFAULT_MANIFEST, verify_manifest

__all__ = [
    "build_server",
    "jev_ask",
    "jev_composite_score",
    "jev_confidence_gate",
    "jev_docs_verify",
    "jev_evaluate",
    "jev_models",
    "jev_tiered_gate",
    "main",
]

_INSTRUCTIONS = (
    "daf-jev: a modular, composable client and decision toolkit for the "
    "TypeSafe Jev (System One) API. Use jev_ask to ask named questions "
    "(noul / choice / score) about a state in a single call, jev_evaluate "
    "to run a fixed question set over many states concurrently, and "
    "jev_models to list or pick models. Deterministic decision helpers "
    "(jev_composite_score, jev_confidence_gate, jev_tiered_gate) combine "
    "answers locally with no API call. jev_docs_verify checks the "
    "docs/reference snapshot against its manifest; the jev://docs/snapshot "
    "resource summarizes it. Question specs follow the daf-jev CLI grammar "
    "(noul:<instructions>, choice:<instructions>:k=desc,..., "
    "score:<instructions>:l1,l2,...) or native "
    "{type, instructions, criteria} dicts."
)


# ------------------------------------------------------------------ helpers


def _require_api_key(provider: str = "jev") -> config.Settings:
    """Resolve settings for ``provider``; raise ``ValueError`` when no API
    key is available."""
    settings = config.load_settings(provider=provider)
    if settings.api_key is None:
        from daf_jev.providers import get_provider

        spec = get_provider(provider)
        fallback = (
            f" (or {spec.api_key_vars[1]})" if len(spec.api_key_vars) > 1 else ""
        )
        raise ValueError(
            f"No API key found: set {spec.api_key_vars[0]}{fallback} so "
            f"daf-jev can reach the {spec.display_name} API"
        )
    return settings


def _validate_provider(provider: str) -> str:
    """Validate ``provider`` against the registry; return the canonical key.

    Raises ``ValueError`` listing the available keys for an unknown
    provider (MCP surfaces it as a JSON-safe tool error).
    """
    from daf_jev.providers import get_provider

    return get_provider(provider).key


def _question_from_value(value: Any, *, context: str = "question") -> Any:
    """Build a question object from a CLI ask-spec string or native dict.

    Spec strings are parsed with :func:`daf_jev.cli.parse_question_spec`;
    native mappings route through
    :func:`daf_jev.questions.question_from_mapping`.
    """
    from daf_jev.cli import parse_question_spec
    from daf_jev.questions import question_from_mapping

    if isinstance(value, str):
        return parse_question_spec(value)
    return question_from_mapping(value, context=context)


def _questions_from_mapping(questions: dict[str, Any]) -> dict[str, Any]:
    return {
        str(qid): _question_from_value(
            spec, context=f"question {str(qid)!r}"
        )
        for qid, spec in questions.items()
    }


# -------------------------------------------------------------------- tools


async def jev_ask(
    state: JSONContent,
    questions: dict[str, str | dict],
    model: str | None = None,
    provider: str = "jev",
) -> dict:
    """Ask named questions about one state in a single API call.

    ``questions`` maps question id to either a CLI ask-spec string
    (``noul:<instructions>``, ``choice:<instructions>:k=desc,...``,
    ``score:<instructions>:l1,l2,...``) or a native
    ``{type, instructions, criteria}`` dict. Returns
    ``{model, answers: {id: answer dict with type}, usage, request_id}``;
    ``request_id`` is omitted when the API did not return one.
    ``provider`` selects the registered API provider (default ``jev``).
    """
    provider = _validate_provider(provider)
    settings = _require_api_key(provider)
    from daf_jev.client import open_async_client

    questions_obj = _questions_from_mapping(questions)
    async with open_async_client(
        provider=provider,
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout=settings.timeout,
    ) as client:
        response = await client.ask(state, questions_obj, model=model)

    payload: dict[str, Any] = {
        "model": response.model,
        "answers": {
            qid: {**dataclasses.asdict(answer), "type": answer.type}
            for qid, answer in response.answers.items()
        },
        "usage": dataclasses.asdict(response.usage),
    }
    if response.request_id is not None:
        payload["request_id"] = response.request_id
    return payload


async def jev_evaluate(
    states: list[str | dict],
    questions: dict[str, str | dict],
    concurrency: int = 4,
    model: str | None = None,
    provider: str = "jev",
) -> dict:
    """Evaluate a fixed question set over many states, concurrently.

    Returns the aggregate summary only (no per-state records):
    ``{n_states, n_errors, total_input_tokens, total_output_tokens,
    mean_latency_s, p95_latency_s, questions}``. Raises ``ValueError``
    on an empty ``states`` list or a state that is neither a string nor
    a JSON object/array.
    ``provider`` selects the registered API provider (default ``jev``).
    """
    provider = _validate_provider(provider)
    if not states:
        raise ValueError("states must be a non-empty list of states to evaluate")
    settings = _require_api_key(provider)
    from daf_jev.client import open_async_client
    from daf_jev.evaluate import Evaluator

    questions_obj = _questions_from_mapping(questions)
    # Evaluator accepts bare str states only; object/array states must be
    # (state_id, state) tuples. Mirror its state_0000-style id assignment.
    items: list[tuple[str, JSONContent]] = []
    for index, state in enumerate(states):
        if not isinstance(state, (str, dict, list)):
            raise ValueError(
                f"states[{index}] must be a string or a JSON object/array, "
                f"got {type(state).__name__}"
            )
        items.append((f"state_{index:04d}", state))

    # Drive the Evaluator's public async entry point (asyncio.Semaphore
    # over AsyncJevClient) directly on the serving loop, like jev_ask, so a
    # long batch never blocks the other tools. evaluate_async() closes the
    # client session when the batch completes; the async-with below only
    # covers error paths.
    async with open_async_client(
        provider=provider,
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout=settings.timeout,
    ) as client:
        evaluator = Evaluator(
            client,
            questions_obj,
            concurrency=concurrency,
            model=model,
        )
        records = await evaluator.evaluate_async(items)
        return evaluator.summary(records)


async def jev_models(
    pick: Literal["latest", "first", "last"] | None = None,
    contains: str | None = None,
    provider: str = "jev",
) -> list[dict]:
    """List available model cards as dicts.

    When ``pick`` (``latest`` | ``first`` | ``last``) or ``contains``
    (case-insensitive substring filter on the model name; the empty
    string is no filter) is given, one card is selected via
    :func:`daf_jev.models.pick_model` and returned as a single-element
    list. Raises ``ValueError`` when nothing matches.
    ``provider`` selects the registered API provider (default ``jev``).
    """
    provider = _validate_provider(provider)
    settings = _require_api_key(provider)
    from daf_jev.client import open_async_client

    async with open_async_client(
        provider=provider,
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout=settings.timeout,
    ) as client:
        cards = await client.models()

    if pick is not None or contains:
        from daf_jev.models import pick_model

        card = pick_model(cards, contains=contains, prefer=pick or "latest")
        return [dataclasses.asdict(card)]
    return [dataclasses.asdict(card) for card in cards]


async def jev_composite_score(
    probabilities: dict[str, float],
    weights: list[float] | None = None,
    provider: str = "jev",
) -> float:
    """Expected value of a score distribution over its level indices.

    ``probabilities`` maps level index (as a string) to probability. With
    ``weights`` (one per level, positional order matching the sorted level
    indices) the distribution is re-weighted as in
    :func:`daf_jev.compose.composite_score`. Requires at least 2 levels;
    probabilities must be finite and non-negative and keys integer level
    indices (ValueError otherwise).
    ``provider`` is validated against the registry; local math is
    provider-agnostic.
    """
    _validate_provider(provider)
    from daf_jev._types import ScoreAnswer
    from daf_jev.compose import composite_score

    if len(probabilities) < 2:
        raise ValueError(
            f"probabilities must cover at least 2 levels, got "
            f"{len(probabilities)}"
        )
    try:
        probs = {str(int(key)): float(value) for key, value in probabilities.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"probabilities keys must be level indices and values numbers: {exc}"
        ) from exc
    indices = sorted(int(key) for key in probs)
    answer = ScoreAnswer(
        score=0.0,
        legend={str(index): str(index) for index in indices},
        probabilities=probs,
        confidence=0.0,
    )
    return composite_score(answer, weights=weights)


async def jev_confidence_gate(
    choice: str,
    confidence: float,
    threshold: float,
    below: str = "review",
    provider: str = "jev",
) -> str:
    """Return ``choice`` when ``confidence >= threshold``, else ``below``.

    Local deterministic routing over a synthesized choice answer — no API
    call.
    ``provider`` is validated against the registry; the gate is
    provider-agnostic.
    """
    _validate_provider(provider)
    from daf_jev._types import ChoiceAnswer
    from daf_jev.compose import confidence_gate

    return confidence_gate(
        ChoiceAnswer(choice=choice, probabilities={}, confidence=confidence),
        threshold=threshold,
        below=below,
    )


async def jev_tiered_gate(
    choice: str,
    confidence: float,
    high: float = 0.85,
    low: float = 0.6,
    high_label: str = "automate",
    middle_label: str = "review",
    low_label: str = "escalate",
    provider: str = "jev",
) -> str:
    """Two-threshold confidence routing (automate / review / escalate).

    ``confidence >= high`` -> ``high_label``, ``>= low`` -> ``middle_label``,
    otherwise ``low_label``. Non-finite thresholds raise ``ValueError``;
    a NaN confidence escalates (fail closed). Local and deterministic — no
    API call.
    ``provider`` is validated against the registry; the gate is
    provider-agnostic.
    """
    _validate_provider(provider)
    from daf_jev._types import ChoiceAnswer
    from daf_jev.compose import tiered_gate

    return tiered_gate(
        ChoiceAnswer(choice=choice, probabilities={}, confidence=confidence),
        high=high,
        low=low,
        high_label=high_label,
        middle_label=middle_label,
        low_label=low_label,
    )


async def jev_docs_verify(
    manifest: str | None = None, provider: str = "jev"
) -> dict:
    """Verify the docs/reference snapshot against its manifest.
    ``manifest`` selects an explicit manifest path; ``None`` (default)
    verifies the shipped snapshot manifest
    (``daf_jev.docs_verify.DEFAULT_MANIFEST``).

    Same verifier as the ``daf-jev docs-verify`` CLI command
    (:func:`daf_jev.docs_verify.verify_manifest`). On success returns
    ``{manifest, pages, missing, drifted, added, ok}``; when the manifest
    cannot be read or parsed, returns
    ``{error, message, ok: false}`` instead.
    An unknown ``provider`` returns the ``{error, message, ok: false}``
    shape instead of raising.
    """
    manifest_path = Path(manifest) if manifest is not None else None
    try:
        _validate_provider(provider)
        return verify_manifest(manifest_path)
    except ValueError as exc:
        return {"error": type(exc).__name__, "message": str(exc), "ok": False}


# ------------------------------------------------------------- server setup


def _snapshot_summary(manifest_path: Path | None = None) -> dict[str, Any]:
    """Summarize a docs snapshot manifest (``jev://docs/snapshot`` body).

    ``manifest_path=None`` (the default) resolves to the shipped
    :data:`DEFAULT_MANIFEST`; pass an explicit path to summarize another
    manifest — the parameterized seam the tests use instead of patching.
    """
    if manifest_path is None:
        manifest_path = DEFAULT_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": type(exc).__name__, "message": str(exc), "ok": False}
    return {
        "page_count": manifest.get("page_count", len(manifest.get("pages", {}))),
        "snapshot_id": manifest.get("snapshot_id"),
        "scraped_at": manifest.get("scraped_at_utc"),
        "index_sha256": manifest.get("index_sha256"),
    }


def _docs_snapshot() -> dict[str, Any]:
    """Resource body for ``jev://docs/snapshot`` (the shipped snapshot)."""
    return _snapshot_summary()


def build_server() -> FastMCP:
    """Build the daf-jev MCP server (stdio transport via ``main()``)."""
    mcp = FastMCP("daf-jev", instructions=_INSTRUCTIONS)
    mcp.tool()(jev_ask)
    mcp.tool()(jev_evaluate)
    mcp.tool()(jev_models)
    mcp.tool()(jev_composite_score)
    mcp.tool()(jev_confidence_gate)
    mcp.tool()(jev_tiered_gate)
    mcp.tool()(jev_docs_verify)
    mcp.resource("jev://docs/snapshot")(_docs_snapshot)
    return mcp


def main(transport: str = "stdio") -> None:
    """Run the MCP server over the given (stdio-only) transport."""
    if transport != "stdio":
        raise ValueError(
            f"unsupported transport {transport!r}; daf-jev serves stdio only"
        )
    build_server().run(transport="stdio")
