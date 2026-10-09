"""Selected retained summaries: identity, denominators, and figure regeneration."""
from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from decimal import localcontext
from pathlib import Path

import pytest
from pypdf import PdfReader

from daf_jev.evidence import (
    has_selected_study,
    has_study_selection,
    selected_study_bytes,
)
from daf_jev.study_evidence import (
    interval,
    load_studies,
    number,
    selected_native_study,
    validate_native_hosted_summary,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def study_tree(tmp_path: Path) -> Path:
    """Relocate real retained public inputs; never depend on newest filenames."""
    source = ROOT
    selection = json.loads((source / "manuscript/evidence.json").read_bytes())
    # Historical-only fixture stays historical even after an additive selection.
    selection["study_summaries"] = {k: v for k, v in selection["study_summaries"].items()
                                     if k in {"cpu", "hosted"}}
    tmp_path.joinpath("manuscript").mkdir()
    for entry in selection["study_summaries"].values():
        dest = tmp_path / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / entry["path"], dest)
    selection.pop("verification", None)
    (tmp_path / "manuscript/evidence.json").write_text(json.dumps(selection))
    return tmp_path


def rewrite(root: Path, section: str, edit) -> None:
    selection_path = root / "manuscript/evidence.json"
    selection = json.loads(selection_path.read_bytes())
    entry = selection["study_summaries"][section]
    path = root / entry["path"]
    payload = json.loads(path.read_bytes())
    edit(payload)
    path.write_text(json.dumps(payload, allow_nan=False))
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    selection_path.write_text(json.dumps(selection))


def test_selected_tokens_and_newer_files_do_not_change_selection(study_tree: Path) -> None:
    s = load_studies(study_tree)
    tokens = s.tokens()
    assert tokens["STUDY_CPU_COMPLETED"] == str(s.cpu["status_counts"]["completed"])
    assert tokens["STUDY_BANK_ACCURACY_PCT"] == f"{100*s.arm('banking77', 'tfidf-logistic-C1')['metrics']['accuracy']:.2f}"
    assert tokens["STUDY_WINE_MAE"] == f"{s.arm('wine', 'wine-hist-gradient-boosting')['metrics']['ordinal_mae']:.4f}"
    assert tokens["STUDY_HOSTED_UNRESOLVED_BILLING"] == "1"
    assert len(tokens) == 17
    (study_tree / "output/newer-result.json").write_text('{"accuracy":1}')
    assert load_studies(study_tree).tokens() == tokens


