"""Shared helpers for the daf-jev benchmark scripts.

Thin bootstrap only: sys.path setup, key resolution with graceful skip,
latency stats, and the JSON result writer. All benchmark logic lives in the
scripts themselves.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from daf_jev.benchmark_metrics import nearest_rank_percentile  # noqa: E402
from daf_jev.config import load_dotenv, load_settings  # noqa: E402

SKIP_MESSAGE = "SKIP: JEV_API_KEY not set"


def settings_or_skip():
    """Load Settings honoring the project .env regardless of the caller's CWD.

    Returns the Settings, or None (after printing the SKIP line) when no API
    key resolves. Precedence is preserved: process env > .env file.
    """
    file_env = load_dotenv(ROOT / ".env")
    merged = {k: v for k, v in file_env.items() if k not in os.environ}
    settings = load_settings(env=merged)
    if not settings.api_key:
        print(SKIP_MESSAGE)
        return None
    return settings


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile matching the documented evaluator protocol."""
    return nearest_rank_percentile(values, pct)


def latency_summary(walls: list[float]) -> dict:
    """Mean / p50 / p95 summary (seconds, rounded) over a list of wall times."""
    return {
        "runs": len(walls),
        "mean_s": round(mean(walls), 4),
        "p50_s": round(percentile(walls, 50), 4),
        "p95_s": round(percentile(walls, 95), 4),
    }


def write_result(name: str, payload: dict, *, out_dir: Path | None = None) -> Path:
    """Write a unique UTC receipt, exclusively, with strict JSON numbers."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError("benchmark name must contain lowercase letters, digits, underscores or hyphens")
    now = datetime.now(timezone.utc)
    receipt_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex}"
    encoded = json.dumps({**payload, "receipt_id": receipt_id,
                          "generated_utc": now.isoformat(),
                          "percentile_method": "nearest_rank"}, indent=2, allow_nan=False) + "\n"
    out_dir = out_dir if out_dir is not None else ROOT / "output" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{receipt_id}.json"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
    return path
