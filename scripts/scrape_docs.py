#!/usr/bin/env python3
"""Standalone re-scraper for the TypeSafe docs snapshot in ``docs/reference/``.

Stdlib only (urllib). Reads the ``llms.txt`` index, fetches every linked
``.md`` page, writes the pages preserving their URL paths, and regenerates
``MANIFEST.json`` byte-compatible with the existing schema:

``{source, base_url, index_url, scraped_at_utc, index_sha256, page_count,
pages: {rel: {title, url, sha256, bytes}}, snapshot_id}`` where
``snapshot_id`` is the first 16 hex chars of the sha256 over the
concatenated per-page hashes (in page order).

``--check`` performs the full scrape in memory and compares it against the
existing manifest and files on disk: exit 0 when everything matches,
1 when anything would change (no files are written).

Importable as a module; logic lives in functions, only the ``__main__``
guard runs anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

SOURCE = "TypeSafe / Jev documentation"
BASE_URL = "https://docs.typesafe.ai"
DEFAULT_INDEX_URL = f"{BASE_URL}/llms.txt"
DEFAULT_OUT_DIR = Path("docs/reference")
MANIFEST_NAME = "MANIFEST.json"
USER_AGENT = "daf-jev-docs-scraper/1.0"

_LINK_RE = re.compile(r"^\s*[-*]\s*\[([^\]]+)\]\(([^)\s]+)\)\s*(?::|$)")

__all__ = [
    "BASE_URL",
    "DEFAULT_INDEX_URL",
    "MANIFEST_NAME",
    "SOURCE",
    "build_manifest",
    "diff_snapshot",
    "fetch",
    "main",
    "page_sha256",
    "parse_index",
    "rel_from_url",
    "scrape",
    "snapshot_id",
    "write_snapshot",
]


# -------------------------------------------------------------- fetching


def fetch(url: str, timeout: float = 30.0) -> bytes:
    """Fetch a URL over HTTP(S) and return the raw body bytes."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# ----------------------------------------------------------- index parse


def _origin(url: str) -> str:
    """``scheme://netloc`` of a URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def parse_index(index_url: str, index_bytes: bytes) -> list[tuple[str, str]]:
    """Extract ``(title, url)`` page entries from an ``llms.txt`` index.

    Keeps markdown-link entries whose target ends in ``.md`` on the index
    host, in file order.
    """
    host = urlparse(index_url).netloc
    pages: list[tuple[str, str]] = []
    seen: set[str] = set()
    text = index_bytes.decode("utf-8")
    for line in text.splitlines():
        match = _LINK_RE.match(line)
        if not match:
            if line.strip():
                print(f"warning: skipping unrecognized llms.txt line: {line.strip()!r}", file=sys.stderr)
            continue
        title, href = match.group(1).strip(), match.group(2).strip()
        url = urljoin(index_url, href)
        parsed = urlparse(url)
        if not parsed.path.endswith(".md") or parsed.netloc != host:
            continue
        if url in seen:
            continue
        seen.add(url)
        pages.append((title, url))
    return pages


def rel_from_url(url: str) -> str:
    """Relative path (from the docs root) a page URL maps to.

    Raises:
        ValueError: When the derived path contains ``..`` — a hostile
            index must not be able to write outside ``out_dir``.
    """
    rel = urlparse(url).path.lstrip("/")
    if ".." in rel:
        raise ValueError(f"unsafe relative path {rel!r} derived from index URL {url!r}")
    return rel


def page_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_id(page_hashes: Sequence[str]) -> str:
    """First 16 hex chars of sha256 over the concatenated page hashes."""
    return hashlib.sha256("".join(page_hashes).encode("ascii")).hexdigest()[:16]


# ------------------------------------------------------------- manifest


def build_manifest(
    index_url: str,
    index_bytes: bytes,
    pages: dict[str, tuple[str, str, bytes]],
) -> dict[str, Any]:
    """Assemble the manifest dict (exact key order of the existing schema).

    ``pages`` maps rel path -> ``(title, url, body bytes)``.
    """
    pages_meta: dict[str, dict[str, Any]] = {}
    hashes: list[str] = []
    for rel, (title, url, body) in pages.items():
        digest = page_sha256(body)
        hashes.append(digest)
        pages_meta[rel] = {
            "title": title,
            "url": url,
            "sha256": digest,
            "bytes": len(body),
        }
    return {
        "source": SOURCE,
        "base_url": _origin(index_url),
        "index_url": index_url,
        "scraped_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "index_sha256": page_sha256(index_bytes),
        "page_count": len(pages_meta),
        "pages": pages_meta,
        "snapshot_id": snapshot_id(hashes),
    }


def scrape(
    index_url: str = DEFAULT_INDEX_URL,
    timeout: float = 30.0,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Fetch the index and every page; return ``(manifest, rel -> body)``."""
    index_bytes = fetch(index_url, timeout=timeout)
    entries = parse_index(index_url, index_bytes)
    if not entries:
        raise RuntimeError(f"no .md pages found in index {index_url!r}")
    contents: dict[str, bytes] = {}
    titles: dict[str, str] = {}
    urls: dict[str, str] = {}
    for title, url in entries:
        rel = rel_from_url(url)
        contents[rel] = fetch(url, timeout=timeout)
        titles[rel] = title
        urls[rel] = url
    manifest = build_manifest(
        index_url,
        index_bytes,
        {rel: (titles[rel], urls[rel], body) for rel, body in contents.items()},
    )
    return manifest, contents