def test_selected_bytes_detect_mutation_escape_and_missing(study_tree: Path) -> None:
    selection = json.loads((study_tree / "manuscript/evidence.json").read_bytes())
    entry = selection["study_summaries"]["cpu"]
    path = study_tree / entry["path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        selected_study_bytes(study_tree, "cpu")
    entry["path"] = "../escaped.json"
    (study_tree / "manuscript/evidence.json").write_text(json.dumps(selection))
    with pytest.raises(ValueError, match="confined"):
        load_studies(study_tree)
    with pytest.raises(ValueError, match="missing selected"):
        selected_study_bytes(study_tree, "unselected")


def test_optional_selection_and_explicit_invalid_map(tmp_path: Path) -> None:
    assert not has_study_selection(tmp_path)
    assert not has_selected_study(tmp_path, "native_hosted")
    p = tmp_path / "manuscript/evidence.json"
    p.parent.mkdir()
    p.write_text('{"format":"dafjev.publication-evidence/1"}')
    assert not has_study_selection(tmp_path)
    assert not has_selected_study(tmp_path, "native_hosted")
    p.write_text('{"format":"dafjev.publication-evidence/1","study_summaries":[]}')
    assert has_study_selection(tmp_path)
    with pytest.raises(ValueError, match="object"):
        selected_study_bytes(tmp_path, "cpu")
    with pytest.raises(ValueError, match="object"):
        has_selected_study(tmp_path, "native_hosted")


@pytest.mark.parametrize("section,edit,match", [
    ("cpu", lambda d: d["status_counts"].update(completed=0), "denominator"),
    ("hosted", lambda d: d["hosted_pilot"].update(actual_transport_attempts=2), "attempt denominator"),
    ("hosted", lambda d: d["hosted_pilot"]["accounting"].update(limit_usd="NaN"), "USD"),
    ("hosted", lambda d: d["hosted_pilot"]["accounting"].update(limit_usd="bad"), "USD"),
    ("hosted", lambda d: d["hosted_pilot"]["accounting"].update(unresolved_attempts=0), "inventory"),
    ("cpu", lambda d: d["arms"].append(d["arms"][0]), "unique"),
    ("cpu", lambda d: d["arms"][0]["metrics"].update(accuracy=-.1), "metric"),
    ("cpu", lambda d: d["arms"][0]["metrics"].update(n_success=True), "integer"),
    ("cpu", lambda d: d["validation_gates"][0]["calibration"].update(n_groups=1), "unadmitted"),
    ("cpu", lambda d: d["validation_gates"][0]["calibration"].update(validation_groups=0), "denominators"),
    ("cpu", lambda d: d["validation_gates"][1]["calibration"].update(wilson_upper=0), "Wilson upper"),
    ("cpu", lambda d: d.update(format="unrecognized"), "format"),
    ("cpu", lambda d: d.pop("arms"), "incomplete"),
    ("hosted", lambda d: d["hosted_pilot"]["accounting"].update(limit_usd=True), "USD"),
    ("cpu", lambda d: d["phase_status_counts"]["quality"].update(completed=100000), "phase/status"),
    ("hosted", lambda d: d["hosted_pilot"]["accounting"].update(unresolved_attempts=[], admission_stopped=False), "stopped"),
    ("cpu", lambda d: d["validation_gates"][1]["calibration"].update(wilson_upper=.99), "Wilson upper"),
    ("cpu", lambda d: d["validation_gates"][1]["calibration"].update(method="not_wilson"), "protocol"),
    ("cpu", lambda d: d["arms"][0]["metrics"].update(n_success=0, n_hard_targets=0), "observed|scored"),
    ("cpu", lambda d: d["arms"][0]["metrics"].update(brier=5), "metric"),
    ("cpu", lambda d: d["arms"][0]["metrics"]["uncertainty"]["accuracy"].update(groups=1000000), "scoring units"),
    ("cpu", lambda d: d["banking77_fivefold_oof"][0]["grouped_interval"].update(groups=1000000), "scoring units"),
])
def test_fail_closed_summary_validation(study_tree: Path, section: str, edit, match: str) -> None:
    rewrite(study_tree, section, edit)
    with pytest.raises(ValueError, match=match):
        load_studies(study_tree)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1, True, "0.1", 1.1, 10**500])
def test_probability_metric_validation(value) -> None:
    with pytest.raises(ValueError):
        number(value, upper=1)


def test_retained_interval_and_absent_arm(study_tree: Path) -> None:
    s = load_studies(study_tree)
    with pytest.raises(ValueError, match="unique"):
        s.arm("banking77", "never-substitute")
    with pytest.raises(ValueError, match="evidence"):
        interval({"status": "missing"}, .5)
    with pytest.raises(ValueError, match="ordered"):
        interval({"status": "ok", "method": "grouped_percentile_95", "samples": 2000,
                  "groups": 10, "low": .7, "high": .6}, .5, upper=1)
    assert interval({"status": "ok", "method": "grouped_percentile_95", "samples": 2000,
                     "groups": 10, "low": .6, "high": .7}, .5, upper=1) == (.6, .7)


def test_single_group_cannot_supply_a_bootstrap_interval() -> None:
    with pytest.raises(ValueError, match="evidence"):
        interval({"status": "ok", "method": "grouped_percentile_95", "samples": 2000,
                  "groups": 1, "low": .5, "high": .5}, .5, max_groups=1)


def test_all_selected_figures_regenerate_deterministically(study_tree: Path, tmp_path: Path) -> None:
    from daf_jev.study_figures import FILENAMES, generate
    s = load_studies(study_tree)
    for name in FILENAMES:
        first = generate(name, tmp_path / "first", study_tree)
        second = generate(name, tmp_path / "second", study_tree)
        for suffix in (".png", ".pdf", ".data.json"):
            assert first.with_suffix(suffix).read_bytes() == second.with_suffix(suffix).read_bytes()
        data = json.loads(first.with_suffix(".data.json").read_bytes())
        assert data["selected_input_sha256"] == s.hashes
        assert len(PdfReader(first.with_suffix(".pdf")).pages) == 1
        if name == "selective_validation":
            assert any(r["eligible_coverage"] == 0 and r["observed_error"] is None for r in data["rows"])
        if name == "wine_ordinal":
            assert sum(data["bin_counts"]) == s.arm("wine", "prior")["metrics"]["n_hard_targets"]
        if name == "execution_coverage":
            assert all(sum(r["counts"].values()) == r["planned_cells"] for r in data["rows"])
    with pytest.raises(ValueError, match="unknown"):
        generate("unselected", tmp_path, study_tree)


