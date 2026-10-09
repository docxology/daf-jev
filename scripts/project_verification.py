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
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from daf_jev._json import strict_json_loads  # noqa: E402


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def project(root: Path, capture: Path, out: Path) -> Path:
    """Write a fresh confined derivative, without changing its original files."""
    root = root.absolute()
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
        substitutions[command[0]] = "<PYTHON_EXECUTABLE>"
    def display(text: str) -> str:
        for old, new in sorted(substitutions.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(old, new)
        if "/Users/" in text or "/home/" in text or "sk-or-" in text:
            raise ValueError("unrecognized private data in projection")
        return text
    emitted = {key: display(raw.decode("utf-8")).encode("utf-8")
               for key, raw in originals.items() if key != "junit"}
    xml = originals["junit"].decode("utf-8")
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("JUnit declarations are unsupported")
    tree = ET.fromstring(xml)
    removed = sum("hostname" in node.attrib for node in tree.iter())
    for node in tree.iter():
        node.attrib.pop("hostname", None)
    emitted["junit"] = display(ET.tostring(tree, encoding="unicode")).encode("utf-8")
    for key in ("unit_command", "live_collection_command"):
        record[key] = [display(x) for x in record[key]]
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
    # Validate every field before publishing anything, including environment
    # and optional record metadata rather than commands/artifact text alone.
    record = relocate(record)
    projection: dict[str, Any] = {
        "format": "dafjev.verification-public-projection/1",
        "original_record_sha256": _hash(raw_record),
        "original_files_sha256": {k: _hash(v) for k, v in originals.items()},
        "transformations": ["relocate project-root display", "relocate interpreter display",
                            "remove JUnit hostname attributes; serialize XML"],
        "removed_hostname_attributes": removed,
        "commands_are_relocated_display": True,
        "original_native_capture_retained_privately": True,
    }
    out.mkdir(parents=True, exist_ok=False)
    names = {"coverage": "coverage.json", "junit": "junit.xml",
             "live_collection": "live-collection.txt", "unit_log": "unit.txt"}
    for key, data in emitted.items():
        destination = out / names[key]
        destination.write_bytes(data)
        record[key] = {"path": destination.relative_to(root).as_posix(), "sha256": _hash(data)}
    record["public_projection"] = projection
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
