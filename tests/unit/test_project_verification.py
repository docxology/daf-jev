"""Bounded stdlib display relocation; fixtures never contain provider credentials."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import sys
import sysconfig
from pathlib import Path
from typing import Any

import pytest

from daf_jev.evidence import selected_verification, verification_inputs
from tests.unit.test_evidence import captured as captured

_PATH = Path(__file__).resolve().parents[2] / "scripts/project_verification.py"
_SPEC = importlib.util.spec_from_file_location("stdlib_project_verification", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PROJECTOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PROJECTOR)


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture()
def projection_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], str]:
    """Small explicitly synthetic record for adversarial display parsing."""
    root = tmp_path / "project"
    (root / "src/daf_jev").mkdir(parents=True)
    (root / "src/daf_jev/core.py").write_text("fixture = True\n")
    native = root / "verification/native"
    native.mkdir(parents=True)
    stdlib = str(Path(sysconfig.get_path("stdlib")).absolute())
    files = {
        "coverage": b'{"fixture":"synthetic coverage"}',
        "junit": b'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0" hostname="private-host"/></testsuites>',
        "live_collection": b"1 test collected in 0.01s\n",
        "unit_log": (f'File "{stdlib}/socketserver.py", line 123, in process_request\n'
                     f'File "{stdlib}/http/server.py", line 321, in handle\n').encode(),
    }
    inputs = verification_inputs(root)
    record: dict[str, Any] = {
        "format": "dafjev.verification-evidence/1", "before": inputs, "after": inputs,
        "environment": {"python_version": platform.python_version(), "platform": "synthetic fixture",
                        "stdlib_directory": stdlib},
        "unit_command": [sys.executable, "-m", "pytest", "tests/unit"],
        "live_collection_command": [sys.executable, "-m", "pytest", "tests/live", "--collect-only"],
        "unit_exit_code": 0, "live_collection_exit_code": 0, "live_execution": False,
    }
    for key, data in files.items():
        path = native / (key + ".txt")
        path.write_bytes(data)
        record[key] = {"path": path.relative_to(root).as_posix(), "sha256": _hash(data)}
    path = native / "verification.json"
    path.write_text(json.dumps(record))
    return root, path, record, stdlib


def _replace_log(root: Path, path: Path, record: dict[str, Any], text: str) -> None:
    log = root / record["unit_log"]["path"]
    log.write_text(text)
    record["unit_log"]["sha256"] = _hash(log.read_bytes())
    path.write_text(json.dumps(record))


def test_exact_captured_stdlib_relocation_declares_transformation_and_preserves_inputs(projection_fixture):
    root, path, _, stdlib = projection_fixture
    originals = {p: p.read_bytes() for p in path.parent.iterdir()}
    before = verification_inputs(root)
    result = _PROJECTOR.project(root, path, root / "verification/public")
    public = json.loads(result.read_text())
    assert public["environment"]["stdlib_directory"] == "<PYTHON_STDLIB>"
    assert public["before"] == public["after"] == before == verification_inputs(root)
    assert public["public_projection"]["original_record_sha256"] == _hash(originals[path])
    assert "relocate exactly captured version-specific stdlib-directory display" in public["public_projection"]["transformations"]
    log = (root / public["unit_log"]["path"]).read_text()
    assert '<PYTHON_STDLIB>/socketserver.py' in log and '<PYTHON_STDLIB>/http/server.py' in log
    assert stdlib not in log and all(p.read_bytes() == raw for p, raw in originals.items())
    for key in ("coverage", "junit", "live_collection", "unit_log"):
        assert _hash((root / public[key]["path"]).read_bytes()) == public[key]["sha256"]


@pytest.mark.parametrize("value", [None, False, 1, {}, "", "/", "/Users", "/home",
    "relative/lib/python3.14", "/Users/private/lib", "/Users/private/lib/python3.14/",
    "/Users/private/lib/python3.14/..", "/Users/private/./lib/python3.14",
    "/Users/private/lib/python0.1", "/Users/private/lib/python3.14-other",
    "/Users/private/data/python3.14", "/Users/private/lib/python3.14\n",
    "//Users/private/lib/python3.14",
    "/Users/sk-or-public-fixture/lib/python3.14"])
def test_malformed_or_overbroad_stdlib_prefix_refuses_before_output(projection_fixture, value):
    root, path, record, _ = projection_fixture
    record["environment"]["stdlib_directory"] = value
    path.write_text(json.dumps(record))
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="stdlib directory"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("version", [None, True, "", "3", "3.99.0", "/Users/private/3.14.4"])
def test_stdlib_version_must_match_capture_not_ambient_interpreter(projection_fixture, version):
    root, path, record, _ = projection_fixture
    record["environment"]["python_version"] = version
    path.write_text(json.dumps(record))
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="stdlib directory"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("suffix", ["-other/socket.py", "/../private.py", "//socket.py",
    "/site-packages/private_package.py", "/dist-packages/private_package.py"])
def test_stdlib_sibling_traversal_and_third_party_paths_are_not_relocated(projection_fixture, suffix):
    root, path, record, stdlib = projection_fixture
    _replace_log(root, path, record, f'File "{stdlib}{suffix}", line 1\n')
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="private data"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


def test_other_private_paths_remain_refused_after_known_stdlib_relocation(projection_fixture):
    root, path, record, stdlib = projection_fixture
    _replace_log(root, path, record, f'File "{stdlib}/socket.py", line 1\n/Users/private/person.txt\n')
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="private data"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("suffix", ["/http\\..\\private.py", "/socket\x00.py", "/http/../../private.py"])
def test_stdlib_backslashes_controls_and_nested_traversal_refuse(projection_fixture, suffix):
    root, path, record, stdlib = projection_fixture
    _replace_log(root, path, record, f'File "{stdlib}{suffix}", line 1\n')
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="private data"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("prefix_kind", ["stdlib", "root", "interpreter"])
def test_relative_prepend_does_not_convert_unknown_paths_to_known_prefixes(projection_fixture, prefix_kind):
    root, path, record, stdlib = projection_fixture
    prefix = {"stdlib": stdlib, "root": str(root), "interpreter": sys.executable}[prefix_kind]
    _replace_log(root, path, record, "relative-prefix" + prefix + ("/socket.py" if prefix_kind != "interpreter" else "") + "\n")
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="private data"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("suffix", ["-sibling/private.py", "/../outside.py", "/http\\..\\private.py", "//private.py"])
def test_project_prefix_siblings_and_escaped_children_refuse(projection_fixture, suffix):
    root, path, record, _ = projection_fixture
    _replace_log(root, path, record, str(root) + suffix + "\n")
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="private data"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("directory", ["/Users/private/site-packages/vendor/lib/python",
                                      "/Users/private/DiSt-PaCkAgEs/vendor/lib/python"])
def test_stdlib_ancestry_cannot_include_third_party_packages(projection_fixture, directory):
    root, path, record, _ = projection_fixture
    version = ".".join(platform.python_version().split(".")[:2])
    record["environment"]["stdlib_directory"] = directory + version
    path.write_text(json.dumps(record))
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="stdlib directory"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


@pytest.mark.parametrize("command", ["/", "/Users", "/Users/private/bin", "/opt/bin", "python",
                                     "/opt/bin/python-other", "/opt/bin/../python", "/opt/bin/python\\private",
                                     "/opt/bin/python\x00", "/opt/bin/python/", "/python", "//opt/cpython/bin/python"])
def test_captured_interpreter_must_be_narrow_canonical_python_executable(projection_fixture, command):
    root, path, record, _ = projection_fixture
    record["unit_command"][0] = record["live_collection_command"][0] = command
    path.write_text(json.dumps(record))
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="interpreter"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


def _replace_coverage(root: Path, path: Path, record: dict[str, Any], raw: bytes) -> None:
    coverage = root / record["coverage"]["path"]
    coverage.write_bytes(raw)
    record["coverage"]["sha256"] = _hash(raw)
    path.write_text(json.dumps(record))


@pytest.mark.parametrize("raw", [
    b'{"files":{"\\u002fUsers\\u002fprivate-fixture\\u002fperson.py":{"fixture":true}}}',
    b'{"fixture":"sk\\u002dor\\u002dpublic-fixture-only"}',
    b'{"fixture":[{"nested":"\\u002fhome\\u002fprivate-fixture\\u002fperson.py"}]}',
    b'{"fixture":"/private/tmp/unrelated/person.py"}',
    b'{"fixture":NaN}',
    b'{"fixture":1,"fixture":2}',
])
def test_coverage_is_strictly_decoded_before_recursive_privacy_scan(projection_fixture, raw):
    root, path, record, _ = projection_fixture
    _replace_coverage(root, path, record, raw)
    originals = {p: p.read_bytes() for p in path.parent.iterdir()}
    out = root / "verification/rejected"
    with pytest.raises(ValueError):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()
    assert all(p.read_bytes() == value for p, value in originals.items())


def test_escaped_known_coverage_paths_relocate_semantically_and_declare_serialization(projection_fixture):
    root, path, record, stdlib = projection_fixture
    raw = json.dumps({"files": {str(root) + "/src/daf_jev/core.py": {"fixture": True}},
                      "nested": [stdlib + "/socket.py"]}).replace("/", "\\u002f").encode()
    _replace_coverage(root, path, record, raw)
    originals = {p: p.read_bytes() for p in path.parent.iterdir()}
    result = _PROJECTOR.project(root, path, root / "verification/decoded-public")
    projected = json.loads(result.read_bytes())
    coverage = json.loads((root / projected["coverage"]["path"]).read_bytes())
    assert coverage == {"files": {"<PROJECT_ROOT>/src/daf_jev/core.py": {"fixture": True}},
                        "nested": ["<PYTHON_STDLIB>/socket.py"]}
    assert "strictly decode coverage JSON; relocate string keys/values; serialize JSON" in projected["public_projection"]["transformations"]
    assert projected["public_projection"]["original_files_sha256"]["coverage"] == _hash(raw)
    assert all(p.read_bytes() == value for p, value in originals.items())


def test_coverage_key_collision_after_relocation_refuses_before_output(projection_fixture):
    root, path, record, _ = projection_fixture
    _replace_coverage(root, path, record, json.dumps({str(root) + "/file.py": 1, "<PROJECT_ROOT>/file.py": 2}).encode())
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="key collision"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


def test_legacy_capture_without_stdlib_provenance_cannot_gain_ambient_relocation(projection_fixture):
    root, path, record, _ = projection_fixture
    record["environment"].pop("stdlib_directory")
    path.write_text(json.dumps(record))
    out = root / "verification/rejected"
    with pytest.raises(ValueError, match="private data"):
        _PROJECTOR.project(root, path, out)
    assert not out.exists()


def test_unmodified_genuine_capture_records_actual_stdlib_and_preserves_statistics(captured):
    root, record_path = captured
    record = json.loads(record_path.read_text())
    assert record["environment"]["stdlib_directory"] == str(Path(sysconfig.get_path("stdlib")).absolute())
    original = selected_verification(root)
    original_bytes = {p: p.read_bytes() for p in record_path.parent.iterdir()}
    projection = _PROJECTOR.project(root, record_path, root / "verification/stdlib-public")
    selection = root / "manuscript/evidence.json"
    evidence = json.loads(selection.read_text())
    evidence["verification"] = {"path": projection.relative_to(root).as_posix(), "sha256": _hash(projection.read_bytes())}
    selection.write_text(json.dumps(evidence))
    assert selected_verification(root) == original
    assert all(p.read_bytes() == raw for p, raw in original_bytes.items())