def test_extended_registry_preserves_legacy_default(tmp_path: Path, study_tree: Path) -> None:
    from daf_jev.figures import write_figure_registry
    from daf_jev.study_figures import FILENAMES
    legacy = json.loads(write_figure_registry(tmp_path / "old").read_bytes())
    extended = json.loads(write_figure_registry(tmp_path / "new", study_tree, include_study=True).read_bytes())
    assert {k: extended[k] for k in legacy if k != "fig:graphical_abstract"} == {k: v for k, v in legacy.items() if k != "fig:graphical_abstract"}
    assert len(extended) == len(legacy) + len(FILENAMES)



def test_overview_preserves_separate_evidence_tiers(study_tree: Path, tmp_path: Path) -> None:
    from daf_jev.study_figures import generate_overview
    first = generate_overview(tmp_path / "overview-a", study_tree)
    second = generate_overview(tmp_path / "overview-b", study_tree)
    for suffix in (".png", ".pdf", ".data.json"):
        assert first.with_suffix(suffix).read_bytes() == second.with_suffix(suffix).read_bytes()
    payload = json.loads(first.with_suffix(".data.json").read_bytes())
    assert "0 quality predictions" in payload["panels"][2][2]
    assert "1 billing unresolved" in payload["panels"][2][2]



def test_study_style_is_independent_of_entry_point_and_caller_theme(study_tree: Path, tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    from daf_jev.figures import generate_one
    from daf_jev.study_figures import generate, generate_overview
    plain = generate("cpu_quality", tmp_path / "plain", study_tree)
    cover = generate_overview(tmp_path / "cover-plain", study_tree)
    with plt.rc_context({"font.size": 22, "axes.facecolor": "red", "axes.grid": True,
                         "font.family": "DejaVu Sans Mono", "lines.linewidth": 4}):
        routed = generate_one("cpu_quality", tmp_path / "routed", study_tree)
        routed_cover = generate_one("graphical_abstract", tmp_path / "cover-routed", study_tree, include_study=True)
    for suffix in (".png", ".pdf", ".data.json"):
        assert plain.with_suffix(suffix).read_bytes() == routed.with_suffix(suffix).read_bytes()
        assert cover.with_suffix(suffix).read_bytes() == routed_cover.with_suffix(suffix).read_bytes()


def native_summary() -> dict:
    """A small local schema fixture, never an assertion of hosted execution."""
    status = {"completed": 0, "failed": 0, "unsupported": 0, "unresolved": 0, "unattempted": 0}
    phase_counts = {phase: {"planned": planned, **status, "unattempted": planned}
                    for phase, planned in (("capability_probe", 2), ("quality", 1),
                                           ("warm_repeat", 1), ("graphical", 0))}
    phase_counts["capability_probe"].update(completed=2, unattempted=0)
    receipts, probes = [], []
    for index, (ident, size, charge) in enumerate((("a", 77, "0.000000002"), ("b", 151, "0.000000003"))):
        receipts.append({"cell_id": ident * 64, "phase": "capability_probe", "dataset_index": index,
                         "receipt": {"attempt_id": f"fixture-attempt-{index}",
                                     "timestamp": "2026-10-09T18:00:00+00:00",
                                     "endpoint": "https://openrouter.ai/api/alpha/decisions",
                                     "requested_model": "typesafe/jev-1.13", "resolved_model": "fixture-native-revision",
                                     "provider": "fixture-provider", "response_id": f"fixture-response-{index}",
                                     "request_hash": "c" * 64, "elapsed_s": .25 + index,
                                     "status_code": 200, "input_tokens": index + 1, "output_tokens": 2,
                                     "cost_usd": charge, "cost_status": "reported", "error": None,
                                     "response_diagnostics": {"body_complete": True,
                                                              "digest_scope": "complete_decoded_body",
                                                              "classification": "json_object", "body_sha256": "d" * 64,
                                                              "media_type": "application/json",
                                                              "body_bytes_observed": 120, "body_limit_bytes": 1048576}}})
        probes.append({"cell_id": ident * 64, "dataset_index": index, "example_id": f"fixture-example-{index}",
                       "status": "completed", "evidence": {"scope": "selected_validation_fixture",
                           "maximum_boundaries_verified": False, "empirical_success": True,
                           "state_sha256": "e" * 64, "question_count": 1, "primitives": ["choice"],
                           "options_per_question": {"decision": size}}})
    return {"format": "dafjev.native-hosted-study-summary/1", "manifest_hash": "1" * 64,
            "journal_hash": "2" * 64, "inference_source_hash": "3" * 64, "source_git_head": "4" * 40,
            "scope": {"through_phase": "capability_probe", "cut_timestamp": "2026-10-09T18:01:00+00:00",
                      "maximum_boundaries_verified": False, "quality_claims": False},
            "planned_cells": 4, "denominators": {**status, "completed": 2, "unattempted": 2},
            "phase_counts": phase_counts,
            "datasets": [{"index": i, "id": name, "name": name, "family": name}
                         for i, name in enumerate(("banking77", "clinc150"))],
            "actual_transport_attempts": 2, "attempt_receipts": receipts, "capability_probes": probes,
            "completed_quality_predictions": [], "completed_warm_predictions": [],
            "accounting": {"limit_usd": "25", "reported_cost_usd": "0.000000005", "reserved_usd": "0",
                           "unresolved_attempts": [], "admission_stopped": False},
            "historical_bounded_unknown": {"original_attempt_ids": ["fixture-original-attempt"],
                                           "held_upper_bound_usd": "0", "charge_status": "UNKNOWN"},
            "evidence": {"manifest": {"path": "manifest.json", "sha256": "1" * 64, "bytes": 123,
                                      "note": "local test fixture"}}}


def select_native(root: Path, value: dict) -> str:
    path = root / "output/native-summary.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    selection_path = root / "manuscript/evidence.json"
    selection = json.loads(selection_path.read_bytes())
    selection["study_summaries"]["native_hosted"] = {"path": "output/native-summary.json", "sha256": sha}
    selection_path.write_text(json.dumps(selection))
    return sha


def test_native_selection_is_additive_and_explicit(study_tree: Path) -> None:
    legacy = load_studies(study_tree)
    assert not has_selected_study(study_tree, "native_hosted")
    (study_tree / "output/newer-native-summary.json").write_text(json.dumps(native_summary()))
    assert load_studies(study_tree).tokens() == legacy.tokens()
    sha = select_native(study_tree, native_summary())
    studies = load_studies(study_tree)
    assert studies.cpu == legacy.cpu and studies.hosted == legacy.hosted
    assert studies.hashes == {**legacy.hashes, "native_hosted": sha}
    assert {k: v for k, v in studies.tokens().items() if k in legacy.tokens()} == legacy.tokens()
    assert {k: v for k, v in studies.tokens().items() if k.startswith("NATIVE_HOSTED_")} == {
        "NATIVE_HOSTED_PLANNED": "4", "NATIVE_HOSTED_PROBES_COMPLETED": "2", "NATIVE_HOSTED_ATTEMPTS": "2",
        "NATIVE_HOSTED_REPORTED_COST_USD": "0.000000005", "NATIVE_HOSTED_QUALITY_COMPLETED": "0",
        "NATIVE_HOSTED_WARM_COMPLETED": "0", "NATIVE_HOSTED_UNATTEMPTED": "2"}
    assert studies.native_hosted["historical_bounded_unknown"]["charge_status"] == "UNKNOWN"
    (study_tree / "output/native-summary.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        load_studies(study_tree)


@pytest.mark.parametrize("edit,match", [
    (lambda d: d.update(format="wrong"), "format"),
    (lambda d: d.update(manifest_hash="not-a-hash"), "SHA-256"),
    (lambda d: d.update(source_git_head="main"), "Git"),
    (lambda d: d["scope"].update(quality_claims=True), "scope"),
    (lambda d: d["scope"].update(maximum_boundaries_verified=True), "scope"),
    (lambda d: d["scope"].update(cut_timestamp="2026-10-09T18:00:00-07:00"), "UTC"),
    (lambda d: d["denominators"].pop("failed"), "denominators"),
    (lambda d: d["phase_counts"]["quality"].update(planned=2), "denominator"),
    (lambda d: d["phase_counts"]["quality"].update(unattempted=0, failed=1), "denominator|cut"),
    (lambda d: d["datasets"][1].update(index=0), "indices"),
    (lambda d: d["datasets"][1].update(id="banking77"), "identities"),
    (lambda d: d.update(actual_transport_attempts=True), "integer"),
    (lambda d: d["attempt_receipts"][1]["receipt"].update(attempt_id="fixture-attempt-0"), "unique"),
    (lambda d: d["attempt_receipts"][0].update(extra="private"), "wrapper"),
    (lambda d: d["attempt_receipts"][0].update(dataset_index=2), "dataset"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(endpoint="https://openrouter.ai/api/v1/chat/completions"), "Decisions"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(endpoint="https://secret@openrouter.ai/api/alpha/decisions"), "Decisions"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(elapsed_s=float("inf")), "finite"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(input_tokens=-1), "integer"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(output_tokens=True), "integer"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(input_tokens=None), "usage"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(status_code=True), "HTTP"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(timestamp="2026-10-09T18:02:00+00:00"), "cut"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(cost_usd="-0.01"), "USD"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(cost_status="estimated"), "provenance"),
    (lambda d: d["attempt_receipts"][0]["receipt"]["response_diagnostics"].update(body_complete=False), "diagnostics|custody"),
    (lambda d: d["accounting"].update(reported_cost_usd="0"), "billing total"),
    (lambda d: d["accounting"].update(limit_usd=25), "decimal strings"),
    (lambda d: d["accounting"].update(unresolved_attempts=["not-an-attempt"]), "stopped"),
    (lambda d: d["historical_bounded_unknown"].update(charge_status="reported"), "UNKNOWN"),
    (lambda d: d["historical_bounded_unknown"].update(original_attempt_ids=["fixture-attempt-0"]), "separate"),
    (lambda d: d["capability_probes"].append(d["capability_probes"][0]), "denominator"),
    (lambda d: d["capability_probes"][0].update(cell_id="f" * 64), "matching"),
    (lambda d: d["capability_probes"][0]["evidence"].update(empirical_success=False), "scope/status"),
    (lambda d: d["capability_probes"][0]["evidence"].update(primitives=["chat"]), "vocabulary"),
    (lambda d: d["capability_probes"][0]["evidence"].update(options_per_question={"decision": 76}), "complete dataset"),
    (lambda d: d.update(accuracy=1), "quality metrics"),
    (lambda d: d["evidence"]["manifest"].update(metrics={"accuracy": 1}), "quality metrics"),
    (lambda d: d["evidence"]["manifest"].update(path="../private-manifest.json"), "public relative"),
    (lambda d: d["evidence"]["manifest"].update(path=".benchmarks/private.json"), "public relative"),
    (lambda d: d.pop("completed_quality_predictions"), "incomplete"),
])
def test_native_summary_rejects_inconsistent_or_fabricated_evidence(edit, match: str) -> None:
    value = native_summary()
    edit(value)
    with pytest.raises(ValueError, match=match):
        validate_native_hosted_summary(value)


def test_native_currency_sum_is_independent_of_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 1
        context.Emax = 0
        assert validate_native_hosted_summary(native_summary())["accounting"]["reported_cost_usd"] == "0.000000005"


def quality_summary() -> dict:
    value = native_summary()
    value["scope"]["through_phase"] = "quality"
    value["denominators"].update(completed=3, unattempted=1)
    value["phase_counts"]["quality"].update(completed=1, unattempted=0)
    wrapper = deepcopy(value["attempt_receipts"][0])
    wrapper.update(cell_id="f" * 64, phase="quality")
    wrapper["receipt"].update(attempt_id="fixture-quality-attempt")
    value["attempt_receipts"].append(wrapper)
    value["actual_transport_attempts"] = 3
    value["accounting"]["reported_cost_usd"] = "0.000000007"
    probabilities = {"a": .66, "b": .33, **{f"option-{i}": 0. for i in range(75)}}
    value["completed_quality_predictions"] = [{"cell_id": "f" * 64, "dataset_index": 0,
                                                "example_id": "fixture-quality-example",
                                                "predictions": {"decision": {"type": "choice", "value": "a",
                                                    "probabilities": probabilities,
                                                    "probability_rounding_digits": 2,
                                                    "probability_source": "native", "confidence": .66,
                                                    "confidence_semantics": "provider_defined"}}}]
    return value


def test_native_completed_outputs_retain_rounding_and_do_not_create_metrics(study_tree: Path) -> None:
    value = quality_summary()
    validate_native_hosted_summary(value)
    select_native(study_tree, value)
    studies = load_studies(study_tree)
    assert studies.tokens()["NATIVE_HOSTED_QUALITY_COMPLETED"] == "1"
    assert studies.native_hosted["completed_quality_predictions"][0]["predictions"]["decision"]["probabilities"] == value["completed_quality_predictions"][0]["predictions"]["decision"]["probabilities"]
    assert not any("ACCURACY" in k for k in studies.tokens() if k.startswith("NATIVE_HOSTED_"))


@pytest.mark.parametrize("edit,match", [
    (lambda d: d["completed_quality_predictions"][0].update(predictions={}), "retained outputs"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"].update(type="chat"), "primitive"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"].update(confidence=float("inf")), "finite"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"].update(probabilities={}), "vocabulary"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"].update(probabilities={"a": .2, "b": .2}), "vocabulary"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"].update(probabilities={"a": -1, "b": 2}), "finite"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"].update(value="missing"), "vocabulary"),
    (lambda d: d["completed_quality_predictions"][0]["predictions"]["decision"]["probabilities"].update(a=0, b=0), "sum"),
    (lambda d: d["scope"].update(through_phase="capability_probe"), "cut"),
    (lambda d: d["completed_quality_predictions"][0].update(cell_id="a" * 64), "unique"),
])
def test_native_completed_outputs_fail_closed(edit, match: str) -> None:
    value = quality_summary()
    edit(value)
    with pytest.raises(ValueError, match=match):
        validate_native_hosted_summary(value)


