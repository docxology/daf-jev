"""GIF animations for discrete Bayes nets (optional ``figures`` extra).

Composes over the public ``daf_jev.graphical`` API only — like
:mod:`daf_jev.graphical_viz`, every function takes a
:class:`~daf_jev.graphical.BayesNet` and reads its variables, edges,
states, and exact posteriors. Two FuncAnimation writers, both encoded
with ``matplotlib.animation.PillowWriter``:

- :func:`animate_posterior` — grouped bars of ``P(state=true)`` per
  query variable growing one evidence step per frame (the same binary
  "true" = LAST state convention as
  ``graphical_viz.plot_posterior_trajectory``; the frame title names the
  evidence added since the previous step).
- :func:`animate_network` — the layered DAG layout of
  ``graphical_viz.plot_network`` (coordinate scheme replicated here
  deterministically; colors, fonts, and arrows come from the shared
  figures theme, lazily imported per call) with each node's fill color
  set to ``P(true)`` (coolwarm, 0..1) at the
  frame's evidence step and the full evidence mapping as the frame title.

matplotlib and Pillow import lazily INSIDE the call — without the
optional ``figures`` extra both raise ImportError pointing at
``uv sync --extra figures``. Every function validates fail-closed
BEFORE any figure is created: empty evidence steps, empty query keys
(:func:`animate_posterior`), a labels-count mismatch, unknown keys or
states, zero-probability evidence (via ``BayesNet.posterior``), or a
non-positive fps/dpi raise ValueError and write no file. Output is
deterministic: identical inputs give byte-identical GIFs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from daf_jev.graphical import BayesNet

from daf_jev.graphical_viz import _node_label

__all__ = ["animate_network", "animate_posterior"]

_ANIMATION_EXTRA_HINT = (
    "graphical_animation requires matplotlib and pillow — install the "
    "figures extra: uv sync --extra figures"
)

# Layout mirrors of src/daf_jev/graphical_viz.py (plot_network's scheme).
# Colors, fonts, and arrow style come from the shared figures theme
# (src/daf_jev/figures.py), imported lazily inside the animators together
# with matplotlib — never duplicated here, never at module import. Local
# literals are documented exceptions: ``_NODE_FACE`` has no theme
# counterpart in figures.py; the coolwarm posterior fills, the bar-grid
# alpha, and the arrow curvature/mutation-scale geometry stay local too.
_NODE_SPACING_X = 2.4
_NODE_SPACING_Y = 2.0
_NODE_FACE = "#EAF2FA"
_ARROW_CURVATURE = 0.08
_GROUP_WIDTH = 0.8


def _pyplot() -> Any:
    """Import matplotlib lazily (Agg first); ImportError names the extra.

    ``Agg`` is selected before the pyplot import (headless GIF frame
    rendering), matching ``graphical_viz._pyplot``.
    """
    try:
        import matplotlib
    except ImportError as exc:
        raise ImportError(_ANIMATION_EXTRA_HINT) from exc
    matplotlib.use("Agg")  # headless rendering; must precede pyplot import
    import matplotlib.pyplot as plt

    return plt


def _require_pillow() -> None:
    """Probe Pillow availability; ImportError names the figures extra.

    ``PillowWriter`` imports PIL only while saving; probing up front keeps
    a missing Pillow inside the fail-closed-before-figure window.
    """
    try:
        import PIL  # noqa: F401 — availability probe, never used directly
    except ImportError as exc:
        raise ImportError(_ANIMATION_EXTRA_HINT) from exc


def _mapping_text(mapping: Mapping[str, str]) -> str:
    """Compact ``key=state`` list for titles (empty mapping -> ``none``)."""
    return ", ".join(f"{key}={state}" for key, state in mapping.items()) or "none"


def _frame_text(index: int, step: Mapping[str, str]) -> str:
    """Title text for one evidence step (``priors`` for an empty step 0)."""
    if index == 0 and not step:
        return "priors"
    return _mapping_text(step)


def _added_titles(steps: list[Mapping[str, str]]) -> list[str]:
    """Per-frame titles naming the evidence ADDED at each step.

    Step 0 names its evidence (``priors`` when empty); later steps name
    the keys whose state differs from the previous step. The step index
    in every title also guarantees adjacent frames render differently.
    """
    titles: list[str] = []
    previous: dict[str, str] = {}
    for index, step in enumerate(steps):
        if index == 0:
            description = _frame_text(0, step)
        else:
            added = {
                key: state
                for key, state in step.items()
                if previous.get(key) != state
            }
            description = (
                f"added {_mapping_text(added)}" if added else "no new evidence"
            )
        titles.append(f"step {index}: {description}")
        previous = dict(step)
    return titles


def _checked_steps(steps: Sequence[Any], name: str, minimum: str) -> list[Any]:
    """Fail closed when a step/key sequence is empty (before any figure)."""
    items = list(steps)
    if not items:
        raise ValueError(f"{name} must contain at least one {minimum}")
    return items


def _checked_positive(value: float, name: str) -> None:
    """Fail closed on non-positive numeric parameters before any figure."""
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value!r}")


def _layered_layout(
    net: BayesNet,
) -> tuple[dict[str, tuple[float, float]], float, float]:
    """Deterministic layered coordinates mirroring ``plot_network``.

    Longest-path levels over :meth:`BayesNet.topological_order` stack
    top-to-bottom; variables within a level spread by declared order.
    Returns the positions plus the layout's width and height in data
    units.
    """
    if not net.variables:
        raise ValueError("cannot animate an empty Bayes net: no variables")
    level: dict[str, int] = {}
    for key in net.topological_order():
        parents = net.parents_of(key)
        level[key] = 0 if not parents else max(level[parent] for parent in parents) + 1
    generations: dict[int, list[str]] = {}
    for var in net.variables:  # declared order: deterministic within a row
        generations.setdefault(level[var.key], []).append(var.key)

    positions: dict[str, tuple[float, float]] = {}
    for row_index, row in enumerate(sorted(generations)):
        members = generations[row]
        for index, key in enumerate(members):
            x = (index - (len(members) - 1) / 2) * _NODE_SPACING_X
            y = -row_index * _NODE_SPACING_Y
            positions[key] = (x, y)

    width = (
        max(len(members) for members in generations.values()) - 1
    ) * _NODE_SPACING_X
    height = (len(generations) - 1) * _NODE_SPACING_Y
    return positions, width, height


def _save_gif(
    fig: Any,
    update: Callable[[int], None],
    target: Path,
    *,
    frames: int,
    fps: float,
    dpi: int,
) -> None:
    """Encode ``frames`` of ``fig`` via ``update`` into a PillowWriter GIF.

    One FuncAnimation frame per step; PillowWriter keeps the encoding
    metadata-free so identical inputs give byte-identical output.
    """
    from matplotlib.animation import FuncAnimation, PillowWriter

    animation = FuncAnimation(fig, update, frames=frames)
    animation.save(target, writer=PillowWriter(fps=fps), dpi=dpi)


def animate_posterior(
    net: BayesNet,
    query_keys: Sequence[str],
    evidence_steps: Sequence[Mapping[str, str]],
    path: str | Path,
    *,
    labels: Sequence[str] | None = None,
    fps: float = 1,
    dpi: int = 110,
) -> Path:
    """Write a GIF growing grouped bars of ``P(true)`` across evidence
    steps and return the path.

    One frame per evidence step (applied cumulatively by the caller — the
    same contract as ``graphical_viz.plot_posterior_trajectory``): each
    frame's bars show, per query variable, the probability of its LAST
    state — the binary convention, ``P(true)`` for ``states=("false",
    "true")``. Frame ``k`` draws bars for steps ``0..k`` (the grouped
    bars grow left-to-right) and its title names the evidence ADDED at
    that step; the legend lists the query keys and x tick labels come
    from ``labels`` (step indices as strings when omitted). One
    ``net.posterior`` per step, computed before any figure exists. Lazy
    matplotlib/pillow imports — without the ``figures`` extra
    ImportError names ``uv sync --extra figures``. Fail closed before any
    figure: empty ``evidence_steps`` or ``query_keys``, a labels-count
    mismatch, unknown query keys, unknown/zero-probability evidence
    (``ValueError`` from ``posterior``), or non-positive fps/dpi — no
    file is written in any of those cases. Deterministic: identical
    inputs give byte-identical GIFs.
    """
    steps_list: list[Mapping[str, str]] = _checked_steps(
        evidence_steps, "evidence_steps", "evidence mapping"
    )
    keys: list[str] = _checked_steps(query_keys, "query_keys", "variable key")
    _checked_positive(fps, "fps")
    _checked_positive(dpi, "dpi")
    if labels is not None and len(labels) != len(steps_list):
        raise ValueError(
            f"labels has {len(labels)} entries for {len(steps_list)} steps"
        )
    known = {var.key for var in net.variables}
    unknown = [key for key in keys if key not in known]
    if unknown:
        raise ValueError(f"unknown query variable key(s): {unknown!r}")

    true_index = {key: len(net.variable(key).states) - 1 for key in keys}
    posteriors = [net.posterior(dict(step)) for step in steps_list]
    values = {
        key: [posterior[key][true_index[key]] for posterior in posteriors]
        for key in keys
    }
    titles = _added_titles(steps_list)

    plt = _pyplot()
    _require_pillow()

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

    fig, ax = plt.subplots(figsize=SIZE_CHART)
    bar_width = _GROUP_WIDTH / len(keys)
    bars: list[tuple[list[Any], list[float]]] = []
    for index, key in enumerate(keys):
        centers = [
            step - _GROUP_WIDTH / 2 + (index + 0.5) * bar_width
            for step in range(len(steps_list))
        ]
        container = ax.bar(
            centers,
            [0.0] * len(steps_list),
            width=bar_width * 0.9,
            color=series_colors[index % len(series_colors)],
            label=key,
        )
        bars.append((list(container), values[key]))

    def _update(frame: int) -> None:
        for patches, series in bars:
            for step, patch in enumerate(patches):
                patch.set_height(series[step] if step <= frame else 0.0)
        ax.set_title(titles[frame])

    ax.set_xticks(list(range(len(steps_list))))
    if labels is not None:
        ax.set_xticklabels(
            [str(label) for label in labels],
            rotation=20,
            ha="right",
            fontsize=FONT_ANNOTATE,
        )
    else:
        ax.set_xticklabels([str(index) for index in range(len(steps_list))])
    ax.set_ylabel("P(true)")
    ax.set_ylim(0.0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend()

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _save_gif(fig, _update, target, frames=len(steps_list), fps=fps, dpi=dpi)
    plt.close(fig)
    return target


def animate_network(
    net: BayesNet,
    evidence_steps: Sequence[Mapping[str, str]],
    path: str | Path,
    *,
    fps: float = 1,
    dpi: int = 110,
) -> Path:
    """Write a GIF of the DAG with node fills set to ``P(true)`` per
    evidence step and return the path.

    The layered layout replicates ``graphical_viz.plot_network``'s
    coordinate scheme (longest-path levels over the topological order;
    edges are FancyArrowPatch arcs drawn below the node boxes). Each
    frame colors every node's fill with ``P(true)`` — the probability of
    the variable's LAST state (coolwarm colormap, 0..1) — from that
    step's posterior and titles the frame with the FULL evidence mapping
    (``priors`` when the first step is empty). One ``net.posterior`` per
    step, computed before any figure exists. Same lazy-import and
    fail-closed-before-figure rules as :func:`animate_posterior` (no
    query keys or labels here): an empty net (no variables), empty
    steps, unknown/zero-probability evidence, or non-positive fps/dpi
    raise ValueError and write no file.
    Deterministic: identical inputs give byte-identical GIFs.
    """
    steps_list: list[Mapping[str, str]] = _checked_steps(
        evidence_steps, "evidence_steps", "evidence mapping"
    )
    _checked_positive(fps, "fps")
    _checked_positive(dpi, "dpi")
    if not net.variables:
        raise ValueError("cannot animate an empty Bayes net: no variables")
    posteriors = [net.posterior(dict(step)) for step in steps_list]
    positions, width, height = _layered_layout(net)

    plt = _pyplot()
    _require_pillow()

    from matplotlib import colormaps
    from matplotlib.patches import FancyArrowPatch

    from daf_jev.figures import (
        ARROW_LW,
        ARROW_STYLE,
        COLOR_EDGE,
        COLOR_LAYER_MAIN,
        COLOR_TEXT,
        FONT_BOX,
    )

    cmap = colormaps["coolwarm"]
    fig, ax = plt.subplots(figsize=(max(6.0, width + 3.0), max(3.5, height + 2.5)))

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

    texts: dict[str, Any] = {}
    for var in net.variables:
        x, y = positions[var.key]
        texts[var.key] = ax.text(
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

    def _update(frame: int) -> None:
        for key, text in texts.items():
            patch = text.get_bbox_patch()
            if patch is not None:
                patch.set_facecolor(cmap(posteriors[frame][key][-1]))
        ax.set_title(f"step {frame}: {_frame_text(frame, steps_list[frame])}")

    ax.set_title(f"step 0: {_frame_text(0, steps_list[0])}")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _save_gif(fig, _update, target, frames=len(steps_list), fps=fps, dpi=dpi)
    plt.close(fig)
    return target