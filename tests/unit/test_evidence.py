"""Byte-bound publication and genuine pytest/coverage capture regressions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from daf_jev.evidence import (
    _unit_count,
    bound_bytes,
    bound_input,
    selected_benchmark,
    selected_verification,
    verification_inputs,
)
from daf_jev.figures import _load_benchmark as figure_benchmark
from daf_jev.manuscript_variables import generate_variables
from tests.unit.test_manuscript_variables import _write_analysis_outputs

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/capture_verification.py"
_SPEC = importlib.util.spec_from_file_location("capture_verification", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_CAPTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CAPTURE)


def _binding(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _select(root: Path, record: Path) -> None:
    path = root / "manuscript/evidence.json"
    value = json.loads(path.read_text())
    value["verification"] = _binding(root, record)
    path.write_text(json.dumps(value))


def test_public_projection_preserves_native_results_and_originals(captured: tuple[Path, Path]) -> None:
    path = Path(__file__).resolve().parents[2] / "scripts/project_verification.py"
    spec = importlib.util.spec_from_file_location("project_verification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root, record = captured
    before = {p: p.read_bytes() for p in record.parent.iterdir() if p.is_file()}
    original = selected_verification(root)
    projected = module.project(root, record, root / "verification/public")
    _select(root, projected)
    assert selected_verification(root) == original
    assert all(p.read_bytes() == raw for p, raw in before.items())
    public = json.loads(projected.read_text())
    assert public["public_projection"]["original_record_sha256"] == hashlib.sha256(before[record]).hexdigest()
    assert public["public_projection"]["commands_are_relocated_display"] is True
    assert "hostname=" not in (root / public["junit"]["path"]).read_text()
    assert str(root) not in projected.read_text()
    with pytest.raises(ValueError, match="original"):
        module.project(root, projected, root / "verification/reprojected")
    with pytest.raises(FileExistsError):
        module.project(root, record, projected.parent)
    raw = json.loads(record.read_text())
    raw["coverage"]["sha256"] = "0" * 64
    malformed = record.parent / "changed.json"
    malformed.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="changed"):
        module.project(root, malformed, root / "verification/changed")
    raw = json.loads(record.read_text())
    raw["environment"]["platform"] = "/Users/private-person/machine"
    malformed.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="private data"):
        module.project(root, malformed, root / "verification/private-metadata")
    assert not (root / "verification/private-metadata").exists()
    for field, value in (("unit_exit_code", False), ("unit_command", [])):
        raw = json.loads(record.read_text())
        raw[field] = value
        malformed.write_text(json.dumps(raw))
        with pytest.raises(ValueError):
            module.project(root, malformed, root / "verification/invalid")
        assert not (root / "verification/invalid").exists()
    # Different bound inputs may legitimately share a source basename.
    raw = json.loads(record.read_text())
    for index, key in enumerate(("coverage", "unit_log")):
        destination = root / f"same-name-{index}" / "same.txt"
        destination.parent.mkdir()
        destination.write_bytes(before[root / raw[key]["path"]])
        raw[key]["path"] = destination.relative_to(root).as_posix()
    malformed.write_text(json.dumps(raw))
    collision = module.project(root, malformed, root / "verification/no-collision")
    _select(root, collision)
    assert selected_verification(root) == original


@pytest.fixture()
def captured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
             request: pytest.FixtureRequest) -> tuple[Path, Path]:
    root = tmp_path / "project"
    (root / "src/daf_jev").mkdir(parents=True)
    (root / "src/daf_jev/__init__.py").write_text("")
    (root / "src/daf_jev/core.py").write_text("def sign(x):\n    return 1 if x > 0 else 0\n")
    (root / "tests/unit").mkdir(parents=True)
    (root / "tests/live").mkdir()
    (root / "tests/unit/test_core.py").write_text(
        "import pytest\nfrom daf_jev.core import sign\n"
        "@pytest.mark.parametrize('x,y', [(1,1),(0,0),(-1,0)])\ndef test_sign(x,y):\n    assert sign(x) == y\n")
    (root / "tests/live/test_never_execute.py").write_text(
        "def test_a():\n    raise AssertionError('live inference prohibited')\n"
        "def test_b():\n    raise AssertionError('live inference prohibited')\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname="daf-jev"\nversion="0.0.0"\nrequires-python=">=3.10"\n'
        '[tool.coverage.run]\nbranch=true\nsource=["src"]\n'
        '[tool.coverage.report]\nfail_under=90\nomit=["*/__init__.py"]\n')
    if getattr(request, "param", "quiet") == "verbose":
        with (root / "pyproject.toml").open("a") as handle:
            handle.write('[tool.pytest.ini_options]\naddopts="-v --tb=short --strict-markers"\n')
    _write_analysis_outputs(root)
    for name in ("AGENTS.md", "docs/README.md", "docs/reference/MANIFEST.json",
                 "benchmarks/bench_calibration.py", "examples/quickstart.py",
                 "manuscript/render/cover.tex"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# original static input\n")
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))
    assert _CAPTURE.capture(root, root / "verification/first") == 0
    record = root / "verification/first/verification.json"
    _select(root, record)
    return root, record


def test_native_capture_regenerates_variables_without_raw_coverage(captured: tuple[Path, Path]) -> None:
    root, _ = captured
    result = selected_verification(root)
    assert result is not None
    assert result.unit_count == 3 and result.live_count == 2 and result.coverage_percent == 100
    assert not list(root.rglob(".coverage*"))
    variables = generate_variables(root)
    assert variables["TEST_UNIT_COUNT"] == "3"
    assert variables["TEST_LIVE_COUNT"] == "2"
    assert variables["TEST_COVERAGE_PCT"] == "100.00"
    assert variables["PLATFORM"] == result.platform
    assert variables["PYTHON_VERSION"] == result.python_version


@pytest.mark.parametrize("captured", ["verbose"], indirect=True)
def test_native_capture_accepts_repository_verbose_collection(captured: tuple[Path, Path]) -> None:
    root, path = captured
    record = json.loads(path.read_text())
    collection = (root / record["live_collection"]["path"]).read_text()
    assert "<Function test_a>" in collection and "2 tests collected in" in collection
    result = selected_verification(root)
    assert result is not None and result.unit_count == 3 and result.live_count == 2
    assert generate_variables(root)["TEST_LIVE_COUNT"] == "2"


@pytest.mark.parametrize("footer", [
    "== 2 tests collected in 0.06s", "2 tests collected in 0.06s ==",
    "==\n2 tests collected in 0.06s\n==", "2 tests collected\n2 tests collected",
])
def test_selected_verification_rejects_truncated_or_multiple_footers(
    captured: tuple[Path, Path], footer: str,
) -> None:
    root, path = captured
    record = json.loads(path.read_text())
    collection = root / record["live_collection"]["path"]
    collection.write_text(footer)
    record["live_collection"] = _binding(root, collection)
    path.write_text(json.dumps(record))
    _select(root, path)
    with pytest.raises(ValueError, match="collection is incomplete"):
        selected_verification(root)


@pytest.mark.parametrize("change", ["source", "test_added", "config", "script_added",
                                    "README.md", "CITATION.cff", ".zenodo.json", "src/daf_jev/py.typed",
                                    "skills/daf-jev/SKILL.md", "AGENTS.md", "docs/README.md",
                                    "docs/reference/MANIFEST.json", "benchmarks/bench_calibration.py",
                                    "examples/quickstart.py", "manuscript/render/cover.tex"])
def test_verification_detects_all_inventory_changes(captured: tuple[Path, Path], change: str) -> None:
    root, _ = captured
    if change == "source":
        (root / "src/daf_jev/core.py").write_text("# changed\n")
    elif change == "test_added":
        (root / "tests/unit/new.py").write_text("# new\n")
    elif change == "config":
        (root / "pyproject.toml").write_text("# changed\n")
    elif change == "script_added":
        (root / "scripts").mkdir()
        (root / "scripts/new.py").write_text("# new\n")
    else:
        (root / change).parent.mkdir(parents=True, exist_ok=True)
        (root / change).write_text("# new consumed release input\n")
    with pytest.raises(ValueError, match="does not match"):
        selected_verification(root)


@pytest.mark.parametrize("change", ["format", "before", "after", "unit_exit_code", "live_collection_exit_code", "live_execution",
                                    "branch", "percent", "environment", "junit", "collection"])
def test_invalid_selected_verification_never_falls_back(captured: tuple[Path, Path], change: str) -> None:
    root, path = captured
    record: dict[str, Any] = json.loads(path.read_text())
    if change in {"format", "before", "after", "unit_exit_code", "live_collection_exit_code", "live_execution", "environment"}:
        record[change] = "bad"
    elif change in {"branch", "percent"}:
        target = root / record["coverage"]["path"]
        coverage = json.loads(target.read_text())
        if change == "branch":
            coverage["meta"]["branch_coverage"] = False
        else:
            coverage["totals"]["percent_covered"] = 101
        target.write_text(json.dumps(coverage))
        record["coverage"] = _binding(root, target)
    elif change == "junit":
        target = root / record["junit"]["path"]
        target.write_text('<testsuite tests="3" failures="1" errors="0" skipped="0"/>')
        record["junit"] = _binding(root, target)
    else:
        target = root / record["live_collection"]["path"]
        target.write_text("collection failed\n")
        record["live_collection"] = _binding(root, target)
    path.write_text(json.dumps(record))
    _select(root, path)
    with pytest.raises(ValueError):
        generate_variables(root, require_analysis_outputs=False)


def test_selected_native_export_tampering_fails(captured: tuple[Path, Path]) -> None:
    root, path = captured
    record = json.loads(path.read_text())
    target = root / record["coverage"]["path"]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        selected_verification(root)


def test_capture_preserves_failed_outputs_and_removes_only_owned_raw(captured: tuple[Path, Path]) -> None:
    root, _ = captured
    existing_raw = root / ".coverage"
    existing_raw.write_bytes(b"unrelated")
    (root / "tests/unit/test_core.py").write_text("def test_fail():\n    assert False\n")
    out_dir = root / "verification/failed"
    assert _CAPTURE.capture(root, out_dir) == 1
    assert existing_raw.read_bytes() == b"unrelated"
    assert not list(out_dir.glob(".coverage*"))
    assert (out_dir / "junit.xml").is_file()
    record = out_dir / "verification.json"
    _select(root, record)
    with pytest.raises(ValueError, match="did not complete"):
        selected_verification(root)
    with pytest.raises(FileExistsError):
        _CAPTURE.capture(root, out_dir)


def test_invalid_after_identity_still_retains_capture_and_cleans_raw(captured: tuple[Path, Path]) -> None:
    root, _ = captured
    (root / "tests/unit/test_core.py").write_text(
        "from pathlib import Path\nfrom daf_jev.core import sign\n"
        "def test_change_identity():\n    assert sign(1) == 1 and sign(0) == 0\n"
        f"    scripts = Path({str(root / 'scripts')!r})\n    scripts.mkdir()\n"
        "    (scripts / 'link.py').symlink_to(scripts.parent / 'pyproject.toml')\n")
    out_dir = root / "verification/identity-failed"
    assert _CAPTURE.capture(root, out_dir) == 1
    record = json.loads((out_dir / "verification.json").read_text())
    assert record["unit_exit_code"] == 0
    assert record["after"] is None and record["identity_error"] == "ValueError"
    assert not list(out_dir.glob(".coverage*"))
    assert (out_dir / "coverage.json").is_file()


@pytest.mark.parametrize("payload", ['{"model":"a","model":"b"}', '[]', '{"cost":NaN}'])
def test_selected_benchmark_intake_rejects_ambiguous_bytes(captured: tuple[Path, Path], payload: str) -> None:
    root, _ = captured
    path = root / "output/benchmarks/batching_20260916.json"
    path.write_text(payload)
    selection_path = root / "manuscript/evidence.json"
    selection = json.loads(selection_path.read_text())
    selection["historical_benchmarks"]["batching"] = _binding(root, path)
    selection_path.write_text(json.dumps(selection))
    with pytest.raises(ValueError):
        generate_variables(root)
    with pytest.raises(ValueError):
        figure_benchmark(root, "batching")


def test_verification_no_selection_and_strict_publication_json(tmp_path: Path) -> None:
    assert selected_verification(tmp_path) is None
    (tmp_path / "manuscript").mkdir()
    selection = tmp_path / "manuscript/evidence.json"
    selection.write_text('{"format":"dafjev.publication-evidence/1","verification":null}')
    assert selected_verification(tmp_path) is None
    selection.write_text('{"format":"bad"}')
    with pytest.raises(ValueError, match="format"):
        selected_verification(tmp_path)
    selection.write_text('{"format":"bad","format":"dafjev.publication-evidence/1"}')
    with pytest.raises(ValueError, match="duplicate"):
        selected_verification(tmp_path)
    selection.unlink()
    selection.symlink_to(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="nonsymlink"):
        selected_verification(tmp_path)
    selection.unlink()
    selection.mkdir()
    with pytest.raises(ValueError, match="regular"):
        selected_verification(tmp_path)


@pytest.mark.parametrize("item", [None, {}, {"path": "x", "sha256": "invalid"},
                                  {"path": "../outside", "sha256": "a" * 64},
                                  {"path": "/outside", "sha256": "a" * 64}])
def test_bound_input_rejects_malformed_and_escaped_paths(tmp_path: Path, item: Any) -> None:
    with pytest.raises(ValueError):
        bound_input(tmp_path, item)


def test_bound_input_and_inventory_reject_symlinks(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.write_text("data")
    link = tmp_path / "link"
    link.symlink_to(original)
    with pytest.raises(ValueError, match="nonsymlink"):
        bound_input(tmp_path, {"path": "link", "sha256": hashlib.sha256(b"data").hexdigest()})
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/link.py").symlink_to(original)
    with pytest.raises(ValueError, match="nonsymlink"):
        verification_inputs(tmp_path)
    with pytest.raises(ValueError, match="confined"):
        _CAPTURE.capture(tmp_path, tmp_path.parent / "outside")
    with pytest.raises(ValueError, match="confined"):
        _CAPTURE.capture(tmp_path, tmp_path / "inside/../../outside")
    assert not (tmp_path.parent / "outside").exists()


def test_missing_selected_benchmark_preserves_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="selection"):
        selected_benchmark(tmp_path, "batching")
    (tmp_path / "manuscript").mkdir()
    (tmp_path / "manuscript/evidence.json").write_text('{"format":"dafjev.publication-evidence/1"}')
    with pytest.raises(FileNotFoundError, match="batching"):
        selected_benchmark(tmp_path, "batching")
    selection = tmp_path / "manuscript/evidence.json"
    selection.write_text('{"format":"dafjev.publication-evidence/1","historical_benchmarks":[]}')
    with pytest.raises(ValueError, match="object"):
        selected_benchmark(tmp_path, "batching")
    original = tmp_path / "original"
    original.write_bytes(selection.read_bytes())
    selection.unlink()
    selection.symlink_to(original)
    with pytest.raises(ValueError, match="nonsymlink"):
        selected_benchmark(tmp_path, "batching")


def test_bound_bytes_verifies_consumed_bytes(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_bytes(b"{}")
    item = _binding(tmp_path, path)
    assert bound_bytes(tmp_path, item) == b"{}"
    path.write_bytes(b"[]")
    with pytest.raises(ValueError, match="changed"):
        bound_bytes(tmp_path, item)


@pytest.mark.parametrize("xml", [
    '<wrapper><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase/></testsuite></wrapper>',
    '<testsuites><testsuite tests="-1" failures="0" errors="0" skipped="0"/>'
    '<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase/></testsuite></testsuites>',
    '<testsuites tests="2"><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase/></testsuite></testsuites>',
    '<testsuites><unknown/></testsuites>', '<testsuites/>', '<testsuite/>', '<broken',
    '<testsuite tests="0" failures="0" errors="0" skipped="0"/>',
    '<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase><skipped/></testcase></testsuite>',
    '<!DOCTYPE testsuite [<!ENTITY v "hello">]><testsuite/>',
])
def test_native_junit_rejects_structural_and_per_suite_count_conflicts(xml: str) -> None:
    with pytest.raises(ValueError):
        _unit_count(xml.encode())


def test_native_junit_preserves_properties_and_aggregates_valid_suites() -> None:
    raw = ('<testsuites tests="2"><testsuite tests="1" failures="0" errors="0" skipped="0">'
           '<testcase><properties><property name="purpose" value="fixture"/></properties></testcase>'
           '</testsuite><testsuite tests="1" failures="0" errors="0" skipped="0">'
           '<testcase><system-out>public fixture output</system-out></testcase></testsuite></testsuites>')
    assert _unit_count(raw.encode()) == 2
