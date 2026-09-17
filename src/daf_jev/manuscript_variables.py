"""Manuscript variable generation for the daf-jev paper.

Reads project metadata and analysis outputs:

- ``pyproject.toml``                    — package name / version / min Python
- ``manuscript/config.yaml``            — paper metadata and experiment params
- ``docs/reference/MANIFEST.json``      — docs snapshot stats
- ``output/benchmarks/{batching,patterns}_*.json`` — benchmark results
- ``output/figures/*.png``              — rendered figure registry
- ``pytest --collect-only``             — per-directory test counts
- ``.coverage`` (coverage python API)   — coverage percent

Returns a flat ``dict[str, str]`` of UPPERCASE_KEY → value for ``{{TOKEN}}``
substitution via
:func:`infrastructure.rendering.manuscript_injection.write_resolved_manuscript_tree`
(inside the template repository) — this module itself never imports
``infrastructure`` so it stays importable standalone.

Every numeric value is computed here; nothing is hardcoded. Called
exclusively by ``scripts/z_generate_manuscript_variables.py`` (thin
orchestrator).
"""

from __future__ import annotations

import ast
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

__all__ = ["generate_variables", "save_variables"]

_SRC_PACKAGE = Path("src") / "daf_jev"
_BENCH_DIR = Path("output") / "benchmarks"
_FIGURES_DIR = Path("output") / "figures"
_MANIFEST_PATH = Path("docs") / "reference" / "MANIFEST.json"
_CONFIG_PATH = Path("manuscript") / "config.yaml"
_COVERAGE_PATH = Path(".coverage")
_PYTEST_TIMEOUT_S = 180

_NA = "N/A"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _build_timestamp() -> str:
    """Build an ISO-8601 UTC timestamp, honoring ``SOURCE_DATE_EPOCH``.

    Deterministic mode (byte-stable rendered manuscripts) sets
    ``SOURCE_DATE_EPOCH``; wall-clock UTC otherwise.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _human_bytes(total: int) -> str:
    """Format a byte count in binary units, e.g. ``1039131`` → ``1.0 MiB``."""
    size = float(total)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GiB"  # pragma: no cover — unreachable loop exit


def _require(condition: bool, kind: str, path: Path, hint: str, *, strict: bool) -> bool:
    """Enforce a required input. Strict mode raises; draft mode returns False."""
    if condition:
        return True
    if strict:
        raise FileNotFoundError(f"Analysis output required but missing: {path}. {hint}")
    return False


def _fmt(value: Optional[float], spec: str) -> str:
    """Format a float, or ``N/A`` when absent."""
    return format(value, spec) if value is not None else _NA


def _config_batching_n_values(config: dict[str, Any]) -> list[str]:
    """String batch sizes from ``experiment.batching_n_values`` (may be empty)."""
    experiment = config.get("experiment") or {}
    values = experiment.get("batching_n_values") if isinstance(experiment, dict) else None
    return [str(value) for value in values] if values else []


# ---------------------------------------------------------------------------
# Readers — thin, per source
# ---------------------------------------------------------------------------


def _load_config(project_root: Path, *, strict: bool) -> dict[str, Any]:
    config_path = project_root / _CONFIG_PATH
    if not _require(config_path.is_file(), "manuscript config", config_path, "Create manuscript/config.yaml first.", strict=strict):
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_package_metadata(project_root: Path) -> dict[str, Any]:
    with (project_root / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def _load_manifest(project_root: Path, *, strict: bool) -> dict[str, Any]:
    manifest_path = project_root / _MANIFEST_PATH
    if not _require(
        manifest_path.is_file(),
        "docs snapshot manifest",
        manifest_path,
        "Run scripts/scrape_docs.py first.",
        strict=strict,
    ):
        return {}
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _code_stats(project_root: Path) -> dict[str, Any]:
    """Count modules, nonblank lines, module names, and ``__all__`` entries."""
    package_dir = project_root / _SRC_PACKAGE
    module_paths = sorted(p for p in package_dir.glob("*.py"))
    modules = [p.name[:-3] for p in module_paths if p.name != "__init__.py"]
    loc = sum(
        1
        for path in module_paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    exports = 0
    for path in module_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ) and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                exports += len(node.value.elts)
    return {"modules": modules, "loc": loc, "exports": exports}


def _pytest_collected(project_root: Path, test_dir: str) -> Optional[int]:
    """Count tests collected by ``pytest --collect-only -q``; None on failure."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", test_dir],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=_PYTEST_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    if match:
        return int(match.group(1))
    ids = [line for line in proc.stdout.splitlines() if "::" in line]
    return len(ids) if ids else None


