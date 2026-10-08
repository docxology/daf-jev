"""Real-file, offline checks of non-executable hosted obligations."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from daf_jev._json import strict_json_loads
from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_sampling import timing_sample_pack
from daf_jev.decision_backends import canonical_json, content_hash

SPEC = importlib.util.spec_from_file_location(
    "hosted_projection", Path(__file__).resolve().parents[2] / "scripts/prepare_hosted_expansion.py"
)
assert SPEC is not None and SPEC.loader is not None
PROJECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROJECTION)


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    datasets = [make_synthetic_dataset("binary", seed=9, n=250),
                make_synthetic_dataset("categorical", seed=9, n=250),
                make_synthetic_dataset("categorical", seed=9, n=35, matched_option_permutations=True)]
    refs, declarations, receipt_inputs = [], [], []
    cohorts = []
    for index, dataset in enumerate(datasets):
        identifier = f"fixture-{index}"
        path = save_dataset(dataset, tmp_path / f"dataset-{index}.json", packed=True)
        role = "quality_control" if index == 2 else "ordinary"
        selected = [e for e in dataset.examples if e.split in {"validation", "test"}]
        cohorts.append(selected)
        refs.append({"id": identifier, "path": str(path), "role": role})
        receipt_inputs.append({"id": identifier, "path": str(path),
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        declarations.append({"id": identifier, "quality_control_examples": len(selected) if index == 2 else 0,
                             "quality_examples": len(selected), "quality_decisions": len(selected),
                             "validation_examples": sum(e.split == "validation" for e in selected),
                             "test_examples": sum(e.split == "test" for e in selected)})
    receipt_path = tmp_path / "selection.json"
    receipt_path.write_text(canonical_json({"inputs": receipt_inputs}))
    fragment = {"format": "dafjev.private-local-study-fragment/2", "datasets": refs,
                "expected_quality_counts": declarations, "sampling": "all", "seed": 9,
                "timing_samples": 100, "timing_repetitions": 5, "timing_sampling_scope": "cohort",
                "timing_sample_pack": timing_sample_pack(cohorts, seed=9, samples=100),
                "selection_receipt": {"path": str(receipt_path),
                                      "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()}}
    catalog = {"format": "dafjev.model-catalog/1",
               "source": "https://openrouter.ai/api/v1/models?output_modalities=decisions",
               "fetched_at": "2026-10-08T00:00:00+00:00", "payload": {"data": []}}
    for identifier, context, rate in (("inception/mercury-decide:free", 65536, "0"),
                                     ("typesafe/jev", 64000, "0.000000042"),
                                     ("togethercomputer/tev1-fixture", 32768, "0.000000042")):
        catalog["payload"]["data"].append({"id": identifier, "context_length": context,
            "pricing": {"prompt": rate, "completion": "0"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]}})
    endpoints = {"data": {"id": "qwen/qwen3.5-9b", "endpoints": [{"tag": "darkbloom/fp4",
        "context_length": 262144, "supported_parameters": ["max_tokens", "response_format", "structured_outputs"],
        "pricing": {"prompt": "0.00000008", "completion": "0.00000013"}}]}}
    prior = {"hosted_pilot": {"allocation_id": PROJECTION.ALLOCATION,
             "accounting": {"limit_usd": "25", "admission_stopped": True,
                            "reported_cost_usd": "0", "reserved_usd": "0",
                            "unresolved_attempts": ["original-unknown-attempt"]},
             "actual_transport_attempts": 1, "manifest_hash": "a" * 64, "journal_hash": "b" * 64}}
    return catalog, endpoints, fragment, prior


def project(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> dict[str, Any]:
    return PROJECTION.build(*inputs, fragment_parent=tmp_path)


def test_fixed_denominators_quotes_and_unknown_are_preserved(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    plan = project(inputs, tmp_path)
    assert plan["format"] == "dafjev.hosted-expansion-obligation/1"
    assert plan["execution_authority"] is False and plan["status"] == "BLOCKED_UNKNOWN_BILLING"
    assert plan["planned_phase_counts"] == {"quality": 968, "warm_repeat": 2000, "capability_probe": 12, "graphical": 4}
    assert plan["planned_cells"] == 2984
    assert plan["new_observed_outcomes"]["unattempted"] == 2984
    assert plan["allocation"]["new_transport_attempts"] == 0
    assert plan["allocation"]["prior_accounting"]["unresolved_attempts"] == ["original-unknown-attempt"]
    assert plan["timing_sample_pack"]["selected_examples"] == 100
    assert all(row["dataset"] != 2 for row in plan["timing_sample_pack"]["examples"])
    by_id = {arm["profile"]["id"]: arm for arm in plan["arms"]}
    assert by_id["typesafe/jev"]["liability_usd_per_attempt"] is None
    assert by_id["inception/mercury-decide:free"]["liability_usd_per_attempt"] == "0"
    assert Decimal(by_id["qwen3.5-9b-chat"]["liability_usd_per_attempt"]) == Decimal("0.02103808")
    assert Decimal(by_id["togethercomputer/tev1-fixture"]["liability_usd_per_attempt"]) == Decimal("0.001376256")
    for arm in plan["arms"]:
        assert arm["profile"]["capabilities"]["probability_semantics"] is None
        assert len(arm["cell_ids_sha256_by_phase"]["quality"]) == 64
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert plan == project(inputs, tmp_path)
    assert "/Users/" not in canonical_json(plan)


@pytest.mark.parametrize("mutation", ["refunded", "new_budget", "timing_bool", "counts_bool", "counts_order",
                                     "control_role", "pack_id", "duplicate_catalog", "endpoint_model"])
def test_malformed_or_changed_contract_refused(inputs: tuple[dict[str, Any], ...], tmp_path: Path, mutation: str) -> None:
    changed = copy.deepcopy(inputs)
    catalog, endpoints, fragment, prior = changed
    if mutation == "refunded":
        prior["hosted_pilot"]["accounting"]["admission_stopped"] = False
    elif mutation == "new_budget":
        prior["hosted_pilot"]["allocation_id"] = "new-budget"
    elif mutation == "timing_bool":
        fragment["timing_repetitions"] = True
    elif mutation == "counts_bool":
        fragment["expected_quality_counts"][0]["quality_decisions"] = True
    elif mutation == "counts_order":
        fragment["expected_quality_counts"].reverse()
    elif mutation == "control_role":
        fragment["datasets"][2]["role"] = "ordinary"
    elif mutation == "pack_id":
        fragment["timing_sample_pack"]["examples"][0]["example_id"] = "unselected"
    elif mutation == "duplicate_catalog":
        catalog["payload"]["data"].append(copy.deepcopy(catalog["payload"]["data"][0]))
    elif mutation == "endpoint_model":
        endpoints["data"]["id"] = "other/model"
    with pytest.raises(ValueError):
        project(changed, tmp_path)


def test_receipt_duplicate_ids_and_changed_input_refused(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> None:
    fragment = copy.deepcopy(inputs[2])
    receipt_path = Path(fragment["selection_receipt"]["path"])
    receipt = strict_json_loads(receipt_path.read_bytes())
    receipt["inputs"].append(copy.deepcopy(receipt["inputs"][0]))
    receipt_path.write_text(canonical_json(receipt))
    fragment["selection_receipt"]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="duplicate input IDs"):
        project((inputs[0], inputs[1], fragment, inputs[3]), tmp_path)
    path = Path(inputs[2]["datasets"][0]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        project(inputs, tmp_path)


def test_bound_reader_and_strict_json_refuse_ambiguous_inputs(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.json"
    path.write_text('{"pricing":{"prompt":"1","prompt":"0"}}')
    raw, _ = PROJECTION.read_bound(path)
    with pytest.raises(ValueError, match="duplicate"):
        strict_json_loads(raw)
    path.write_text('{"rate":NaN}')
    with pytest.raises(ValueError):
        strict_json_loads(PROJECTION.read_bound(path)[0])
    with pytest.raises(ValueError, match="SHA-256"):
        PROJECTION.read_bound(path, "0" * 64)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        PROJECTION.read_bound(alias)


def test_public_projection_omits_untrusted_extra_account_fields(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> None:
    changed = copy.deepcopy(inputs)
    changed[3]["hosted_pilot"]["accounting"]["private_payload"] = "fixture-private-sentinel"
    assert "fixture-private-sentinel" not in canonical_json(project(changed, tmp_path))
    changed[3]["hosted_pilot"]["accounting"]["unresolved_attempts"] = ["private\npath"]
    with pytest.raises(ValueError, match="portable identity"):
        project(changed, tmp_path)


def test_static_matrix_two_renders_are_exact(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> None:
    from pypdf import PdfReader

    plan = project(inputs, tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    hashes = PROJECTION.render_matrix(plan, first)
    assert hashes == PROJECTION.render_matrix(plan, second)
    matrix = strict_json_loads((first / "admission-matrix.json").read_bytes())
    assert matrix["plan_sha256"] == content_hash(plan)
    assert matrix["rows"][1]["cells"][-1] == "unbounded"
    assert matrix["rows"][0]["cells"][-1] == "zero_tariff"
    pdf = PdfReader(first / "admission-matrix.pdf")
    text = "".join(page.extract_text() for page in pdf.pages)
    assert "UNKNOWN charge" in text and "No quality, latency" in text
    assert "calibrated/posterior meaning is unknown" in text
    assert "/Users/" not in text and "fixture-private-sentinel" not in text
    for page in pdf.pages:
        outside = []
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        def visitor(value: str, cm: list[float], tm: list[float], _font: Any, _size: float,
                    width: float = width, height: float = height,
                    outside: list[tuple[float, float]] = outside) -> None:
            if value.strip():
                x, y = cm[4] + tm[4], cm[5] + tm[5]
                if not 0 <= x <= width or not 0 <= y <= height:
                    outside.append((x, y))
        page.extract_text(visitor_text=visitor)
        assert not outside
    with pytest.raises(FileExistsError):
        PROJECTION.render_matrix(plan, first)


def test_cli_symlinked_output_refused_before_any_artifact(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> None:
    actual = tmp_path / "actual-destination"
    actual.mkdir()
    alias = tmp_path / "output-alias"
    alias.symlink_to(actual, target_is_directory=True)
    args = []
    for name, value in zip(("catalog", "endpoints", "fragment", "prior-summary"), inputs, strict=True):
        path = tmp_path / (name + ".json")
        path.write_text(canonical_json(value))
        args.extend(["--" + name, str(path), "--" + name + "-sha256",
                     hashlib.sha256(path.read_bytes()).hexdigest()])
    completed = subprocess.run([sys.executable, str(SPEC.origin), *args,
                                "--out-dir", str(alias / "new-output")],
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 1
    assert "ValueError; no inference performed" in completed.stderr
    assert list(actual.iterdir()) == []
    assert not (alias / "new-output").exists()


def test_hostile_theme_cannot_change_matrix_bytes_and_is_restored(inputs: tuple[dict[str, Any], ...], tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    plan = project(inputs, tmp_path)
    baseline, hostile = tmp_path / "baseline", tmp_path / "hostile"
    baseline.mkdir()
    hostile.mkdir()
    ambient = dict(plt.rcParams)
    baseline_hashes = PROJECTION.render_matrix(plan, baseline)
    assert dict(plt.rcParams) == ambient
    with plt.rc_context({"image.origin": "lower", "text.color": "red", "font.size": 22,
                         "axes.facecolor": "black", "axes.labelcolor": "yellow",
                         "figure.facecolor": "magenta", "savefig.facecolor": "cyan",
                         "pdf.compression": 0, "svg.fonttype": "none", "lines.linewidth": 8}):
        caller = dict(plt.rcParams)
        assert PROJECTION.render_matrix(plan, hostile) == baseline_hashes
        assert dict(plt.rcParams) == caller
    assert dict(plt.rcParams) == ambient
