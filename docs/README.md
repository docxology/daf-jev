# docs/

Documentation for daf-jev.

## ARCHITECTURE.md — the contract

`docs/ARCHITECTURE.md` (v1, 2026-09-16) is the **single source of truth**
for the package build: wire facts (endpoint, question/answer shapes, error
statuses, retry semantics), environment variables, module-by-module
signatures, the no-mock test convention, and benchmark conventions. All
workers must match its signatures exactly; on contradiction, report the
delta — do not silently deviate.

## reference/ — TypeSafe docs snapshot

`docs/reference/` is a **108-page** hashed snapshot of
<https://docs.typesafe.ai> (fetched via its `llms.txt` index), preserving
the docs' `.md` URL paths: `introduction/`, `concepts/`, `primitives/`,
`patterns/`, `cookbooks/`, `demos/`, `sdk/` (JS and Python), etc.

`MANIFEST.json` schema:

```json
{
  "source": "...", "base_url": "...", "index_url": "...",
  "scraped_at_utc": "...", "index_sha256": "...",
  "page_count": 108,
  "pages": {"<rel-path>.md": {"title", "url", "sha256", "bytes"}},
  "snapshot_id": "b79c9cd6008489f1"
}
```

The current snapshot was scraped 2026-09-16T21:19:06Z and has
`snapshot_id` **`b79c9cd6008489f1`** (first 16 hex chars of the sha256 over
the concatenated per-page hashes, in page order). The per-page `sha256`
values are what `daf-jev docs-verify` re-checks.

### Regenerate / verify

```bash
# Full re-scrape (network): fetches every page and rewrites MANIFEST.json
python scripts/scrape_docs.py

# Offline drift check against the current snapshot (no network, no writes)
python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json

# Online check: fresh scrape compared against disk, exit 1 on drift
python scripts/scrape_docs.py --check

# Equivalent check from the installed CLI
uv run daf-jev docs-verify
```

Snapshot pages are the source of record for API behavior questions — read
them (e.g. `sdk/python/api/exceptions.md`) before changing wire-facing
code. Do not hand-edit pages: changes are detected as drift by
`docs-verify`.
