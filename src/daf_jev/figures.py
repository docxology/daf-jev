"""Figure registry for the daf-jev manuscript.

One ``generate_<name>()`` function per manuscript figure plus
:func:`generate_all`, orchestrated by the thin
``scripts/generate_figures.py``. The graphical abstract opens the registry
as figure 1; figures 2-3 (architecture, primitives) are data-free
diagrams; figures 4-5 (batching, latency) read the latest benchmark JSONs
from ``output/benchmarks/`` at generation time; figure 6 (confidence) is
a parametric illustration of confidence-gated routing; figure 7
(calibration) plots the live reliability benchmark.

Every label, color, and size is a module-level constant below — no magic
numbers inline. All generators share :func:`_style` (palette, fonts,
gridlines, dpi) and the :func:`_panel_letter` helper for multi-panel
layouts. Generation is offline (no network). Missing benchmark data
raises :class:`FileNotFoundError` naming the missing file; figures 2, 3,
and 6 never touch benchmark data and are always renderable.
"""
import json
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless PNG rendering; must precede pyplot import

import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.patches import ConnectionPatch, FancyArrowPatch, FancyBboxPatch
from matplotlib.ticker import MaxNLocator

__all__ = ["architecture_mermaid", "generate_all", "generate_architecture", "generate_batching", "generate_calibration", "generate_confidence", "generate_graphical_abstract", "generate_latency", "generate_one", "generate_primitives", "write_figure_registry"]


# ---------------------------------------------------------------------------
# Style constants — single source for every visual parameter
# ---------------------------------------------------------------------------

DPI = 200

COLOR_LAYER_MAIN = "#2E5E8C"  # daf-jev package layers
COLOR_LAYER_SIDE = "#7FA6C9"  # side-input modules
COLOR_EXTERNAL = "#8C8C8C"  # external services
COLOR_ACCENT = "#C46A2B"  # emphasis / second series
COLOR_BAND_AUTOMATE = "#BFDCA8"
COLOR_BAND_REVIEW = "#F2D38B"
COLOR_BAND_ESCALATE = "#E5A48C"
COLOR_TEXT = "#222222"
COLOR_EDGE = "#444444"
FONT_BOX = 9
FONT_TITLE = 12
FONT_AXIS = 10
FONT_ANNOTATE = 9
FONT_MINI = 7.5  # graphical-abstract mini charts

ARROW_STYLE = "-|>"
ARROW_LW = 1.4

BENCHMARK_DIR = Path("output") / "benchmarks"

SIZE_ABSTRACT = (8.5, 3.2)  # graphical abstract: 1700 x 640 px at DPI
SIZE_DIAGRAM = (7.5, 4.6)
SIZE_CHART = (7.5, 4.2)


# Meta keys of patterns_*.json that are not pipeline result objects.
_PATTERN_META_KEYS = frozenset({"name", "date", "model", "runs"})


def _style() -> None:
    """Apply the shared manuscript style: palette, fonts, gridlines, dpi.

    Every generator calls this first so all figures render from one set of
    rcParams — consistent fonts, colors, light gridlines, and output dpi.
    """
    plt.rcParams.update(
        {
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "font.family": "DejaVu Sans",
            "font.size": FONT_AXIS,
            "text.color": COLOR_TEXT,
            "axes.edgecolor": COLOR_EDGE,
            "axes.labelcolor": COLOR_TEXT,
            "axes.titlesize": FONT_TITLE,
            "axes.titlecolor": COLOR_TEXT,
            "axes.grid": True,
            "grid.color": "#D9D9D9",
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "xtick.color": COLOR_TEXT,
            "ytick.color": COLOR_TEXT,
            "legend.frameon": False,
            "axes.prop_cycle": cycler(
                color=[COLOR_LAYER_MAIN, COLOR_ACCENT, COLOR_LAYER_SIDE, COLOR_EXTERNAL]
            ),
        }
    )


def _panel_letter(ax, letter: str, *, dx: float = 0.015, dy: float = 0.96) -> None:
    """Annotate a bold ``(letter)`` panel tag inside an axis's top-left corner."""
    ax.text(
        dx, dy, f"({letter})",
        transform=ax.transAxes,
        ha="left", va="top",
        fontsize=FONT_TITLE, fontweight="bold", color=COLOR_TEXT,
    )


# ---------------------------------------------------------------------------
# Drawing helpers — thin wrappers over matplotlib primitives
# ---------------------------------------------------------------------------


def _new_diagram(title: str):
    """Create an axis-off diagram canvas with a title."""
    fig, ax = plt.subplots(figsize=SIZE_DIAGRAM)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_axis_off()
    ax.set_title(title, fontsize=FONT_TITLE, color=COLOR_TEXT)
    return fig, ax


def _box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    *,
    facecolor: str,
    sublabel: str | None = None,
    dashed: bool = False,
    aspect: float = SIZE_DIAGRAM[0] / SIZE_DIAGRAM[1],
) -> None:
    """Draw a labeled rounded box with ``(x, y)`` as its lower-left corner."""
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.4",
        linewidth=1.2,
        edgecolor=COLOR_EDGE,
        facecolor=facecolor,
        linestyle="--" if dashed else "-",
        mutation_aspect=aspect,
    )
    ax.add_patch(patch)
    if sublabel is None:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=FONT_BOX, color=COLOR_TEXT)
    else:
        ax.text(x + w / 2, y + h * 0.68, label, ha="center", va="center", fontsize=FONT_BOX, color=COLOR_TEXT, fontweight="bold")
        ax.text(x + w / 2, y + h * 0.30, sublabel, ha="center", va="center", fontsize=FONT_BOX - 1, color=COLOR_TEXT)


