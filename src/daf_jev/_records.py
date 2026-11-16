"""Pure JSON record projections shared by the CLI and MCP surfaces.

These helpers project existing typed domain values without rounding, inference
or validation. Callers retain file/client lifecycle, exception selection, exit
codes and transport-specific envelopes.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from daf_jev.bayesnet_posteriors import PosteriorsSidecar, row_sum_deviations

if TYPE_CHECKING:
    from daf_jev._types import SystemOneResponse
    from daf_jev.reask import ReAskPlan


def response_record(response: SystemOneResponse) -> dict[str, Any]:
    """Preserve answer IDs, values, types, usage and an available request ID."""
    payload: dict[str, Any] = {
        "model": response.model,
        "answers": {
            qid: {**asdict(answer), "type": answer.type}
            for qid, answer in response.answers.items()
        },
        "usage": asdict(response.usage),
    }
    if response.request_id is not None:
        payload["request_id"] = response.request_id
    return payload


def posteriors_record(sidecar: PosteriorsSidecar) -> dict[str, Any]:
    """Summarize validated rows without changing probabilities or provenance."""
    deviations = row_sum_deviations(sidecar).values()
    return {
        "ok": True,
        "format": sidecar.format,
        "evidence_count": len(sidecar.evidence or {}),
        "variable_count": len(sidecar.posteriors),
        "min_row_sum_deviation": min(deviations, default=0.0),
        "max_row_sum_deviation": max(deviations, default=0.0),
    }


def reask_record(plan: ReAskPlan) -> dict[str, Any]:
    """Keep queue order, nullable exhaustion fields and recorded evidence."""
    return {
        "next_question": plan.next_question,
        "entropy": plan.entropy,
        "queue": [list(entry) for entry in plan.queue],
        "evidence": dict(plan.evidence),
    }


def error_record(exc: Exception) -> dict[str, str]:
    """Project an already-selected failure without deciding how to handle it."""
    return {"error": type(exc).__name__, "message": str(exc)}