def _coverage_percent(project_root: Path) -> Optional[float]:
    """Return the enforced coverage percentage from an existing ``.coverage``.

    Delegates to ``coverage.Coverage.report()`` so the number is computed by
    the same machinery the gate uses (branch mode, exclude_lines, and omit
    patterns all come from ``pyproject.toml``) — no hand-rolled aggregation
    to drift out of sync. Returns None when the data file is missing or the
    report covers nothing.
    """
    data_file = project_root / _COVERAGE_PATH
    if not data_file.is_file():
        return None
    import io
    from contextlib import redirect_stdout

    import coverage

    cov = coverage.Coverage(data_file=str(data_file), config_file=str(project_root / "pyproject.toml"))
    cov.load()
    if not cov.get_data().measured_files():
        return None
    with redirect_stdout(io.StringIO()) as _sink:
        pct = cov.report(show_missing=False)
    if pct is None or pct <= 0:
        return None
    return float(pct)


def _latest_benchmark(project_root: Path, prefix: str, *, strict: bool) -> Optional[Path]:
    """Newest ``<prefix>_*.json`` under ``output/benchmarks``, or None."""
    bench_dir = project_root / _BENCH_DIR
    matches = sorted(bench_dir.glob(f"{prefix}_*.json"))
    _require(
        bool(matches),
        f"{prefix} benchmark data",
        bench_dir / f"{prefix}_*.json",
        f"Expected e.g. '{prefix}_20260916.json'; run the benchmark script first.",
        strict=strict,
    )
    return matches[-1] if matches else None


def _load_benchmark(project_root: Path, prefix: str, *, strict: bool) -> dict[str, Any]:
    path = _latest_benchmark(project_root, prefix, strict=strict)
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _bench_row(results: list[dict[str, Any]], n: int) -> Optional[dict[str, Any]]:
    for row in results:
        if row.get("n") == n:
            return row
    return None


def _bench_value(source: dict[str, Any], *keys: str) -> Optional[Any]:
    value: Any = source
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _opt_str(source: dict[str, Any], key: str) -> str:
    """String value of *key*, or ``N/A`` when absent."""
    value = source.get(key) if isinstance(source, dict) else None
    return str(value) if value is not None else _NA