def test_native_retries_count_physical_attempts_and_reject_terminal_failure() -> None:
    value = native_summary()
    retry = deepcopy(value["attempt_receipts"][0])
    retry["receipt"].update(attempt_id="fixture-retry", timestamp="2026-10-09T18:00:02+00:00")
    original = value["attempt_receipts"][0]["receipt"]
    original.update(status_code=503, error="BackendHTTPError")
    value["attempt_receipts"].append(retry)
    value["actual_transport_attempts"] = 3
    value["accounting"]["reported_cost_usd"] = "0.000000007"
    validate_native_hosted_summary(value)
    retry["receipt"].update(status_code=503, error="BackendHTTPError")
    with pytest.raises(ValueError, match="matching successful receipt"):
        validate_native_hosted_summary(value)
    retry["receipt"].update(timestamp="2026-10-09T17:59:00+00:00")
    with pytest.raises(ValueError, match="attempt order"):
        validate_native_hosted_summary(value)
    retry.update(dataset_index=1)
    with pytest.raises(ValueError, match="changed cell identity"):
        validate_native_hosted_summary(value)


def test_native_retains_reported_overrun_with_stopped_admission() -> None:
    value = native_summary()
    value["accounting"]["limit_usd"] = "0.000000001"
    with pytest.raises(ValueError, match="liability"):
        validate_native_hosted_summary(value)
    value["accounting"]["admission_stopped"] = True
    assert validate_native_hosted_summary(value)["accounting"]["reported_cost_usd"] == "0.000000005"


