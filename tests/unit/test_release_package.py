"""Adversarial real archive inputs for the release artifact inspector."""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_package_inspector", Path(__file__).resolve().parents[2] / "scripts/check_release_package.py"
)
assert SPEC is not None and SPEC.loader is not None
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)


def write_wheel(path: Path, members: dict[str, bytes]) -> None:
    record_name = "daf_jev-0.7.0.dist-info/RECORD"
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for name, content in sorted(members.items()):
        if name != record_name:
            hashed = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
            writer.writerow([name, "sha256=" + hashed, len(content)])
    writer.writerow([record_name, "", ""])
    members[record_name] = output.getvalue().encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def wheel_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {entry.filename: archive.read(entry) for entry in archive.infolist()}


def rewrite_sdist(path: Path, mutate) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = {entry.name: archive.extractfile(entry).read()
                   for entry in archive.getmembers() if entry.isfile()}
    mutate(members)
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))


def artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "source"
    package = root / "src/daf_jev"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="daf-jev"\nversion="0.7.0"\nrequires-python=">=3.10"\n'
        'license="MIT"\nlicense-files=["LICENSE"]\nclassifiers=["Typing :: Typed"]\n'
        '''dependencies=["httpx>=0.27.0", "tomli>=1.1.0; python_version < '3.11'"]\n'''
        '[project.urls]\nRepository="https://github.com/docxology/daf-jev"\n'
        '[project.scripts]\ndaf-jev="daf_jev.cli:main"\n'
        '[project.optional-dependencies]\nfigures=["matplotlib>=3.7,<4"]\nmcp=["mcp>=1.2,<2"]\n'
    )
    (root / "README.md").write_text("A literal fixture description.\n")
    (root / "LICENSE").write_text("MIT license fixture\n")
    (package / "__init__.py").write_text('__version__="0.7.0"\n')
    (package / "py.typed").write_text("")
    wheel = tmp_path / "fixture.whl"
    prefix = "daf_jev-0.7.0.dist-info/"
    metadata = (
            b"Metadata-Version: 2.4\nName: daf-jev\nVersion: 0.7.0\n"
            b"Requires-Python: >=3.10\nLicense-Expression: MIT\n"
            b"Description-Content-Type: text/markdown\n"
            b"Project-URL: Repository, https://github.com/docxology/daf-jev\n"
            b"Classifier: Typing :: Typed\nLicense-File: LICENSE\n"
            b"Requires-Dist: httpx>=0.27.0\nRequires-Dist: tomli>=1.1.0; python_version < \"3.11\"\n"
            b'Provides-Extra: figures\nRequires-Dist: matplotlib<4,>=3.7; extra == "figures"\n'
            b'Provides-Extra: mcp\nRequires-Dist: mcp<2,>=1.2; extra == "mcp"\n'
            b"\nA literal fixture description.\n"
        )
    entries = b"[console_scripts]\ndaf-jev = daf_jev.cli:main\n"
    write_wheel(wheel, {"daf_jev/__init__.py": (package / "__init__.py").read_bytes(),
                       "daf_jev/py.typed": b"", prefix + "METADATA": metadata,
                       prefix + "licenses/LICENSE": (root / "LICENSE").read_bytes(),
                       prefix + "entry_points.txt": entries, prefix + "top_level.txt": b"daf_jev\n",
                       prefix + "WHEEL": b"Wheel-Version: 1.0\nGenerator: setuptools (84.0.0)\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"})
    egg = root / "src/daf_jev.egg-info"
    egg.mkdir()
    (egg / "PKG-INFO").write_bytes(metadata)
    (egg / "entry_points.txt").write_bytes(entries)
    (egg / "top_level.txt").write_bytes(b"daf_jev\n")
    (egg / "dependency_links.txt").write_bytes(b"\n")
    (egg / "requires.txt").write_text('httpx>=0.27.0\n\n[:python_version < "3.11"]\ntomli>=1.1.0\n\n[figures]\nmatplotlib<4,>=3.7\n\n[mcp]\nmcp<2,>=1.2\n')
    names = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    (egg / "SOURCES.txt").write_text("\n".join(sorted(names | {"src/daf_jev.egg-info/SOURCES.txt"})) + "\n")
    (root / "PKG-INFO").write_bytes(metadata)
    (root / "setup.cfg").write_text("[egg_info]\ntag_build = \ntag_date = 0\n\n")
    sdist = tmp_path / "fixture.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.add(path, arcname="daf_jev-0.7.0/" + path.relative_to(root).as_posix())
    return root, wheel, sdist


