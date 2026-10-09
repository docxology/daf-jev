"""Standalone offline Markdown/PDF reports bound to selected run evidence."""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from daf_jev.decision_backends import canonical_json


def _display(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _dataset_id(item: dict[str, Any]) -> str:
    """Legacy reports retained only the dataset family name."""
    return str(item.get("dataset_id", item["dataset"]))


def _cohort_key(item: dict[str, Any]) -> tuple[str, ...]:
    return (item["dataset"], _dataset_id(item), str(item.get("dataset_index", "")),
            item["backend"], item["split"], item["phase"])


def _dataset_label(item: dict[str, Any]) -> str:
    return f"{_display(item['dataset'])} (ID {_display(_dataset_id(item))}, index {_display(item.get('dataset_index'))})"


def markdown_report(report: dict[str, Any]) -> str:
    if report.get("format") != "dafjev.benchmark-report/1":
        raise ValueError("expected an evidence-bound benchmark report")
    lines = ["# Decision-model benchmark", "",
        f"Manifest SHA256: `{report['manifest_hash']}`. Journal SHA256: `{report['journal_hash']}`.", "",
        f"Status: **{report['status']}**. Planned cells: {report['planned_cells']}.", "",
        "Cell denominators: " + canonical_json(report["denominators"]), "",
        "Accounting: " + canonical_json(report["accounting"]), "",
        "Reported billing, tariff liability and unknown local monetary expense remain separate.", "",
        "## Direct predictions", "",
        "| Backend | Dataset | Dataset ID | Dataset index | Split | Phase | N | Accuracy | Macro-F1 | Brier | MAE | p50 s | p95 s | Failure rate |",
        "|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    if "shared_accounting" in report:
        shared = report["shared_accounting"]
        display = {key: shared[key] for key in ("status", "scope", "snapshot", "reason")
                   if key in shared}
        if shared.get("binding"):
            display["binding"] = {key: shared["binding"][key]
                                  for key in ("allocation_id", "manifest_hash")}
        lines[12:12] = ["Shared accounting inspection: " + canonical_json(display), "",
                        "This current allocation snapshot is separate from the original per-run receipts.", ""]
    if "reporter_source_hash" in report:
        lines[4:4] = [f"Inference source SHA256: {_display(report.get('inference_source_hash'))}. "
                      f"Reporter source SHA256: {_display(report['reporter_source_hash'])}.",
                      "Reporter environment: " + canonical_json(report["reporter_environment"]), "",
                      "Reporter identity describes this offline reduction; inference identity remains frozen in the run manifest.", ""]
    for cohort in sorted(report["cohorts"], key=_cohort_key):
        m = cohort["metrics"]
        values = [cohort["backend"], cohort["dataset"], _dataset_id(cohort), cohort.get("dataset_index"),
                  cohort["split"], cohort["phase"]]
        values.extend([m.get("n_attempted", m.get("n")), *[m.get(k) for k in ("accuracy", "macro_f1", "brier", "ordinal_mae")],
            m.get("latency", {}).get("p50_s"), m.get("latency", {}).get("p95_s"), m.get("failure_rate")])
        lines.append("| " + " | ".join(_display(v) for v in values) + " |")
    lines.extend(["", "Uncertainty and denominators:", ""])
    for cohort in sorted(report["cohorts"], key=_cohort_key):
        m = cohort["metrics"]
        identity = "/".join((cohort["backend"], _dataset_label(cohort), cohort["split"], cohort["phase"]))
        lines.extend([identity + ": " + canonical_json({k: m[k] for k in m
                      if k.startswith(("n_", "planned_")) or k in ("uncertainty", "coverage_scope")}), ""])
        meaning = m.get("probability_meaning_summary")
        lines.extend(["Probability meaning: " + (canonical_json(meaning) if meaning is not None else
                      "unavailable; this retained report did not record a meaning summary."), ""])
        lines.extend(["Recorded request billing: " + canonical_json({key: m.get(key) for key in
            ("known_cost_usd", "total_cost_usd", "n_missing_cost", "cost_per_decision_usd",
             "cost_per_correct_decision_usd", "currency_arithmetic", "cost_scope")}), "",
            "Local hardware and energy expense is unavailable without supplied rates.", ""])
        if m.get("out_of_scope_detection") is not None:
            lines.extend(["Out-of-scope detection: " + canonical_json(m["out_of_scope_detection"]), ""])
    if report.get("dataset_audits"):
        lines.extend(["## Dataset provenance and information loss", "", canonical_json(report["dataset_audits"]), ""])
    if report.get("repeatability"):
        stability = [{key: value for key, value in item.items() if key != "groups"}
                     for item in report["repeatability"]]
        lines.extend(["## Repeated-prediction stability", "", canonical_json(stability), "",
                      "Per-example repeated observations remain in the complete JSON report.", ""])
    for title, field in (("Capability probes", "capability_probes"), ("Observed resources", "resources"),
                         ("Graphical experiments", "graphical_experiments")):
        if report.get(field):
            lines.extend(["## " + title, "", canonical_json(report[field]), ""])
    lines.extend(["## Validation-fitted policy replay", ""])
    for policy in report.get("policies", []):
        lines.extend([f"{_dataset_label(policy)}: {policy['weak']} → {policy.get('strong') or policy['policy']}.",
            "Gate: " + canonical_json(policy["gate"]), "Metrics: " + canonical_json(policy["metrics"]), ""])
    lines.extend(["## Evidence limits", ""])
    lines.extend("- " + limit for limit in report.get("limits", []))
    lines.extend(["- Percentiles use nearest rank; uncertainty uses 2,000 sample-grouped bootstrap resamples.",
        "- Primary quality and repeated timing cohorts have separate denominators.",
        "- Missing distributions produce unavailable proper scoring metrics; zero probability can yield infinite log loss.",
        "- Probability provenance alone does not establish meaning, calibration, or Bayesian posterior interpretation.",
        "- Gate admission is descriptive validation evidence; replay latency is unavailable.", "",
        "## Planned-cell outcomes", ""])
    incomplete = [cell for cell in report["cells"] if cell["status"] != "completed"]
    for cell in incomplete[:50]:
        lines.append(f"- {cell['id']}: {cell['status']}; {_display(cell.get('reason'))}")
    if len(incomplete) > 50:
        lines.append(f"- Remaining {len(incomplete) - 50} outcomes are retained in the complete JSON report and frozen run journal.")
    return "\n".join(lines) + "\n"


def write_publication(report: dict[str, Any], path: Path) -> None:
    """Exclusive output; PDF uses the optional figures environment, no network."""
    text = markdown_report(report)
    if path.suffix == ".md":
        with path.open("x") as handle:
            handle.write(text)
        return
    if path.suffix != ".pdf":
        raise ValueError("standalone publication path must end in .md or .pdf")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    lines = [part for line in text.splitlines() for part in (textwrap.wrap(line, width=105, replace_whitespace=False) or [""])]
    # Place each line in physical points. A fixed number of multiline rows
    # depends on font metrics and can silently place text below the page.
    page_size = (11.7, 8.3)
    margin = .03
    font_size = 8
    line_height = font_size * 1.3
    height_points = page_size[1] * 72
    rows_per_page = int((height_points * (1 - 2 * margin) - font_size) // line_height) + 1
    # Fixed PDF metadata makes repeated reduction of retained observations byte-stable.
    stamp = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with path.open("xb") as binary_handle, PdfPages(binary_handle, metadata={"Title": "Decision-model benchmark",
        "CreationDate": stamp, "ModDate": stamp, "Subject": report["manifest_hash"]}) as pdf:
        for start in range(0, len(lines), rows_per_page):
            figure = plt.figure(figsize=page_size)
            for row, line in enumerate(lines[start:start+rows_per_page]):
                y = 1 - margin - row * line_height / height_points
                figure.text(margin, y, line, va="top", family="monospace", fontsize=font_size)
            pdf.savefig(figure)
            plt.close(figure)
