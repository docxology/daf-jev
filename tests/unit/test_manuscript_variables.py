"""Unit tests for daf_jev.manuscript_variables: full-token contract on a fake project.

No-mock convention: daf_jev internals are never patched. Each test builds a
minimal, schema-faithful project tree (pyproject.toml, manuscript/config.yaml,
docs/reference/MANIFEST.json, benchmark JSONs, src/daf_jev) in ``tmp_path`` and
asserts the computed token values. Strict mode (missing analysis output raises)
and draft mode (``--allow-draft``: missing output becomes ``"N/A"``) are both
covered; only ``SOURCE_DATE_EPOCH`` is touched via the environment, which the
module reads itself for deterministic timestamps. The timestamp-from-git tests
run git only inside ``tmp_path`` fixtures — the real repo is never touched.
The stale/fresh coverage fixtures build real ``.coverage`` state via
``os.utime`` (mtimes) and the ``coverage`` subprocess (a genuine data file).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from daf_jev.manuscript_variables import generate_variables, save_variables

FAKE_VERSION = "1.2.3"

_STALE_TS = datetime(1988, 1, 1, tzinfo=timezone.utc).timestamp()
_NEWER_TS = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()

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
    selected = {p.stem.split("_")[0]: {"path": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in bench_dir.glob("*.json")}
    (root / "manuscript" / "evidence.json").write_text(json.dumps({"format": "dafjev.publication-evidence/1", "historical_benchmarks": selected}))
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


# -------------------------- coverage freshness + provenance (regen hygiene) ---


def _age_fixtures(root: Path, mtime: float) -> None:
    """Pin every source/test ``.py`` mtime so the guard's "newest" is deterministic."""
    for path in (root / "src" / "daf_jev").rglob("*.py"):
        os.utime(path, (mtime, mtime))
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for path in tests_dir.rglob("*.py"):
            os.utime(path, (mtime, mtime))


def _make_stale_coverage(root: Path) -> Path:
    """A ``.coverage`` placeholder with a 1988 mtime; the guard fires before any load."""
    data_file = root / ".coverage"
    data_file.write_bytes(b"stale placeholder - never loaded by these tests")
    os.utime(data_file, (_STALE_TS, _STALE_TS))
    return data_file


def _write_real_coverage(root: Path) -> Path:
    """Build a REAL ``.coverage`` for the fake src tree via ``python -m coverage run``.

    A subprocess (not an in-process second collector): under the battery's
    pytest-cov this must never steal the session's trace function.
    """
    data_file = root / ".coverage"
    probe = root / "_coverage_probe.py"
    probe.write_text(
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import daf_jev.core\n"
        "daf_jev.core.alpha()\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "coverage", "run",
                f"--data-file={data_file}",
                "--source", str(root / "src" / "daf_jev"),
                str(probe), str(root / "src"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
    finally:
        probe.unlink(missing_ok=True)
    return data_file


def test_generate_variables_stale_coverage_strict_raises_with_timestamps(
    fake_project: Path,
) -> None:
    _age_fixtures(fake_project, _NEWER_TS)
    _make_stale_coverage(fake_project)

    with pytest.raises(
        FileNotFoundError,
        match=r"Stale coverage data.*1988-01-01T00:00:00Z.*2020-01-01T00:00:00Z.*"
        + re.escape("run `uv run pytest tests/unit --cov=src` then re-run"),
    ):
        generate_variables(fake_project, require_analysis_outputs=True)


def test_generate_variables_stale_coverage_draft_warns_and_na(
    fake_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _age_fixtures(fake_project, _NEWER_TS)
    _make_stale_coverage(fake_project)

    variables = generate_variables(fake_project, require_analysis_outputs=False)

    assert variables["TEST_COVERAGE_PCT"] == "N/A"
    err = capsys.readouterr().err
    assert "1988-01-01T00:00:00Z" in err
    assert "2020-01-01T00:00:00Z" in err
    assert "uv run pytest tests/unit --cov=src" in err


def test_generate_variables_fresh_coverage_still_reported(fake_project: Path) -> None:
    """A current .coverage flows through the guard and yields a numeric token."""
    _age_fixtures(fake_project, _NEWER_TS)
    data_file = _write_real_coverage(fake_project)
    assert data_file.stat().st_mtime >= _NEWER_TS  # fresh by construction

    variables = generate_variables(fake_project)

    token = variables["TEST_COVERAGE_PCT"]
    assert token != "N/A"
    assert re.fullmatch(r"\d+\.\d{2}", token)


def test_generate_variables_timestamp_derived_from_head_commit(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No SOURCE_DATE_EPOCH: GENERATION_TIMESTAMP pins to the HEAD commit date."""
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.invalid",
        "GIT_COMMITTER_NAME": "Test Committer",
        "GIT_COMMITTER_EMAIL": "committer@example.invalid",
        "GIT_AUTHOR_DATE": "2023-11-14T22:13:20+00:00",
        "GIT_COMMITTER_DATE": "2023-11-14T22:13:20+00:00",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    init = subprocess.run(["git", "init", "-q"], cwd=fake_project, capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    commit = subprocess.run(
        ["git", "commit", "--allow-empty", "--no-gpg-sign", "-q", "-m", "init"],
        cwd=fake_project,
        env=env,
        capture_output=True,
        text=True,
    )
    assert commit.returncode == 0, commit.stderr

    first = generate_variables(fake_project)
    second = generate_variables(fake_project)

    assert first["GENERATION_TIMESTAMP"] == "2023-11-14T22:13:20Z"
    assert second["GENERATION_TIMESTAMP"] == "2023-11-14T22:13:20Z"


def test_generate_variables_timestamp_falls_back_to_wall_clock_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    _write_minimal_skeleton(tmp_path)  # not a git repo -> git fails -> wall clock

    variables = generate_variables(tmp_path, require_analysis_outputs=False)

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", variables["GENERATION_TIMESTAMP"])


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
