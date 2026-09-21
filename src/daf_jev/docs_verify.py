"""Shared verifier for a docs snapshot manifest (read-only).

:func:`daf_jev.docs_verify.verify_manifest` re-hashes every page a
manifest lists (sha256 + byte length), flags entries whose ``url`` no
longer maps to the listed relative path, and reports extra ``.md`` files
on disk the manifest does not list. The CLI (``daf-jev docs-verify``) and
the MCP server (``jev_docs_verify``) route through it so the report schema
is defined exactly once:

``{manifest, pages, missing, drifted, added, ok}`` where ``ok`` is True
only when all three finding lists are empty.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["DEFAULT_MANIFEST", "verify_manifest"]

#: Default snapshot manifest, anchored to the repo root this module is
#: installed in (not the process CWD) so servers launched from any
#: directory still find it.
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2] / "docs" / "reference" / "MANIFEST.json"
)


def _rel_from_url(url: str) -> str:
    """Relative path (from the docs root) that a page URL maps to."""
    return urlparse(url).path.lstrip("/")


def verify_manifest(manifest_path: Path) -> dict[str, Any]:
    """Verify a docs snapshot manifest against the files next to it.

    Pure read-only. Raises ``ValueError`` when the manifest cannot be read
    or parsed, or when an entry has the wrong shape. The report contains:

    - ``pages``: number of manifest entries,
    - ``missing``: listed pages absent from disk,
    - ``drifted``: pages whose stored sha256/byte size no longer matches,
      or whose ``url`` maps to a relative path other than the listed key
      (entries without a ``url`` fall back to the key and are never
      drifted for lacking one),
    - ``added``: ``.md`` files on disk under the manifest's directory the
      manifest does not list,
    - ``ok``: True when all three finding lists are empty.
    """
    manifest_path = Path(manifest_path)
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read manifest {manifest_path}: {exc}") from exc
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"invalid JSON in manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest {manifest_path} must be a JSON object")
    pages = manifest.get("pages", {})
    if not isinstance(pages, dict):
        raise ValueError(f"manifest {manifest_path}: 'pages' must be a JSON object")

    base = manifest_path.parent
    missing: list[str] = []
    drifted: list[str] = []
    for rel, meta in pages.items():
        if not isinstance(meta, dict):
            raise ValueError(
                f"manifest {manifest_path}: page {rel!r} must be a JSON object"
            )
        url = meta.get("url")
        if url:
            expected_rel = _rel_from_url(str(url))
            if expected_rel != rel:
                drifted.append(f"{rel} (url maps to {expected_rel!r})")
                continue
        try:
            data = (base / rel).read_bytes()
        except OSError:
            missing.append(rel)
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != meta.get("sha256") or len(data) != meta.get("bytes"):
            drifted.append(rel)

    listed = set(pages)
    added: list[str] = []
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(base).as_posix()
        if rel not in listed:
            added.append(rel)

    return {
        "manifest": str(manifest_path),
        "pages": len(pages),
        "missing": sorted(missing),
        "drifted": sorted(drifted),
        "added": sorted(added),
        "ok": not missing and not drifted and not added,
    }
