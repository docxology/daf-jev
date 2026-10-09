"""Evidence-selected empirical manuscript figures (optional matplotlib extra)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes

from .study_evidence import (
    StudyEvidence,
    count,
    interval,
    load_studies,
    number,
    statuses,
)

FILENAMES = {name: f"{name}.png" for name in (
    "cpu_quality", "wine_ordinal", "cohort_sensitivity", "validation_folds",
    "selective_validation", "execution_coverage")}
# Freeze the complete plotting context so standalone/full entry points do not
# inherit a caller's theme. The runtime revision remains bound by uv.lock.
_STYLE = {**matplotlib.rcParamsDefault, "backend": "Agg", "font.family": "DejaVu Sans",
          "font.size": 10, "axes.labelsize": 10, "xtick.labelsize": 9,
          "ytick.labelsize": 10, "pdf.fonttype": 42}
BLUE, ORANGE, GREY = "#0072B2", "#D55E00", "#6B7280"
BACKENDS = {"prior": "Training prior", "tfidf-logistic-C1": "TF-IDF + logistic (C=1)",
            "wine-hist-gradient-boosting": "Histogram gradient boosting"}
DATASETS = {"banking77": "BANKING77", "clinc150": "CLINC150 + OOS", "wine": "Wine ordinal bins"}

CAPTIONS = {
    "cpu_quality": "Canonical test accuracy for applicable CPU comparators. Whiskers are retained 95% grouped bootstrap intervals for fixed predictions; they exclude refitting uncertainty. Wine accuracy uses probability argmax over bins. Unsupported comparator/task pairs supply no plotted estimate.",
    "wine_ordinal": "Wine errors use raw scalar bin indices, not original grades. MAE has a retained grouped bootstrap interval; RMSE is a point estimate. Bin support and conditional grade entropy disclose sparse extremes and information lost through binning.",
    "cohort_sensitivity": "Canonical and leakage-filtered text results use separately refitted models and different test cohorts. Connecting lines are descriptive, without paired or causal change intervals; denominators are shown for each cohort.",
    "validation_folds": "BANKING77 validation accuracy across five overlapping training fits. Pooled out-of-fold intervals resample input groups for fixed predictions and do not measure shared-training or refitting uncertainty.",
    "selective_validation": "Descriptive validation gates show eligible group coverage, observed error and the recorded Wilson upper error bound. Threshold selection is adaptive: these are not simultaneous guarantees and are not transferred to final refits. Ineligible gates have zero coverage and unavailable risk.",
    "execution_coverage": "Status fractions preserve each distinct study denominator. CPU studies, the older partial native study and the hosted pilot have different cohorts and source identities. The full hosted proposal is unexecuted. Completion counts include capability work and cannot be read as quality sample counts.",
}


def metadata() -> tuple[dict[str, str], ...]:
    return tuple({"label": f"fig:{name}", "filename": filename, "section": "Results",
                  "width": "1.0\\textwidth", "caption": CAPTIONS[name],
                  "alt_text": CAPTIONS[name]} for name, filename in FILENAMES.items())


def _axes(ax: Axes, title: str, xlabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, weight="bold", pad=14)
    ax.set_xlabel(xlabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.7)
    ax.set_axisbelow(True)


def _error(ax: Axes, x: float, y: float, limits: tuple[float, float], **kwargs: Any) -> None:
    # Percentile intervals need not contain the point estimate. Draw the
    # retained endpoints independently instead of clipping or moving either.
    midpoint = (limits[0] + limits[1]) / 2
    ax.errorbar(midpoint, y, xerr=[[midpoint - limits[0]], [limits[1] - midpoint]],
                fmt="none", capsize=3, linewidth=1.5, color=kwargs.get("color"))
    ax.plot([x], [y], kwargs.pop("fmt", "o"), markersize=6, **kwargs)


def _quality(s: StudyEvidence) -> tuple[plt.Figure, dict[str, Any]]:
    fig, axs = plt.subplots(1, 3, figsize=(11, 4.5), constrained_layout=True)
    data = []
    for ax, dataset, comparator in zip(axs, DATASETS, (
            "tfidf-logistic-C1", "tfidf-logistic-C1", "wine-hist-gradient-boosting"), strict=True):
        for y, backend, color in ((1, comparator, BLUE), (0, "prior", ORANGE)):
            row = s.arm(dataset, backend)
            value, limits = s.metric(row, "accuracy"), s.limits(row, "accuracy")
            _error(ax, value, y, limits, fmt="o", color=color)
            ax.text(value, y + .18, f"{value:.1%}", ha="center", color=color)
            data.append({"dataset": dataset, "backend": backend, "accuracy": value,
                         "interval": limits, "n": row["metrics"]["n_hard_targets"]})
        ax.set_yticks([0, 1], ["Prior", "Supervised"])
        ax.set_ylim(-.5, 1.55)
        ax.set_xlim(0, 1)
        ax.text(.04, .96, f"n = {data[-1]['n']:,}", transform=ax.transAxes, va="top", fontsize=9)
        _axes(ax, DATASETS[dataset], "Accuracy (fraction)")
    return fig, {"rows": data, "scope": CAPTIONS["cpu_quality"]}


def _wine(s: StudyEvidence) -> tuple[plt.Figure, dict[str, Any]]:
    fig, (ax, support) = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    rows = []
    for y, backend, color in ((1, "wine-hist-gradient-boosting", BLUE), (0, "prior", ORANGE)):
        row = s.arm("wine", backend)
        mae, rmse, limits = s.metric(row, "ordinal_mae"), s.metric(row, "ordinal_rmse"), s.limits(row, "ordinal_mae")
        _error(ax, mae, y + .08, limits, fmt="o", color=color, label="MAE + 95% interval" if y == 1 else None)
        ax.scatter([rmse], [y - .08], marker="D", color=color, s=34, label="RMSE (point)" if y == 1 else None)
        ax.text(mae, y + .25, f"MAE {mae:.3f}", ha="center", fontsize=10, color=color)
        rows.append({"backend": backend, "mae": mae, "mae_interval": limits, "rmse": rmse})
    ax.set_yticks([0, 1], ["Prior", "Supervised"])
    ax.set_ylim(-.55, 1.55)
    ax.set_xlim(0, .65)
    _axes(ax, "a  Scalar ordinal error", "Error in bin-index units (lower is better)")
    ax.legend(loc="lower right", fontsize=9)
    audits = [r for r in s.cpu["dataset_audits"] if r["dataset"] == "wine" and r["job"] == "official-final-train"]
    if len(audits) != 1:
        raise ValueError("wine audit must be unique")
    b = audits[0]["selected"]["wine_binning"]
    counts = [count(b["bins"][str(i)]["n"]) for i in range(5)]
    if sum(counts) != count(b["n"]):
        raise ValueError("wine bin denominator mismatch")
    loss = number(b["conditional_grade_entropy_bits"])
    bars = support.barh(range(5), counts, color=BLUE, height=.6)
    for bar, n in zip(bars, counts, strict=True):
        support.text(n + 16, bar.get_y() + bar.get_height() / 2, f"{n:,}", va="center", fontsize=10)
    support.set_yticks(range(5), ["0: grades 0-2", "1: grades 3-4", "2: grades 5-6", "3: grades 7-8", "4: grades 9-10"])
    support.invert_yaxis()
    support.set_xlim(0, max(counts) * 1.18)
    _axes(support, "b  Canonical test support", "Records in each declared bin")
    support.text(.98, .06, f"H(grade | bin) = {loss:.3f} bits", ha="right", transform=support.transAxes, fontsize=10)
    return fig, {"rows": rows, "bin_counts": counts, "lost_grade_information_bits": loss, "scope": CAPTIONS["wine_ordinal"]}


def _sensitivity(s: StudyEvidence) -> tuple[plt.Figure, dict[str, Any]]:
    fig, axs = plt.subplots(1, 2, figsize=(11, 5), constrained_layout=True)
    rows = []
    identities = [(d, b) for d in ("banking77", "clinc150") for b in ("tfidf-logistic-C1", "prior")]
    for y, (dataset, backend) in enumerate(identities):
        old, clean = s.arm(dataset, backend), s.arm(dataset, backend, job="official-final-clean")
        n = [count(r["metrics"]["n_hard_targets"]) for r in (old, clean)]
        data = {"dataset": dataset, "backend": backend, "canonical_n": n[0], "filtered_n": n[1]}
        for ax, metric in zip(axs, ("accuracy", "brier"), strict=True):
            values = [s.metric(r, metric) for r in (old, clean)]
            ax.plot(values, [y, y], color=GREY, linewidth=1.3)
            for value, color, marker, label in zip(values, (BLUE, ORANGE), ("o", "s"),
                     ("Canonical", "Filtered + refitted"), strict=True):
                ax.scatter(value, y, c=color, marker=marker, s=38, label=label if y == 0 else None)
            data[metric] = values
            delta = values[1] - values[0]
            annotation = f"Δ {100 * delta:+.3f} pp" if metric == "accuracy" else f"Δ {delta:+.4f}"
            ax.text(max(values) + (.045 if metric == "accuracy" else .09), y,
                    annotation, va="center", fontsize=9)
        rows.append(data)
    labels = [f"{DATASETS[d]} / {'logistic' if b != 'prior' else 'prior'}\nn: {r['canonical_n']:,} → {r['filtered_n']:,}"
              for (d, b), r in zip(identities, rows, strict=True)]
    for ax, title, xlabel in zip(axs, ("a  Hard-label quality", "b  Distribution quality"),
                              ("Accuracy (higher is better)", "Multiclass Brier (lower is better)"), strict=True):
        ax.set_yticks(range(4), labels)
        ax.invert_yaxis()
        _axes(ax, title, xlabel)
        ax.set_xlim(0, 1 if ax is axs[0] else 2)
    fig.legend(*axs[0].get_legend_handles_labels(), loc="outside lower center", ncols=2, fontsize=9)
    return fig, {"rows": rows, "scope": CAPTIONS["cohort_sensitivity"]}


def _folds(s: StudyEvidence) -> tuple[plt.Figure, dict[str, Any]]:
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    rows = []
    for ax, backend, color in zip(axs, ("tfidf-logistic-C1", "prior"), (BLUE, ORANGE), strict=True):
        values = []
        for i in range(5):
            row = s.arm("banking77", backend, job=f"banking77-selection-fold{i}", split="validation")
            value = s.metric(row, "accuracy")
            values.append(value)
            ax.scatter(value, i, color=color, s=36)
        pooled = [r for r in s.cpu["banking77_fivefold_oof"] if r["backend"] == backend]
        if len(pooled) != 1:
            raise ValueError("pooled OOF comparator must be unique")
        value = number(pooled[0]["accuracy"], upper=1)
        limits = interval(pooled[0]["grouped_interval"], value, upper=1,
                          max_groups=count(pooled[0]["input_groups"]))
        _error(ax, value, 6, limits, fmt="D", color=color)
        ax.axhline(5, color="#D1D5DB", linewidth=.8)
        ax.set_yticks([0, 1, 2, 3, 4, 6], ["Fold 1", "Fold 2", "Fold 3", "Fold 4", "Fold 5", "Pooled OOF"])
        ax.invert_yaxis()
        _axes(ax, BACKENDS[backend], "Validation accuracy (fraction)")
        # Separate, visibly labelled scales retain the low-accuracy prior contrast.
        ax.set_xlim(.8, .91) if backend != "prior" else ax.set_xlim(0, .04)
        rows.append({"backend": backend, "fold_accuracy": values, "pooled_accuracy": value, "pooled_interval": limits})
    return fig, {"rows": rows, "scope": CAPTIONS["validation_folds"]}


def _gates(s: StudyEvidence) -> tuple[plt.Figure, dict[str, Any]]:
    records = sorted(s.gates(), key=lambda r: (r["job"], r["dataset_id"], r["backend"]))
    fig, (coverage, risk) = plt.subplots(1, 2, figsize=(11, max(5.4, .35 * len(records))),
                                       sharey=True, constrained_layout=True, gridspec_kw={"width_ratios": [1.6, 1]})
    rows, labels = [], []
    for y, r in enumerate(records):
        c = r["calibration"]
        accepted, total, errors = (count(c[k]) for k in ("n_groups", "validation_groups", "n_errors"))
        fraction = accepted / total
        label = r["dataset_id"].replace("banking77-selection-", "BANK ").replace("banking77-", "BANK ").replace("clinc150", "CLINC").replace("wine", "Wine")
        labels.append(f"{label} / {'prior' if r['backend'] == 'prior' else 'supervised'}")
        coverage.barh(y, fraction, color=BLUE, height=.6)
        coverage.text(fraction + .015, y, f"{accepted:,}/{total:,}", va="center", fontsize=8)
        observed = errors / accepted if accepted else None
        upper = c["wilson_upper"]
        if observed is None:
            risk.text(.003, y, "unavailable", va="center", fontsize=8, color=GREY)
        else:
            risk.plot([observed, upper], [y, y], color=GREY)
            risk.scatter(observed, y, color=BLUE, marker="o", s=28)
            risk.scatter(upper, y, color=ORANGE, marker="|", s=100)
        rows.append({"job": r["job"], "dataset_id": r["dataset_id"], "backend": r["backend"],
                     "eligible_coverage": fraction, "observed_error": observed, "wilson_upper": upper})
    coverage.set_yticks(range(len(records)), labels, fontsize=8)
    coverage.invert_yaxis()
    coverage.set_xlim(0, 1)
    risk.set_xlim(0, .065)
    risk.axvline(.05, color=GREY, linestyle="--", linewidth=1)
    _axes(coverage, "a  Eligible validation groups", "Group coverage (fraction)")
    _axes(risk, "b  Recorded error bounds", "Error fraction / Wilson upper")
    risk.plot([], [], "o", color=BLUE, label="Observed")
    risk.plot([], [], "|", color=ORANGE, label="Wilson upper")
    risk.legend(loc="upper center", bbox_to_anchor=(.5, -.12), ncols=2, fontsize=8)
    return fig, {"rows": rows, "scope": CAPTIONS["selective_validation"]}


def _execution(s: StudyEvidence) -> tuple[plt.Figure, dict[str, Any]]:
    fig, ax = plt.subplots(figsize=(11, 4.5), constrained_layout=True)
    h = s.hosted["hosted_pilot"]
    rows = [
        ("CPU baselines", {"planned_cells": s.cpu["planned_cells"], **s.cpu["status_counts"]}, False),
        ("Older native study", s.hosted["historical_native_study"], False),
        ("Hosted pilot", h, True),
    ]
    colors = (BLUE, "#A7B4C4", ORANGE, "#CC79A7", "#F3F4F6")
    collected = []
    for y, (label, r, nested) in enumerate(rows):
        counts = statuses(r, nested=nested)
        n, left = count(r["planned_cells"]), 0.0
        for (status, total), color in zip(counts.items(), colors, strict=True):
            width = total / n
            ax.barh(y, width, left=left, color=color, edgecolor="#374151", linewidth=.5,
                    label=status.title() if y == 0 else None)
            left += width
        text = " / ".join(f"{k}: {v:,}" for k, v in counts.items() if v)
        ax.text(0, y + .39, text, fontsize=8, va="top")
        collected.append({"cohort": label, "planned_cells": n, "counts": counts})
    proposed = count(s.hosted["full_study_obligations"]["full_proposed_cells"])
    ax.barh(3, 1, color="white", edgecolor=GREY, hatch="////", height=.65)
    ax.text(.5, 3, f"PROPOSED: {proposed:,} cells; no full-study execution", ha="center", va="center", fontsize=10)
    ax.set_yticks(range(4), [f"{r[0]}\nn = {r[1]['planned_cells']:,}" for r in rows] + ["Full hosted proposal"])
    ax.set_ylim(3.65, -.6)
    ax.set_xlim(0, 1)
    _axes(ax, "Distinct cohorts and retained execution status", "Within-cohort planned-cell fraction")
    ax.legend(loc="upper center", bbox_to_anchor=(.5, -.18), ncols=5, fontsize=9)
    return fig, {"rows": collected, "full_hosted_proposed_cells": proposed, "scope": CAPTIONS["execution_coverage"]}


_GENERATORS = dict(zip(FILENAMES, (_quality, _wine, _sensitivity, _folds, _gates, _execution), strict=True))


def generate(name: str, out_dir: Path, project_root: Path) -> Path:
    if name not in _GENERATORS:
        raise ValueError("unknown study figure")
    selected = load_studies(project_root)
    with plt.rc_context(_STYLE):
        fig, data = _GENERATORS[name](selected)
        return _write(fig, name, out_dir, selected.hashes, data)


def _write(fig: plt.Figure, name: str, out_dir: Path, hashes: dict[str, str], data: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    try:
        fig.savefig(path, dpi=220, facecolor="white", metadata={"Software": "daf-jev"})
        fig.savefig(path.with_suffix(".pdf"), facecolor="white",
                    metadata={"Creator": "daf-jev", "CreationDate": None, "ModDate": None})
        payload = {"format": "dafjev.study-figure-data/1", "figure": name,
                   "selected_input_sha256": hashes, **data}
        path.with_suffix(".data.json").write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    finally:
        plt.close(fig)
    return path



def generate_overview(out_dir: Path, project_root: Path) -> Path:
    """Expanded manuscript cover: interfaces and the separate evidence tiers."""
    s = load_studies(project_root)
    specs = [
        ("a  Define the comparison", BLUE, [
            "Independent targets\nPublic labels • rules • exact Bayes nets",
            "Frozen design\nSplits • model profiles • options • policy",
            "Typed request\nState + questions + execution settings",
        ]),
        ("b  Execute declared lanes", ORANGE, [
            "Admission + scheduling\nBudget • clock • timeout • cancellation",
            "Backend interface\nCPU • local native/chat • hosted native/chat",
            "Validated result + attempt receipt\nPredictions • meaning • usage • failures",
        ]),
        ("c  Retain distinct evidence", GREY, [
            f"CPU comparator studies\n{s.cpu['status_counts']['completed']:,} completed cells / {s.cpu['planned_cells']:,}",
            f"Older partial native study\n{s.hosted['historical_native_study']['completed']:,} / {s.hosted['historical_native_study']['planned_cells']:,} cells completed",
            f"Hosted pilot\n{s.hosted['hosted_pilot']['actual_transport_attempts']} transport attempt(s); {s.hosted['hosted_pilot']['completed_quality_predictions']} quality predictions\n{len(s.hosted['hosted_pilot']['accounting']['unresolved_attempts'])} billing unresolved",
        ]),
    ]
    with plt.rc_context(_STYLE):
        fig, axes = plt.subplots(1, 3, figsize=(11, 4.4))
        fig.subplots_adjust(left=.025, right=.975, top=.78, bottom=.07, wspace=.28)
        fig.suptitle("Modular decisions: independent targets, explicit execution, retained evidence",
                     fontsize=14, weight="bold", y=.96)

        for ax, (title, color, texts) in zip(axes, specs, strict=True):
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.set_axis_off()
            ax.set_title(title, loc="left", fontsize=12, color=color, weight="bold", pad=16)
            for i, text in enumerate(texts):
                y = .82 - .32 * i
                ax.text(.5, y, text, ha="center", va="center", fontsize=9.3, linespacing=1.65,
                        bbox={"boxstyle": "round,pad=.7", "facecolor": "#F3F4F6", "edgecolor": color, "linewidth": 1.3})
                if i < 2 and ax is not axes[2]:
                    ax.annotate("", xy=(.5, y - .23), xytext=(.5, y - .13),
                                arrowprops={"arrowstyle": "->", "color": color, "linewidth": 1.3})
        fig.text(.5, .025, "Completion includes capability work. Cohorts and source identities differ; the full comparative study remains unfinished.",
                 ha="center", fontsize=9, color=GREY)
        data = {"panels": [texts for _, _, texts in specs],
                "scope": "Schematic workflow and separate retained execution counts; no comparable model-quality or billing conclusion."}
        return _write(fig, "graphical_abstract", out_dir, s.hashes, data)
