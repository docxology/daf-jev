#!/usr/bin/env python3
"""Create a declared public projection of a retained native verification capture.

The original capture stays immutable. Only command/path display and JUnit
hostname attributes are removed or relocated. Results, coverage and source
identities are retained. The projection binds each original and emitted file
by hash; it is explicitly a derivative, never a native byte-identical receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from daf_jev._json import strict_json_loads  # noqa: E402

_PRIVATE = re.compile(r"/Users/|/home/|/private/|/tmp/|[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+|~[\\/]", re.I)
_SECRET = re.compile(r"sk-or-|sk-[A-Za-z0-9_-]{12,}|(?:Bearer|Basic)\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)
_ESCAPED_CHARACTER = re.compile(r"\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2}))")


def _display_forms(text: str) -> list[str]:
    """Inspect common display encodings without modifying published evidence.

    JSON/XML inputs are also parsed in their own formats. These additional
    forms cover escaped log text and nested HTML/URL spellings; this is a
    bounded recognized-marker check, not a claim to detect arbitrary secrets.
    """
    forms = [text]
    for _ in range(8):
        decoded = _ESCAPED_CHARACTER.sub(lambda match: chr(int(match[1] or match[2], 16)),
                                         unquote(html.unescape(forms[-1])))
        if decoded == forms[-1]:
            return forms
        forms.append(decoded)
    raise ValueError("unrecognized nested display encoding in projection")


def _contains_secret(text: str) -> bool:
    return any(_SECRET.search(form) is not None for form in _display_forms(text))


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_path(value: str, *, context: str) -> Path:
    if (not value or "\\" in value or any(char.isspace() or ord(char) < 32 for char in value)
            or any(char in value for char in ('"', "'", "<", ">")) or _contains_secret(value)):
        raise ValueError(f"invalid captured {context}")
    path = Path(value)
    if value.startswith("//") or not path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise ValueError(f"captured {context} must be canonical and absolute")
    return path


def _interpreter(value: str) -> str:
    path = _canonical_path(value, context="interpreter path")
    if (path.parent.name != "bin" or re.fullmatch(r"python(?:3(?:\.\d+)?)?", path.name) is None
            or len(path.parts) < 4):
        raise ValueError("captured interpreter path must name a narrow Python executable")
    return value


def _stdlib_directory(record: dict[str, Any]) -> str | None:
    """Accept only the capture's explicit, version-specific POSIX stdlib path.

    There is no ambient interpreter lookup or inference from a command path.
    Legacy captures without this field receive no additional substitutions.
    """
    environment = record.get("environment")
    if not isinstance(environment, dict) or "stdlib_directory" not in environment:
        return None
    value = environment["stdlib_directory"]
    version = environment.get("python_version")
    match = re.fullmatch(r"(3)\.(\d+)\.\d+(?:[a-z]+\d+)?", version) if isinstance(version, str) else None
    if not isinstance(value, str) or match is None:
        raise ValueError("invalid captured stdlib directory")
    path = _canonical_path(value, context="stdlib directory")
    if (path.name != f"python{match[1]}.{match[2]}" or path.parent.name not in {"lib", "lib64"}
            or {"site-packages", "dist-packages"} & {part.lower() for part in path.parts}):
        raise ValueError("captured stdlib directory must be a narrow version-specific lib/python directory")
    return value


def _relocate_path(text: str, prefix: str, replacement: str, *, children: bool,
                   stdlib: bool = False) -> str:
    """Relocate one exact absolute path at both boundaries; never a substring."""
    pattern = re.compile(r"(?<![A-Za-z0-9_./\\-])" + re.escape(prefix)
                         + r"(?=/|$|[\s\"'<>),])(\/[^\s\"'<>]*)?")

    def replace(match: re.Match[str]) -> str:
        suffix = match[1] or ""
        if suffix:
            relative = Path(suffix[1:])
            if (not children or not suffix[1:] or "\\" in suffix or any(ord(char) < 32 for char in suffix)
                    or relative.as_posix() != suffix[1:] or relative.is_absolute() or ".." in relative.parts
                    or (stdlib and {"site-packages", "dist-packages"} & {part.lower() for part in relative.parts})):
                raise ValueError("unrecognized private data beneath captured path")
        return replacement + suffix

    relocated, count = pattern.subn(replace, text)
    if count != text.count(prefix):
        raise ValueError("unrecognized private data at captured path boundary")
    return relocated


def _relocate_stdlib(text: str, directory: str) -> str:
    return _relocate_path(text, directory, "<PYTHON_STDLIB>", children=True, stdlib=True)


def project(root: Path, capture: Path, out: Path) -> Path:
    """Write a fresh confined derivative, without changing its original files."""
    root = root.absolute()
    _canonical_path(str(root), context="project root")
    if not (root / "src/daf_jev").is_dir():
        raise ValueError("project root must name the captured package checkout")
    for path in (root, capture.absolute(), out.absolute()):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("projection paths must be nonsymlink")
    capture, out = capture.absolute(), out.absolute()
    if not capture.is_file() or not out.is_relative_to(root) or ".." in out.parts:
        raise ValueError("projection requires a capture file and confined fresh destination")
    raw_record = capture.read_bytes()
    record = strict_json_loads(raw_record)
    if (not isinstance(record, dict) or record.get("format") != "dafjev.verification-evidence/1"
            or record.get("public_projection") is not None
            or type(record.get("unit_exit_code")) is not int or record.get("unit_exit_code") != 0
            or type(record.get("live_collection_exit_code")) is not int or record.get("live_collection_exit_code") != 0
            or record.get("before") != record.get("after") or record.get("live_execution") is not False):
        raise ValueError("only a successful original native capture can be projected")
    originals: dict[str, bytes] = {}
    for key in ("coverage", "junit", "live_collection", "unit_log"):
        item = record[key]
        relative = Path(item["path"])
        source = root / relative
        if (relative.is_absolute() or ".." in relative.parts or not source.is_file()
                or source.is_symlink() or any(p.is_symlink() for p in source.parents)):
            raise ValueError("capture input must be regular, confined and nonsymlink")
        raw = source.read_bytes()
        if _hash(raw) != item["sha256"]:
            raise ValueError("original capture input changed")
        originals[key] = raw
    # Take command substitutions from the capture itself, never from ambient secrets.
    substitutions = {str(root): "<PROJECT_ROOT>"}
    for key in ("unit_command", "live_collection_command"):
        command = record[key]
        if (not isinstance(command, list) or not command
                or not all(isinstance(x, str) for x in command) or not command[0].strip()):
            raise ValueError("invalid original command")
        substitutions[_interpreter(command[0])] = "<PYTHON_EXECUTABLE>"
    stdlib = _stdlib_directory(record)
    def display(text: str) -> str:
        # Check before relocation too: a captured prefix cannot launder an
        # embedded credential marker by replacing the whole path.
        if _contains_secret(text):
            raise ValueError("unrecognized private data in projection")
        if stdlib is not None:
            text = _relocate_stdlib(text, stdlib)
        for old, new in sorted(substitutions.items(), key=lambda pair: -len(pair[0])):
            text = _relocate_path(text, old, new, children=new == "<PROJECT_ROOT>")
        if any(_PRIVATE.search(form) or _SECRET.search(form) for form in _display_forms(text)):
            raise ValueError("unrecognized private data in projection")
        return text
    def relocate(value: Any) -> Any:
        if isinstance(value, str):
            return display(value)
        if isinstance(value, list):
            return [relocate(item) for item in value]
        if isinstance(value, dict):
            result = {display(key): relocate(item) for key, item in value.items()}
            if len(result) != len(value):
                raise ValueError("projection key collision")
            return result
        return value
    emitted = {key: display(raw.decode("utf-8")).encode("utf-8")
               for key, raw in originals.items() if key not in {"junit", "coverage"}}
    # Decode before scanning: JSON escape spelling cannot hide private keys/values.
    coverage = strict_json_loads(originals["coverage"])
    if not isinstance(coverage, dict):
        raise ValueError("coverage export must be a JSON object")
    emitted["coverage"] = (json.dumps(relocate(coverage), sort_keys=True, ensure_ascii=False,
                                     allow_nan=False) + "\n").encode("utf-8")
    xml = originals["junit"].decode("utf-8")
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("JUnit declarations are unsupported")
    tree = ET.fromstring(xml)
    removed = sum("hostname" in node.attrib for node in tree.iter())
    for node in tree.iter():
        node.attrib.pop("hostname", None)
        # Inspect parsed values before XML serialization can encode whitespace
        # inside attributes and hide a credential scheme from the scanner.
        node.tag = display(node.tag)
        node.attrib = relocate(node.attrib)
        if node.text is not None:
            node.text = display(node.text)
        if node.tail is not None:
            node.tail = display(node.tail)
    emitted["junit"] = display(ET.tostring(tree, encoding="unicode")).encode("utf-8")
    for key in ("unit_command", "live_collection_command"):
        record[key] = [display(x) for x in record[key]]
    # Validate every field before publishing anything, including environment
    # and optional record metadata rather than commands/artifact text alone.
    record = relocate(record)
    projection: dict[str, Any] = {
        "format": "dafjev.verification-public-projection/1",
        "original_record_sha256": _hash(raw_record),
        "original_files_sha256": {k: _hash(v) for k, v in originals.items()},
        "transformations": ["relocate project-root display", "relocate interpreter display",
                            *(["relocate exactly captured version-specific stdlib-directory display"] if stdlib is not None else []),
                            "strictly decode coverage JSON; relocate string keys/values; serialize JSON",
                            "remove JUnit hostname attributes; inspect decoded XML values; serialize XML",
                            "reject recognized credential and private-path markers in decoded display forms"],
        "removed_hostname_attributes": removed,
        "commands_are_relocated_display": True,
        "original_native_capture_retained_privately": True,
    }
    names = {"coverage": "coverage.json", "junit": "junit.xml",
             "live_collection": "live-collection.txt", "unit_log": "unit.txt"}
    # Generated destination references are publication data too. Assemble and
    # inspect the final record before creating any directory or derivative.
    display(str(out))
    for key, data in emitted.items():
        destination = out / names[key]
        record[key] = {"path": destination.relative_to(root).as_posix(), "sha256": _hash(data)}
    record["public_projection"] = projection
    record = relocate(record)
    out.mkdir(parents=True, exist_ok=False)
    for key, data in emitted.items():
        (out / names[key]).write_bytes(data)
    destination = out / "verification.json"
    destination.write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(project(ROOT, args.capture, args.out_dir))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
