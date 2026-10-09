"""Selected retained summaries: identity, denominators, and figure regeneration."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from daf_jev.evidence import has_study_selection, selected_study_bytes
from daf_jev.study_evidence import interval, load_studies, number

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def study_tree(tmp_path: Path) -> Path:
    """Relocate real retained public inputs; never depend on newest filenames."""
    source = ROOT
    selection = json.loads((source / "manuscript/evidence.json").read_bytes())
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
    p = tmp_path / "manuscript/evidence.json"
    p.parent.mkdir()
    p.write_text('{"format":"dafjev.publication-evidence/1"}')
    assert not has_study_selection(tmp_path)
    p.write_text('{"format":"dafjev.publication-evidence/1","study_summaries":[]}')
    assert has_study_selection(tmp_path)
    with pytest.raises(ValueError, match="object"):
        selected_study_bytes(tmp_path, "cpu")


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


def test_extended_registry_preserves_legacy_default(tmp_path: Path) -> None:
    from daf_jev.figures import write_figure_registry
    from daf_jev.study_figures import FILENAMES
    legacy = json.loads(write_figure_registry(tmp_path / "old").read_bytes())
    extended = json.loads(write_figure_registry(tmp_path / "new", include_study=True).read_bytes())
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
