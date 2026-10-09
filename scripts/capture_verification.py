#!/usr/bin/env python3
"""Run unit coverage and collect live tests into a fresh, byte-bound receipt.

No live test executes. This does not select publication inputs or publish them.
Raw coverage data is temporary; native JSON/JUnit and command logs are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from daf_jev.evidence import verification_inputs  # noqa: E402


def capture(root: Path, out_dir: Path) -> int:
    """Capture genuine commands, preserving failed output without acceptance."""
    root = root.absolute()
    out_dir = out_dir.absolute()
    if (".." in out_dir.parts or not out_dir.resolve().is_relative_to(root.resolve()) or out_dir.is_symlink()
            or any(p.is_symlink() for p in out_dir.parents)):
        raise ValueError("verification directory must be confined and nonsymlink")
    out_dir.mkdir(parents=True, exist_ok=False)
    before = verification_inputs(root)
    coverage = out_dir / "coverage.json"
    junit = out_dir / "junit.xml"
    live = out_dir / "live-collection.txt"
    raw_coverage = out_dir / ".coverage"
    unit_command = [sys.executable, "-m", "pytest", "tests/unit", "--cov=src",
                    "--cov-report=term-missing", f"--cov-report=json:{coverage}",
                    f"--junitxml={junit}"]
    live_command = [sys.executable, "-m", "pytest", "tests/live", "--collect-only", "-q"]
    record: dict[str, object] = {
        "format": "dafjev.verification-evidence/1", "before": before,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python_version": platform.python_version(), "platform": platform.platform(),
                        "stdlib_directory": str(Path(sysconfig.get_path("stdlib")).absolute())},
        "unit_command": unit_command, "live_collection_command": live_command,
        "live_execution": False,
    }
    try:
        with (out_dir / "unit.txt").open("xb") as output:
            unit = subprocess.run(unit_command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                  env={**os.environ, "COVERAGE_FILE": str(raw_coverage)},
                                  timeout=1800, check=False)
        record["unit_exit_code"] = unit.returncode
        with live.open("xb") as output:
            collected = subprocess.run(live_command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                       timeout=180, check=False)
        record["live_collection_exit_code"] = collected.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        record["capture_error"] = type(exc).__name__
    finally:
        try:
            record["after"] = verification_inputs(root)
        except (OSError, ValueError) as exc:
            record["after"] = None
            record["identity_error"] = type(exc).__name__
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        for key, path in (("coverage", coverage), ("junit", junit), ("live_collection", live),
                          ("unit_log", out_dir / "unit.txt")):
            if path.is_file():
                record[key] = {"path": path.relative_to(root).as_posix(),
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        # Only this invocation's private raw data is removed; prior data is not touched.
        for path in out_dir.glob(".coverage*"):
            path.unlink()
        with (out_dir / "verification.json").open("x") as output:
            json.dump(record, output, indent=2, sort_keys=True, allow_nan=False)
    accepted = (record.get("unit_exit_code") == 0 and record.get("live_collection_exit_code") == 0
                and record["before"] == record["after"])
    print(out_dir / "verification.json")
    return 0 if accepted else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path, help="Fresh directory inside this checkout")
    args = parser.parse_args()
    try:
        return capture(ROOT, args.out_dir)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
