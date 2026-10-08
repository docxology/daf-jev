"""Offline publication keeps frozen folds and recorded probability meaning."""
import json

from pypdf import PdfReader

from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_publication import markdown_report, write_publication
from daf_jev.benchmark_runner import plan_run, report_run


def test_actual_same_family_folds_remain_distinct_in_publication(tmp_path):
    datasets = [make_synthetic_dataset("categorical", seed=seed, n=10) for seed in (3, 4)]
    inputs = []
    for index, dataset in enumerate(datasets):
        path = tmp_path / f"fold-{index}.json"
        save_dataset(dataset, path)
        inputs.append({"id": f"fold-{index}", "path": path.name})
    config = {"format": "dafjev.benchmark-run/1", "seed": 3, "budget_usd": "0",
              "sampling": "all", "capability_probes": False,
              "timing_samples": 1, "timing_repetitions": 1, "datasets": inputs,
              "backends": [{"id": "fixture", "kind": "uniform"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    for cell in store.manifest["cells"]:
        dataset = datasets[cell["dataset"]]
        example = next(e for e in dataset.examples if e.id == cell["example_id"])
        predictions = {qid: {"value": target, "confidence": .9,
                            "probabilities": {label: float(label == target) for label in dataset.manifest.labels},
                            "probability_source": "fixture",
                            "probability_semantics": "fixture class probabilities" if cell["dataset"] == 0 else None}
                       for qid, target in example.targets.items()}
        store.append({"event": "cell_finished", "cell_id": cell["id"], "status": "completed",
                      "predictions": predictions, "elapsed_s": .01})
    held = {name: (store.directory / name).read_bytes() for name in ("manifest.json", "events.jsonl", "head.json")}
    report = report_run(store.directory)
    text = markdown_report(report)
    assert report["reporter_source_hash"] in text and report["inference_source_hash"] in text
    assert "Reporter identity describes this offline reduction" in text
    assert '"planned_cells":2' in text and '"planned_decisions":2' in text
    assert "| Dataset ID | Dataset index |" in text
    assert "| fixture | synthetic-categorical | fold-0 | 0 |" in text
    assert "| fixture | synthetic-categorical | fold-1 | 1 |" in text
    assert "synthetic-categorical (ID fold-0, index 0): fixture" in text
    assert "synthetic-categorical (ID fold-1, index 1): fixture" in text
    assert 'Probability meaning: {"declared":["fixture class probabilities"],"unknown_distributions":0}' in text
    assert 'Probability meaning: {"declared":[],"unknown_distributions":2}' in text
    assert "Probability provenance alone does not establish meaning" in text
    output = tmp_path / "publication.md"
    write_publication(report, output)
    assert output.read_text() == text
    assert all((store.directory / name).read_bytes() == raw for name, raw in held.items())


def test_legacy_publication_keeps_family_fallback_and_unknown_meaning():
    report = {"format": "dafjev.benchmark-report/1", "manifest_hash": "a" * 64,
              "journal_hash": "b" * 64, "status": "partial", "planned_cells": 1,
              "denominators": {"unattempted": 1}, "accounting": {}, "cells": [],
              "cohorts": [{"backend": "fixture", "dataset": "historical", "split": "test",
                           "phase": "quality", "metrics": {"n_attempted": 0}}],
              "policies": [{"dataset": "historical", "weak": "fixture", "policy": "gate",
                            "gate": {}, "metrics": {}}]}
    text = markdown_report(report)
    assert "| fixture | historical | historical | unavailable | test | quality | 0 |" in text
    assert "historical (ID historical, index unavailable): fixture" in text
    assert "Probability meaning: unavailable; this retained report did not record a meaning summary." in text
    assert "calibrated posterior" not in text


def test_multipage_pdf_retains_every_line_inside_the_actual_page(tmp_path):
    sentinels = [f"LAYOUT-SENTINEL-{index:03d}" for index in range(130)]
    report = {"format": "dafjev.benchmark-report/1", "manifest_hash": "a" * 64,
              "journal_hash": "b" * 64, "status": "partial", "planned_cells": 0,
              "denominators": {}, "accounting": {}, "cells": [],
              "cohorts": [], "policies": [], "limits": sentinels}
    path = tmp_path / "multipage.pdf"
    write_publication(report, path)
    reader = PdfReader(path)
    text = ""
    positions = []
    for page in reader.pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)

        def visitor(value, cm, tm, font, size, *, width=width, height=height):
            if not value.strip():
                return
            # PDF text matrices map through the actual current transform;
            # intended figure coordinates alone would miss renderer clipping.
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            assert 0 <= x <= width
            assert size <= y <= height - size
            positions.append((value, x, y))

        text += page.extract_text(visitor_text=visitor)
    assert len(reader.pages) >= 3
    assert all(text.count(marker) == 1 for marker in sentinels)
    assert all(any(marker in value for value, _, _ in positions) for marker in sentinels)
