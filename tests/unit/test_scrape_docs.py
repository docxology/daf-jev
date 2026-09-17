"""Unit tests for scripts/scrape_docs.py --check mode (no network, no writes).

The script is standalone (stdlib urllib) and lives outside the package, so it
is loaded via importlib.util from its file path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "scrape_docs.py"


def load_script():
    spec = importlib.util.spec_from_file_location("scrape_docs_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_fixture(root: Path) -> Path:
    pages = {
        "introduction.md": "# Introduction\n\nhello\n",
        "concepts/system-one.md": "# System One\n\nbody text\n",
    }
    entries: dict[str, Any] = {}
    for rel, text in pages.items():
        page = root / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        entries[rel] = {
            "title": rel,
            "url": f"https://docs.typesafe.ai/{rel}",
            "sha256": digest,
            "bytes": len(text.encode("utf-8")),
        }
    concatenated = "".join(entries[rel]["sha256"] for rel in entries)
    manifest = {
        "source": "test fixture",
        "base_url": "https://docs.typesafe.ai",
        "index_url": "https://docs.typesafe.ai/llms.txt",
        "scraped_at_utc": "2026-09-16T00:00:00Z",
        "index_sha256": "0" * 64,
        "page_count": len(entries),
        "pages": entries,
        "snapshot_id": hashlib.sha256(concatenated.encode("utf-8")).hexdigest()[:16],
    }
    manifest_path = root / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def run_check(module, manifest_path: Path) -> int:
    """Invoke the script's --check mode; tolerate either flag or positional form.

    A usage exit (2) means that argv form was not accepted; the next form is
    tried. Only a real verdict (0 = match, 1 = drift) is returned.
    """
    forms = (
        ["--check", "--manifest", str(manifest_path)],
        ["--check", str(manifest_path)],
        [str(manifest_path), "--check"],
    )
    codes: list[int] = []
    for argv in forms:
        try:
            code = module.main(argv)
        except SystemExit as exc:
            code = exc.code
        code = 0 if code is None else int(code)
        if code in (0, 1):
            return code
        codes.append(code)
    pytest.fail(f"scrape_docs --check never returned 0/1; got {codes}")


def test_check_matches_fixture(tmp_path: Path) -> None:
    module = load_script()
    manifest = build_fixture(tmp_path)
    before = manifest.read_bytes()
    assert run_check(module, manifest) == 0
    assert manifest.read_bytes() == before  # --check writes nothing


def test_check_detects_drift(tmp_path: Path) -> None:
    module = load_script()
    manifest = build_fixture(tmp_path)
    page = tmp_path / "introduction.md"
    page.write_text(page.read_text() + "drift\n", encoding="utf-8")
    assert run_check(module, manifest) == 1


def test_check_detects_missing_page(tmp_path: Path) -> None:
    module = load_script()
    manifest = build_fixture(tmp_path)
    (tmp_path / "concepts" / "system-one.md").unlink()
    assert run_check(module, manifest) == 1


def test_check_matches_real_snapshot(tmp_path: Path) -> None:
    module = load_script()
    assert run_check(module, PROJECT_ROOT / "docs" / "reference" / "MANIFEST.json") == 0
