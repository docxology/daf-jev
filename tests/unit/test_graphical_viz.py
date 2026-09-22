"""Unit tests for ``daf_jev.graphical_viz`` (offline; matplotlib Agg only).

No network, no repo ``.env`` reads: the net fixtures are built inline and
the plotters run under the Agg backend. Plot tests skip cleanly when
matplotlib is absent (``pytest.importorskip``); ``to_mermaid`` is
zero-dependency and always runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from daf_jev.graphical import CPT, BayesNet, Edge, Variable
from daf_jev.graphical_viz import plot_network, plot_posterior_trajectory, to_mermaid


def _chain_net() -> BayesNet:
    """Validated 3-variable chain a -> b -> c with hand-written CPTs."""
    variables = (
        Variable("a", "Root cause present", ("false", "true")),
        Variable("b", "Medium effect present", ("false", "true")),
        Variable("c", "Observable symptom present", ("false", "true")),
    )
    edges = (Edge("a", "b"), Edge("b", "c"))
    cpts = {
        "a": CPT("a", (), ((((), (0.7, 0.3)),))),
        "b": CPT(
            "b",
            ("a",),
            (
                (("false",), (0.8, 0.2)),
                (("true",), (0.1, 0.9)),
            ),
        ),
        "c": CPT(
            "c",
            ("b",),
            (
                (("false",), (0.9, 0.1)),
                (("true",), (0.3, 0.7)),
            ),
        ),
    }
    net = BayesNet(variables, edges, cpts)
    net.validate()
    return net


def test_to_mermaid_shape_and_determinism() -> None:
    """Deterministic output: header, node order, then edge order."""
    source = to_mermaid(_chain_net())
    assert source == to_mermaid(_chain_net())
    lines = source.splitlines()
    assert lines[0] == "graph TD"
    assert lines[1] == '    a["a<br/>Root cause present"]'
    assert lines[2] == '    b["b<br/>Medium effect present"]'
    assert lines[3] == '    c["c<br/>Observable symptom present"]'
    assert lines[4] == "    a --> b"
    assert lines[5] == "    b --> c"
    assert len(lines) == 6


def test_to_mermaid_edge_order_follows_edges() -> None:
    """Edge lines follow the net's edge order, not sorted order."""
    net = BayesNet(
        (
            Variable("x", "First", ("lo", "hi")),
            Variable("y", "Second", ("lo", "hi")),
            Variable("z", "Third", ("lo", "hi")),
        ),
        (Edge("x", "y"), Edge("y", "z"), Edge("x", "z")),
        {},
    )
    source = to_mermaid(net)
    assert source.index("    x --> y") < source.index("    y --> z")
    assert source.index("    y --> z") < source.index("    x --> z")


def test_to_mermaid_strips_unsafe_label_characters() -> None:
    """[<>"] never survives into the label text (only the <br/> join)."""
    net = BayesNet(
        (Variable("q", 'Uses <angles> and "quotes"', ("no", "yes")),),
        (),
        {},
    )
    source = to_mermaid(net)
    # The only quote/angle characters left are the node-label delimiters,
    # the <br/> joins, and the --> edge arrows; the label TEXT itself is
    # stripped of [<>"].
    assert source.count('"') == 2  # one node: its two label delimiters
    assert "Uses angles and quotes" in source
    syntax_only = source.replace("<br/>", "").replace("-->", "")
    assert "<" not in syntax_only
    assert ">" not in syntax_only


def test_to_mermaid_truncates_at_word_boundary() -> None:
    """Over-limit descriptions truncate at a word boundary, ellipsis-marked."""
    net = BayesNet(
        (Variable("n", "word " + "x" * 60, ("a", "b")),),
        (),
        {},
    )
    assert to_mermaid(net).splitlines()[1] == '    n["n<br/>word…"]'


def test_to_mermaid_truncates_long_descriptions() -> None:
    """The ~40-char limit drops the tail; short labels pass through whole."""
    long = "A very long description that certainly exceeds forty characters"
    net = BayesNet(
        (Variable("n", long + " in total", ("a", "b")),),
        (),
        {},
    )
    source = to_mermaid(net)
    assert "…" in source
    assert "in total" not in source
    assert long not in source


def test_to_mermaid_hard_cuts_unbreakable_words() -> None:
    """A single over-long word hard-cuts at the limit (no space to break at)."""
    net = BayesNet(
        variables=(Variable("n", "x" * 45, ("a", "b")),),
        edges=(),
        cpts={},
    )
    assert to_mermaid(net).splitlines()[1] == '    n["n<br/>' + "x" * 40 + '…"]'


def test_plot_network_handles_empty_description(tmp_path: Path) -> None:
    """A variable with no description labels its node with the key alone."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")

    net = BayesNet(
        variables=(
            Variable("a", "Has a cause", ("false", "true")),
            Variable("b", "", ("false", "true")),
        ),
        edges=(Edge("a", "b"),),
        cpts={},
    )
    path = plot_network(net, tmp_path / "nested" / "empty.png")
    assert path == tmp_path / "nested" / "empty.png"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_plot_network_writes_deterministic_png(tmp_path: Path) -> None:
    """A layered-layout PNG; identical input gives byte-identical output."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")

    first = plot_network(_chain_net(), tmp_path / "a.png")
    second = plot_network(_chain_net(), tmp_path / "b.png")
    assert first == tmp_path / "a.png"
    assert second == tmp_path / "b.png"
    assert first.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert first.stat().st_size > 0
    assert second.read_bytes() == first.read_bytes()


def test_plot_posterior_trajectory_png(tmp_path: Path) -> None:
    """Trajectory PNG writes; fail-closed on bad steps/labels/keys."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")

    net = _chain_net()
    steps: list[dict[str, str]] = [{}, {"a": "true"}]
    path = plot_posterior_trajectory(
        net,
        ("b", "c"),
        steps,
        tmp_path / "trajectory.png",
        labels=["priors", "a=true"],
    )
    assert path == tmp_path / "trajectory.png"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert path.stat().st_size > 0

    with pytest.raises(ValueError, match="labels"):
        plot_posterior_trajectory(
            net, ("b",), steps, tmp_path / "x.png", labels=["one"]
        )
    with pytest.raises(ValueError, match="steps"):
        plot_posterior_trajectory(net, ("b",), [], tmp_path / "y.png")
    with pytest.raises(ValueError, match="query_keys"):
        plot_posterior_trajectory(net, (), steps, tmp_path / "w.png")
    with pytest.raises(KeyError, match="nope"):
        plot_posterior_trajectory(net, ("nope",), steps, tmp_path / "z.png")


def test_plotters_without_matplotlib_name_figures_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The missing-figures-extra path fails closed with the install hint."""
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    with pytest.raises(ImportError, match="uv sync --extra figures"):
        plot_network(_chain_net(), tmp_path / "network.png")
    with pytest.raises(ImportError, match="uv sync --extra figures"):
        plot_posterior_trajectory(_chain_net(), ("b",), [{}], tmp_path / "t.png")