def _arrow(ax, start: tuple[float, float], end: tuple[float, float], *, dashed: bool = False) -> None:
    """Draw a directed arrow between two coordinate points."""
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=ARROW_STYLE,
            mutation_scale=14,
            linewidth=ARROW_LW,
            color=COLOR_EDGE,
            linestyle="--" if dashed else "-",
            shrinkA=1.5,
            shrinkB=1.5,
        )
    )

def _save(fig: plt.Figure, out_dir: Path, filename: str, *, tight: bool = True) -> Path:
    """Save a figure as PNG into *out_dir* and return the written path.

    With ``tight=False`` the canvas is written at its exact figsize so the
    graphical abstract lands at its designed pixel size.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    fig.savefig(path, dpi=DPI, bbox_inches="tight" if tight else None)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Benchmark data loading (figures 3-4; strict, offline)
# ---------------------------------------------------------------------------


def _latest_benchmark(project_root: Path, prefix: str) -> Path:
    """Return the path of the newest ``<prefix>_*.json`` under ``output/benchmarks``.

    Raises :class:`FileNotFoundError` naming the missing file when none exist.
    """
    bench_dir = project_root / BENCHMARK_DIR
    matches = sorted(bench_dir.glob(f"{prefix}_*.json"))
    if not matches:
        raise FileNotFoundError(
            f"Missing benchmark data: no {bench_dir / f'{prefix}_*.json'} found "
            f"(expected e.g. '{prefix}_20260916.json'). Run the benchmark script first."
        )
    return matches[-1]


def _load_benchmark(project_root: Path, prefix: str) -> dict[str, Any]:
    path = _latest_benchmark(project_root, prefix)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Figure 1 — package architecture
# ---------------------------------------------------------------------------


# Static tables for Figure 1 — the single source for what
# :func:`generate_architecture` draws and :func:`architecture_mermaid`
# emits, so the PNG and the ``architecture.mmd`` sibling can never drift.
# Nodes are (node_id, label, sublabel, role, x, y, w, h) with (x, y) the
# lower-left corner; the role picks the facecolor from _ROLE_FACECOLORS
# and marks side modules dashed. Edges are (src_id, dst_id, dashed,
# start_xy, end_xy) in draw order.
_ARCHITECTURE_NODES: tuple[tuple[str, str, str | None, str, float, float, float, float], ...] = (
    # Layer 4 (top): entry points.
    ("cli", "cli.py", "daf-jev command line", "main", 6, 86, 38, 11),
    ("scripts", "scripts/", "benchmarks, docs snapshot", "main", 56, 86, 38, 11),
    # Layer 3: composition surface.
    ("primitives", "primitives.py", "noul / choice / score", "main", 6, 60, 38, 12),
    ("compose", "compose.py", "routing + decision patterns", "main", 56, 60, 38, 12),
    # Layer 2: transport.
    ("client", "client.py", "JevClient", "main", 2, 34, 24, 12),
    ("http", "_http.py", "transport", "main", 30, 34, 22, 12),
    ("retry", "_retry.py", "retry policy", "main", 56, 34, 20, 12),
    ("errors", "_errors.py", "typed errors", "main", 80, 34, 18, 12),
    # Layer 1 (bottom): the external API.
    ("api", "TypeSafe Jev API", "System One", "external", 20, 6, 60, 12),
    # Side inputs (dashed).
    ("models", "models.py", None, "side", 2, 12, 14, 10),
    ("config", "config.py", None, "side", 84, 76, 14, 10),
    ("types", "_types.py", None, "side", 84, 48, 14, 10),
    ("evaluate", "evaluate.py", None, "side", 2, 48, 14, 10),
)

_ARCHITECTURE_EDGES: tuple[tuple[str, str, bool, tuple[float, float], tuple[float, float]], ...] = (
    # Entry → composition.
    ("cli", "primitives", False, (25, 86), (25, 73)),
    ("scripts", "compose", False, (75, 86), (75, 73)),
    # primitives ↔ compose flow.
    ("primitives", "compose", False, (40, 66), (58, 66)),
    ("compose", "primitives", False, (58, 66), (40, 66)),
    # Composition → transport.
    ("primitives", "client", False, (25, 60), (16, 47)),
    ("compose", "http", False, (75, 60), (41, 47)),
    ("compose", "retry", False, (66, 60), (66, 47)),
    # The diagram genuinely draws two primitives → client arrows; keep both.
    ("primitives", "client", False, (16, 60), (16, 47)),
    # Transport → API.
    ("client", "api", False, (14, 34), (40, 19)),
    ("http", "api", False, (41, 34), (46, 19)),
    ("retry", "api", False, (66, 34), (52, 19)),
    ("errors", "api", False, (89, 34), (60, 19)),
    # Side inputs (dashed arrows into their consumers).
    ("evaluate", "client", True, (9, 48), (14, 46)),
    ("config", "compose", True, (91, 76), (86, 72)),
    ("types", "errors", True, (91, 48), (89, 47)),
    ("models", "client", True, (9, 22), (14, 34)),
)

# Role → facecolor; side modules draw dashed (boxes and arrows).
_ROLE_FACECOLORS = {
    "main": COLOR_LAYER_MAIN,
    "side": COLOR_LAYER_SIDE,
    "external": COLOR_EXTERNAL,
}


def generate_architecture(out_dir: Path, project_root: Path | None = None) -> Path:
    """Draw the package layer diagram: entry points down to the TypeSafe API."""
    _style()
    fig, ax = _new_diagram("daf-jev package architecture")

    for _node_id, label, sublabel, role, x, y, w, h in _ARCHITECTURE_NODES:
        _box(ax, x, y, w, h, label, facecolor=_ROLE_FACECOLORS[role], sublabel=sublabel, dashed=role == "side")
    for _src_id, _dst_id, dashed, start_xy, end_xy in _ARCHITECTURE_EDGES:
        _arrow(ax, start_xy, end_xy, dashed=dashed)
    return _save(fig, out_dir, "architecture.png")


def architecture_mermaid() -> str:
    """Render the architecture diagram as a byte-deterministic mermaid source.

    Nodes and edges come from the static :data:`_ARCHITECTURE_NODES` /
    :data:`_ARCHITECTURE_EDGES` tables — the same data
    :func:`generate_architecture` draws — and emission is sorted (nodes by
    id, edges by ``(src, dst)``; the duplicate ``primitives → client`` arrow
    the figure draws is kept), so the returned string is byte-identical on
    every run. Ids are mermaid-safe; real filenames stay in the labels. The
    string carries no trailing newline; writers add one.
    """
    nodes = sorted(_ARCHITECTURE_NODES, key=lambda row: row[0])
    edges = sorted(_ARCHITECTURE_EDGES, key=lambda row: (row[0], row[1]))
    lines = ["graph TD"]
    for node_id, label, sublabel, _role, _x, _y, _w, _h in nodes:
        label_text = label if sublabel is None else f"{label}<br/>{sublabel}"
        lines.append(f'    {node_id}["{label_text}"]')
    for src_id, dst_id, dashed, _start, _end in edges:
        arrow = "-.->" if dashed else "-->"
        lines.append(f"    {src_id} {arrow} {dst_id}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Figure 2 — the three question primitives
# ---------------------------------------------------------------------------


def generate_primitives(out_dir: Path, project_root: Path | None = None) -> Path:
    """Diagram the three question types and their typed answer shapes."""
    _style()
    fig, ax = _new_diagram("Jev question primitives and typed answers")

    columns = [
        ("noul", "NoulQuestion", "NoulAnswer", "free-text content\n(no confidence axis)"),
        ("choice", "ChoiceQuestion", "ChoiceAnswer", "choice + probabilities\n+ confidence"),
        ("score", "ScoreQuestion", "ScoreAnswer", "score + probabilities\n+ legend + confidence"),
    ]
    col_w = 26
    gap = 9
    x0 = (100 - 3 * col_w - 2 * gap) / 2
    for i, (name, qtype, atype, shape) in enumerate(columns):
        x = x0 + i * (col_w + gap)
        _box(ax, x, 74, col_w, 12, f"{name}()", facecolor=COLOR_LAYER_MAIN, sublabel=qtype)
        _box(ax, x, 40, col_w, 14, atype, facecolor=COLOR_LAYER_SIDE, sublabel=shape)
        _arrow(ax, (x + col_w / 2, 74), (x + col_w / 2, 55))
        ax.text(x + col_w / 2, 26, "confidence:\n" + ("absent" if name == "noul" else "second decision axis"), ha="center", va="center", fontsize=FONT_ANNOTATE - 1, color=COLOR_TEXT)

    return _save(fig, out_dir, "primitives_overview.png")


# ---------------------------------------------------------------------------
# Figure 3 — batching speedup
# ---------------------------------------------------------------------------


def generate_batching(out_dir: Path, project_root: Path | None = None) -> Path:
    """Bar chart of batching speedup vs N, with token-cost ratio overlay."""
    _style()
    root = Path.cwd() if project_root is None else project_root
    data = _load_benchmark(root, "batching")

    results = sorted(data["results"], key=lambda r: r["n"])
    ns = [str(r["n"]) for r in results]
    speedups = [float(r["speedup_ratio"]) for r in results]
    token_ratios = [float(r["token_cost_ratio"]) for r in results]
    # token_cost_ratio = sequential tokens / batched tokens: values above one
    # mean the sequential strategy costs MORE tokens (it re-sends the state).

    fig, ax = plt.subplots(figsize=SIZE_CHART)
    ax.set_ylim(0, max(speedups) * 1.14)  # headroom so labels clear the overlay
    bars = ax.bar(ns, speedups, width=0.55, color=COLOR_LAYER_MAIN, label="wall-clock speedup")
    for bar, value in zip(bars, speedups, strict=True):  # same results list
        ax.annotate(
            f"{value:.1f}x",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            textcoords="offset points",
            xytext=(0, 4),
            ha="center",
            fontsize=FONT_ANNOTATE,
            color=COLOR_TEXT,
        )

    ax.set_xlabel("batch size N", fontsize=FONT_AXIS)
    ax.set_ylabel("speedup vs single calls (x)", fontsize=FONT_AXIS)
    ax.tick_params(labelsize=FONT_AXIS)

    ax2 = ax.twinx()
    ax2.plot(ns, token_ratios, color=COLOR_ACCENT, marker="o", linewidth=1.6, label="sequential token cost relative to batched")
    # Margins keep the markers and their labels clear of the bar tops.
    ax2.set_ylim(min(token_ratios) * 0.92, max(token_ratios) * 1.14)
    for x_pos, value in zip(range(len(ns)), token_ratios, strict=True):  # same results list
        ax2.annotate(
            f"{value:.2f}",
            (x_pos, value),
            textcoords="offset points",
            xytext=(8, -10),
            fontsize=FONT_ANNOTATE - 1,
            color=COLOR_ACCENT,
        )
    ax2.set_ylabel("sequential ÷ batched tokens", fontsize=FONT_AXIS, color=COLOR_ACCENT)
    ax2.tick_params(labelsize=FONT_AXIS, colors=COLOR_ACCENT)

    # Title reads model + run date from the benchmark JSON, never hardcoded.
    ax.set_title(f"Batching speedup — {data['model']} ({data['date']})", fontsize=FONT_TITLE, color=COLOR_TEXT)

    # BarContainer and Line2D both expose get_label(); matplotlib's artist
    # typing is loose here, so the handle list is explicitly Any-typed.
    handles: list[Any] = [bars, ax2.lines[0]]
    ax.legend(handles, [h.get_label() for h in handles], loc="upper left", fontsize=FONT_ANNOTATE)

    fig.tight_layout()
    return _save(fig, out_dir, "batching_speedup.png")


# ---------------------------------------------------------------------------
# Figure 4 — latency percentiles
# ---------------------------------------------------------------------------


def generate_latency(out_dir: Path, project_root: Path | None = None) -> Path:
    """Grouped p50/p95 bars per pipeline, labeled from the benchmark JSON."""
    root = Path.cwd() if project_root is None else project_root
    _style()
    data = _load_benchmark(root, "patterns")

    pipelines = [key for key in sorted(data) if key not in _PATTERN_META_KEYS]
    p50 = [float(data[key]["p50_s"]) for key in pipelines]
    p95 = [float(data[key]["p95_s"]) for key in pipelines]

    fig, ax = plt.subplots(figsize=SIZE_CHART)
    x_pos = list(range(len(pipelines)))
    width = 0.35
    bars_p50 = ax.bar([x - width / 2 for x in x_pos], p50, width=width, color=COLOR_LAYER_MAIN, label="p50 latency (s)")
    bars_p95 = ax.bar([x + width / 2 for x in x_pos], p95, width=width, color=COLOR_ACCENT, label="p95 latency (s)")
    for bars in (bars_p50, bars_p95):
        for bar in bars:
            ax.annotate(
                f"{bar.get_height():.3f}",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                textcoords="offset points",
                xytext=(0, 3),
                ha="center",
                fontsize=FONT_ANNOTATE - 1,
                color=COLOR_TEXT,
            )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(pipelines, fontsize=FONT_AXIS)
    ax.set_ylabel("latency (s)", fontsize=FONT_AXIS)
    ax.tick_params(labelsize=FONT_AXIS)
    ax.set_title(f"Pipeline latency percentiles — {data['model']} ({data['date']})", fontsize=FONT_TITLE, color=COLOR_TEXT)
    ax.legend(fontsize=FONT_ANNOTATE)

    fig.tight_layout()
    return _save(fig, out_dir, "latency_percentiles.png")


# ---------------------------------------------------------------------------
# Figure 5 — confidence-gated routing bands


def generate_confidence(out_dir: Path, project_root: Path | None = None) -> Path:
    """Parametric illustration of confidence-gated routing (illustrative thresholds)."""
    _style()
    thresholds = (0.6, 0.85)
    bands = [
        ("escalate", 0.0, thresholds[0], COLOR_BAND_ESCALATE),
        ("review", thresholds[0], thresholds[1], COLOR_BAND_REVIEW),
        ("automate", thresholds[1], 1.0, COLOR_BAND_AUTOMATE),
    ]

    fig, ax = plt.subplots(figsize=SIZE_CHART)
    band_height = 1.0
    for i, (label, lo, hi, color) in enumerate(bands):
        y = (len(bands) - 1 - i) * band_height
        ax.add_patch(
            plt.Rectangle(
                (lo, y),
                hi - lo,
                band_height,
                facecolor=color,
                edgecolor=COLOR_EDGE,
                linewidth=1.0,
            )
        )
        text = f"{label}\nconfidence in [{lo:.2f}, {hi:.2f}]"
        if hi - lo < 0.2:
            # Narrow band: place the label just left of the band so it
            # cannot overflow the axis.
            ax.text(
                lo - 0.015, y + band_height / 2, text,
                ha="right", va="center",
                fontsize=FONT_ANNOTATE, color=COLOR_TEXT,
            )
        else:
            ax.text(
                (lo + hi) / 2, y + band_height / 2, text,
                ha="center", va="center",
                fontsize=FONT_ANNOTATE + 1, color=COLOR_TEXT,
            )

    for threshold in thresholds:
        ax.axvline(
            threshold,
            color=COLOR_EDGE,
            linestyle="--",
            linewidth=1.2,
            ymin=0,
            ymax=1,
        )
        ax.annotate(
            f"example threshold\n{threshold:.2f}",
            (threshold, len(bands) * band_height),
            textcoords="offset points",
            xytext=(0, -4),
            fontsize=FONT_ANNOTATE - 1,
            color=COLOR_EDGE,
            ha="center",
            va="top",
        )

    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(bands) * band_height)
    ax.set_xlabel("answer confidence", fontsize=FONT_AXIS)
    ax.set_yticks([])
    ax.tick_params(labelsize=FONT_AXIS)
    ax.set_title("Confidence-gated routing bands", fontsize=FONT_TITLE, color=COLOR_TEXT)

    fig.tight_layout()
    return _save(fig, out_dir, "confidence_bands.png")


# ---------------------------------------------------------------------------
# Figure 6 — calibration reliability


def generate_calibration(out_dir: Path, project_root: Path | None = None) -> Path:
    """Reliability curve from the live calibration benchmark (bench_calibration.py).

    Per confidence bucket, markers plot mean reported confidence against the
    observed rate of agreement with the modal choice — a self-consistency
    correctness proxy, not ground truth. The dashed diagonal is perfect
    calibration; the title and annotation carry the model, run date, ECE,
    and Brier score read from the benchmark JSON.
    """
    _style()
    root = Path.cwd() if project_root is None else project_root
    data = _load_benchmark(root, "calibration")

    choice = data.get("choice") or {}
    buckets = list(choice.get("buckets") or [])

    fig, ax = plt.subplots(figsize=SIZE_CHART)
    ax.plot(
        [0.0, 1.0], [0.0, 1.0],
        linestyle="--", color=COLOR_EXTERNAL, linewidth=1.2,
        label="perfect calibration",
    )
    if buckets:
        xs = [float(bucket["mean_confidence"]) for bucket in buckets]
        ys = [float(bucket["accuracy"]) for bucket in buckets]
        ax.plot(
            xs, ys,
            color=COLOR_LAYER_MAIN, marker="o", linewidth=1.6,
            label="observed reliability",
        )
        for bucket in buckets:
            x = float(bucket["mean_confidence"])
            y = float(bucket["accuracy"])
            # Keep size labels inside the axes near the top-right corner.
            if x >= 0.95 or y >= 0.95:
                offset, ha = (-6, -14), "right"
            else:
                offset, ha = (5, -9), "left"
            ax.annotate(
                f"n={int(bucket['n'])}",
                (x, y),
                textcoords="offset points",
                xytext=offset,
                ha=ha,
                fontsize=FONT_ANNOTATE - 1,
                color=COLOR_TEXT,
            )

    ece = choice.get("ece")
    brier = choice.get("brier")
    if ece is not None and brier is not None:
        ax.text(
            0.03, 0.97,
            f"ECE = {float(ece):.4f}\nBrier = {float(brier):.4f}",
            transform=ax.transAxes, ha="left", va="top",
            fontsize=FONT_ANNOTATE, color=COLOR_TEXT,
        )
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.06)  # headroom so top markers are not clipped
    ax.set_xlabel("mean reported confidence in bucket", fontsize=FONT_AXIS)
    ax.set_ylabel("observed accuracy (modal agreement)", fontsize=FONT_AXIS)
    ax.tick_params(labelsize=FONT_AXIS)
    # Title reads model + run date from the benchmark JSON, never hardcoded.
    ax.set_title(
        f"Confidence calibration reliability — {data['model']} ({data['date']})",
        fontsize=FONT_TITLE, color=COLOR_TEXT,
    )
    ax.legend(loc="lower right", fontsize=FONT_ANNOTATE)

    fig.tight_layout()
    return _save(fig, out_dir, "calibration_reliability.png")


# ---------------------------------------------------------------------------
# Graphical abstract — wide cover composition with live benchmark numbers
# ---------------------------------------------------------------------------


def generate_graphical_abstract(out_dir: Path, project_root: Path | None = None) -> Path:
    """Render the wide cover composition into ``graphical_abstract.png``.

    Three zones: (a) the decision state and the three typed question
    primitives; (b) the daf-jev processing stack; (c) live benchmark outputs
    (batching speedup, pipeline p50 latency, calibration reliability) read at
    generation time from the latest benchmark JSONs. Arrows trace state →
    typed answers → routed decisions. Missing benchmark data raises
    :class:`FileNotFoundError` naming the missing file.
    """
    _style()
    root = Path.cwd() if project_root is None else project_root
    batching = _load_benchmark(root, "batching")
    patterns = _load_benchmark(root, "patterns")
    calibration = _load_benchmark(root, "calibration")

    fig = plt.figure(figsize=SIZE_ABSTRACT)
    gs = fig.add_gridspec(
        1, 3,
        width_ratios=[1.0, 0.85, 1.45],
        wspace=0.42,
        left=0.01, right=0.99, top=0.82, bottom=0.07,
    )
    ax_state = fig.add_subplot(gs[0, 0])
    ax_stack = fig.add_subplot(gs[0, 1])
    gs_live = gs[0, 2].subgridspec(3, 1, height_ratios=[1.25, 0.85, 1.25], hspace=0.72)
    ax_batch = fig.add_subplot(gs_live[0])
    ax_lat = fig.add_subplot(gs_live[1])
    ax_cal = fig.add_subplot(gs_live[2])

    fig.suptitle(
        "daf-jev: typed questions, routed decisions, measured trust",
        fontsize=FONT_TITLE, fontweight="bold", color=COLOR_TEXT, y=0.97,
    )

    # --- Zone (a): STATE + question-type cards -------------------------------
    ax_state.set_xlim(0, 100)
    ax_state.set_ylim(0, 100)
    ax_state.set_axis_off()
    ax_state.set_title("ask: state + question primitives", loc="left", fontsize=FONT_MINI + 1, fontweight="bold", color=COLOR_TEXT)
    _panel_letter(ax_state, "a", dx=0.02, dy=0.90)
    _box(ax_state, 22, 70, 56, 16, "STATE", sublabel="context under judgment", facecolor=COLOR_EXTERNAL, aspect=1.0)
    _box(ax_state, 12, 50, 76, 12, "noul()", sublabel="probability", facecolor=COLOR_LAYER_SIDE, aspect=1.0)
    _box(ax_state, 12, 32, 76, 12, "choice()", sublabel="distribution", facecolor=COLOR_LAYER_SIDE, aspect=1.0)
    _box(ax_state, 12, 14, 76, 12, "score()", sublabel="rubric", facecolor=COLOR_LAYER_SIDE, aspect=1.0)
    _arrow(ax_state, (30, 69.5), (30, 63.5))
    _arrow(ax_state, (50, 69.5), (50, 63.5))
    _arrow(ax_state, (70, 69.5), (70, 63.5))

    # --- Zone (b): daf-jev processing stack ----------------------------------
    ax_stack.set_xlim(0, 100)
    ax_stack.set_ylim(0, 100)
    ax_stack.set_axis_off()
    ax_stack.set_title("decide: daf-jev pipeline", loc="left", fontsize=FONT_MINI + 1, fontweight="bold", color=COLOR_TEXT)
    _box(ax_stack, 8, 6, 84, 15, "typed client", sublabel="JevClient", facecolor=COLOR_LAYER_MAIN, aspect=1.0)
    _box(ax_stack, 8, 29, 84, 15, "compose", sublabel="gates + routing", facecolor=COLOR_LAYER_MAIN, aspect=1.0)
    _box(ax_stack, 8, 52, 84, 15, "evaluator", sublabel="calibration", facecolor=COLOR_LAYER_MAIN, aspect=1.0)
    _box(ax_stack, 8, 75, 84, 15, "CLI · MCP · agent skill", facecolor=COLOR_EXTERNAL, aspect=1.0)
    _panel_letter(ax_stack, "b", dx=0.02, dy=0.99)
    _arrow(ax_stack, (50, 45), (50, 51))
    _arrow(ax_stack, (50, 68), (50, 74))

    # Zone-to-zone flow arrows: state → typed answers → routed decisions.
    fig.add_artist(ConnectionPatch(
        xyA=(1.0, 0.45), coordsA="axes fraction", axesA=ax_state,
        xyB=(0.0, 0.45), coordsB="axes fraction", axesB=ax_stack,
        arrowstyle=ARROW_STYLE, mutation_scale=14, linewidth=ARROW_LW, color=COLOR_EDGE,
    ))
    fig.add_artist(ConnectionPatch(
        xyA=(1.0, 0.45), coordsA="axes fraction", axesA=ax_stack,
        xyB=(0.0, 0.45), coordsB="axes fraction", axesB=ax_lat,
        arrowstyle=ARROW_STYLE, mutation_scale=14, linewidth=ARROW_LW, color=COLOR_EDGE,
    ))
    fig.text(0.335, 0.50, "typed\nanswers", ha="center", va="center", fontsize=FONT_MINI - 1, color=COLOR_TEXT, style="italic")
    fig.text(0.615, 0.55, "routed\ndecisions", ha="center", va="center", fontsize=FONT_MINI - 1, color=COLOR_TEXT, style="italic")

    # --- Zone (c): live benchmark outputs ------------------------------------
    _panel_letter(ax_batch, "c", dx=0.02, dy=0.94)

    results = sorted(batching["results"], key=lambda r: r["n"])
    ns = [str(r["n"]) for r in results]
    speedups = [float(r["speedup_ratio"]) for r in results]
    bars = ax_batch.bar(ns, speedups, width=0.55, color=COLOR_LAYER_MAIN)
    for bar, value in zip(bars, speedups, strict=True):  # bar container built from these values
        ax_batch.annotate(
            f"{value:.1f}x",
            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
            textcoords="offset points", xytext=(0, 2),
            ha="center", fontsize=FONT_MINI - 1, color=COLOR_TEXT,
        )
    ax_batch.set_title("batching speedup (×) — N", loc="left", fontsize=FONT_MINI, color=COLOR_TEXT)  # noqa: RUF001  # multiplication sign is intentional typography in the rendered label
    ax_batch.set_ylim(0, max(speedups) * 1.7)
    ax_batch.text(
        0.99, 0.95, f"{batching['model']} · {batching['date']}",
        transform=ax_batch.transAxes, ha="right", va="top",
        fontsize=FONT_MINI - 1, color=COLOR_TEXT,
    )

    pipelines = [key for key in sorted(patterns) if key not in _PATTERN_META_KEYS]
    p50 = [float(patterns[key]["p50_s"]) for key in pipelines]
    _ga_pipeline_labels = {"composite_score_pipeline": "composite scoring", "intent_routing": "intent routing"}
    labels = [textwrap.fill(_ga_pipeline_labels.get(key, key), 16) for key in pipelines]
    bars = ax_lat.barh(labels, p50, height=0.5, color=COLOR_LAYER_MAIN)
    for bar, value in zip(bars, p50, strict=True):  # bar container built from these values
        ax_lat.annotate(
            f"{value:.3f}s",
            (bar.get_width(), bar.get_y() + bar.get_height() / 2),
            textcoords="offset points", xytext=(-4, -1),
            ha="right", va="center", fontsize=FONT_MINI - 1, color="white",
        )
    ax_lat.set_xlim(0, max(p50) * 1.15)
    ax_lat.set_title("pipeline p50 latency (s)", loc="left", fontsize=FONT_MINI, color=COLOR_TEXT)
    ax_lat.tick_params(labelsize=FONT_MINI - 1)
    ax_lat.xaxis.set_major_locator(MaxNLocator(4))
    ax_lat.invert_yaxis()
    choice = calibration.get("choice") or {}
    buckets = list(choice.get("buckets") or [])
    ax_cal.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color=COLOR_EXTERNAL, linewidth=1.0, label="perfect")
    if buckets:
        ax_cal.plot(
            [float(b["mean_confidence"]) for b in buckets],
            [float(b["accuracy"]) for b in buckets],
            color=COLOR_LAYER_MAIN, marker="o", markersize=3.5, linewidth=1.4,
            label="observed",
        )
    ax_cal.set_xlim(0.0, 1.0)
    ax_cal.set_ylim(0.0, 1.06)
    ece = choice.get("ece")
    if ece is not None:
        ax_cal.text(
            0.03, 0.10, f"ECE {float(ece):.3f}",
            transform=ax_cal.transAxes, ha="left", va="bottom",
        )
    ax_cal.set_title("calibration reliability", loc="left", fontsize=FONT_MINI, color=COLOR_TEXT)
    ax_cal.tick_params(labelsize=FONT_MINI - 1)
    ax_cal.legend(loc="lower right", fontsize=FONT_MINI - 2)

    return _save(fig, out_dir, "graphical_abstract.png", tight=False)


_REGISTRY: dict[str, Callable[[Path, Path | None], Path]] = {
    "graphical_abstract": generate_graphical_abstract,
    "architecture": generate_architecture,
    "primitives": generate_primitives,
    "batching": generate_batching,
    "latency": generate_latency,
    "confidence": generate_confidence,
    "calibration": generate_calibration,
}

FIGURE_FILENAMES: dict[str, str] = {
    "graphical_abstract": "graphical_abstract.png",
    "architecture": "architecture.png",
    "primitives": "primitives_overview.png",
    "batching": "batching_speedup.png",
    "latency": "latency_percentiles.png",
    "confidence": "confidence_bands.png",
    "calibration": "calibration_reliability.png",
}


def generate_one(name: str, out_dir: Path, project_root: Path | None = None) -> Path:
    """Render a single registered figure by name.

    Raises :class:`ValueError` naming the valid choices for an unknown name.
    """
    if name not in _REGISTRY:
        raise ValueError(f"unknown figure name {name!r}; valid names: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[name](out_dir, project_root)



FIGURE_REGISTRY_FILENAME = "figure_registry.json"

_FIGURE_META: tuple[dict[str, str], ...] = (
    {
        "label": "fig:graphical_abstract",
        "filename": "graphical_abstract.png",
        "section": "Abstract",
        "width": "1.0\\textwidth",
        "caption": (
            "Graphical abstract of daf-jev. Left: a decision state enters the "
            "package through the three typed question primitives — noul "
            "probability, choice distribution, score rubric. Centre: the "
            "processing stack, from the typed client through the composition "
            "layer with its confidence gates and routing patterns and the "
            "evaluator with its calibration machinery up to the surfaced entry "
            "points (CLI, MCP server, agent skill). Right: live benchmark "
            "outputs read at figure-generation time from the benchmark JSONs — "
            "batching wall-clock speedup with the benchmarked model and run "
            "date, per-pipeline median latency, and the confidence reliability "
            "curve with its expected calibration error (correctness via the "
            "self-consistency proxy across repeated asks; a calibration "
            "proxy, not ground-truth accuracy). Arrows trace the flow "
            "from state, to typed answers, to routed decisions."
        ),
        "alt_text": (
            "Three-panel cover figure: question-type cards fed by a decision "
            "state, a four-layer processing stack from typed client to surfaced "
            "entry points, and miniature benchmark charts of batching speedup, "
            "median pipeline latency, and calibration reliability, annotated "
            "with the benchmarked model and run date."
        ),
    },
    {
        "label": "fig:architecture",
        "filename": "architecture.png",
        "section": "Methodology",
        "width": "0.85\\textwidth",
        "caption": (
            "Package layer diagram for daf-jev. The CLI (src/daf_jev/cli.py) and the "
            "thin orchestration scripts (scripts/, benchmarks/) sit on the application "
            "layer; compose.py (pure decision patterns) and primitives.py (typed "
            "question builders and QuestionSet) form the logic layer over the wire "
            "dataclasses in _types.py; client.py and _http.py own the single transport "
            "to the System One endpoint, with _retry.py and _errors.py providing the "
            "pure retry policy and the typed exception hierarchy. Boxes are named "
            "modules only; no measured values appear in the diagram."
        ),
        "alt_text": (
            "Module graph of daf-jev arranged as stacked layers: the CLI and "
            "orchestration scripts on top, the pure composition and typed-primitive "
            "modules beneath them, the frozen wire dataclasses below that, and the "
            "client/transport layer with the retry policy and typed exceptions at the "
            "bottom, with models.py, config.py, and the batch harness entering as side "
            "inputs."
        ),
    },
    {
        "label": "fig:primitives",
        "filename": "primitives_overview.png",
        "section": "Methodology",
        "width": "0.85\\textwidth",
        "caption": (
            "The three question primitives of the System One surface and the typed "
            "answer shapes daf-jev parses them into. A noul question yields a "
            "calibrated yes/no probability; a choice question yields a selected label, "
            "a full probability distribution over the named options, and a scalar "
            "confidence; a score question yields a probability-weighted score over "
            "ordered levels together with the level legend, the level distribution, "
            "and a confidence. The diagram is a schematic of shapes only — it carries "
            "no measured data."
        ),
        "alt_text": (
            "Schematic of the three question builders (noul, choice, score) with "
            "arrows to their typed answer shapes: a yes/no probability, a selected "
            "label with probability distribution and confidence, and a "
            "probability-weighted score with level legend, level distribution, and "
            "confidence."
        ),
    },
    {
        "label": "fig:batching",
        "filename": "batching_speedup.png",
        "section": "Results",
        "width": "0.85\\textwidth",
        "caption": (
            "Batching speedup of the benchmark model versus sequential "
            "single-question calls, measured by benchmarks/bench_batching.py. Bars "
            "give the wall-time speedup of one batched call over one sequential call "
            "per question for each configured batch width; the secondary axis "
            "shows the token-cost ratio — sequential tokens divided by batched "
            "tokens — which exceeds unity because the sequential "
            "strategy re-sends the state once per question. Bars are annotated with "
            "their values; the title carries the model and run date read from the "
            "benchmark JSON itself."
        ),
        "alt_text": (
            "Bar chart of wall-time speedup versus sequential calls for each "
            "configured batch width, with a secondary-axis token-cost ratio "
            "measuring sequential tokens relative to batched tokens; the "
            "speedup grows with batch width while the sequential strategy "
            "costs proportionally more tokens than the single batched call."
        ),
    },
    {
        "label": "fig:latency",
        "filename": "latency_percentiles.png",
        "section": "Results",
        "width": "0.85\\textwidth",
        "caption": (
            "Median (p50) and tail (p95) end-to-end wall time per decision pipeline, "
            "measured by benchmarks/bench_patterns.py. Each bar is one pipeline "
            "(composite scoring, intent routing) with paired p50/p95 groups; axis "
            "labels are read from the benchmark JSON fields at figure-generation "
            "time."
        ),
        "alt_text": (
            "Grouped bar chart pairing the median and tail wall times of the "
            "composite scoring and intent routing decision pipelines."
        ),
    },
    {
        "label": "fig:confidence",
        "filename": "confidence_bands.png",
        "section": "Methodology",
        "width": "0.8\\textwidth",
        "caption": (
            "Parametric illustration of confidence-gated routing as implemented by "
            "confidence_gate() and route() in src/daf_jev/compose.py. The horizontal "
            "axis is the model-reported confidence on the unit interval; the three "
            "horizontal bands assign an action per confidence region — automate, "
            "review, escalate. The boundary markers are annotated as example "
            "thresholds: they illustrate the band semantics and are not fitted or "
            "recommended values."
        ),
        "alt_text": (
            "Confidence axis on the unit interval divided into three horizontal "
            "bands labelled escalate, review, and automate, with example threshold "
            "markers between the bands."
        ),
    },
    {
        "label": "fig:calibration",
        "filename": "calibration_reliability.png",
        "section": "Results",
        "width": "0.85\\textwidth",
        "caption": (
            "Reliability of the benchmark model's reported confidence, measured "
            "by benchmarks/bench_calibration.py. The same three-option "
            "classification question is asked independently once per repeat for "
            "each of several distinct states; per confidence bucket, markers "
            "plot the mean reported confidence against the observed rate of "
            "agreement with the modal (majority) choice — a self-consistency "
            "correctness proxy, not ground truth. The dashed diagonal is "
            "perfect calibration; bucket sizes are annotated at each marker, "
            "and the annotation and title carry the expected calibration error, "
            "Brier score, model, and run date read from the benchmark JSON."
        ),
        "alt_text": (
            "Reliability diagram plotting mean reported confidence against "
            "observed agreement with the modal choice per confidence bucket, "
            "each marker annotated with its bucket size, close to the dashed "
            "perfect-calibration diagonal, with the expected calibration error "
            "and Brier score annotated in the corner."
        ),
    },
)


def write_figure_registry(out_dir: Path, project_root: Path | None = None) -> Path:
    """Write ``figure_registry.json`` describing every manuscript figure.

    The registry is the engine-facing manifest consumed by template
    validation: one entry per figure label, mirroring the manuscript's own
    figure lines (captions, sections, widths). It is static metadata — no
    measured statistics are embedded.

    Args:
        out_dir: Destination directory (created if absent); the registry is
            written alongside the PNGs as :data:`FIGURE_REGISTRY_FILENAME`.
        project_root: Accepted for signature symmetry with the generator
            functions; the registry is static and reads nothing from the tree.

    Returns:
        The written registry path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    registry: dict[str, Any] = {}
    for index, meta in enumerate(_FIGURE_META, start=1):
        registry[meta["label"]] = {
            "figure_id": f"figure_{index:03d}",
            "filename": meta["filename"],
            "caption": meta["caption"],
            "label": meta["label"],
            "section": meta["section"],
            "width": meta["width"],
            "placement": "h",
            "generated_by": "daf_jev.figures",
            "metadata": {
                "alt_text": meta["alt_text"],
                "source": "daf-jev benchmark/figure pipeline",
            },
        }
    path = out_dir / FIGURE_REGISTRY_FILENAME
    path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def generate_all(out_dir: Path, project_root: Path | None = None) -> list[Path]:
    """Render every registered figure as a PNG into *out_dir*.

    Args:
        out_dir: Destination directory (created if absent).
        project_root: Project root holding ``output/benchmarks/``; defaults
            to the current working directory.

    Returns:
        The written PNG paths, in registry order. As a side effect,
        ``figure_registry.json`` is written into *out_dir* after the PNGs
        (see :func:`write_figure_registry`).

    Raises:
        FileNotFoundError: When a benchmark JSON needed by a data-driven
            figure is missing; the error names the missing file. The
            graphical abstract renders first and needs all three benchmark
            JSONs; the architecture, primitives, and confidence figures are
            data-free and never trigger this.
    """
    paths = [_REGISTRY[name](out_dir, project_root) for name in _REGISTRY]
    write_figure_registry(out_dir, project_root)
    return paths
