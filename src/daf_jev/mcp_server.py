"""MCP server for the daf-jev toolkit.

Exposes the TypeSafe Jev (System One) client and decision toolkit as MCP
tools over the official SDK (:mod:`mcp.server.fastmcp`). Every tool returns
a JSON-safe dict/list/float/str; keys, base URL and default model are
resolved once per call via :func:`daf_jev.config.load_settings` (a missing
API key raises ``ValueError``, which MCP surfaces as a tool error). Client,
compose and evaluate modules are imported lazily inside the tools, mirroring
:mod:`daf_jev.cli`.

Run with ``daf-jev serve`` (stdio transport, the default and only
supported transport).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from daf_jev import config

DEFAULT_MANIFEST = Path("docs/reference/MANIFEST.json")

__all__ = [
    "build_server",
    "main",
    "jev_ask",
    "jev_evaluate",
    "jev_models",
    "jev_composite_score",
    "jev_confidence_gate",
    "jev_tiered_gate",
    "jev_docs_verify",
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


def _require_api_key() -> config.Settings:
    """Resolve settings; raise ``ValueError`` when no API key is available."""
    settings = config.load_settings()
    if settings.api_key is None:
        raise ValueError(
            "No API key found: set JEV_API_KEY (or TYPESAFE_API_KEY) so "
            "daf-jev can reach the TypeSafe API"
        )
    return settings


def _question_from_value(value: Any) -> Any:
    """Build a question object from a CLI ask-spec string or native dict.

    Spec strings are parsed with :func:`daf_jev.cli.parse_question_spec`;
    native dicts must be ``{type, instructions, criteria}`` mappings.
    """
    from daf_jev._types import ChoiceQuestion, NoulQuestion, ScoreQuestion
    from daf_jev.cli import parse_question_spec

    if isinstance(value, str):
        return parse_question_spec(value)
    if not isinstance(value, dict):
        raise ValueError(
            f"question must be a spec string or a {{type, instructions, "
            f"criteria}} mapping, got {type(value).__name__}"
        )
    qtype = value.get("type")
    instructions = value.get("instructions")
    criteria = value.get("criteria")
    if not qtype:
        raise ValueError("native question mapping requires 'type'")
    if instructions is None:
        raise ValueError("native question mapping requires 'instructions'")
    if qtype == "noul":
        if criteria is not None and not isinstance(criteria, dict):
            raise ValueError(
                "noul criteria must be a mapping with optional "
                "'true'/'false' keys"
            )
        return NoulQuestion(instructions=instructions, criteria=criteria)
    if qtype == "choice":
        if not isinstance(criteria, dict) or not criteria:
            raise ValueError(
                "choice criteria must be a non-empty mapping of "
                "option -> description"
            )
        return ChoiceQuestion(
            instructions=instructions,
            criteria={str(key): desc for key, desc in criteria.items()},
        )
    if qtype == "score":
        if not isinstance(criteria, list) or len(criteria) < 2:
            raise ValueError(
                "score criteria must be a list of >= 2 level names"
            )
        return ScoreQuestion(
            instructions=instructions,
            criteria=[str(level) for level in criteria],
        )
    raise ValueError(
        f"unknown question type {qtype!r} (expected noul, choice or score)"
    )


def _questions_from_mapping(questions: dict[str, Any]) -> dict[str, Any]:
    return {
        str(qid): _question_from_value(spec) for qid, spec in questions.items()
    }


def _derive_rel(url: str) -> str:
    """Relative path (from the docs root) that a page URL maps to."""
    return urlparse(url).path.lstrip("/")


# -------------------------------------------------------------------- tools


async def jev_ask(
    state: str | dict,
    questions: dict[str, str | dict],
    model: str | None = None,
) -> dict:
    """Ask named questions about one state in a single API call.

    ``questions`` maps question id to either a CLI ask-spec string
    (``noul:<instructions>``, ``choice:<instructions>:k=desc,...``,
    ``score:<instructions>:l1,l2,...``) or a native
    ``{type, instructions, criteria}`` dict. Returns
    ``{model, answers: {id: answer dict with type}, usage, request_id}``;
    ``request_id`` is omitted when the API did not return one.
    """
    settings = _require_api_key()
    from daf_jev.client import AsyncJevClient

    questions_obj = _questions_from_mapping(questions)
    async with AsyncJevClient(
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
) -> dict:
    """Evaluate a fixed question set over many states, concurrently.

    Returns the aggregate summary only (no per-state records):
    ``{n_states, n_errors, total_input_tokens, total_output_tokens,
    mean_latency_s, p95_latency_s, questions}``.
    """
    settings = _require_api_key()
    from daf_jev.client import JevClient
    from daf_jev.evaluate import Evaluator

    questions_obj = _questions_from_mapping(questions)
    with JevClient(
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
        records = evaluator.evaluate(states)
        return evaluator.summary(records)


async def jev_models(
    pick: str | None = None,
    contains: str | None = None,
) -> list[dict]:
    """List available model cards as dicts.

    When ``pick`` (``latest`` | ``first`` | ``last``) or ``contains``
    (case-insensitive substring filter on the model name) is given, one
    card is selected via :func:`daf_jev.models.pick_model` and returned as
    a single-element list. Raises ``ValueError`` when nothing matches.
    """
    settings = _require_api_key()
    from daf_jev.client import JevClient

    with JevClient(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout=settings.timeout,
    ) as client:
        cards = client.models()

    if pick is not None or contains is not None:
        from daf_jev.models import pick_model

        card = pick_model(cards, contains=contains, prefer=pick or "latest")
        return [dataclasses.asdict(card)]
    return [dataclasses.asdict(card) for card in cards]


async def jev_composite_score(
    probabilities: dict[str, float],
    weights: list[float] | None = None,
) -> float:
    """Expected value of a score distribution over its level indices.

    ``probabilities`` maps level index (as a string) to probability. With
    ``weights`` (one per level, positional order matching the sorted level
    indices) the distribution is re-weighted as in
    :func:`daf_jev.compose.composite_score`. Requires at least 2 levels.
    """
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
) -> str:
    """Return ``choice`` when ``confidence >= threshold``, else ``below``.

    Local deterministic routing over a synthesized choice answer — no API
    call.
    """
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
) -> str:
    """Two-threshold confidence routing (automate / review / escalate).

    ``confidence >= high`` -> ``high_label``, ``>= low`` -> ``middle_label``,
    otherwise ``low_label``. Local and deterministic — no API call.
    """
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


async def jev_docs_verify(manifest: str | None = None) -> dict:
    """Verify the docs/reference snapshot against its manifest.

    Same logic as the ``daf-jev docs-verify`` CLI command. On success
    returns ``{manifest, pages, missing, drifted, ok}``; when the manifest
    cannot be read or parsed, returns
    ``{error, message, ok: false}`` instead.
    """
    manifest_path = Path(manifest) if manifest is not None else DEFAULT_MANIFEST
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": type(exc).__name__, "message": str(exc), "ok": False}

    root = manifest_path.parent
    pages = manifest_data.get("pages", {})
    missing: list[str] = []
    drifted: list[str] = []
    for rel, meta in pages.items():
        expected_rel = _derive_rel(meta.get("url", ""))
        if expected_rel != rel:
            drifted.append(f"{rel} (url maps to {expected_rel!r})")
            continue
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            missing.append(rel)
            continue
        if (
            hashlib.sha256(data).hexdigest() != meta.get("sha256")
            or len(data) != meta.get("bytes")
        ):
            drifted.append(rel)

    return {
        "manifest": str(manifest_path),
        "pages": len(pages),
        "missing": sorted(missing),
        "drifted": sorted(drifted),
        "ok": not missing and not drifted,
    }


# ------------------------------------------------------------- server setup


def _docs_snapshot() -> dict[str, Any]:
    """Summarize the docs snapshot manifest (``jev://docs/snapshot``)."""
    try:
        manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "error": f"cannot read docs snapshot manifest "
            f"{DEFAULT_MANIFEST}: {exc}"
        }
    return {
        "page_count": manifest.get("page_count", len(manifest.get("pages", {}))),
        "snapshot_id": manifest.get("snapshot_id"),
        "scraped_at": manifest.get("scraped_at_utc"),
        "index_sha256": manifest.get("index_sha256"),
    }


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


def main() -> None:
    """Run the MCP server over the stdio transport."""
    build_server().run(transport="stdio")
