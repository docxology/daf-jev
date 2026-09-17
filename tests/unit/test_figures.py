"""Unit tests for daf_jev.figures: real PNG rendering against a fake project tree.

No-mock convention: daf_jev internals are never patched. The module under test
loads benchmark JSONs from ``output/benchmarks`` under ``project_root``, so each
test builds a minimal, schema-faithful project tree in ``tmp_path``. Rendering
is headless (the module selects the Agg backend itself).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from daf_jev.figures import (
    FIGURE_REGISTRY_FILENAME,
    generate_all,
    generate_graphical_abstract,
    generate_architecture,
    generate_batching,
    generate_calibration,
    generate_confidence,
    generate_latency,
    generate_one,
    generate_primitives,
    write_figure_registry,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

EXPECTED_PNGS = {
    "graphical_abstract": "graphical_abstract.png",
    "architecture": "architecture.png",
    "primitives": "primitives_overview.png",
    "batching": "batching_speedup.png",
    "latency": "latency_percentiles.png",
    "confidence": "confidence_bands.png",
    "calibration": "calibration_reliability.png",
}

EXPECTED_REGISTRY_KEYS = {f"fig:{name}" for name in EXPECTED_PNGS}
EXPECTED_REGISTRY_SECTIONS = {
    "fig:architecture": "Methodology",
    "fig:primitives": "Methodology",
    "fig:graphical_abstract": "Abstract",
    "fig:batching": "Results",
    "fig:latency": "Results",
    "fig:confidence": "Methodology",
    "fig:calibration": "Results",
}
EXPECTED_REGISTRY_WIDTHS = {
    "fig:graphical_abstract": "1.0\\textwidth",
    "fig:confidence": "0.8\\textwidth",
}


def _batching_payload() -> dict:
    """Synthetic batching benchmark with the real JSON schema, small numbers."""
    return {
        "name": "batching",
        "date": "2026-09-16",
        "model": "jev-latest",
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


def _patterns_payload() -> dict:
    """Synthetic patterns benchmark with the real JSON schema."""
    return {
        "name": "patterns",
        "date": "2026-09-16",
        "model": "jev-latest",
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


def _calibration_payload() -> dict:
    """Synthetic calibration benchmark with the real JSON schema."""
    return {
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
                {"bucket_lo": 0.6, "bucket_hi": 0.7, "n": 5,
                 "mean_confidence": 0.65, "accuracy": 0.8},
                {"bucket_lo": 0.9, "bucket_hi": 1.0, "n": 4,
                 "mean_confidence": 0.95, "accuracy": 1.0},
            ],
        },
        "noul_stability": {"mean_pairwise_gap": 0.025},
        "n_errors": 0,
        "notes": "correctness proxy = agreement with modal choice "
                 "(self-consistency), not ground truth",
    }


def _write_benchmark(root: Path, name: str, payload: dict) -> None:
    bench_dir = root / "output" / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / f"{name}_20260916.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_benchmarks(root: Path) -> None:
    _write_benchmark(root, "batching", _batching_payload())
    _write_benchmark(root, "patterns", _patterns_payload())
    _write_benchmark(root, "calibration", _calibration_payload())


@pytest.fixture()
def fake_project(tmp_path: Path) -> Path:
    """Project root with schema-faithful benchmark JSONs under output/benchmarks."""
    _write_benchmarks(tmp_path)
    return tmp_path


def _assert_valid_png(path: Path) -> None:
    assert path.is_file(), f"missing PNG: {path}"
    data = path.read_bytes()
    assert len(data) > 1000, f"PNG suspiciously small ({len(data)} bytes): {path}"
    assert data.startswith(PNG_MAGIC), f"not a PNG: {path}"


# --------------------------------------------------------------- generate_all ---
def test_generate_all_writes_all_seven_pngs(fake_project: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "figures"
    paths = generate_all(out_dir, project_root=fake_project)

    assert paths == [out_dir / name for name in EXPECTED_PNGS.values()]
    for png in paths:
        _assert_valid_png(png)


def test_generate_all_regenerates_byte_deterministically(fake_project: Path, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_all(first, project_root=fake_project)
    generate_all(second, project_root=fake_project)

    for filename in EXPECTED_PNGS.values():
        assert (first / filename).read_bytes() == (second / filename).read_bytes(), filename


def test_graphical_abstract_is_byte_deterministic(fake_project: Path, tmp_path: Path) -> None:
    """The cover figure renders byte-identically from the same benchmark JSONs."""
    first = tmp_path / "first"
    second = tmp_path / "second"

    path_a = generate_graphical_abstract(first, project_root=fake_project)
    path_b = generate_graphical_abstract(second, project_root=fake_project)

    assert path_a == first / "graphical_abstract.png"
    assert path_b == second / "graphical_abstract.png"
    assert path_a.read_bytes() == path_b.read_bytes()


def test_graphical_abstract_missing_benchmark_raises_file_not_found(tmp_path: Path) -> None:
    """The cover figure needs all three benchmark JSONs; the error names the path."""
    root = tmp_path / "empty"
    root.mkdir()

    with pytest.raises(FileNotFoundError) as excinfo:
        generate_graphical_abstract(tmp_path / "out", project_root=root)

    assert str(root / "output" / "benchmarks") in str(excinfo.value)


def test_registry_orders_graphical_abstract_first(generated_project: Path) -> None:
    """The abstract opens the registry and is figure_001."""
    registry = json.loads((generated_project / FIGURE_REGISTRY_FILENAME).read_text(encoding="utf-8"))

    assert next(iter(registry)) == "fig:graphical_abstract"
    assert registry["fig:graphical_abstract"]["figure_id"] == "figure_001"
    assert registry["fig:graphical_abstract"]["section"] == "Abstract"
    assert registry["fig:graphical_abstract"]["width"] == "1.0\\textwidth"


def test_generate_all_stops_at_first_missing_benchmark(tmp_path: Path) -> None:
    """The graphical abstract renders first and needs all three benchmark JSONs."""
    out_dir = tmp_path / "figures"
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    with pytest.raises(FileNotFoundError):
        generate_all(out_dir, project_root=empty_root)

    for filename in EXPECTED_PNGS.values():
        assert not (out_dir / filename).exists()


def test_confidence_figure_is_data_free(tmp_path: Path) -> None:
    """Figure 5 renders even when the project has no benchmarks at all."""
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    path = generate_confidence(tmp_path / "out", project_root=empty_root)
    _assert_valid_png(path)


def test_calibration_figure_is_byte_deterministic(fake_project: Path, tmp_path: Path) -> None:
    """The reliability figure renders byte-identically from the same JSON."""
    first = tmp_path / "first"
    second = tmp_path / "second"

    path_a = generate_calibration(first, project_root=fake_project)
    path_b = generate_calibration(second, project_root=fake_project)

    assert path_a == first / "calibration_reliability.png"
    assert path_b == second / "calibration_reliability.png"
    assert path_a.read_bytes() == path_b.read_bytes()


def test_missing_calibration_benchmark_raises_file_not_found(tmp_path: Path) -> None:
    """The calibration figure needs its benchmark JSON; the error names it."""
    root = tmp_path / "partial"
    root.mkdir()
    _write_benchmark(root, "batching", _batching_payload())
    _write_benchmark(root, "patterns", _patterns_payload())

    with pytest.raises(FileNotFoundError, match="calibration"):
        generate_calibration(tmp_path / "out", project_root=root)


# ------------------------------------------------------------ generate_one ---
@pytest.mark.parametrize(
    ("generate", "filename"),
    [
        (generate_graphical_abstract, "graphical_abstract.png"),
        (generate_architecture, "architecture.png"),
        (generate_primitives, "primitives_overview.png"),
        (generate_batching, "batching_speedup.png"),
        (generate_latency, "latency_percentiles.png"),
        (generate_confidence, "confidence_bands.png"),
        (generate_calibration, "calibration_reliability.png"),
    ],
)
def test_each_registered_figure_renders(
    fake_project: Path, tmp_path: Path, generate, filename: str
) -> None:
    out_dir = tmp_path / filename.removesuffix(".png")
    path = generate(out_dir, project_root=fake_project)
    assert path == out_dir / filename
    _assert_valid_png(path)


def test_generate_one_dispatches_by_name(fake_project: Path, tmp_path: Path) -> None:
    for name, filename in EXPECTED_PNGS.items():
        out_dir = tmp_path / name
        path = generate_one(name, out_dir, project_root=fake_project)
        assert path == out_dir / filename
        _assert_valid_png(path)


def test_generate_one_unknown_name_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no-such-figure"):
        generate_one("no-such-figure", tmp_path / "out")
    # The error also names every valid choice.
    with pytest.raises(ValueError, match="batching"):
        generate_one("no-such-figure", tmp_path / "out")


# ------------------------------------------------------- missing benchmarks ---


def test_missing_batching_benchmark_raises_file_not_found(tmp_path: Path) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()

    with pytest.raises(FileNotFoundError, match="batching") as excinfo:
        generate_batching(tmp_path / "out", project_root=empty_root)
    assert str(empty_root / "output" / "benchmarks") in str(excinfo.value)


def test_missing_patterns_benchmark_raises_file_not_found(tmp_path: Path) -> None:
    root = tmp_path / "partial"
    _write_benchmark(root, "batching", _batching_payload())

    with pytest.raises(FileNotFoundError, match="patterns") as excinfo:
        generate_latency(tmp_path / "out", project_root=root)
    assert str(root / "output" / "benchmarks") in str(excinfo.value)


# ----------------------------------------------------- figure_registry.json ---


@pytest.fixture()
def generated_project(fake_project: Path, tmp_path: Path) -> Path:
    """Out directory holding the five PNGs and the registry written by generate_all."""
    out_dir = tmp_path / "figures"
    generate_all(out_dir, project_root=fake_project)
    return out_dir


def test_generate_all_writes_figure_registry(generated_project: Path) -> None:
    """generate_all leaves a loadable registry beside the PNGs."""
    path = generated_project / FIGURE_REGISTRY_FILENAME
    assert path.is_file()

    registry = json.loads(path.read_text(encoding="utf-8"))
    assert set(registry) == EXPECTED_REGISTRY_KEYS


def test_write_figure_registry_standalone(tmp_path: Path) -> None:
    """write_figure_registry also works on its own, creating the directory."""
    out_dir = tmp_path / "fresh" / "nested"
    path = write_figure_registry(out_dir)

    assert path == out_dir / FIGURE_REGISTRY_FILENAME
    assert set(json.loads(path.read_text(encoding="utf-8"))) == EXPECTED_REGISTRY_KEYS


def test_figure_registry_schema_and_values(generated_project: Path) -> None:
    """Every entry carries the exemplar schema with manuscript-faithful metadata."""
    registry = json.loads((generated_project / FIGURE_REGISTRY_FILENAME).read_text(encoding="utf-8"))

    for figure_id, (label, entry) in enumerate(registry.items(), start=1):
        assert set(entry) == {
            "figure_id",
            "filename",
            "caption",
            "label",
            "section",
            "width",
            "placement",
            "generated_by",
            "metadata",
        }
        assert entry["figure_id"] == f"figure_{figure_id:03d}"
        assert entry["label"] == label
        assert entry["filename"] == EXPECTED_PNGS[label.removeprefix("fig:")]
        assert entry["section"] == EXPECTED_REGISTRY_SECTIONS[label]
        assert entry["width"].endswith("\\textwidth")
        assert entry["width"] == EXPECTED_REGISTRY_WIDTHS.get(label, "0.85\\textwidth")
        assert entry["placement"] == "h"
        assert entry["generated_by"] == "daf_jev.figures"
        assert set(entry["metadata"]) == {"alt_text", "source"}
        assert len(entry["metadata"]["alt_text"]) > 40, label
        assert entry["metadata"]["source"] == "daf-jev benchmark/figure pipeline"
        assert entry["caption"] and entry["caption"].isprintable()


def test_figure_registry_captions_derived_from_manuscript(generated_project: Path) -> None:
    """Captions name the same objects the manuscript's figure lines describe."""
    registry = json.loads((generated_project / FIGURE_REGISTRY_FILENAME).read_text(encoding="utf-8"))

    assert "layer diagram" in registry["fig:architecture"]["caption"].lower()
    assert "noul" in registry["fig:primitives"]["caption"] and "score" in registry["fig:primitives"]["caption"]
    assert "speedup" in registry["fig:batching"]["caption"].lower()
    assert "p50" in registry["fig:latency"]["caption"] and "p95" in registry["fig:latency"]["caption"]
    assert "automate" in registry["fig:confidence"]["caption"]


def test_figure_registry_filenames_match_written_pngs(generated_project: Path) -> None:
    """Every registered filename is a valid PNG sitting next to the registry."""
    registry = json.loads((generated_project / FIGURE_REGISTRY_FILENAME).read_text(encoding="utf-8"))

    filenames = [entry["filename"] for entry in registry.values()]
    assert sorted(filenames) == sorted(EXPECTED_PNGS.values())
    for filename in filenames:
        _assert_valid_png(generated_project / filename)


def test_figure_registry_is_byte_deterministic(fake_project: Path, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_all(first, project_root=fake_project)
    generate_all(second, project_root=fake_project)

    assert (first / FIGURE_REGISTRY_FILENAME).read_bytes() == (second / FIGURE_REGISTRY_FILENAME).read_bytes()