# --------------------------------------------------------------- writing


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=2) + "\n").encode("utf-8")


def write_snapshot(
    manifest: dict[str, Any],
    contents: dict[str, bytes],
    out_dir: Path = DEFAULT_OUT_DIR,
) -> None:
    """Write every page and ``MANIFEST.json`` under ``out_dir``."""
    out_dir = Path(out_dir)
    for rel, body in contents.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (out_dir / MANIFEST_NAME).write_bytes(_manifest_bytes(manifest))


def diff_snapshot(
    manifest: dict[str, Any],
    contents: dict[str, bytes],
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, list[str]]:
    """Compare a fresh scrape against the existing snapshot on disk."""
    out_dir = Path(out_dir)
    report: dict[str, list[str]] = {"missing": [], "drifted": [], "added": []}
    manifest_path = out_dir / MANIFEST_NAME
    try:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if old is None:
        report["missing"].append(MANIFEST_NAME)

    for rel, _body in contents.items():
        path = out_dir / rel
        try:
            on_disk = path.read_bytes()
        except OSError:
            report["missing"].append(rel)
            continue
        if page_sha256(on_disk) != manifest["pages"][rel]["sha256"]:
            report["drifted"].append(rel)

    if old is not None:
        old_pages = old.get("pages", {})
        for rel in old_pages:
            if rel not in contents:
                report["drifted"].append(f"{rel} (in manifest, not in index)")
        if old.get("index_sha256") != manifest["index_sha256"]:
            report["drifted"].append(f"{MANIFEST_NAME} (index_sha256 changed)")
        elif old.get("snapshot_id") != manifest["snapshot_id"] and not report["drifted"]:
            for rel, meta in old_pages.items():
                new_meta = manifest["pages"].get(rel)
                if new_meta and (new_meta["sha256"] != meta.get("sha256") or new_meta["bytes"] != meta.get("bytes")):
                    report["drifted"].append(f"{rel} (manifest hash changed)")
        if old.get("page_count") != manifest["page_count"] and not report["drifted"] and not report["missing"]:
            report["drifted"].append(f"{MANIFEST_NAME} (page_count changed)")

    for key in report:
        report[key] = sorted(set(report[key]))
    return report


def diff_manifest_offline(manifest_path: Path) -> dict[str, list[str]]:
    """Offline variant of ``--check``: re-hash the files a manifest lists.

    No network. Page paths are derived from each entry's ``url`` and
    resolved relative to the manifest's own directory. Extra ``.md``
    files on disk that the manifest does not list are reported as
    ``added``.
    """
    manifest_path = Path(manifest_path)
    report: dict[str, list[str]] = {"missing": [], "drifted": [], "added": []}
    base = manifest_path.parent
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pages = manifest["pages"]
    except (OSError, ValueError, KeyError, TypeError):
        report["missing"].append(manifest_path.name)
        return report

    rels: set[str] = set()
    for key, meta in pages.items():
        rel = rel_from_url(meta["url"]) if isinstance(meta, dict) and meta.get("url") else key
        rels.add(rel)
        try:
            on_disk = (base / rel).read_bytes()
        except OSError:
            report["missing"].append(rel)
            continue
        if (
            page_sha256(on_disk) != meta.get("sha256")
            or len(on_disk) != meta.get("bytes")
        ):
            report["drifted"].append(rel)

    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(base).as_posix()
        if rel not in rels:
            report["added"].append(rel)

    for key in report:
        report[key] = sorted(set(report[key]))
    return report


# ------------------------------------------------------------------- CLI


def _positive_timeout(text: str) -> float:
    """Argparse type: a per-request timeout in seconds, strictly positive."""
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid timeout value: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError(f"--timeout must be > 0 seconds, got {text!r}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scrape_docs",
        description="Re-scrape the TypeSafe docs into docs/reference/ (stdlib only).",
    )
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL, help="llms.txt index URL")
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="output directory"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare a fresh scrape against disk; exit 1 on drift; write nothing",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        metavar="PATH",
        help="with --check: offline diff against the snapshot listed in this manifest (no network)",
    )
    parser.add_argument(
        "manifest_path",
        nargs="?",
        type=Path,
        default=None,
        metavar="MANIFEST",
        help="same as --manifest (bare positional form)",
    )
    parser.add_argument("--timeout", type=_positive_timeout, default=30.0, help="per-request timeout seconds")
    args = parser.parse_args(argv)
    manifest_path = args.manifest_path if args.manifest_path is not None else args.manifest
    if args.manifest is not None and args.manifest_path is not None and args.manifest != args.manifest_path:
        parser.error("--manifest and a positional path were both given but differ")
    if manifest_path is not None and not args.check:
        parser.error("--manifest requires --check (offline diff mode)")
    if args.check and manifest_path is not None:
        report = diff_manifest_offline(manifest_path)
        report["ok"] = not report["missing"] and not report["drifted"] and not report["added"]
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    try:
        manifest, contents = scrape(index_url=args.index_url, timeout=args.timeout)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 1

    if args.check:
        report = diff_snapshot(manifest, contents, out_dir=args.out_dir)
        report["ok"] = not report["missing"] and not report["drifted"] and not report["added"]
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    write_snapshot(manifest, contents, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "snapshot_id": manifest["snapshot_id"],
                "page_count": manifest["page_count"],
                "out_dir": str(args.out_dir),
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