@pytest.mark.parametrize("edit", [
    lambda d: d.update(phase_counts={}),
    lambda d: d["phase_counts"]["graphical"].pop("failed"),
    lambda d: d.update(datasets=[]),
    lambda d: d["attempt_receipts"][0].update(phase="warm_repeat"),
    lambda d: d["scope"].update(cut_timestamp="invalid"),
    lambda d: d.update(evidence=[]),
    lambda d: d.update(evidence={"manifest": "private"}),
    lambda d: d["historical_bounded_unknown"].update(original_attempt_ids=[], held_upper_bound_usd="1"),
    lambda d: d["historical_bounded_unknown"].update(held_upper_bound_usd=0),
    lambda d: d["capability_probes"][0].update(status="unattempted"),
    lambda d: d["capability_probes"][1].update(cell_id="a" * 64),
    lambda d: d["capability_probes"].pop(),
])
def test_native_incomplete_cut_and_provenance_are_not_publication_evidence(edit) -> None:
    value = native_summary()
    edit(value)
    with pytest.raises(ValueError):
        validate_native_hosted_summary(value)


@pytest.mark.parametrize("edit,match", [
    (lambda d: d["attempt_receipts"][0]["receipt"].update(requested_model="sk-or-public-fixture-only"), "private material"),
    (lambda d: d["datasets"][0].update(id="/Users/private-fixture/person"), "private material"),
    (lambda d: d["datasets"][0].update(id="/var/custom-private-fixture"), "private material"),
    (lambda d: d["datasets"][0].update(id="C:\\custom-private-fixture"), "private material"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(headers={"Authorization": "synthetic-private-fixture"}), "credential/header"),
    (lambda d: d["evidence"]["manifest"].update(note="Bearer synthetic-private-fixture"), "private material"),
    (lambda d: d["evidence"]["manifest"].update(**{"Access-Token": "synthetic-private-fixture"}), "credential/header"),
    (lambda d: d["attempt_receipts"][0]["receipt"].update(unrecognized=1), "CallReceipt"),
    (lambda d: d["attempt_receipts"][0]["receipt"]["response_diagnostics"].update(body_limit_bytes=10**30, body_bytes_observed=10**20), "bounded HTTP"),
    (lambda d: d["attempt_receipts"][0]["receipt"]["response_diagnostics"].update(extra=1), "complete SDK"),
    (lambda d: d["capability_probes"][0].update(attempts=999), "attempt denominator"),
    (lambda d: d["capability_probes"][0].update(dataset_id="other-dataset"), "dataset identity"),
    (lambda d: d["capability_probes"][0].update(dataset="other-family"), "dataset family"),
    (lambda d: d["accounting"].update(reserved_usd="1"), "reserved balance"),
    (lambda d: d["accounting"].update(extra=1), "accounting schema"),
    (lambda d: d["scope"].update(extra=1), "scope"),
    (lambda d: d["datasets"][0].update(extra=1), "identity fields"),
    (lambda d: d.update(extra=1), "summary fields"),
])
def test_independent_review_regressions_fail_before_figure_output(study_tree: Path, tmp_path: Path, edit, match: str) -> None:
    from daf_jev.figures import generate_native_capabilities, write_figure_registry
    value = native_summary()
    edit(value)
    select_native(study_tree, value)
    output = tmp_path / "refused-native-figure"
    with pytest.raises(ValueError, match=match):
        generate_native_capabilities(output, study_tree)
    assert not output.exists()
    with pytest.raises(ValueError, match=match):
        write_figure_registry(output, study_tree, include_study=True)
    assert not (output / "figure_registry.json").exists()


