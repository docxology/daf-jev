"""Visualization for discrete Bayes nets: text diagrams and PNG artifacts.

Composes over the public ``daf_jev.graphical`` API only: every function
takes a :class:`~daf_jev.graphical.BayesNet` and reads its variables,
edges, states, and — for the trajectory — exact posteriors. Three
surfaces:

- :func:`to_mermaid` — a zero-dependency mermaid ``graph TD`` source for
  docs, issue text, and stdout (no matplotlib required).
- :func:`plot_network` — a layered PNG of the DAG: topological
  generations top-to-bottom, deterministic coordinates, arrow-patch edges.
- :func:`plot_posterior_trajectory` — grouped bars of ``P(state=true)``
  per query variable across cumulative evidence steps ("true" = the LAST
  state of each variable's states tuple — the binary convention; values
  from :meth:`BayesNet.posterior`).

The two plotters import matplotlib lazily INSIDE the call; without the
optional ``figures`` extra they raise ImportError pointing at
``uv sync --extra figures``. Every function is pure over its inputs
except the file writes it is told to make (the plotters also create the
output's parent directory when missing); no global state.

Plotters draw with the shared figures theme (``src/daf_jev/figures.py``
color/font/size constants, imported lazily per call together with
matplotlib); ``to_mermaid`` stays matplotlib-free.
"""

from __future__ import annotations

import math
import textwrap
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Static only: plotting imports matplotlib lazily inside the plotters,
    # keeping matplotlib off the core import graph (optional ``figures``
    # extra).
    from daf_jev.graphical import BayesNet, Variable

__all__ = ["plot_network", "plot_posterior_trajectory", "to_mermaid"]

# Mermaid labels: one node per variable, label ``key<br/>description``.
# Description is truncated to ~40 chars at a word boundary; [<>"] is
# stripped from the label text so nothing but the ``<br/>`` separators can
# interact with mermaid's HTML labels.
_MERMAID_DESCRIPTION_LIMIT = 40
_MERMAID_DIRECTIONS = ("TD", "TB", "BT", "RL", "LR")
_UNSAFE_LABEL_CHARS = str.maketrans("", "", '<>"')

# Theme consumption: colors, fonts, and arrow style come from the shared
# figures theme (src/daf_jev/figures.py), imported lazily inside the
# plotters together with matplotlib — never duplicated here, and never at
# module import (``to_mermaid`` stays matplotlib-free). Local literals
# below are documented exceptions: ``_DPI`` is a def-time signature
# default (== figures.DPI, sync-pinned in tests) and ``_NODE_FACE`` has
# no theme counterpart in figures.py.
_DPI = 200
_NODE_FACE = "#EAF2FA"
_NODE_SPACING_X = 2.4
_NODE_SPACING_Y = 2.0
_PLOT_DESCRIPTION_WIDTH = 24
_PLOT_DESCRIPTION_LINES = 2
_ARROW_CURVATURE = 0.08

_FIGURES_EXTRA_HINT = (
    "graphical_viz plotting requires matplotlib — install the figures "
    "extra: uv sync --extra figures"
)


def _checked_dpi(dpi: int) -> None:
    """Fail closed on non-positive dpi before any figure is drawn."""
    if dpi <= 0:
        raise ValueError(f"dpi must be > 0, got {dpi!r}")


def _checked_figsize(figsize: tuple[float, float] | None) -> None:
    """Fail closed on a malformed figsize; ``None`` keeps the default size."""
    if figsize is None:
        return
    if len(figsize) != 2:
        raise ValueError("figsize must be a (width, height) pair")
    if not all(math.isfinite(value) and value > 0 for value in figsize):
        raise ValueError("figsize values must be finite and > 0")


def _node_id(key: str) -> str:
    """Mermaid node id: the key with [<>"] stripped (never truncated)."""
    return key.translate(_UNSAFE_LABEL_CHARS)


