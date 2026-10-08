#!/usr/bin/env python3
"""Check exact wheel/sdist bytes and an optionally installed core package.

No package is installed by this script. The optional interpreter runs only a
real owned loopback HTTP fixture, with explicit fake credentials and no models.
Run it from a fresh directory outside the checkout and pass --python after
installing the reviewed wheel into a fresh core-only environment.
"""
from __future__ import annotations

import argparse
import ast
import base64
import configparser
import csv
import hashlib
import json
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections import Counter
from email.parser import Parser
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _name(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("unsafe archive member path")


def _members(data: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    directories: set[str] = set()
    with zipfile.ZipFile(BytesIO(data)) as archive:
        seen: set[str] = set()
        for entry in archive.infolist():
            _name(entry.filename)
            if entry.filename in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("duplicate or symbolic archive member")
            seen.add(entry.filename)
            if entry.is_dir():
                directories.add(entry.filename.rstrip("/"))
            else:
                result[entry.filename] = archive.read(entry)
    if not directories <= _parents(result):
        raise ValueError("unexpected archive directory")
    return result


def _parents(names: Any) -> set[str]:
    return {parent.as_posix() for name in names for parent in PurePosixPath(name).parents
            if parent.as_posix() != "."}


def _normalized_name(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is None:
        raise ValueError("invalid dependency or extra name")
    return re.sub(r"[-_.]+", "-", value).lower()


def _marker(value: str) -> tuple[str, ...]:
    # Compare literal declarations; do not evaluate markers or import packages.
    tokens: list[str] = []
    pattern = re.compile(r'''\s*(('[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*"|===|~=|==|!=|<=|>=|<|>|\(|\)|[A-Za-z_][A-Za-z0-9_]*))''')
    remaining = value.strip()
    while remaining:
        match = pattern.match(remaining)
        if match is None:
            raise ValueError("unsupported dependency marker syntax")
        token = match[1]
        if token.startswith(("'", '"')):
            token = json.dumps(ast.literal_eval(token), ensure_ascii=True)
        tokens.append(token)
        remaining = remaining[match.end():]
    return tuple(tokens)


def _requirement(value: str) -> tuple[Any, ...]:
    declaration, separator, marker = value.partition(";")
    match = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[([^\]]+)\])?\s*(.*?)\s*", declaration)
    if match is None:
        raise ValueError("unsupported dependency declaration")
    extras = tuple(sorted(_normalized_name(x.strip()) for x in (match[2] or "").split(",") if x))
    specifiers = match[3].strip()
    if specifiers.startswith("(") and specifiers.endswith(")"):
        specifiers = specifiers[1:-1].strip()
    specs = []
    for specification in specifiers.split(",") if specifiers else []:
        part = re.fullmatch(r"\s*(===|~=|==|!=|<=|>=|<|>)\s*([A-Za-z0-9.*+!_-]+)\s*", specification)
        if part is None:
            raise ValueError("unsupported dependency version syntax")
        specs.append(part[1] + part[2])
    return _normalized_name(match[1]), extras, tuple(sorted(specs)), _marker(marker) if separator else ()


def _extra_requirement(requirement: str, extra: str) -> str:
    base, separator, marker = requirement.partition(";")
    condition = f"extra == {json.dumps(_normalized_name(extra))}"
    return base + "; " + (f"({marker.strip()}) and " if separator else "") + condition


def _declared_requirements(project: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    requirements = list(project.get("dependencies", []))
    for extra, dependencies in project.get("optional-dependencies", {}).items():
        requirements.extend(_extra_requirement(item, extra) for item in dependencies)
    return Counter(_requirement(item) for item in requirements)


def _metadata(raw: bytes, project: dict[str, Any], readme: str) -> None:
    metadata = Parser().parsestr(raw.decode("utf-8"))
    allowed_headers = {"metadata-version", "name", "version", "summary", "author", "keywords",
                       "license-expression", "project-url", "classifier", "requires-python",
                       "description-content-type", "license-file", "requires-dist", "provides-extra", "dynamic"}
    if any(key.lower() not in allowed_headers for key in metadata):
        raise ValueError("unexpected package metadata header")
    expected = {"Metadata-Version": "2.4", "Name": project["name"], "Version": project["version"],
                "Requires-Python": project["requires-python"], "License-Expression": project["license"],
                "Description-Content-Type": "text/markdown"}
    for field, value in (("Summary", project.get("description")),
                         ("Author", ", ".join(item["name"] for item in project.get("authors", [])) or None),
                         ("Keywords", ",".join(project.get("keywords", [])) or None)):
        if value is not None:
            expected[field] = value
        elif metadata.get_all(field):
            raise ValueError("undeclared package metadata value")
    if any(metadata.get_all(key) != [value] for key, value in expected.items()):
        raise ValueError("package metadata disagrees with source contract")
    description = metadata.get_payload()
    if not isinstance(description, str) or description.strip() != readme.strip() or not description.strip():
        raise ValueError("package description differs from source README")
    if Counter(metadata.get_all("Project-URL", [])) != Counter(f"{name}, {url}" for name, url in project.get("urls", {}).items()):
        raise ValueError("package project links differ from source")
    if Counter(metadata.get_all("Classifier", [])) != Counter(project.get("classifiers", [])):
        raise ValueError("package classifiers differ from source")
    if Counter(metadata.get_all("License-File", [])) != Counter(project.get("license-files", [])):
        raise ValueError("package license files differ from source")
    if Counter(_requirement(item) for item in metadata.get_all("Requires-Dist", [])) != _declared_requirements(project):
        raise ValueError("package dependencies differ from source")
    if Counter(_normalized_name(item) for item in metadata.get_all("Provides-Extra", [])) != Counter(
            _normalized_name(item) for item in project.get("optional-dependencies", {})):
        raise ValueError("package extras differ from source")
    if metadata.get_all("Dynamic", []) not in ([], ["license-file"]):
        raise ValueError("unexpected dynamic package metadata")


class _CaseSensitiveConfig(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _literal_ini(raw: bytes) -> str:
    text = raw.decode("utf-8")
    if any(line.lstrip().startswith(("#", ";")) for line in text.splitlines()):
        raise ValueError("unexpected comments in generated package metadata")
    return text


def _entry_points(raw: bytes, project: dict[str, Any]) -> None:
    expected = dict(project.get("entry-points", {}))
    for key, section in (("scripts", "console_scripts"), ("gui-scripts", "gui_scripts")):
        if project.get(key):
            if section in expected:
                raise ValueError("conflicting project entry point groups")
            expected[section] = project[key]
    config = _CaseSensitiveConfig(interpolation=None)
    config.read_string(_literal_ini(raw))
    actual = {section: dict(config.items(section)) for section in config.sections()}
    if config.defaults() or actual != expected:
        raise ValueError("package entry points differ from source")


def _record(raw: bytes, members: dict[str, bytes], record_name: str) -> None:
    rows = list(csv.reader(StringIO(raw.decode("utf-8"))))
    if any(len(row) != 3 for row in rows) or len({row[0] for row in rows}) != len(rows):
        raise ValueError("invalid wheel RECORD")
    if {row[0] for row in rows} != set(members):
        raise ValueError("wheel RECORD members differ")
    for name, hashed, size in rows:
        expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(members[name]).digest()).decode().rstrip("=")
        if (hashed, size) != (("", "") if name == record_name else (expected, str(len(members[name])))):
            raise ValueError("wheel RECORD bytes differ")


def _egg_requirements(raw: bytes, project: dict[str, Any]) -> None:
    extra = marker = ""
    declarations = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        if line.startswith("[") and line.endswith("]"):
            extra, _, marker = line[1:-1].partition(":")
            if extra and _normalized_name(extra) not in project.get("optional-dependencies", {}):
                raise ValueError("undeclared egg-info extra")
        else:
            declaration = line + ("; " + marker if marker else "")
            declarations.append(_extra_requirement(declaration, extra) if extra else declaration)
    if Counter(_requirement(item) for item in declarations) != _declared_requirements(project):
        raise ValueError("egg-info dependencies differ from source")


def inspect_artifacts(root: Path, wheel: Path, sdist: Path) -> dict[str, Any]:
    project_bytes = (root / "pyproject.toml").read_bytes()
    project = tomllib.loads(project_bytes.decode())["project"]
    source_bytes = {p.name: p.read_bytes() for p in sorted((root / "src/daf_jev").glob("*.py"))}
    source = {name: digest(data) for name, data in source_bytes.items()}
    if not source or not (root / "src/daf_jev/py.typed").is_file():
        raise ValueError("source package or typed marker missing")
    wheel_bytes, sdist_bytes = wheel.read_bytes(), sdist.read_bytes()
    members = _members(wheel_bytes)
    readme = (root / "README.md").read_text(encoding="utf-8")
    distribution = project["name"].replace("-", "_")
    metadata_prefix = f"{distribution}-{project['version']}.dist-info/"
    metadata_files = {"METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD", "licenses/LICENSE"}
    expected_package = {"daf_jev/" + name for name in source} | {"daf_jev/py.typed"}
    if set(members) != expected_package | {metadata_prefix + name for name in metadata_files}:
        raise ValueError("wheel contains unexpected or missing payload")
    _metadata(members[metadata_prefix + "METADATA"], project, readme)
    if members.get("daf_jev/py.typed") != (root / "src/daf_jev/py.typed").read_bytes():
        raise ValueError("wheel typed marker missing or changed")
    actual = {n.removeprefix("daf_jev/"): digest(data) for n, data in members.items()
              if n.startswith("daf_jev/") and n.endswith(".py")}
    if actual != source:
        raise ValueError("wheel source files differ from the current package")
    if members[metadata_prefix + "licenses/LICENSE"] != (root / "LICENSE").read_bytes():
        raise ValueError("wheel license differs from source")
    _entry_points(members[metadata_prefix + "entry_points.txt"], project)
    if members[metadata_prefix + "top_level.txt"].decode("utf-8") != "daf_jev\n":
        raise ValueError("unexpected wheel top-level declaration")
    wheel_metadata = Parser().parsestr(members[metadata_prefix + "WHEEL"].decode("utf-8"))
    if (set(key.lower() for key in wheel_metadata) != {"wheel-version", "generator", "root-is-purelib", "tag"}
            or any(wheel_metadata.get_all(key) != [value] for key, value in {
                "Wheel-Version": "1.0", "Root-Is-Purelib": "true", "Tag": "py3-none-any"}.items())
            or len(wheel_metadata.get_all("Generator", [])) != 1
            or re.fullmatch(r"setuptools \([0-9][A-Za-z0-9.+_-]*\)", wheel_metadata["Generator"]) is None
            or str(wheel_metadata.get_payload()).strip()):
        raise ValueError("unexpected wheel format declaration")
    _record(members[metadata_prefix + "RECORD"], members, metadata_prefix + "RECORD")
    source_members: dict[str, bytes] = {}
    directories = set()
    with tarfile.open(fileobj=BytesIO(sdist_bytes)) as archive:
        seen = set()
        for entry in archive.getmembers():
            _name(entry.name)
            if entry.name in seen or not (entry.isfile() or entry.isdir()):
                raise ValueError("duplicate or linked sdist member")
            seen.add(entry.name)
            if entry.isdir():
                directories.add(entry.name.rstrip("/"))
            else:
                stream = archive.extractfile(entry)
                if stream is None:
                    raise ValueError("unreadable sdist member")
                source_members[entry.name] = stream.read()
    prefixes = {PurePosixPath(n).parts[0] for n in source_members}
    if len(prefixes) != 1:
        raise ValueError("sdist must have one root")
    prefix = prefixes.pop() + "/"
    if prefix != f"{distribution}-{project['version']}/" or not directories <= _parents(source_members):
        raise ValueError("unexpected sdist root or directory")
    expected = {"pyproject.toml": project_bytes,
                "README.md": (root / "README.md").read_bytes(),
                "LICENSE": (root / "LICENSE").read_bytes(),
                "src/daf_jev/py.typed": (root / "src/daf_jev/py.typed").read_bytes()}
    expected.update({"src/daf_jev/" + n: data for n, data in source_bytes.items()})
    if any(source_members.get(prefix + n) != data for n, data in expected.items()):
        raise ValueError("sdist required source bytes differ")
    egg_prefix = f"src/{distribution}.egg-info/"
    egg_names = {"PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt"}
    allowed_source = set(expected) | {"PKG-INFO", "setup.cfg"} | {egg_prefix + name for name in egg_names}
    allowed_tests = {path.relative_to(root).as_posix(): path.read_bytes()
                     for path in (root / "tests").rglob("*.py") if not path.is_symlink() and "__pycache__" not in path.parts}
    relative_members = {name.removeprefix(prefix): data for name, data in source_members.items()}
    if not allowed_source <= set(relative_members) or not set(relative_members) <= allowed_source | set(allowed_tests):
        raise ValueError("sdist contains unexpected or missing payload")
    if any(relative_members[name] != allowed_tests[name] for name in set(relative_members) & set(allowed_tests)):
        raise ValueError("sdist test source bytes differ")
    for name in ("PKG-INFO", egg_prefix + "PKG-INFO"):
        _metadata(relative_members[name], project, readme)
    _entry_points(relative_members[egg_prefix + "entry_points.txt"], project)
    _egg_requirements(relative_members[egg_prefix + "requires.txt"], project)
    if (relative_members[egg_prefix + "dependency_links.txt"].strip()
            or relative_members[egg_prefix + "top_level.txt"] != b"daf_jev\n"):
        raise ValueError("unexpected egg-info package declaration")
    sources = relative_members[egg_prefix + "SOURCES.txt"].decode("utf-8").splitlines()
    if len(set(sources)) != len(sources) or set(sources) != set(relative_members) - {"PKG-INFO", "setup.cfg"}:
        raise ValueError("sdist SOURCES members differ")
    setup = configparser.ConfigParser(interpolation=None)
    setup.read_string(_literal_ini(relative_members["setup.cfg"]))
    if (setup.defaults() or setup.sections() != ["egg_info"]
            or dict(setup.items("egg_info")) != {"tag_build": "", "tag_date": "0"}):
        raise ValueError("unexpected generated sdist setup configuration")
    return {"format": "dafjev.release-package-check/1", "version": project["version"],
            "source_files": source, "typed_marker": True,
            "wheel": {"name": wheel.name, "sha256": digest(wheel_bytes), "bytes": len(wheel_bytes)},
            "sdist": {"name": sdist.name, "sha256": digest(sdist_bytes), "bytes": len(sdist_bytes)},
            "metadata_links": [f"{name}, {url}" for name, url in project.get("urls", {}).items()],
            "wheel_members": sorted(members), "sdist_members": sorted(source_members),
            "dependencies_and_extras_equal": True, "entry_points_equal": True,
            "hosted_requests": 0}


INSTALLED_CHECK = r'''
import asyncio, hashlib, importlib.util, json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import daf_jev
from daf_jev import AsyncJevClient, JevClient, noul
expected=json.loads(sys.argv[1]);package=Path(daf_jev.__file__).parent
assert 'site-packages' in package.parts
files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in package.glob('*.py')}
assert files==expected['source_files'] and daf_jev.__version__==expected['version']
assert (package/'py.typed').is_file()
assert all(importlib.util.find_spec(n) is None for n in ('pytest','matplotlib','sklearn','psutil','mcp','pypdf'))
hits=[]
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        hits.append((self.path,list(request['questions']),self.client_address[1]))
        body=json.dumps({'id':'release-loopback','model':'fixture','answers':{'flag':{'type':'noul','noul':0.75}},'usage':{'input_tokens':7,'output_tokens':1}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base='http://127.0.0.1:'+str(server.server_port)
try:
    with JevClient(api_key='fixture',base_url=base,model='fixture') as client:
        assert client.ask('fixture',{'flag':noul('Allow?')}).nouls['flag'].noul==0.75
    async def run():
        async with AsyncJevClient(api_key='fixture',base_url=base,model='fixture') as client:
            for _ in range(2):assert (await client.ask('fixture',{'flag':noul('Allow?')})).nouls['flag'].noul==0.75
    asyncio.run(run())
finally:
    server.shutdown();server.server_close();thread.join(5)
assert not thread.is_alive() and len(hits)==3 and hits[1][2]==hits[2][2]
print(json.dumps({'python':sys.version.split()[0],'source_bytes_equal':True,'core_only':True,'loopback_requests':3,'async_connection_reused':True,'hosted_requests':0}))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument("--python", type=Path, help="Fresh installed core-only interpreter")
    parser.add_argument("--output", required=True, type=Path, help="Fresh receipt file")
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("receipt already exists")
        result = inspect_artifacts(args.source_root, args.wheel, args.sdist)
        if args.python is not None:
            completed = subprocess.run([str(args.python.absolute()), "-I", "-c", INSTALLED_CHECK,
                                        json.dumps(result)], cwd=args.output.absolute().parent,
                                       capture_output=True, text=True, timeout=60, check=True)
            result["installed"] = json.loads(completed.stdout)
        with args.output.open("x") as output:
            json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        print(json.dumps({"status": "passed", "version": result["version"],
                          "source_modules": len(result["source_files"])}))
        return 0
    except (OSError, ValueError, SyntaxError, KeyError, configparser.Error, csv.Error, zipfile.BadZipFile, tarfile.TarError,
            subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
