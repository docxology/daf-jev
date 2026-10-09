"""Shared explicit, byte-bound publication input selection (offline)."""
from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._json import strict_json_loads


def _selection(project_root: Path) -> dict[str, Any]:
    path = project_root / "manuscript/evidence.json"
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("publication selection must be nonsymlink")
    if not path.is_file():
        raise ValueError("publication selection must be a regular file")
    spec = strict_json_loads(path.read_bytes())
    if not isinstance(spec, dict) or spec.get("format") != "dafjev.publication-evidence/1":
        raise ValueError("invalid publication evidence format")
    return spec


def _input_path(project_root: Path, item: Any) -> Path:
    if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
        raise ValueError("publication input requires path and SHA-256")
    relative = Path(item["path"])
    path = project_root / relative
    if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)
            or not path.resolve().is_relative_to(project_root.resolve())):
        raise ValueError("publication input must be confined and nonsymlink")
    if not path.is_file():
        raise FileNotFoundError(f"Missing publication input: {path}")
    return path


def bound_bytes(project_root: Path, item: Any) -> bytes:
    """Consume the same bytes whose SHA-256 is checked, with no second read."""
    path = _input_path(project_root, item)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError(f"selected publication input changed: {item['path']}")
    return raw


def bound_input(project_root: Path, item: Any) -> Path:
    """Resolve and verify an input for compatibility with path-based callers."""
    bound_bytes(project_root, item)
    path = _input_path(project_root, item)
    return path


def _benchmark_selection(project_root: Path, prefix: str) -> Any:
    bench_dir = project_root / "output" / "benchmarks"
    selection = project_root / "manuscript" / "evidence.json"
    if not selection.is_file():
        raise FileNotFoundError(f"Missing benchmark data selection: {selection}; {bench_dir} requires explicit evidence")
    spec = _selection(project_root)
    historical = spec.get("historical_benchmarks", {})
    if not isinstance(historical, dict):
        raise ValueError("historical publication selection must contain an object")
    item = historical.get(prefix)
    if not item:
        raise FileNotFoundError(f"Missing benchmark data selection for {prefix} in {selection}; {bench_dir}")
    return item


def selected_benchmark(project_root: Path, prefix: str) -> Path:
    """Select an exact historical input; never choose independently by date."""
    return bound_input(project_root, _benchmark_selection(project_root, prefix))


def selected_benchmark_bytes(project_root: Path, prefix: str) -> bytes:
    """Read and verify selected benchmark bytes in a single consumption."""
    return bound_bytes(project_root, _benchmark_selection(project_root, prefix))


def selected_study_bytes(project_root: Path, name: str) -> bytes:
    """Read an explicitly selected aggregate, preserving its own evidence scope."""
    summaries = _selection(project_root).get("study_summaries")
    if not isinstance(summaries, dict):
        raise ValueError("study publication selection must contain an object")
    if name not in summaries:
        raise ValueError(f"missing selected study summary: {name}")
    return bound_bytes(project_root, summaries[name])


def has_study_selection(project_root: Path) -> bool:
    """Legacy publications may omit studies; explicit malformed maps still fail."""
    path = project_root / "manuscript/evidence.json"
    return (path.exists() or path.is_symlink()) and "study_summaries" in _selection(project_root)


def has_selected_study(project_root: Path, name: str) -> bool:
    """Optional named studies are absent by default; malformed maps still fail."""
    if not has_study_selection(project_root):
        return False
    summaries = _selection(project_root)["study_summaries"]
    if not isinstance(summaries, dict):
        raise ValueError("study publication selection must contain an object")
    return name in summaries


