"""Invariant pins: mechanize AGENTS.md MUSTs that had no automated gate.

No-mock and offline by construction: static file reads plus a registry
import only — no HTTP, no patching. The pins run against the POST-WAVE
tree (they execute after every wave-1 lane folds), so parallel lanes'
additions are expected to be present: W1-A adds the jaggedness SKILL.md
content, W1-E adds four new examples under ``examples/``.
"""

from __future__ import annotations

import re
from pathlib import Path

from daf_jev.providers import list_providers

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "skills" / "daf-jev" / "SKILL.md"

# Public modules skills/daf-jev/SKILL.md does not yet reference in any
# tracked form (as of the 2026-09-24 tree). This set is a debt ledger: it
# may ONLY shrink (each removal paired with a SKILL.md mention in the same
# commit); new modules must never be added here — they enter the required
# set of test_skill_md_mentions_every_public_module automatically.
# jaggedness.py is deliberately ABSENT from this ledger: W1-A adds its
# mention in wave 1, so the pin enforces it post-fold.
_SKILL_MD_LAGGING_MODULES = frozenset(
    {
        "client",
        "providers",
        "evaluate",
        "models",
        "primitives",
        "questions",
        "docs_verify",
        "cli",
        "mcp_server",
        "figures",
        "manuscript_variables",
    }
)


def _public_module_stems() -> list[str]:
    """Module-level stems under src/daf_jev (private ``_*.py`` excluded)."""
    src = REPO_ROOT / "src" / "daf_jev"
    return sorted(
        p.stem for p in src.glob("*.py") if not p.name.startswith("_")
    )


def _mentions_module(skill_text: str, stem: str) -> bool:
    """SKILL.md references the module as ``<stem>.py`` or ``daf_jev.<stem>``."""
    escaped = re.escape(stem)
    return bool(
        re.search(rf"\b{escaped}\.py\b", skill_text)
        or re.search(rf"daf_jev\.{escaped}\b", skill_text)
    )


def test_skill_md_mentions_every_provider_key() -> None:
    """Provider keys are stable API (AGENTS.md:417-422): the SKILL.md
    provider quick reference must name every registered key."""
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    keys = [spec.key for spec in list_providers()]
    assert keys, "provider registry must not be empty"
    unmentioned = [key for key in keys if f"`{key}`" not in skill_text]
    assert not unmentioned, (
        "skills/daf-jev/SKILL.md does not mention provider key(s) "
        f"{unmentioned} (registry keys are stable API; the SKILL.md "
        "provider quick reference must stay in sync)"
    )


def test_skill_md_mentions_every_public_module() -> None:
    """skills/daf-jev/SKILL.md must stay consistent with the package it
    documents (AGENTS.md:430-432): every public module under
    ``src/daf_jev/*.py`` is referenced, enumerated dynamically so future
    modules (and the post-fold jaggedness.py) are covered automatically.
    """
    skill_text = SKILL_MD.read_text(encoding="utf-8")
    stems = _public_module_stems()
    assert stems, "src/daf_jev must contain public modules"
    missing = [
        stem
        for stem in stems
        if stem not in _SKILL_MD_LAGGING_MODULES
        and not _mentions_module(skill_text, stem)
    ]
    assert not missing, (
        "skills/daf-jev/SKILL.md does not mention public module(s) "
        f"{missing}; add the reference and shrink _SKILL_MD_LAGGING_MODULES"
    )
    stale = sorted(
        stem
        for stem in stems
        if stem in _SKILL_MD_LAGGING_MODULES
        and _mentions_module(skill_text, stem)
    )
    assert not stale, (
        f"SKILL.md now mentions {stale}; shrink _SKILL_MD_LAGGING_MODULES "
        "in the same commit"
    )


def test_bench_calibration_carries_proxy_caveat() -> None:
    """Calibration numbers are a self-consistency proxy, NOT ground-truth
    accuracy (AGENTS.md:408-413): the benchmark source must keep carrying
    the caveat strings its JSON ``notes`` field propagates.
    """
    source = (
        REPO_ROOT / "benchmarks" / "bench_calibration.py"
    ).read_text(encoding="utf-8")
    assert "self-consistency" in source, (
        "bench_calibration.py lost its self-consistency proxy caveat"
    )
    assert "not ground truth" in source, (
        "bench_calibration.py lost its not-ground-truth caveat"
    )


def test_every_example_skips_without_key() -> None:
    """Every ``examples/*.py`` script carries the exact keyless SKIP
    contract (AGENTS.md:414-416). Dynamic enumeration over the directory
    covers W1-E's four new examples automatically once they fold.
    """
    examples = sorted((REPO_ROOT / "examples").glob("*.py"))
    assert examples, "examples/ must contain scripts"
    missing = [
        p.name
        for p in examples
        if "SKIP: JEV_API_KEY not set" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"examples missing the keyless SKIP contract: {missing}"
    )


def test_skill_md_relative_link_targets_exist() -> None:
    """SKILL.md must stay consistent with repo facts (AGENTS.md:430-432):
    every relative pointer link resolves to a file on disk. Fragment
    (heading-anchor) validity is deliberately not checked here — anchor
    validation is a separate mechanism; CI clones contain only tracked
    files, so a target deleted or moved without a SKILL.md update turns
    this red.
    """
    skill_dir = SKILL_MD.parent
    text = SKILL_MD.read_text(encoding="utf-8")
    broken = []
    for link in sorted(set(re.findall(r"\]\(([^)\s]+)\)", text))):
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = link.split("#", 1)[0]
        if target and not (skill_dir / target).exists():
            broken.append(link)
    assert not broken, (
        f"SKILL.md relative links point at missing files: {broken}"
    )
