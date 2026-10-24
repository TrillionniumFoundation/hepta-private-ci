"""Render the fixed systems facts without fitting, prediction or resampling."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import numpy as np


MODES = ("linear", "gated", "residual")
COLORS = {"linear": "#1766a3", "gated": "#df7d23", "residual": "#237d64"}
LABELS = {"linear": "Linear", "gated": "Gated", "residual": "Residual r4"}
INK, MUTED, GRID = "#1a2d45", "#586676", "#e4e9ef"
MIB = 1024**2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def style(axis):
    axis.set_axisbelow(True)
    axis.grid(axis="y", color=GRID, linewidth=.8)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["bottom", "left"]].set_color("#bec8d3")
    axis.tick_params(colors=MUTED, labelsize=10)
    axis.xaxis.label.set_color(MUTED)
    axis.yaxis.label.set_color(MUTED)


def title(axis, heading, description):
    axis.set_title(heading, loc="left", fontsize=13, fontweight="bold", color=INK, pad=29)
    axis.text(0, 1.035, description, transform=axis.transAxes, ha="left", va="bottom",
              fontsize=10, color=MUTED)


def plot(facts_path, output):
    facts_path, output = Path(facts_path), Path(output)
    if output.exists():
        raise ValueError("new figure output required")
    source_sha = sha(facts_path)
    facts = json.loads(facts_path.read_bytes())
    if (facts["schema"] != "hepta.runtime-770-fixed-facts.v1"
            or facts["input"]["width"] != 770 or facts["input"]["task_count"] != 1
            or facts["serving"]["condition_count"] != 27
            or facts["training"]["condition_count"] != 9):
        raise ValueError("fixed one-task 770D systems observations required")
    serving = {(r["mode"], r["physical_cells"], r["batch_rows"]): r
               for r in facts["serving"]["conditions"]}
    training = {(r["mode"], r["physical_cells"]): r for r in facts["training"]["conditions"]}
    scales = sorted({r["physical_cells"] for r in facts["training"]["conditions"]})
    if scales != [64, 256, 1024] or any(r["logical_states"] != 9 for r in serving.values()):
        raise ValueError("complete frozen scales and nine serving states required")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.labelsize": 11, "figure.facecolor": "white",
                         "savefig.facecolor": "white", "axes.facecolor": "white"})
    fig = plt.figure(figsize=(16, 11.8))
    grid = fig.add_gridspec(2, 2, left=.075, right=.965, bottom=.13, top=.845,
                           hspace=.66, wspace=.25)
    a = fig.add_subplot(grid[0, 0])
    b_grid = grid[0, 1].subgridspec(2, 1, height_ratios=[3.2, 1.15], hspace=.19)
    b = fig.add_subplot(b_grid[0, 0])
    cold = fig.add_subplot(b_grid[1, 0])
    c, d = fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])
    for axis in (a, b, c, d):
        style(axis)

    title(a, "A  Reusing frozen states reduces repeated dispatch",
          "64 source rows / call  |  9 unique states per architecture  |  1 task")
    for mode in MODES:
        rows = [serving[mode, scale, 64] for scale in scales]
        a.plot(scales, [r["physical_p50_ms"] for r in rows], color=COLORS[mode],
               marker="s", markersize=5, linestyle="--", linewidth=1.6, alpha=.85)
        a.plot(scales, [r["logical_p50_ms"] for r in rows], color=COLORS[mode],
               marker="o", markersize=6, linewidth=2.3)
    a.set_xscale("log", base=2)
    a.set_xticks(scales, labels=[str(v) for v in scales])
    a.set_xlim(53, 1240)
    a.set_yscale("log")
    a.set_ylim(4, 1800)
    a.set_yticks([5, 10, 20, 50, 100, 200, 500, 1000])
    a.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    a.set_xlabel("Physical serving Cell IDs")
    a.set_ylabel("Outer-call p50, ms (log scale)")
    handles = [Line2D([0], [0], color=COLORS[m], lw=2, label=LABELS[m]) for m in MODES]
    handles += [Line2D([0], [0], color=INK, ls="--", marker="s", label="All physical copies"),
                Line2D([0], [0], color=INK, lw=2.3, marker="o", label="Reuse + fanout")]
    a.legend(handles=handles, loc="upper left", fontsize=9, frameon=False, ncol=2,
             columnspacing=1.4, handlelength=2.4)

    title(b, "B  Small requests and cold setup retain real costs",
          "1 source row / call  |  warm physical p50 / reuse p50  |  >1 is faster")
    for mode in MODES:
        b.plot(scales, [serving[mode, scale, 1]["warm_p50_ratio"] for scale in scales],
               color=COLORS[mode], marker="o", markersize=5, linewidth=2)
    b.axhline(1, color=INK, lw=1, ls=":")
    b.set_xscale("log", base=2)
    b.set_yscale("log", base=2)
    b.set_xlim(53, 1240)
    b.set_ylim(.65, 16)
    b.set_xticks(scales, labels=[str(v) for v in scales])
    b.set_yticks([1, 2, 4, 8, 16], labels=["1×", "2×", "4×", "8×", "16×"])
    b.set_ylabel("Warm p50 ratio")
    below = [f"{LABELS[m]} {serving[m, 64, 1]['warm_p50_ratio']:.2f}×"
             for m in ("linear", "gated")]
    b.text(.025, .94, "64 IDs: " + "  |  ".join(below) + "  (slower)",
           transform=b.transAxes, va="top", fontsize=9.5, color="#9b3b25",
           bbox={"facecolor": "#fff5ef", "edgecolor": "none", "pad": 4})
    cold.axis("off")
    cold.text(0, 1.02, "Cold construction at 1024 IDs / 1 row (ms)",
              fontsize=10, fontweight="bold", color=INK, va="top")
    cold_rows = [[LABELS[m], f"{serving[m, 1024, 1]['physical_setup_ms']:.2f}",
                  f"{serving[m, 1024, 1]['logical_setup_ms']:.2f}"] for m in MODES]
    table = cold.table(cellText=cold_rows, colLabels=["", "Physical", "Reuse"],
                       colWidths=[.42, .29, .29], cellLoc="left", colLoc="left",
                       bbox=[0, -.14, .91, .97])
    table.auto_set_font_size(False)
    table.set_fontsize(9.2)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        cell.set_facecolor("#eef2f7" if row == 0 else "#f8fafc")
        cell.set_text_props(color=INK, weight="bold" if row == 0 else "normal")

    title(c, "C  Microbatch training speeds up distinct private states",
          "1 task  |  one fit per path / condition  |  ratio = scalar fit / batched fit")
    positions, bar_width = np.arange(len(scales)), .24
    for index, mode in enumerate(MODES):
        ratios = [training[mode, scale]["fit_ratio"] for scale in scales]
        bars = c.bar(positions + (index-1)*bar_width, ratios, bar_width,
                     color=COLORS[mode], label=LABELS[mode])
        c.bar_label(bars, labels=[f"{value:.2f}×" for value in ratios], padding=4,
                     fontsize=9, color=INK)
    c.axhline(1, color=INK, ls=":", linewidth=1)
    c.set_ylim(0, 3.0)
    c.set_xticks(positions, labels=[str(v) for v in scales])
    c.set_xlabel("Independently updated private Cell states")
    c.set_ylabel("Fit-time ratio (>1 is faster)")
    c.legend(loc="upper right", ncol=3, fontsize=9, frameon=False, handlelength=1.1,
             columnspacing=1.1)

    title(d, "D  Training retains private weights and optimizer state",
          "1024 distinct states per architecture  |  trainer tensor scope, 1 task")
    selected = [training[mode, 1024] for mode in MODES]
    params = np.array([r["parameter_bytes"] for r in selected])/MIB
    moments = np.array([r["optimizer_bytes"] for r in selected])/MIB
    bounds = np.array([r["total_tensor_bound_bytes"] for r in selected])/MIB
    other = bounds-params-moments
    if np.any(other < 0):
        raise ValueError("tensor envelope cannot be smaller than parameters and moments")
    at = np.arange(len(MODES))
    d.bar(at, params, .58, color="#1766a3", label="Private parameters (allocated)")
    d.bar(at, moments, .58, bottom=params, color="#76a9ce", label="Adam moments (allocated)")
    d.bar(at, other, .58, bottom=params+moments, color="#e2e8ef", edgecolor="#8796a8",
           linewidth=.5, hatch="///", label="Other tensors + workspace allowance")
    for index, total in enumerate(bounds):
        d.text(index, total+9, f"{total:.1f}", ha="center", fontsize=10,
               fontweight="bold", color=INK)
    limit = facts["training"]["trainer_tensor_limit_bytes"]/MIB
    d.axhline(limit, color="#9b3b25", ls="--", linewidth=1.2)
    d.text(2.43, limit+7, f"{limit:g} MiB trainer limit", ha="right", color="#9b3b25", fontsize=9.5)
    d.set_ylim(0, limit*1.10)
    d.set_xlim(-.55, 2.55)
    d.set_xticks(at, labels=[LABELS[m] for m in MODES])
    d.set_ylabel("MiB (tensor allocation / conservative bound)")
    d.legend(loc="upper left", bbox_to_anchor=(0, .88), fontsize=9, frameon=False,
             handlelength=1.5, labelspacing=.5)

    fig.suptitle("Shared features, small Cell heads: measured runtime trade-offs",
                 x=.075, y=.975, ha="left", fontsize=21, fontweight="bold", color=INK)
    fig.text(.075, .937, "770D frozen features  |  One historical task  |  Zero new Encoder calls  |  Systems regression only",
             fontsize=12, color=MUTED)
    fig.text(.075, .909,
             f"Serving: {facts['serving']['repeats']} timed repeats after warmup. Training: one matched fit per condition; no quality evaluation.",
             fontsize=10.5, color=MUTED)
    fig.text(.075, .078,
             "A–B: exact serving replicas share 9 states; they are not 1024 learned tasks. Cold construction is separate from warm calls.",
             fontsize=10, color=MUTED)
    fig.text(.075, .055,
             "C: fit-only timing; setup, snapshots and I/O are separate. D: bound excludes caller copies, snapshots, Python and BLAS memory.",
             fontsize=10, color=MUTED)
    fig.text(.075, .031,
             "Shared CPU observations; no latency SLO, energy or quality claim. SHADOW_ONLY / DENY_ALL.  "
             + f"Source: runtime-facts.json · SHA256 {source_sha[:16]}…", fontsize=9.5, color=MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, metadata={"Software": "Matplotlib; fixed runtime-facts.json only",
                                          "SourceSHA256": source_sha})
    plt.close(fig)
    if sha(facts_path) != source_sha:
        raise ValueError("fixed numeric facts changed during rendering")
    return {"schema": "hepta.runtime-fixed-figure.v1", "facts_sha256": source_sha,
            "source_sha256": sha(__file__), "png_sha256": sha(output),
            "png_bytes": output.stat().st_size, "pixels": [3200, 2360],
            "matplotlib_version": matplotlib.__version__, "numpy_version": np.__version__,
            "numeric_input_count": 1, "new_predictions": 0, "new_fits": 0, "resampling": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(plot(args.facts, args.output), sort_keys=True))
