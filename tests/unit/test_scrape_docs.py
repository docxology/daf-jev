"""Unit tests for scripts/scrape_docs.py --check mode and prune-on-refresh.

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


# ----------------------------------------------------------- full rescrape ----


def test_full_rescrape_writes_snapshot_and_check_passes(
    stub, tmp_path: Path, capsys
) -> None:
    """Real HTTP via the conftest stub: index + pages -> files + manifest."""
    module = load_script()
    index_text = (
        "# TypeSafe docs\n"
        "- [Intro](introduction.md)\n"
        "- [System One](concepts/system-one.md)\n"
    )
    pages = {
        "introduction.md": b"# Introduction\n\nhello\n",
        "concepts/system-one.md": b"# System One\n\nbody text\n",
    }
    stub.enqueue(text=index_text)
    for body in pages.values():
        stub.enqueue(text=body.decode("utf-8"))

    out_dir = tmp_path / "reference"
    code = module.main(
        [
            "--index-url",
            f"{stub.base_url}/llms.txt",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["page_count"] == 2

    for rel, body in pages.items():
        assert (out_dir / rel).read_bytes() == body

    manifest = json.loads(
        (out_dir / "MANIFEST.json").read_text(encoding="utf-8")
    )
    hashes: list[str] = []
    for rel, body in pages.items():
        entry = manifest["pages"][rel]
        assert entry["sha256"] == hashlib.sha256(body).hexdigest()
        assert entry["bytes"] == len(body)
        hashes.append(entry["sha256"])
    assert manifest["page_count"] == 2
    assert manifest["snapshot_id"] == module.snapshot_id(hashes)
    assert manifest["index_sha256"] == hashlib.sha256(
        index_text.encode("utf-8")
    ).hexdigest()

    # The freshly written snapshot verifies offline with no network.
    assert run_check(module, out_dir / "MANIFEST.json") == 0


def test_hostile_index_url_never_writes_outside_out_dir(
    stub, tmp_path: Path, capsys
) -> None:
    module = load_script()
    stub.enqueue(text="- [Evil](..hidden/pwned.md)\n")
    out_dir = tmp_path / "reference"
    code = module.main(
        [
            "--index-url",
            f"{stub.base_url}/llms.txt",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "ValueError"
    assert "unsafe relative path" in payload["message"]
    # The rejection happened before any page fetch or write.
    assert len(stub.hits) == 1  # only the index itself was fetched
    assert not out_dir.exists()
    assert not list(tmp_path.rglob("*pwned*"))

    # Unit pin: the '..' rejection lives in rel_from_url itself.
    with pytest.raises(ValueError, match="unsafe relative path"):
        module.rel_from_url(f"{stub.base_url}/..hidden/pwned.md")


def test_zero_timeout_is_a_usage_error(capsys) -> None:
    module = load_script()
    with pytest.raises(SystemExit) as excinfo:
        module.main(["--timeout", "0"])
    assert excinfo.value.code == 2
    assert "must be > 0" in capsys.readouterr().err


def test_unrecognized_index_line_warns_but_scrape_proceeds(
    stub, tmp_path: Path, capsys
) -> None:
    module = load_script()
    index_text = (
        "Random prose the parser cannot parse.\n"
        "- [Intro](introduction.md)\n"
    )
    body = "# Introduction\n\nhello\n"
    stub.enqueue(text=index_text)
    stub.enqueue(text=body)
    out_dir = tmp_path / "reference"
    code = module.main(
        [
            "--index-url",
            f"{stub.base_url}/llms.txt",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 0
    assert "warning: skipping unrecognized" in capsys.readouterr().err
    assert (out_dir / "introduction.md").read_text(encoding="utf-8") == body
    manifest = json.loads(
        (out_dir / "MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["page_count"] == 1


# ------------------------------------------------------- prune-on-refresh ----


def test_prune_orphans_removes_unlisted_pages_only(tmp_path: Path) -> None:
    """Offline unit: unlisted .md pages are removed; listed pages,
    MANIFEST.json and non-.md files survive; the return value lists
    exactly what was pruned."""
    module = load_script()
    manifest_path = build_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    orphan = tmp_path / "legacy" / "old-client.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("# Legacy client page\n", encoding="utf-8")
    stray = tmp_path / "notes.txt"
    stray.write_text("not a page\n", encoding="utf-8")

    pruned = module.prune_orphans(manifest, out_dir=tmp_path)

    assert pruned == ["legacy/old-client.md"]
    assert not orphan.exists()
    assert (tmp_path / "introduction.md").exists()
    assert (tmp_path / "concepts" / "system-one.md").exists()
    assert manifest_path.exists()
    assert stray.exists()
    # Only files are deleted; the emptied directory remains.
    assert (tmp_path / "legacy").is_dir()


def test_full_rescrape_prunes_orphans_and_reports_receipt(
    stub, tmp_path: Path, capsys
) -> None:
    """Two scrapes against the stub: the second index drops a page; the
    orphan is pruned and the summary receipt lists exactly the removed
    paths; the pruned snapshot verifies offline."""
    module = load_script()
    index_first = (
        "# TypeSafe docs\n"
        "- [Intro](introduction.md)\n"
        "- [System One](concepts/system-one.md)\n"
        "- [Legacy Client](legacy/old-client.md)\n"
    )
    pages = {
        "introduction.md": b"# Introduction\n\nhello\n",
        "concepts/system-one.md": b"# System One\n\nbody text\n",
        "legacy/old-client.md": b"# Legacy client page\n",
    }
    stub.enqueue(text=index_first)
    for body in pages.values():
        stub.enqueue(text=body.decode("utf-8"))
    out_dir = tmp_path / "reference"
    assert module.main(
        ["--index-url", f"{stub.base_url}/llms.txt", "--out-dir", str(out_dir)]
    ) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["pruned"] == []
    assert (out_dir / "legacy" / "old-client.md").exists()

    index_second = (
        "# TypeSafe docs\n"
        "- [Intro](introduction.md)\n"
        "- [System One](concepts/system-one.md)\n"
    )
    stub.enqueue(text=index_second)
    stub.enqueue(text=pages["introduction.md"].decode("utf-8"))
    stub.enqueue(text=pages["concepts/system-one.md"].decode("utf-8"))
    assert module.main(
        ["--index-url", f"{stub.base_url}/llms.txt", "--out-dir", str(out_dir)]
    ) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["pruned"] == ["legacy/old-client.md"]
    assert not (out_dir / "legacy" / "old-client.md").exists()
    assert (out_dir / "introduction.md").exists()
    assert (out_dir / "concepts" / "system-one.md").exists()
    assert (out_dir / "MANIFEST.json").exists()

    # The pruned snapshot verifies offline: custody-green after the prune.
    assert run_check(module, out_dir / "MANIFEST.json") == 0


def test_check_offline_never_deletes(tmp_path: Path) -> None:
    """--check (offline form) reports the unlisted page as ``added`` and
    writes nothing: the orphan, the manifest and listed pages all
    survive byte-identical."""
    module = load_script()
    manifest_path = build_fixture(tmp_path)
    orphan = tmp_path / "legacy" / "old-client.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("# Legacy client page\n", encoding="utf-8")
    manifest_before = manifest_path.read_bytes()
    listed = {
        rel: (tmp_path / rel).read_bytes()
        for rel in ("introduction.md", "concepts/system-one.md")
    }

    assert run_check(module, manifest_path) == 1  # orphan reported as added

    assert orphan.read_text(encoding="utf-8") == "# Legacy client page\n"
    assert manifest_path.read_bytes() == manifest_before
    for rel, body in listed.items():
        assert (tmp_path / rel).read_bytes() == body


def test_check_online_never_deletes(stub, tmp_path: Path, capsys) -> None:
    """--check (online form) against a restructured index: the page the
    new index dropped is reported as drift and nothing on disk is
    deleted or rewritten."""
    module = load_script()
    index_first = (
        "# TypeSafe docs\n"
        "- [Intro](introduction.md)\n"
        "- [System One](concepts/system-one.md)\n"
        "- [Legacy Client](legacy/old-client.md)\n"
    )
    pages = {
        "introduction.md": b"# Introduction\n\nhello\n",
        "concepts/system-one.md": b"# System One\n\nbody text\n",
        "legacy/old-client.md": b"# Legacy client page\n",
    }
    stub.enqueue(text=index_first)
    for body in pages.values():
        stub.enqueue(text=body.decode("utf-8"))
    out_dir = tmp_path / "reference"
    assert module.main(
        ["--index-url", f"{stub.base_url}/llms.txt", "--out-dir", str(out_dir)]
    ) == 0
    capsys.readouterr()
    manifest_before = (out_dir / "MANIFEST.json").read_bytes()

    index_second = (
        "# TypeSafe docs\n"
        "- [Intro](introduction.md)\n"
        "- [System One](concepts/system-one.md)\n"
    )
    stub.enqueue(text=index_second)
    stub.enqueue(text=pages["introduction.md"].decode("utf-8"))
    stub.enqueue(text=pages["concepts/system-one.md"].decode("utf-8"))
    code = module.main(
        [
            "--check",
            "--index-url",
            f"{stub.base_url}/llms.txt",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert "legacy/old-client.md (in manifest, not in index)" in report["drifted"]
    assert (out_dir / "MANIFEST.json").read_bytes() == manifest_before
    assert (out_dir / "legacy" / "old-client.md").read_bytes() == pages["legacy/old-client.md"]
    for rel in ("introduction.md", "concepts/system-one.md"):
        assert (out_dir / rel).read_bytes() == pages[rel]
