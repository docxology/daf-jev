"""Retained inference and current offline reducer source remain distinct."""
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_runner import (
    _check_reporter_source,
    _reporter_source,
    plan_run,
    report_run,
    save_report,
)
from daf_jev.benchmark_store import RunStore
from daf_jev.decision_backends import content_hash


def test_actual_report_binds_inventory_and_preserves_older_inference(tmp_path):
    data = tmp_path / "dataset.json"
    save_dataset(make_synthetic_dataset("binary", n=10), data)
    config = {"format": "dafjev.benchmark-run/1", "sampling": "all", "seed": 3,
              "budget_usd": "0", "capability_probes": False,
              "timing_samples": 1, "timing_repetitions": 1,
              "datasets": [{"id": "retained-cohort", "path": data.name}],
              "backends": [{"id": "fixture", "kind": "uniform"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    original = plan_run(path, tmp_path / "runs")
    manifest = json.loads((original.directory / "manifest.json").read_bytes())
    # A deliberately labeled owned historical source fixture, never executed.
    manifest["source"]["files"] = {"src/daf_jev/benchmark_runner.py": "0" * 64}
    manifest["source"]["python"] = "historical fixture"
    store = RunStore.create(tmp_path / "historical", manifest)
    (store.directory / "inputs").mkdir()
    for item in manifest["datasets"]:
        (store.directory / item["file"]).write_bytes((original.directory / item["file"]).read_bytes())
    held = {name: (store.directory / name).read_bytes() for name in ("manifest.json", "events.jsonl", "head.json")}
    first = report_run(store.directory)
    package = Path(__file__).resolve().parents[2] / "src/daf_jev"
    expected = {"src/daf_jev/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in package.glob("*.py")}
    assert expected and first["reporter_source"]["files"] == expected
    assert first["reporter_source_hash"] == content_hash(expected)
    assert first["inference_source"] == manifest["source"]
    assert first["inference_source_hash"] == content_hash(manifest["source"]["files"])
    assert first["inference_source_hash"] != first["reporter_source_hash"]
    assert first["reporter_environment"]["python"] == platform.python_version()
    assert first["reporter_environment"]["dependencies"]["httpx"] == importlib.metadata.version("httpx")
    assert "hardware" not in first["reporter_environment"]
    first_path, second_path = tmp_path / "first.json", tmp_path / "second.json"
    save_report(first, first_path)
    save_report(report_run(store.directory), second_path)
    assert first_path.read_bytes() == second_path.read_bytes()
    assert all((store.directory / name).read_bytes() == raw for name, raw in held.items())


@pytest.mark.parametrize("change", ["bytes", "added", "removed", "symlink", "ancestor"])
def test_reporter_inventory_refuses_owned_fixture_custody_changes(tmp_path, change):
    package = tmp_path / "package"
    package.mkdir()
    path = package / "reducer.py"
    path.write_text("# owned reducer input fixture\n")
    before = _reporter_source(package)
    if change == "bytes":
        path.write_text("# changed\n")
    elif change == "added":
        (package / "additional.py").write_text("# added\n")
    elif change == "removed":
        path.unlink()
    elif change == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "missing.py")
    else:
        actual = tmp_path / "original-package"
        package.rename(actual)
        package.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match=r"reporter source|symlink"):
        _check_reporter_source(before, package)


def test_missing_reporter_python_inventory_never_yields_a_source_hash(tmp_path):
    with pytest.raises(ValueError, match="nonempty"):
        _reporter_source(tmp_path)


def test_real_relocated_package_reports_its_loaded_python_inventory(tmp_path):
    """A library layout has daf_jev/*.py and no repository src directory."""
    package = Path(__file__).resolve().parents[2] / "src/daf_jev"
    install = tmp_path / "installed"
    copied = install / "daf_jev"
    shutil.copytree(package, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    store = RunStore.create(tmp_path / "runs", {"datasets": [], "cells": [], "backends": [],
        "protocol": {}, "seed": 3, "budget_usd": "0", "source": {"files": {"historical.py": "0" * 64}}})
    held = {name: (store.directory / name).read_bytes() for name in ("manifest.json", "events.jsonl", "head.json")}
    command = [sys.executable, "-c",
               "import json,sys; from pathlib import Path; import daf_jev.benchmark_runner as runner; "
               "print(json.dumps({'module':runner.__file__, 'report':runner.report_run(Path(sys.argv[1]))}))",
               str(store.directory)]
    result = subprocess.run(command, cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(install),
                            "PYTHONDONTWRITEBYTECODE": "1"}, check=True, capture_output=True, text=True, timeout=30)
    value = json.loads(result.stdout)
    assert Path(value["module"]) == copied / "benchmark_runner.py"
    expected = {"src/daf_jev/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in copied.glob("*.py")}
    assert value["report"]["reporter_source"]["files"] == expected
    assert value["report"]["reporter_source_hash"] == content_hash(expected)
    assert value["report"]["inference_source"] == {"files": {"historical.py": "0" * 64}}
    assert not (tmp_path / "src").exists()
    assert all((store.directory / name).read_bytes() == raw for name, raw in held.items())