def test_decoded_privacy_screen_handles_json_unicode_escapes(study_tree: Path) -> None:
    value = native_summary()
    value["datasets"][0]["id"] = "/Users/private-fixture/person"
    select_native(study_tree, value)
    selection_path = study_tree / "manuscript/evidence.json"
    selection = json.loads(selection_path.read_bytes())
    entry = selection["study_summaries"]["native_hosted"]
    path = study_tree / entry["path"]
    encoded = path.read_text().replace("/Users/", "\\u002fUsers\\u002f")
    path.write_text(encoded)
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    selection_path.write_text(json.dumps(selection))
    with pytest.raises(ValueError, match="private material"):
        selected_native_study(study_tree)


def test_probe_annotation_counts_match_physical_retries() -> None:
    value = native_summary()
    for row in value["capability_probes"]:
        row.update(attempts=1, dataset=value["datasets"][row["dataset_index"]]["name"],
                   dataset_id=value["datasets"][row["dataset_index"]]["id"],
                   prepared_dataset_sha256="c" * 64, backend="fixture-native-backend", reason=None)
    validate_native_hosted_summary(value)
    retry = deepcopy(value["attempt_receipts"][0])
    retry["receipt"].update(attempt_id="fixture-retry", timestamp="2026-10-09T18:00:02+00:00")
    value["attempt_receipts"].append(retry)
    value["actual_transport_attempts"] = 3
    value["accounting"]["reported_cost_usd"] = "0.000000007"
    with pytest.raises(ValueError, match="attempt denominator"):
        validate_native_hosted_summary(value)
    value["capability_probes"][0]["attempts"] = 2
    validate_native_hosted_summary(value)