def _opt_float(source: dict[str, Any], *keys: str) -> Optional[float]:
    """Nested float at *keys*, or None when any level is missing."""
    value = _bench_value(source, *keys)
    return None if value is None else float(value)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_variables(project_root: Path, *, require_analysis_outputs: bool = True) -> dict[str, str]:
    """Generate all contracted manuscript variables from project sources.

    Args:
        project_root: Root directory (contains ``pyproject.toml``,
            ``manuscript/``, ``output/``, ``src/daf_jev``, ``tests/``).
        require_analysis_outputs: When True (pipeline mode), missing
            analysis outputs (manuscript config, docs manifest, benchmark
            JSONs) raise :class:`FileNotFoundError`. When False (draft
            mode, ``--allow-draft``), those become ``"N/A"``. Test counts
            and coverage degrade to ``"N/A"`` on unavailability in both
            modes.

    Returns:
        ``dict[str, str]`` with plain UPPERCASE_KEY keys (no braces), ready
        for ``{{TOKEN}}`` substitution.
    """
    strict = require_analysis_outputs
    variables: dict[str, str] = {}

    # ---- Configuration-derived (manuscript/config.yaml) ----
    config = _load_config(project_root, strict=strict)
    paper = config.get("paper", {}) if isinstance(config, dict) else {}
    keywords = [str(k) for k in (config.get("keywords", []) or [])]
    variables["CONFIG_TITLE"] = str(paper.get("title", _NA))
    variables["CONFIG_SUBTITLE"] = str(paper.get("subtitle", _NA))
    variables["CONFIG_VERSION"] = str(paper.get("version", _NA))
    variables["CONFIG_DATE"] = str(paper.get("date", _NA))
    variables["CONFIG_KEYWORDS"] = ", ".join(keywords)
    variables["CONFIG_KEYWORDS_BULLETS"] = "\n".join(f"- {keyword}" for keyword in keywords)

    batching_n_values = _config_batching_n_values(config)
    for i, n in enumerate((5, 10, 20)):
        value = batching_n_values[i] if i < len(batching_n_values) else None
        variables[f"CONFIG_BATCHING_N{n}"] = value if value is not None else _NA

    # ---- Package metadata (pyproject.toml) ----
    package = _load_package_metadata(project_root)
    project = package.get("project", {})
    requires_python = str(project.get("requires-python", _NA))
    variables["PACKAGE_NAME"] = str(project.get("name", _NA))
    variables["PACKAGE_VERSION"] = str(project.get("version", _NA))
    variables["PACKAGE_PYTHON_MIN"] = requires_python.lstrip(">=").strip() or _NA

    # ---- Code statistics (src/daf_jev) ----
    code = _code_stats(project_root)
    variables["CODE_MODULES"] = str(len(code["modules"]))
    variables["CODE_LOC"] = str(code["loc"])
    variables["CODE_MODULE_LIST"] = ", ".join(code["modules"])
    variables["CODE_PUBLIC_EXPORTS"] = str(code["exports"])

    # ---- Test statistics (pytest --collect-only; coverage API) ----
    unit_count = _pytest_collected(project_root, "tests/unit")
    live_count = _pytest_collected(project_root, "tests/live")
    test_files = sorted((project_root / "tests").glob("**/test_*.py"))
    coverage_pct = _coverage_percent(project_root)
    variables["TEST_UNIT_COUNT"] = str(unit_count) if unit_count is not None else _NA
    variables["TEST_LIVE_COUNT"] = str(live_count) if live_count is not None else _NA
    variables["TEST_COVERAGE_PCT"] = _fmt(coverage_pct, ".2f")
    variables["TEST_FILES_COUNT"] = str(len(test_files))

    # ---- Docs snapshot (docs/reference/MANIFEST.json) ----
    manifest = _load_manifest(project_root, strict=strict)
    pages = manifest.get("pages", {}) if isinstance(manifest, dict) else {}
    total_bytes = sum(int(page.get("bytes", 0)) for page in pages.values())
    variables["DOCS_SNAPSHOT_PAGES"] = str(manifest.get("page_count", _NA)) if manifest else _NA
    variables["DOCS_SNAPSHOT_ID"] = str(manifest.get("snapshot_id", _NA)) if manifest else _NA
    variables["DOCS_SNAPSHOT_BYTES_HUMAN"] = _human_bytes(total_bytes) if manifest else _NA
    variables["DOCS_SNAPSHOT_DATE"] = str(manifest.get("scraped_at_utc", _NA))[:10] if manifest else _NA

    # ---- Benchmarks (output/benchmarks/*.json, latest by filename date) ----
    batching = _load_benchmark(project_root, "batching", strict=strict)
    patterns = _load_benchmark(project_root, "patterns", strict=strict)
    model = batching.get("model") or patterns.get("model")
    run_date = batching.get("date") or patterns.get("date")
    variables["BENCH_MODEL"] = str(model) if model is not None else _NA
    variables["BENCH_DATE"] = str(run_date) if run_date is not None else _NA

    results = batching.get("results", []) if isinstance(batching, dict) else []
    for n in (5, 10, 20):
        row = _bench_row(results, n)
        speedup = _bench_value(row or {}, "speedup_ratio")
        variables[f"BENCH_BATCHING_SPEEDUP_N{n}"] = _fmt(None if speedup is None else float(speedup), ".2f")
    token_ratio = _bench_value(_bench_row(results, 20) or {}, "token_cost_ratio")
    variables["BENCH_BATCHING_TOKEN_RATIO_N20"] = _fmt(None if token_ratio is None else float(token_ratio), ".2f")

    def _pattern_seconds(pipeline: str, percentile: str) -> str:
        value = _bench_value(patterns, pipeline, percentile)
        return _fmt(None if value is None else float(value), ".3f")

    runs = patterns.get("runs") if isinstance(patterns, dict) else None
    variables["BENCH_PATTERNS_RUNS"] = str(runs) if runs is not None else _NA
    variables["BENCH_PATTERNS_COMPOSITE_P50_S"] = _pattern_seconds("composite_score_pipeline", "p50_s")
    variables["BENCH_PATTERNS_COMPOSITE_P95_S"] = _pattern_seconds("composite_score_pipeline", "p95_s")
    variables["BENCH_PATTERNS_ROUTING_P50_S"] = _pattern_seconds("intent_routing", "p50_s")
    variables["BENCH_PATTERNS_ROUTING_P95_S"] = _pattern_seconds("intent_routing", "p95_s")

    calibration = _load_benchmark(project_root, "calibration", strict=strict)
    variables["BENCH_CALIB_MODEL"] = _opt_str(calibration, "model")
    variables["BENCH_CALIB_DATE"] = _opt_str(calibration, "date")
    variables["BENCH_CALIB_STATES"] = _opt_str(calibration, "states")
    variables["BENCH_CALIB_REPEATS"] = _opt_str(calibration, "repeats")
    variables["BENCH_CALIB_ECE"] = _fmt(_opt_float(calibration, "choice", "ece"), ".4f")
    variables["BENCH_CALIB_BRIER"] = _fmt(_opt_float(calibration, "choice", "brier"), ".4f")
    variables["BENCH_CALIB_MEAN_GAP"] = _fmt(
        _opt_float(calibration, "noul_stability", "mean_pairwise_gap"), ".4f"
    )


    # ---- Provenance ----
    variables["GENERATION_TIMESTAMP"] = _build_timestamp()
    variables["PLATFORM"] = platform.platform()
    variables["PYTHON_VERSION"] = platform.python_version()

    # ---- Figure registry (output/figures/*.png) ----
    figures_dir = project_root / _FIGURES_DIR
    figures = sorted(p.name for p in figures_dir.glob("*.png")) if figures_dir.is_dir() else []
    variables["FIGURES"] = ", ".join(figures)

    return variables


def save_variables(variables: dict[str, str], output_path: Path) -> Path:
    """Persist *variables* as JSON for downstream rendering and debugging.

    Args:
        variables: The flat UPPERCASE_KEY → value mapping from
            :func:`generate_variables`.
        output_path: Destination ``.json`` file (parent is created if absent).

    Returns:
        Resolved path to the written file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(variables, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path