def verification_inputs(project_root: Path) -> dict[str, dict[str, str | int]]:
    """Inventory code and static documentation consumed by checks and renders.

    File additions/removals participate in identity. Evidence selection is
    excluded so selecting a completed check cannot change its tested inputs.
    """
    paths: set[Path] = set()
    for folder in ("src/daf_jev", "tests", "scripts", "benchmarks", "examples",
                   "docs", "skills", "manuscript"):
        tree = project_root / folder
        if tree.is_symlink():
            raise ValueError("verification inputs must be nonsymlink")
        for path in tree.rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError("verification inputs must be nonsymlink")
            if path.relative_to(project_root).as_posix() == "manuscript/evidence.json":
                continue
            suffixes = ({".md", ".json", ".yaml", ".yml", ".bib", ".tex"}
                        if folder in {"docs", "skills", "manuscript"} else {".py"})
            if path.is_file() and path.suffix in suffixes:
                paths.add(path)
    paths.update(p for name in ("pyproject.toml", "uv.lock", "AGENTS.md",
                               ".github/workflows/ci.yml", "README.md", "CITATION.cff",
                               ".zenodo.json", "src/daf_jev/py.typed")
                 if (p := project_root / name).exists() or p.is_symlink())
    result: dict[str, dict[str, str | int]] = {}
    for path in sorted(paths):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("verification inputs must be nonsymlink")
        raw = path.read_bytes()
        result[path.relative_to(project_root).as_posix()] = {
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return result


@dataclass(frozen=True)
class VerificationStatistics:
    """Retained unit execution and live collection, never live acceptance."""

    unit_count: int
    live_count: int
    coverage_percent: float
    python_version: str
    platform: str


def _unit_count(raw: bytes) -> int:
    # Native pytest XML has no declarations; reject entities before parsing.
    text = raw.decode("utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("verification JUnit must not declare entities")
    try:
        root = ET.fromstring(text)
        if root.tag not in ("testsuite", "testsuites"):
            raise ValueError("invalid verification JUnit root")
        suites = [root] if root.tag == "testsuite" else list(root)
        if not suites or any(s.tag != "testsuite" for s in suites):
            raise ValueError("invalid verification JUnit suites")
        count = 0
        for suite in suites:
            tests = int(suite.attrib["tests"])
            if tests < 0 or any(int(suite.attrib[key]) != 0 for key in ("errors", "failures", "skipped")):
                raise ValueError("verification requires passing, unskipped unit tests")
            cases = suite.findall("testcase")
            if len(cases) != tests or any(case.find(tag) is not None for case in cases
                                         for tag in ("failure", "error", "skipped")):
                raise ValueError("verification JUnit count or outcome mismatch")
            count += tests
        if count <= 0 or (root.tag == "testsuites" and any(
                int(root.attrib[key]) != (count if key == "tests" else 0)
                for key in ("tests", "errors", "failures", "skipped") if key in root.attrib)):
            raise ValueError("invalid verification JUnit aggregate")
    except (ET.ParseError, KeyError) as exc:
        raise ValueError("invalid verification JUnit") from exc
    return count


def selected_verification(project_root: Path) -> VerificationStatistics | None:
    """Read a selected completed capture without pytest or raw coverage state.

    A malformed, stale or incomplete explicit selection fails even in draft
    mode. With no selection, callers retain the historical collection path.
    """
    selection = project_root / "manuscript/evidence.json"
    if not selection.exists() and not selection.is_symlink():
        return None
    item = _selection(project_root).get("verification")
    if item is None:
        return None
    record = strict_json_loads(bound_bytes(project_root, item))
    if not isinstance(record, dict) or record.get("format") != "dafjev.verification-evidence/1":
        raise ValueError("invalid verification evidence format")
    current = verification_inputs(project_root)
    if (not current or record.get("before") != current or record.get("after") != current):
        raise ValueError("verification evidence does not match current source, tests or configuration")
    if (any(type(record.get(key)) is not int or record[key] != 0
            for key in ("unit_exit_code", "live_collection_exit_code"))
            or record.get("live_execution") is not False):
        raise ValueError("verification capture did not complete successfully")
    unit_count = _unit_count(bound_bytes(project_root, record.get("junit")))
    collection = bound_bytes(project_root, record.get("live_collection")).decode("utf-8")
    footer = (r"^(?:(\d+) tests? collected(?: in \d+(?:\.\d+)?s)?|"
              r"=+[ \t]+(\d+) tests? collected in \d+(?:\.\d+)?s[ \t]+=+)[ \t]*$")
    counts = re.findall(footer, collection, flags=re.MULTILINE)
    lines = collection.rstrip().splitlines()
    if len(counts) != 1 or not lines or re.fullmatch(footer, lines[-1]) is None:
        raise ValueError("verification live collection is incomplete")
    coverage = strict_json_loads(bound_bytes(project_root, record.get("coverage")))
    try:
        totals = coverage["totals"]
        if any(type(totals[key]) is not int or totals[key] < 0 for key in (
                "num_statements", "num_branches", "covered_lines", "covered_branches")):
            raise ValueError("invalid verification coverage counts")
        percent = float(totals["percent_covered"])
        denominator = totals["num_statements"] + totals["num_branches"]
        numerator = totals["covered_lines"] + totals["covered_branches"]
        if (coverage["meta"]["branch_coverage"] is not True or denominator <= 0
                or type(totals["percent_covered"]) not in (int, float)
                or totals["covered_lines"] > totals["num_statements"]
                or totals["covered_branches"] > totals["num_branches"]
                or not math.isfinite(percent) or not 0 <= percent <= 100
                or not math.isclose(percent, 100 * numerator / denominator, abs_tol=1e-10)):
            raise ValueError("invalid verification coverage totals")
        environment = record["environment"]
        if any(not isinstance(environment[key], str) or not environment[key]
               for key in ("python_version", "platform")):
            raise ValueError("invalid verification environment")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("invalid verification evidence statistics") from exc
    return VerificationStatistics(unit_count, int(counts[0][0] or counts[0][1]), percent,
                                  environment["python_version"], environment["platform"])