def test_native_noul_and_unsupported_fixture_has_no_invented_charge(study_tree: Path, tmp_path: Path) -> None:
    from daf_jev.figures import generate_native_capabilities
    value = native_summary()
    value["datasets"][1].update(id="synthetic-binary-v3", family="synthetic-binary")
    probe = value["capability_probes"][1]
    probe["status"] = "unsupported"
    probe["evidence"].update(empirical_success=False, primitives=["noul"], options_per_question={})
    value["attempt_receipts"].pop()
    value["actual_transport_attempts"] = 1
    value["accounting"]["reported_cost_usd"] = "0.000000002"
    value["denominators"].update(completed=1, unsupported=1)
    value["phase_counts"]["capability_probe"].update(completed=1, unsupported=1)
    select_native(study_tree, value)
    path = generate_native_capabilities(tmp_path / "unsupported", study_tree)
    row = json.loads(path.with_suffix(".data.json").read_bytes())["rows"][1]
    assert row["http_elapsed_s_sum"] is None and row["reported_cost_usd"] is None
    assert row["options_per_question"] == {} and "scalar probability" in row["label"]


def test_native_unknown_failure_is_retained_and_stops_admission(study_tree: Path, tmp_path: Path) -> None:
    value = native_summary()
    receipt = value["attempt_receipts"][1]["receipt"]
    receipt.update(status_code=404, error="BackendHTTPError", cost_status="unknown", cost_usd=None,
                   input_tokens=None, output_tokens=None, response_diagnostics=None)
    value["capability_probes"][1]["status"] = "failed"
    value["capability_probes"][1]["evidence"]["empirical_success"] = False
    value["denominators"].update(completed=1, failed=1)
    value["phase_counts"]["capability_probe"].update(completed=1, failed=1)
    value["accounting"].update(reported_cost_usd="0.000000002", unresolved_attempts=[receipt["attempt_id"]],
                               admission_stopped=True)
    validate_native_hosted_summary(value)
    select_native(study_tree, value)
    from daf_jev.figures import generate_native_capabilities
    path = generate_native_capabilities(tmp_path / "unknown", study_tree)
    rows = json.loads(path.with_suffix(".data.json").read_bytes())["rows"]
    assert rows[1]["reported_cost_usd"] is None and rows[1]["cost_status"] == "unknown"
    value["accounting"]["admission_stopped"] = False
    with pytest.raises(ValueError, match="stopped"):
        validate_native_hosted_summary(value)


