"""Real BibTeX inputs exercise the renderer's bibliography diagnostic gate."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("manuscript_renderer", ROOT / "scripts/render_pdf.py")
assert SPEC is not None and SPEC.loader is not None
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def run_bibtex(directory: Path, bibliography: str, citation: str = "fixture") -> tuple[int, str]:
    """Use the real declared plainnat style; no renderer/SDK behavior is patched."""
    if shutil.which("bibtex") is None:
        pytest.skip("native BibTeX toolchain is required for this render regression")
    (directory / "references.bib").write_text(bibliography)
    (directory / "out.aux").write_text(
        "\\relax\n\\citation{" + citation + "}\n\\bibstyle{plainnat}\n\\bibdata{references}\n"
    )
    result = subprocess.run(
        ["bibtex", "out"], cwd=directory, capture_output=True, text=True, check=False,
        timeout=10,
    )
    return result.returncode, (directory / "out.blg").read_text()


@pytest.mark.parametrize(
    ("bibliography", "accepted"),
    [
        ("@misc{fixture, author={A. Author}, title={A title}, year={2026}}", True),
        ("@online{fixture, author={A. Author}, title={A title}, year={2026}}", False),
        (
            "% Entry examples use @online (unsupported syntax in comment prose).\n"
            "@misc{fixture, author={A. Author}, title={A title}, year={2026}}",
            False,
        ),
        ("@misc{fixture, title={A title}, year={2026}}", False),
    ],
    ids=["supported-misc", "unsupported-type", "literal-at-comment", "missing-author"],
)
def test_native_bibtex_diagnostics_are_not_excused_by_bbl(
    tmp_path: Path, bibliography: str, accepted: bool,
) -> None:
    returncode, log = run_bibtex(tmp_path, bibliography)
    assert (tmp_path / "out.bbl").is_file()
    assert RENDERER.bibtex_succeeded(returncode, log) is accepted
    if accepted:
        assert returncode == 0
        assert "Warning--" not in log
    else:
        assert returncode != 0 or "Warning--" in log


def test_complete_current_bibliography_is_plainnat_compatible(tmp_path: Path) -> None:
    bibliography = (ROOT / "manuscript/references.bib").read_text()
    returncode, log = run_bibtex(tmp_path, bibliography, "*")
    assert returncode == 0, log
    assert "Warning--" not in log
    assert RENDERER.bibtex_succeeded(returncode, log)