def _truncate(text: str, limit: int) -> str:
    """Collapse whitespace, then truncate to <= ``limit`` chars at a word
    boundary (hard cut for one overlong word), ellipsis-marked."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    boundary = flat[: limit + 1].rfind(" ")
    if boundary > 0:
        return flat[:boundary].rstrip() + "…"
    return flat[:limit].rstrip() + "…"


def to_mermaid(
    net: BayesNet,
    *,
    direction: str = "TD",
    description_limit: int = _MERMAID_DESCRIPTION_LIMIT,
) -> str:
    """Render ``net`` as a mermaid ``graph TD`` source string.

    One node per variable — ``key["key<br/>short description"]`` with the
    description truncated to ~40 chars at a word boundary and ``[<>"]``
    stripped from the label text, so nothing but the ``<br/>`` separators
    interacts with mermaid's HTML labels — and one ``parent --> child``
    line per edge. Node and edge order follow ``net.variables`` /
    ``net.edges`` (deterministic: identical input gives identical output).
    Keyword-only options: ``direction`` is the mermaid flow direction
    (one of ``TD``, ``TB``, ``BT``, ``RL``, ``LR``; default ``TD``) and
    ``description_limit`` bounds each node description (default 40);
    both fail closed before any line is built.
    """
    if direction not in _MERMAID_DIRECTIONS:
        allowed = ", ".join(repr(value) for value in _MERMAID_DIRECTIONS)
        raise ValueError(f"direction must be one of {allowed}, got {direction!r}")
    if description_limit < 1:
        raise ValueError(f"description_limit must be >= 1, got {description_limit!r}")
    lines = [f"graph {direction}"]
    for var in net.variables:
        key = _node_id(var.key)
        description = _truncate(
            var.description.translate(_UNSAFE_LABEL_CHARS), description_limit
        )
        lines.append(f'    {key}["{key}<br/>{description}"]')
    for edge in net.edges:
        lines.append(f"    {_node_id(edge.parent)} --> {_node_id(edge.child)}")
    return "\n".join(lines)


def _pyplot() -> Any:
    """Import matplotlib lazily; fail closed with the figures-extra hint.

    ``Agg`` is selected before the pyplot import (headless PNG rendering),
    matching the convention in ``src/daf_jev/figures.py``.
    """
    try:
        import matplotlib
    except ImportError as exc:
        raise ImportError(_FIGURES_EXTRA_HINT) from exc
    matplotlib.use("Agg")  # headless PNG rendering; must precede pyplot import
    import matplotlib.pyplot as plt

    return plt


def _node_label(var: Variable) -> str:
    """Two-line node label: the key plus the wrapped description."""
    flat = " ".join(var.description.split())
    if not flat:
        return var.key
    wrapped = textwrap.wrap(
        flat,
        width=_PLOT_DESCRIPTION_WIDTH,
        max_lines=_PLOT_DESCRIPTION_LINES,
        placeholder="…",
    )
    return "\n".join([var.key, *wrapped])


def plot_network(
    net: BayesNet,
    path: str | Path,
    *,
    dpi: int = _DPI,
    figsize: tuple[float, float] | None = None,
) -> Path:
    """Write a layered PNG of ``net``'s DAG and return the path.

    Layout is deterministic: topological generations (longest-path levels
    over :meth:`BayesNet.topological_order`) stack top-to-bottom, and the
    variables within a generation spread by variable index. Edges are
    FancyArrowPatch arcs parent->child (slight curvature, drawn below the
    node boxes); nodes are rounded boxes labeled with the key and the
    description truncated to two lines. No title is drawn (the caller
    adds one). Colors, fonts, and the arrow style come from the shared
    figures theme (``src/daf_jev/figures.py`` constants, imported lazily
    together with matplotlib). matplotlib imports lazily — ImportError names the
    ``figures`` extra — and the output's parent directory is created when
    missing. Keyword-only options: ``dpi`` sets the saved figure's pixel
    density and ``figsize`` overrides the computed figure size in inches
    verbatim (``None`` keeps the layered default). Fails closed before
    any file is written: an empty net, a non-positive ``dpi``, or a
    malformed ``figsize`` raise ``ValueError``.
    """
    if not net.variables:
        raise ValueError("cannot plot an empty Bayes net: no variables")
    _checked_dpi(dpi)
    _checked_figsize(figsize)
    plt = _pyplot()
    from daf_jev.figures import (
        ARROW_LW,
        ARROW_STYLE,
        COLOR_EDGE,
        COLOR_LAYER_MAIN,
        COLOR_TEXT,
        FONT_BOX,
    )
    from matplotlib.patches import FancyArrowPatch

    order = net.topological_order()
    level: dict[str, int] = {}
    for key in order:
        parents = net.parents_of(key)
        level[key] = (
            0 if not parents else max(level[parent] for parent in parents) + 1
        )

    generations: dict[int, list[str]] = {}
    for var in net.variables:  # declared order: deterministic within a row
        generations.setdefault(level[var.key], []).append(var.key)
    rows = sorted(generations)

    positions: dict[str, tuple[float, float]] = {}
    for row_index, row in enumerate(rows):
        members = generations[row]
        for index, key in enumerate(members):
            x = (index - (len(members) - 1) / 2) * _NODE_SPACING_X
            y = -row_index * _NODE_SPACING_Y
            positions[key] = (x, y)

    width = (
        max(len(members) for members in generations.values()) - 1
    ) * _NODE_SPACING_X
    height = (len(rows) - 1) * _NODE_SPACING_Y
    fig_size = figsize if figsize is not None else (
        max(6.0, width + 3.0), max(3.5, height + 2.5)
    )
    fig, ax = plt.subplots(figsize=fig_size)

    for edge in net.edges:  # arrows first: node boxes paint over the ends
        x0, y0 = positions[edge.parent]
        x1, y1 = positions[edge.child]
        ax.add_patch(
            FancyArrowPatch(
                (x0, y0),
                (x1, y1),
                connectionstyle=f"arc3,rad={_ARROW_CURVATURE}",
                arrowstyle=ARROW_STYLE,
                mutation_scale=14,
                color=COLOR_EDGE,
                lw=ARROW_LW,
                zorder=1,
            )
        )

    for var in net.variables:
        x, y = positions[var.key]
        ax.text(
            x,
            y,
            _node_label(var),
            ha="center",
            va="center",
            fontsize=FONT_BOX,
            color=COLOR_TEXT,
            bbox=dict(
                boxstyle="round,pad=0.35",
                facecolor=_NODE_FACE,
                edgecolor=COLOR_LAYER_MAIN,
            ),
            zorder=2,
        )

    ax.set_xlim(-width / 2 - 2.0, width / 2 + 2.0)
    ax.set_ylim(-height - 1.0, 1.0)
    ax.axis("off")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return target


def plot_posterior_trajectory(
    net: BayesNet,
    query_keys: Sequence[str],
    steps: Sequence[Mapping[str, str]],
    path: str | Path,
    *,
    labels: Sequence[str] | None = None,
    dpi: int = _DPI,
    figsize: tuple[float, float] | None = None,
) -> Path:
    """Write one grouped bar chart of the posterior trajectory to ``path``.

    For each step (an evidence mapping; the caller applies evidence
    cumulatively — this function takes the evidence dicts as given),
    ``net.posterior(evidence)`` runs once, and each query variable's bar
    shows the probability of its LAST state — the binary convention: for
    ``states=("false", "true")`` that is P(true). The x axis is the step
    index, labeled ``labels`` when given (same length as ``steps``) and
    the step index as a string otherwise; the legend lists the query keys;
    colors follow the shared figures theme cycle. Deterministic. Fail
    closed before any figure is drawn: empty ``steps`` or ``query_keys``,
    a label-count mismatch, unknown query keys (``KeyError`` naming the
    key), invalid evidence (``ValueError`` from ``posterior``), or a
    non-positive ``dpi`` / a malformed ``figsize``. ``figsize=None``
    keeps the shared theme's ``SIZE_CHART`` (7.5, 4.2) default size.
    """
    steps_list = list(steps)
    keys = list(query_keys)
    if not steps_list:
        raise ValueError("steps must contain at least one evidence mapping")
    if not keys:
        raise ValueError("query_keys must contain at least one variable key")
    if labels is not None and len(labels) != len(steps_list):
        raise ValueError(
            f"labels has {len(labels)} entries for {len(steps_list)} steps"
        )
    _checked_dpi(dpi)
    _checked_figsize(figsize)
    step_labels = (
        [str(label) for label in labels]
        if labels is not None
        else [str(index) for index in range(len(steps_list))]
    )

    true_index = {key: len(net.variable(key).states) - 1 for key in keys}
    posteriors = [net.posterior(dict(step)) for step in steps_list]
    values = [
        [posterior[key][true_index[key]] for posterior in posteriors]
        for key in keys
    ]

    plt = _pyplot()
    from daf_jev.figures import (
        COLOR_ACCENT,
        COLOR_EXTERNAL,
        COLOR_LAYER_MAIN,
        COLOR_LAYER_SIDE,
        FONT_ANNOTATE,
        SIZE_CHART,
    )

    # D4: grouped bars follow the shared theme's _style() prop_cycle order
    # (documented here; no new theme API added to figures.py).
    series_colors = (
        COLOR_LAYER_MAIN, COLOR_ACCENT, COLOR_LAYER_SIDE, COLOR_EXTERNAL
    )
    fig_size = figsize if figsize is not None else SIZE_CHART
    fig, ax = plt.subplots(figsize=fig_size)
    group_width = 0.8
    bar_width = group_width / len(keys)
    for index, key in enumerate(keys):
        centers = [
            step - group_width / 2 + (index + 0.5) * bar_width
            for step in range(len(steps_list))
        ]
        ax.bar(
            centers,
            values[index],
            width=bar_width * 0.9,
            color=series_colors[index % len(series_colors)],
            label=key,
        )
    ax.set_xticks(list(range(len(steps_list))))
    ax.set_xticklabels(step_labels, rotation=20, ha="right", fontsize=FONT_ANNOTATE)
    ax.set_ylabel("P(true)")
    ax.set_ylim(0.0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend()

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return target