def test_native_figure_is_explicit_reproducible_and_receipt_bound(study_tree: Path, tmp_path: Path) -> None:
    import matplotlib.pyplot as plt

    from daf_jev.figures import (
        generate_native_capabilities,
        generate_one,
        write_figure_registry,
    )
    from daf_jev.study_figures import FILENAMES
    with pytest.raises(ValueError, match="missing selected"):
        generate_native_capabilities(tmp_path / "absent", study_tree)
    sha = select_native(study_tree, native_summary())
    first = generate_native_capabilities(tmp_path / "native-a", study_tree)
    with plt.rc_context({"font.family": "DejaVu Sans Mono", "font.size": 25, "axes.facecolor": "red"}):
        second = generate_one("native_capabilities", tmp_path / "native-b", study_tree, include_study=True)
    for suffix in (".png", ".pdf", ".data.json"):
        assert first.with_suffix(suffix).read_bytes() == second.with_suffix(suffix).read_bytes()
    data = json.loads(first.with_suffix(".data.json").read_bytes())
    assert data["selected_input_sha256"] == {"native_hosted": sha}
    assert data["scope"]["maximum_boundaries_verified"] is False
    assert data["scope"]["quality_claims"] is False
    assert data["rows"][1]["http_elapsed_s_sum"] == 1.25
    assert data["rows"][0]["options_per_question"] == {"decision": 77}
    assert data["rows"][0]["reported_cost_usd"] == "2E-9"
    assert len(PdfReader(first.with_suffix(".pdf")).pages) == 1
    legacy = json.loads(write_figure_registry(tmp_path / "legacy", study_tree).read_bytes())
    assert "fig:native_capabilities" not in legacy
    registry = json.loads(write_figure_registry(tmp_path / "native-registry", study_tree, include_study=True).read_bytes())
    assert len(registry) == len(legacy) + len(FILENAMES) + 1
    provenance = registry["fig:native_capabilities"]["metadata"]["native_provenance"]
    assert provenance["selected_input_sha256"] == {"native_hosted": sha}
    assert provenance["journal_hash"] == "2" * 64
    assert selected_native_study(study_tree)[1] == sha
