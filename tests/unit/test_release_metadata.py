"""Release-metadata consistency pins (offline, no-mock).

Static reads bind the current software version while preserving the published
v0.6.0 record as historical metadata. A new version DOI must not be invented
before the publisher creates its record. Provider membership remains public API.

No network, no client I/O, no monkeypatching: files are read as text and
the provider registry is pure in-process data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from daf_jev.providers import list_providers

REPO_ROOT = Path(__file__).resolve().parents[2]

CONCEPT_DOI = "10.5281/zenodo.22816187"
HISTORICAL_RECORD_ID = "22921974"

BUILT_IN_PROVIDERS = {
    "jev",
    "jeff",
    "kev",
    "localjev",
    "openthai-systemone",
    "openrouter",
}


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text(encoding="utf-8")


def _pyproject_version() -> str:
    match = re.search(r'(?m)^version = "([^"]+)"$', _read("pyproject.toml"))
    assert match is not None, "pyproject.toml has no version line"
    return match.group(1)


def _init_version() -> str:
    match = re.search(
        r'(?m)^__version__ = "([^"]+)"$', _read("src", "daf_jev", "__init__.py")
    )
    assert match is not None, "src/daf_jev/__init__.py has no __version__ line"
    return match.group(1)


def test_version_surfaces_agree() -> None:
    cff = yaml.safe_load(_read("CITATION.cff"))
    zenodo = json.loads(_read(".zenodo.json"))
    versions = {
        "pyproject.toml": _pyproject_version(),
        "src/daf_jev/__init__.py": _init_version(),
        "CITATION.cff": str(cff["version"]),
        ".zenodo.json": str(zenodo["version"]),
    }
    assert len(set(versions.values())) == 1, versions


def test_readme_cites_concept_doi() -> None:
    readme = _read("README.md")
    badge_lines = [ln for ln in readme.splitlines() if ln.startswith("[![DOI]")]
    assert badge_lines, "README.md has no DOI badge"
    assert any(CONCEPT_DOI in ln for ln in badge_lines)
    record_list = readme[
        readme.index("- **Concept DOI**") : readme.index("- **Public repository**")
    ]
    assert CONCEPT_DOI in record_list


def test_historical_record_is_preserved() -> None:
    readme = _read("README.md")
    badge_lines = [ln for ln in readme.splitlines() if "v0.6.0 on Zenodo" in ln]
    assert badge_lines, "README.md has no v0.6.0 Zenodo badge"
    assert any(f"zenodo.org/records/{HISTORICAL_RECORD_ID}" in ln for ln in badge_lines)
    record_list = readme[
        readme.index("- **Concept DOI**") : readme.index("- **Public repository**")
    ]
    assert f"zenodo.org/records/{HISTORICAL_RECORD_ID}" in record_list
    assert HISTORICAL_RECORD_ID in _read("AGENTS.md")


def test_citation_current_version_uses_verified_family() -> None:
    cff = yaml.safe_load(_read("CITATION.cff"))
    assert cff["doi"] == CONCEPT_DOI
    preferred = cff["preferred-citation"]
    assert preferred["title"] == f"daf-jev (v{_pyproject_version()})"
    assert preferred["doi"].startswith("10.5281/zenodo.")
    # During release preparation the concept DOI is valid; a confirmed
    # version-specific DOI can replace it without discarding the family DOI.
    if preferred["doi"] == CONCEPT_DOI:
        assert preferred["url"] == f"https://doi.org/{CONCEPT_DOI}"
    else:
        record_id = preferred["doi"].rsplit(".", 1)[1]
        assert record_id.isdecimal()
        assert preferred["url"] == f"https://zenodo.org/records/{record_id}"


def test_no_stale_pending_release_language() -> None:
    for rel in ("docs/README.md", "AGENTS.md"):
        text = _read(rel)
        assert "deposit pending" not in text, rel
        assert "platform incident" not in text, rel


def test_readme_providers_table_matches_registry() -> None:
    assert {spec.key for spec in list_providers()} == BUILT_IN_PROVIDERS
    readme = _read("README.md")
    section = readme.split("## Providers", 1)[1]
    section = section.split("\n## ", 1)[0]
    table_keys = set(re.findall(r"(?m)^\| `([a-z0-9-]+)`", section))
    assert table_keys == BUILT_IN_PROVIDERS
