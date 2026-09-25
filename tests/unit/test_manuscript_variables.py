"""Unit tests for daf_jev.manuscript_variables: full-token contract on a fake project.

No-mock convention: daf_jev internals are never patched. Each test builds a
minimal, schema-faithful project tree (pyproject.toml, manuscript/config.yaml,
docs/reference/MANIFEST.json, benchmark JSONs, src/daf_jev) in ``tmp_path`` and
asserts the computed token values. Strict mode (missing analysis output raises)
and draft mode (``--allow-draft``: missing output becomes ``"N/A"``) are both
covered; only ``SOURCE_DATE_EPOCH`` is touched via the environment, which the
module reads itself for deterministic timestamps.
"""

from __future__ import annotations

import json
import platform
import re
from pathlib import Path

import pytest

from daf_jev.manuscript_variables import generate_variables, save_variables

FAKE_VERSION = "1.2.3"

_CONFIG_YAML = """\
paper:
  title: "Test Title"
  subtitle: "Test Subtitle"
  version: "0.9.0"
  date: "2026-09-16"
keywords:
  - "alpha"
  - "beta"
experiment:
  batching_n_values: [5, 10, 20]
"""

_MANIFEST_JSON = {
    "source": "Test docs",
    "base_url": "https://docs.example.com",
    "scraped_at_utc": "2026-09-16T12:00:00Z",
    "page_count": 2,
    "pages": {
        "a.html": {"bytes": 1048576, "path": "a.md"},
        "b.html": {"bytes": 1049088, "path": "b.md"},
    },
    "snapshot_id": "abc123def4567890",
}
_BATCHING_JSON = {
    "date": "2026-09-16",
    "model": "jev-test",
    "runs": 2,
    "state_chars": 544,
    "results": [
        {
            "n": 5,
            "batched": {"mean_wall_s": 0.2, "input_tokens": 100, "output_tokens": 50},
            "single": {"mean_total_wall_s": 0.7, "input_tokens": 300, "output_tokens": 60},
            "speedup_ratio": 3.5,
            "token_cost_ratio": 1.25,
        },
        {
            "n": 10,
            "batched": {"mean_wall_s": 0.11, "input_tokens": 200, "output_tokens": 100},
            "single": {"mean_total_wall_s": 1.0, "input_tokens": 600, "output_tokens": 120},
            "speedup_ratio": 9.25,
            "token_cost_ratio": 2.5,
        },
        {
            "n": 20,
            "batched": {"mean_wall_s": 0.12, "input_tokens": 400, "output_tokens": 200},
            "single": {"mean_total_wall_s": 2.0, "input_tokens": 1200, "output_tokens": 240},
            "speedup_ratio": 18.75,
            "token_cost_ratio": 4.0,
        },
    ],
}

_PATTERNS_JSON = {
    "name": "patterns",
    "date": "2026-09-16",
    "model": "jev-test",
    "runs": 6,
    "composite_score_pipeline": {
        "runs": 6,
        "mean_s": 0.1,
        "p50_s": 0.12,
        "p95_s": 0.2,
        "tokens": 100,
        "last_decision": {"composite": 2.0, "gate": "good"},
    },
    "intent_routing": {
        "runs": 6,
        "mean_s": 0.09,
        "p50_s": 0.11,
        "p95_s": 0.13,
        "tokens": 90,
        "last_decision": {"choice": "billing", "routed": "handler:billing"},
    },
}


_CALIBRATION_JSON = {
    "name": "calibration",
    "date": "2026-09-16",
    "model": "jev-test",
    "states": 6,
    "repeats": 5,
    "choice": {
        "ece": 0.0312,
        "brier": 0.15,
        "buckets": [
            {"bucket_lo": 0.5, "bucket_hi": 0.6, "n": 3,
             "mean_confidence": 0.55, "accuracy": 0.6667},
            {"bucket_lo": 0.9, "bucket_hi": 1.0, "n": 4,
             "mean_confidence": 0.95, "accuracy": 1.0},
        ],
    },
    "noul_stability": {"mean_pairwise_gap": 0.025},
    "n_errors": 0,
    "notes": "correctness proxy = agreement with modal choice "
             "(self-consistency), not ground truth",
}

