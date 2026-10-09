"""Platform-scoped native dependencies and real optional-runtime diagnostics."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared development dependency.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("system_operator", ["==", "!="])
def test_release_checker_preserves_compound_benchmark_markers(system_operator):
    spec = importlib.util.spec_from_file_location(
        "runtime_release_checker", ROOT / "scripts/check_release_package.py")
    assert spec is not None and spec.loader is not None
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    requirement = (f"scipy>=1.14.1,<1.15; sys_platform {system_operator} 'darwin' "
                   "and python_version < '3.11'")
    declared = inspector._extra_requirement(requirement, "benchmark")
    rendered = str(Requirement(declared))
    assert inspector._requirement(declared) == inspector._requirement(rendered)
    for changed in (rendered.replace('python_version <', 'python_version >='),
                    rendered.replace('"darwin"', '"linux"'),
                    rendered.replace('"benchmark"', '"figures"')):
        assert inspector._requirement(declared) != inspector._requirement(changed)


@pytest.mark.parametrize("system,python,active", [
    ("darwin", "3.10", "<1.15,>=1.14.1"),
    ("linux", "3.10", ">=1.15.3"),
    ("win32", "3.10", ">=1.15.3"),
    ("darwin", "3.11", None),
    ("linux", "3.11", None),
    ("darwin", "3.14", None),
])
def test_benchmark_scipy_requirement_is_platform_scoped(system, python, active):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    requirements = [Requirement(value) for value in project["optional-dependencies"]["benchmark"]]
    selected = [str(req.specifier) for req in requirements if req.name == "scipy"
                and req.marker is not None
                and req.marker.evaluate({"sys_platform": system, "python_version": python})]
    assert selected == ([] if active is None else [active])
    assert all(Requirement(value).name != "scipy" for value in project["dependencies"])


@pytest.mark.parametrize("system,python,expected", [
    ("darwin", "3.10.20", "1.14.1"),
    ("linux", "3.10.20", "1.15.3"),
    ("win32", "3.10.20", "1.15.3"),
    ("darwin", "3.11.15", "1.17.1"),
    ("linux", "3.14.4", "1.18.1"),
])
def test_lock_preserves_other_platform_scipy_versions(system, python, expected):
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    environment = {"sys_platform": system, "python_full_version": python}
    selected = [package["version"] for package in lock["package"] if package["name"] == "scipy"
                and any(Marker(marker).evaluate(environment)
                        for marker in package["resolution-markers"])]
    assert selected == [expected]


def test_installed_benchmark_runtime_uses_real_compiled_fit(tmp_path):
    # Invoke a real process; neither imports nor the comparator are patched.
    env = {"PATH": os.defpath, "PYTHONPATH": str(ROOT / "src"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_benchmark_runtime.py")],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout)
    assert record["status"] == "passed"
    assert record["training_examples"] == 120
    assert record["vocabulary"] == ["low", "high", "absent"]
    assert record["checks"] == {"sparse_linalg_import": True, "structured_fit_predict": True,
                                "complete_unseen_class_vocabulary": True}
    assert set(record["dependency_versions"]) == {"numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl"}
    assert len(record["training_input_sha256"]) == 64
    assert [(row["value"], row["probabilities"]["absent"]) for row in record["predictions"]] == [
        ("low", 0.0), ("high", 0.0)]
    assert str(ROOT) not in result.stdout and str(tmp_path) not in result.stdout