def test_exact_archive_inputs_and_receipt(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    result = INSPECTOR.inspect_artifacts(root, wheel, sdist)
    assert result["typed_marker"] and result["hosted_requests"] == 0
    assert result["source_files"]["__init__.py"] == INSPECTOR.digest((root / "src/daf_jev/__init__.py").read_bytes())
    assert result["wheel"]["sha256"] == INSPECTOR.digest(wheel.read_bytes())


@pytest.mark.parametrize("member", ["../escape", "/absolute", "other-package/hidden", "daf_jev/.env", "daf_jev/private.json"])
def test_unsafe_or_private_wheel_payload_refused(tmp_path: Path, member: str) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(member, "not a credential")
    with pytest.raises(ValueError):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_duplicate_wheel_member_refused(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    with zipfile.ZipFile(wheel, "a") as archive, pytest.warns(UserWarning):
        archive.writestr("daf_jev/__init__.py", "contradictory")
    with pytest.raises(ValueError, match="duplicate"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_stale_wheel_source_refused(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    (root / "src/daf_jev/__init__.py").write_text("# source changed after build\n")
    with pytest.raises(ValueError, match="source files differ"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_stale_wheel_description_refused(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    (root / "README.md").write_text("New reviewable release description.\n")
    with pytest.raises(ValueError, match="description differs"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_stale_wheel_typing_marker_refused(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    (root / "src/daf_jev/py.typed").write_text("partial\n")
    with pytest.raises(ValueError, match="typed marker missing or changed"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_sdist_link_refused(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    with tarfile.open(sdist, "r:gz") as original:
        members = [(m, original.extractfile(m).read()) for m in original.getmembers() if m.isfile()]
    with tarfile.open(sdist, "w:gz") as archive:
        for entry, content in members:
            archive.addfile(entry, io.BytesIO(content))
        link = tarfile.TarInfo("daf_jev-0.7.0/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    with pytest.raises(ValueError, match="linked sdist"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def checker_command(root: Path, wheel: Path, sdist: Path, output: Path) -> list[str]:
    assert SPEC.origin is not None
    return [sys.executable, SPEC.origin, "--source-root", str(root),
            "--wheel", str(wheel), "--sdist", str(sdist), "--output", str(output)]


def test_existing_receipt_is_preserved(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    output = tmp_path / "receipt.json"
    output.write_bytes(b"previous retained receipt\n")
    result = subprocess.run(checker_command(root, wheel, sdist, output), capture_output=True,
                            text=True, check=False, timeout=10)
    assert result.returncode == 1 and "receipt already exists" in result.stderr
    assert output.read_bytes() == b"previous retained receipt\n"


def test_malformed_archive_fails_without_receipt(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    wheel.write_bytes(b"not a zip archive")
    output = tmp_path / "receipt.json"
    result = subprocess.run(checker_command(root, wheel, sdist, output), capture_output=True,
                            text=True, check=False, timeout=10)
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("before,after,reason", [
    (b"Requires-Dist: httpx>=0.27.0\n", b"Requires-Dist: httpx>=0.27.0\nRequires-Dist: numpy>=2\n", "dependencies"),
    (b"Requires-Dist: httpx>=0.27.0\n", b"", "dependencies"),
    (b'python_version < "3.11"', b'python_version >= "3.11"', "dependencies"),
    (b' extra == "figures"', b' extra == "mcp"', "dependencies"),
    (b"Provides-Extra: figures\n", b"Provides-Extra: unknown\n", "extras"),
    (b"Provides-Extra: figures\n", b"Provides-Extra: figures\nProvides-Extra: figures\n", "extras"),
    (b"Classifier: Typing :: Typed", b"Classifier: Development Status :: 5 - Production/Stable", "classifiers"),
    (b"Project-URL: Repository, https://github.com/docxology/daf-jev", b"Project-URL: Repository, https://example.invalid/elsewhere", "links"),
    (b"Name: daf-jev\n", b"Name: daf-jev\nName: another-package\n", "metadata"),
    (b"License-File: LICENSE\n", b"License-File: LICENSE\nPrivate-Record: inert sentinel\n", "header"),
])
def test_undeclared_wheel_metadata_refused_with_valid_record(
    tmp_path: Path, before: bytes, after: bytes, reason: str,
) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    members = wheel_members(wheel)
    key = "daf_jev-0.7.0.dist-info/METADATA"
    assert before in members[key]
    members[key] = members[key].replace(before, after)
    write_wheel(wheel, members)
    with pytest.raises(ValueError, match=reason):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


@pytest.mark.parametrize("addition", [
    b"undeclared-command = fixture_only:main\n",
    b"\n[gui_scripts]\nundeclared-command = fixture_only:main\n",
    b"\n[plugin_group]\nplugin = fixture_only:main\n",
])
def test_complete_entrypoint_contract_refuses_extra_commands(tmp_path: Path, addition: bytes) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    members = wheel_members(wheel)
    members["daf_jev-0.7.0.dist-info/entry_points.txt"] += addition
    write_wheel(wheel, members)
    with pytest.raises(ValueError, match="entry points"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


@pytest.mark.parametrize("member", [
    "daf_jev-0.7.0.dist-info/private-user-record.json",
    "daf_jev-0.7.0.dist-info/licenses/extra-private-record.txt",
])
def test_metadata_payload_allowlist_refuses_inert_private_records(tmp_path: Path, member: str) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    members = wheel_members(wheel)
    members[member] = b"inert private record fixture"
    write_wheel(wheel, members)
    with pytest.raises(ValueError, match="payload"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_record_must_bind_exact_member_bytes(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    members = wheel_members(wheel)
    members["daf_jev-0.7.0.dist-info/RECORD"] = members["daf_jev-0.7.0.dist-info/RECORD"].replace(b"sha256=", b"sha999=", 1)
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="RECORD"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


@pytest.mark.parametrize("name,content,reason", [
    ("private-user-record.json", b"inert sentinel", "payload"),
    ("src/daf_jev.egg-info/private-user-record.json", b"inert sentinel", "payload"),
    ("tests/private-user-record.json", b"inert sentinel", "payload"),
    ("src/daf_jev.egg-info/requires.txt", b"httpx>=0.27.0\nnumpy>=2\n", "dependencies"),
    ("src/daf_jev.egg-info/entry_points.txt", b"[console_scripts]\ndaf-jev=daf_jev.cli:main\nextra=fixture:main\n", "entry points"),
    ("src/daf_jev.egg-info/dependency_links.txt", b"https://example.invalid/hidden\n", "declaration"),
    ("src/daf_jev.egg-info/SOURCES.txt", b"../escape\n", "SOURCES"),
    ("setup.cfg", b"[egg_info]\ntag_build=\ntag_date=0\n[install]\ncommand=inert\n", "setup configuration"),
])
def test_sdist_payload_and_consumed_build_metadata_refused(
    tmp_path: Path, name: str, content: bytes, reason: str,
) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    rewrite_sdist(sdist, lambda members: members.update({"daf_jev-0.7.0/" + name: content}))
    with pytest.raises(ValueError, match=reason):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_sdist_current_test_source_is_allowed_but_stale_test_is_not(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    test = root / "tests/unit/test_owned.py"
    test.parent.mkdir(parents=True)
    test.write_text("def test_literal():\n    assert True\n")
    def add_current_test(members):
        members["daf_jev-0.7.0/tests/unit/test_owned.py"] = test.read_bytes()
        members["daf_jev-0.7.0/src/daf_jev.egg-info/SOURCES.txt"] += b"tests/unit/test_owned.py\n"
    rewrite_sdist(sdist, add_current_test)
    assert INSPECTOR.inspect_artifacts(root, wheel, sdist)["dependencies_and_extras_equal"] is True
    test.write_text("# changed test after build\n")
    with pytest.raises(ValueError, match="test source bytes"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)


def test_legitimate_specifier_order_quotes_and_dependency_name_normalization(tmp_path: Path) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    members = wheel_members(wheel)
    key = "daf_jev-0.7.0.dist-info/METADATA"
    members[key] = members[key].replace(b"matplotlib<4,>=3.7", b"Matplotlib>=3.7,<4").replace(b'python_version < "3.11"', b"python_version < '3.11'")
    write_wheel(wheel, members)
    assert INSPECTOR.inspect_artifacts(root, wheel, sdist)["dependencies_and_extras_equal"] is True


@pytest.mark.parametrize("archive", ["wheel", "sdist"])
def test_consumed_ini_metadata_comments_cannot_carry_unknown_payload(tmp_path: Path, archive: str) -> None:
    root, wheel, sdist = artifacts(tmp_path)
    inert = b"\n# inert private-record sentinel\n"
    if archive == "wheel":
        members = wheel_members(wheel)
        members["daf_jev-0.7.0.dist-info/entry_points.txt"] += inert
        write_wheel(wheel, members)
    else:
        def comment(members):
            members["daf_jev-0.7.0/setup.cfg"] += inert
        rewrite_sdist(sdist, comment)
    with pytest.raises(ValueError, match="unexpected comments"):
        INSPECTOR.inspect_artifacts(root, wheel, sdist)