_INIT_PY = '''"""Fake daf-jev package."""

__all__ = ["alpha", "beta"]
'''

_CORE_PY = '''"""Core helpers."""

def alpha():
    return "alpha"

def beta():
    return "beta"
'''

PYPROJECT_TOML = (
    f'[project]\nname = "daf-jev"\nversion = "{FAKE_VERSION}"\n'
    'requires-python = ">=3.11"\n'
)


def _write_minimal_skeleton(root: Path) -> None:
    """Everything generate_variables requires unconditionally, even in draft mode."""
    (root / "src" / "daf_jev").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(PYPROJECT_TOML, encoding="utf-8")
    (root / "src" / "daf_jev" / "__init__.py").write_text(_INIT_PY, encoding="utf-8")
    (root / "src" / "daf_jev" / "core.py").write_text(_CORE_PY, encoding="utf-8")


def _write_analysis_outputs(root: Path) -> None:
    (root / "manuscript").mkdir(parents=True, exist_ok=True)
    (root / "manuscript" / "config.yaml").write_text(_CONFIG_YAML, encoding="utf-8")
    manifest_dir = root / "docs" / "reference"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "MANIFEST.json").write_text(json.dumps(_MANIFEST_JSON), encoding="utf-8")
    bench_dir = root / "output" / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / "batching_20260916.json").write_text(json.dumps(_BATCHING_JSON), encoding="utf-8")
    (bench_dir / "patterns_20260916.json").write_text(json.dumps(_PATTERNS_JSON), encoding="utf-8")
    (bench_dir / "calibration_20260916.json").write_text(json.dumps(_CALIBRATION_JSON), encoding="utf-8")
    figures_dir = root / "output" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    registry = {"fig:b": {"filename": "b.png"}, "fig:a": {"filename": "a.png"}}
    (figures_dir / "figure_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    (figures_dir / "stray.png").write_bytes(b"png")  # must NOT leak into FIGURES


@pytest.fixture()
def fake_project(tmp_path: Path) -> Path:
    """Complete fake project: every input generate_variables can consume."""
    _write_minimal_skeleton(tmp_path)
    _write_analysis_outputs(tmp_path)
    return tmp_path


# ----------------------------------------------------- generate_variables ---


def test_generate_variables_full_token_dict(fake_project: Path) -> None:
    variables = generate_variables(fake_project)

    assert variables["CONFIG_TITLE"] == "Test Title"
    assert variables["CONFIG_SUBTITLE"] == "Test Subtitle"
    assert variables["CONFIG_VERSION"] == "0.9.0"
    assert variables["CONFIG_DATE"] == "2026-09-16"
    assert variables["CONFIG_KEYWORDS"] == "alpha, beta"
    assert variables["CONFIG_KEYWORDS_BULLETS"] == "- alpha\n- beta"
    assert variables["CONFIG_BATCHING_N5"] == "5"
    assert variables["CONFIG_BATCHING_N10"] == "10"
    assert variables["CONFIG_BATCHING_N20"] == "20"
    assert variables["BATCHING_RUNS"] == "3"
    assert variables["CALIBRATION_STATES"] == "6"
    assert variables["CALIBRATION_REPEATS"] == "5"

    assert variables["PACKAGE_NAME"] == "daf-jev"
    assert variables["PACKAGE_VERSION"] == FAKE_VERSION
    assert variables["PACKAGE_PYTHON_MIN"] == "3.11"

    # Code stats: __init__.py excluded from the module list, __all__ counted.
    assert variables["CODE_MODULES"] == "1"
    assert variables["CODE_LOC"] == "7"
    assert variables["CODE_MODULE_LIST"] == "core"
    assert variables["CODE_PUBLIC_EXPORTS"] == "2"

    # No tests directory and no .coverage in the fake project: degrade to N/A.
    assert variables["TEST_UNIT_COUNT"] == "N/A"
    assert variables["TEST_LIVE_COUNT"] == "N/A"
    assert variables["TEST_COVERAGE_PCT"] == "N/A"
    assert variables["TEST_FILES_COUNT"] == "0"

    # 2049 bytes total: 2049 B -> 2.0009... MiB -> "2.0 MiB".
    assert variables["DOCS_SNAPSHOT_PAGES"] == "2"
    assert variables["DOCS_SNAPSHOT_ID"] == "abc123def4567890"
    assert variables["DOCS_SNAPSHOT_BYTES_HUMAN"] == "2.0 MiB"
    assert variables["DOCS_SNAPSHOT_DATE"] == "2026-09-16"

    assert variables["BENCH_MODEL"] == "jev-test"
    assert variables["BENCH_DATE"] == "2026-09-16"
    assert variables["BENCH_BATCHING_SPEEDUP_N5"] == "3.50"
    assert variables["BENCH_BATCHING_SPEEDUP_N10"] == "9.25"
    assert variables["BENCH_BATCHING_SPEEDUP_N20"] == "18.75"
    assert variables["BENCH_BATCHING_TOKEN_RATIO_N20"] == "4.00"
    assert variables["BENCH_PATTERNS_RUNS"] == "6"
    assert variables["BENCH_PATTERNS_COMPOSITE_P50_S"] == "0.120"
    assert variables["BENCH_PATTERNS_COMPOSITE_P95_S"] == "0.200"
    assert variables["BENCH_PATTERNS_ROUTING_P50_S"] == "0.110"
    assert variables["BENCH_PATTERNS_ROUTING_P95_S"] == "0.130"

    assert variables["BENCH_CALIB_MODEL"] == "jev-test"
    assert variables["BENCH_CALIB_DATE"] == "2026-09-16"
    assert variables["BENCH_CALIB_STATES"] == "6"
    assert variables["BENCH_CALIB_REPEATS"] == "5"
    assert variables["BENCH_CALIB_ECE"] == "0.0312"
    assert variables["BENCH_CALIB_BRIER"] == "0.1500"
    assert variables["BENCH_CALIB_MEAN_GAP"] == "0.0250"

    assert variables["PLATFORM"] == platform.platform()
    assert variables["PYTHON_VERSION"] == platform.python_version()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", variables["GENERATION_TIMESTAMP"])
    # Sorted registry filenames; stray.png (present on disk) is absent.
    assert variables["FIGURES"] == "a.png, b.png"


def test_generate_variables_token_count_stable(fake_project: Path) -> None:
    """The contracted variable set must not silently grow or shrink."""
    variables = generate_variables(fake_project)
    assert len(variables) == 49


def test_generate_variables_timestamp_honors_source_date_epoch(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    variables = generate_variables(fake_project)
    assert variables["GENERATION_TIMESTAMP"] == "2023-11-14T22:13:20Z"


def test_generate_variables_draft_mode_equals_strict_on_complete_project(fake_project: Path) -> None:
    """Draft and strict modes agree on a complete project modulo the timestamp.

    The three experiment knobs (BATCHING_RUNS/CALIBRATION_STATES/CALIBRATION_REPEATS)
    diverge by design when the config omits them — config wins, strict falls back to
    defaults, draft degrades to N/A (see
    test_generate_variables_experiment_producers_config_defaults_and_draft) — so the
    complete-project fixture supplies them and they are compared after popping.
    """
    knobs = ("BATCHING_RUNS", "CALIBRATION_STATES", "CALIBRATION_REPEATS")
    strict = generate_variables(fake_project, require_analysis_outputs=True)
    draft = generate_variables(fake_project, require_analysis_outputs=False)
    for variables in (strict, draft):
        variables.pop("GENERATION_TIMESTAMP")
        for knob in knobs:
            variables.pop(knob)
    assert strict == draft


def test_generate_variables_draft_mode_missing_outputs_become_na(tmp_path: Path) -> None:
    _write_minimal_skeleton(tmp_path)  # no config, manifest, benchmarks, figures

    variables = generate_variables(tmp_path, require_analysis_outputs=False)

    for token in (
        "CONFIG_TITLE",
        "CONFIG_SUBTITLE",
        "CONFIG_VERSION",
        "CONFIG_DATE",
        "CONFIG_BATCHING_N5",
        "CONFIG_BATCHING_N10",
        "CONFIG_BATCHING_N20",
        "BATCHING_RUNS",
        "CALIBRATION_STATES",
        "CALIBRATION_REPEATS",
        "DOCS_SNAPSHOT_PAGES",
        "DOCS_SNAPSHOT_ID",
        "DOCS_SNAPSHOT_BYTES_HUMAN",
        "DOCS_SNAPSHOT_DATE",
        "BENCH_MODEL",
        "BENCH_DATE",
        "BENCH_BATCHING_SPEEDUP_N5",
        "BENCH_BATCHING_SPEEDUP_N10",
        "BENCH_BATCHING_SPEEDUP_N20",
        "BENCH_BATCHING_TOKEN_RATIO_N20",
        "BENCH_PATTERNS_RUNS",
        "BENCH_PATTERNS_COMPOSITE_P50_S",
        "BENCH_PATTERNS_COMPOSITE_P95_S",
        "BENCH_PATTERNS_ROUTING_P50_S",
        "BENCH_PATTERNS_ROUTING_P95_S",
        "BENCH_CALIB_MODEL",
        "BENCH_CALIB_DATE",
        "BENCH_CALIB_STATES",
        "BENCH_CALIB_REPEATS",
        "BENCH_CALIB_ECE",
        "BENCH_CALIB_BRIER",
        "BENCH_CALIB_MEAN_GAP",
    ):
        assert variables[token] == "N/A", token
    assert variables["CONFIG_KEYWORDS"] == ""
    assert variables["FIGURES"] == "N/A"
    # Inputs that exist regardless of mode are still computed.
    assert variables["PACKAGE_VERSION"] == FAKE_VERSION
    assert variables["CODE_MODULES"] == "1"


@pytest.mark.parametrize(
    ("removal", "needle"),
    [
        ("manuscript/config.yaml", "config.yaml"),
        ("docs/reference/MANIFEST.json", "MANIFEST.json"),
        ("output/benchmarks/batching_20260916.json", "batching"),
        ("output/benchmarks/patterns_20260916.json", "patterns"),
        ("output/benchmarks/calibration_20260916.json", "calibration"),
        ("output/figures/figure_registry.json", "figure_registry"),
    ],
)
def test_generate_variables_strict_missing_analysis_output_raises(
    tmp_path: Path, removal: str, needle: str
) -> None:
    _write_minimal_skeleton(tmp_path)
    _write_analysis_outputs(tmp_path)
    (tmp_path / removal).unlink()

    with pytest.raises(FileNotFoundError, match=re.escape(needle)):
        generate_variables(tmp_path, require_analysis_outputs=True)


@pytest.mark.parametrize("require", [True, False])
def test_generate_variables_stray_png_never_leaks_into_figures(
    fake_project: Path, require: bool
) -> None:
    variables = generate_variables(fake_project, require_analysis_outputs=require)
    assert variables["FIGURES"] == "a.png, b.png"
    assert "stray.png" not in variables["FIGURES"]


@pytest.mark.parametrize("require", [True, False])
def test_generate_variables_malformed_figure_registry_raises(
    tmp_path: Path, require: bool
) -> None:
    _write_minimal_skeleton(tmp_path)
    _write_analysis_outputs(tmp_path)
    registry_path = tmp_path / "output" / "figures" / "figure_registry.json"
    registry_path.write_text(json.dumps({"fig:bad": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="filename"):
        generate_variables(tmp_path, require_analysis_outputs=require)


def test_generate_variables_missing_pyproject_raises_even_in_draft(tmp_path: Path) -> None:
    (tmp_path / "src" / "daf_jev").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match=re.escape("pyproject.toml")):
        generate_variables(tmp_path, require_analysis_outputs=False)


def test_generate_variables_experiment_producers_config_defaults_and_draft(tmp_path: Path) -> None:
    """BATCHING_RUNS/CALIBRATION_STATES/CALIBRATION_REPEATS: config wins, strict defaults, draft N/A."""
    _write_minimal_skeleton(tmp_path)
    _write_analysis_outputs(tmp_path)  # config.yaml lacks the experiment.* keys

    strict_no_keys = generate_variables(tmp_path, require_analysis_outputs=True)
    assert strict_no_keys["BATCHING_RUNS"] == "3"
    assert strict_no_keys["CALIBRATION_STATES"] == "6"
    assert strict_no_keys["CALIBRATION_REPEATS"] == "5"

    draft_no_keys = generate_variables(tmp_path, require_analysis_outputs=False)
    assert draft_no_keys["BATCHING_RUNS"] == "N/A"
    assert draft_no_keys["CALIBRATION_STATES"] == "N/A"
    assert draft_no_keys["CALIBRATION_REPEATS"] == "N/A"

    config_path = tmp_path / "manuscript" / "config.yaml"
    config_path.write_text(
        _CONFIG_YAML + "  batching_runs: 4\n  calibration_states: 8\n  calibration_repeats: 7\n",
        encoding="utf-8",
    )
    configured = generate_variables(tmp_path, require_analysis_outputs=True)
    assert configured["BATCHING_RUNS"] == "4"
    assert configured["CALIBRATION_STATES"] == "8"
    assert configured["CALIBRATION_REPEATS"] == "7"


def test_generate_variables_batching_n_tokens_derive_from_config(fake_project: Path) -> None:
    """CONFIG_BATCHING_N* token names AND values follow experiment.batching_n_values."""
    (fake_project / "manuscript" / "config.yaml").write_text(
        _CONFIG_YAML.replace("  batching_n_values: [5, 10, 20]", "  batching_n_values: [4, 8]"),
        encoding="utf-8",
    )

    variables = generate_variables(fake_project)

    assert variables["CONFIG_BATCHING_N4"] == "4"
    assert variables["CONFIG_BATCHING_N8"] == "8"
    assert "CONFIG_BATCHING_N5" not in variables
    assert "CONFIG_BATCHING_N10" not in variables
    assert "CONFIG_BATCHING_N20" not in variables


def test_generate_variables_unit_count_reflects_pytest_collection(fake_project: Path) -> None:
    """TEST_UNIT_COUNT is the real pytest --collect-only tally for tests/unit."""
    unit_dir = fake_project / "tests" / "unit"
    unit_dir.mkdir(parents=True)
    (unit_dir / "test_smoke.py").write_text(
        "def test_smoke() -> None:\n    assert True\n", encoding="utf-8"
    )

    variables = generate_variables(fake_project)

    assert variables["TEST_UNIT_COUNT"] == "1"
    assert variables["TEST_LIVE_COUNT"] == "N/A"  # tests/live stays absent


# ------------------------------------------------------------ save_variables ---


def test_save_variables_round_trip(fake_project: Path, tmp_path: Path) -> None:
    variables = generate_variables(fake_project)
    output_path = tmp_path / "out" / "variables.json"

    written = save_variables(variables, output_path)

    assert written == output_path
    assert output_path.is_file()
    assert json.loads(output_path.read_text(encoding="utf-8")) == variables


def test_save_variables_output_is_byte_stable_across_calls(fake_project: Path, tmp_path: Path) -> None:
    variables = generate_variables(fake_project)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    save_variables(variables, first)
    save_variables(variables, second)

    text = first.read_text(encoding="utf-8")
    assert text == second.read_text(encoding="utf-8")
    assert json.loads(text)["FIGURES"] == "a.png, b.png"
