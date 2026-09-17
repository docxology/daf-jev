"""Shared helpers for the daf-jev benchmark scripts.

Thin bootstrap only: sys.path setup, key resolution with graceful skip,
latency stats, and the JSON result writer. All benchmark logic lives in the
scripts themselves.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

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
    """Linear-interpolated percentile of a non-empty list (pct in [0, 100])."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of an empty list")
    rank = (len(ordered) - 1) * pct / 100.0
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def latency_summary(walls: list[float]) -> dict:
    """Mean / p50 / p95 summary (seconds, rounded) over a list of wall times."""
    return {
        "runs": len(walls),
        "mean_s": round(mean(walls), 4),
        "p50_s": round(percentile(walls, 50), 4),
        "p95_s": round(percentile(walls, 95), 4),
    }


def write_result(name: str, payload: dict) -> Path:
    """Write JSON to output/benchmarks/<name>_<YYYYMMDD>.json; return the path."""
    out_dir = ROOT / "output" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{date.today().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
