"""Unit tests for ``daf_jev.graphical_animation`` (offline; Agg GIFs).

No network, no repo ``.env`` reads: the net fixtures are built inline,
the backend is Agg (selected by the module itself before pyplot), and
the whole module skips cleanly without the ``figures`` extra
(matplotlib + Pillow are importorskipped). The GIF gate is the contract:
magic bytes, frame counts, byte determinism, and fail-closed validation
that writes no file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from daf_jev.graphical import CPT, BayesNet, Edge, Variable
from daf_jev.graphical_animation import animate_network, animate_posterior

pytest.importorskip("matplotlib")
pytest.importorskip("PIL.Image")

STEPS: list[dict[str, str]] = [{}, {"a": "false"}, {"a": "false", "b": "true"}]
QUERY_KEYS = ("a", "b", "c")


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


def _gif_frames(path: Path) -> int:
    """Frame count of a GIF via PIL (the contract's n_frames probe)."""
    import PIL.Image

    with PIL.Image.open(path) as gif:
        frames: int = getattr(gif, "n_frames", 0)
    return frames


def test_animate_posterior_gif_magic_and_frames(tmp_path: Path) -> None:
    """A valid GIF with magic bytes and one frame per evidence step."""
    path = animate_posterior(_chain_net(), QUERY_KEYS, STEPS, tmp_path / "post.gif")
    assert path.read_bytes()[:6].startswith(b"GIF8")
    assert _gif_frames(path) == len(STEPS)


def test_animate_posterior_byte_determinism(tmp_path: Path) -> None:
    """Identical inputs give byte-identical GIFs (PillowWriter, no metadata)."""
    net = _chain_net()
    first = animate_posterior(net, QUERY_KEYS, STEPS, tmp_path / "one.gif")
    second = animate_posterior(net, QUERY_KEYS, STEPS, tmp_path / "two.gif")
    assert first.read_bytes() == second.read_bytes()


def test_animate_posterior_fail_closed(tmp_path: Path) -> None:
    """Bad steps/keys/labels/states/fps/dpi raise ValueError and write nothing."""
    net = _chain_net()
    with pytest.raises(ValueError, match="evidence_steps"):
        animate_posterior(net, QUERY_KEYS, [], tmp_path / "steps.gif")
    with pytest.raises(ValueError, match="query_keys"):
        animate_posterior(net, (), STEPS, tmp_path / "keys.gif")
    with pytest.raises(ValueError, match="labels"):
        animate_posterior(
            net, QUERY_KEYS, STEPS, tmp_path / "labels.gif", labels=["x", "y"]
        )
    with pytest.raises(ValueError, match="unknown query variable"):
        animate_posterior(net, ("nope",), STEPS, tmp_path / "keys.gif")
    with pytest.raises(ValueError, match="unknown evidence state"):
        animate_posterior(net, QUERY_KEYS, [{"a": "maybe"}], tmp_path / "state.gif")
    with pytest.raises(ValueError, match="fps"):
        animate_posterior(net, QUERY_KEYS, STEPS, tmp_path / "fps.gif", fps=0)
    with pytest.raises(ValueError, match="dpi"):
        animate_posterior(net, QUERY_KEYS, STEPS, tmp_path / "dpi.gif", dpi=-2)
    assert list(tmp_path.iterdir()) == []  # every failure case above stayed dry


def test_animate_posterior_fail_closed_zero_probability(tmp_path: Path) -> None:
    """Zero-probability evidence fails closed before any figure exists."""
    variables = (
        Variable("a", "Root cause present", ("false", "true")),
        Variable("b", "Fully determined effect", ("false", "true")),
    )
    cpts = {
        "a": CPT("a", (), ((((), (0.7, 0.3)),))),
        "b": CPT(
            "b",
            ("a",),
            (
                (("false",), (1.0, 0.0)),
                (("true",), (0.0, 1.0)),
            ),
        ),
    }
    net = BayesNet(variables, (Edge("a", "b"),), cpts)
    net.validate()
    with pytest.raises(
        ValueError, match="zero probability"
    ):
        animate_posterior(
            net, ("b",), [{}, {"a": "false", "b": "true"}], tmp_path / "z.gif"
        )
    assert list(tmp_path.iterdir()) == []


def test_animate_network_gif_magic_and_frames(tmp_path: Path) -> None:
    """The network GIF carries magic bytes and one frame per step."""
    path = animate_network(_chain_net(), STEPS, tmp_path / "net.gif")
    assert path.read_bytes()[:6].startswith(b"GIF8")
    assert _gif_frames(path) == len(STEPS)


def test_animate_network_byte_determinism(tmp_path: Path) -> None:
    """Identical inputs give byte-identical network GIFs."""
    net = _chain_net()
    first = animate_network(net, STEPS, tmp_path / "one.gif")
    second = animate_network(net, STEPS, tmp_path / "two.gif")
    assert first.read_bytes() == second.read_bytes()


def test_animate_network_fail_closed(tmp_path: Path) -> None:
    """Empty steps, unknown states, and bad fps/dpi fail with no file."""
    with pytest.raises(ValueError, match="evidence_steps"):
        animate_network(_chain_net(), [], tmp_path / "empty.gif")
    with pytest.raises(ValueError, match="unknown evidence state"):
        animate_network(_chain_net(), [{"a": "maybe"}], tmp_path / "state.gif")
    with pytest.raises(ValueError, match="fps"):
        animate_network(_chain_net(), STEPS, tmp_path / "fps.gif", fps=0)
    with pytest.raises(ValueError, match="dpi"):
        animate_network(_chain_net(), STEPS, tmp_path / "dpi.gif", dpi=0)
    assert list(tmp_path.iterdir()) == []


def test_animate_network_empty_net_fails_closed(tmp_path: Path) -> None:
    """An empty net (no variables) fails closed and writes no file."""
    empty = BayesNet(variables=(), edges=(), cpts={})
    with pytest.raises(ValueError, match="empty Bayes net"):
        animate_network(empty, STEPS, tmp_path / "empty.gif")
    assert list(tmp_path.iterdir()) == []


def test_animate_network_explicit_dpi_smoke(tmp_path: Path) -> None:
    """An explicit low dpi still yields a valid one-frame-per-step GIF."""
    path = animate_network(_chain_net(), STEPS, tmp_path / "net.gif", dpi=72)
    assert path.read_bytes()[:6].startswith(b"GIF8")
    assert _gif_frames(path) == len(STEPS)


def test_animators_without_matplotlib_name_figures_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The missing-figures-extra path fails closed with the install hint."""
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    with pytest.raises(ImportError, match="uv sync --extra figures"):
        animate_posterior(_chain_net(), QUERY_KEYS, STEPS, tmp_path / "p.gif")
    with pytest.raises(ImportError, match="uv sync --extra figures"):
        animate_network(_chain_net(), STEPS, tmp_path / "n.gif")
