"""Static scientific figures; seeds are observations, not confidence intervals."""

from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D


COLORS = ("#1976a3", "#63a5ba", "#b33273", "#8b7b4c", "#46754e",
          "#8c78ad", "#5c6472", "#dd7a27")
MARKERS = ("o", "s", "D", "^", "v", "P", "X", "*")
NAMES = ("Ordinary dual", "Probit", "Analytic renewal", "LIF + surrogate",
         "Continuous RNN", "CfC", "Mamba-1 CPU", "SDPA Transformer")


def make_figures(output, families, per_seed, aggregate, amortized):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none"})
    style = {family: (COLORS[i], MARKERS[i], NAMES[i])
             for i, family in enumerate(families)}
    handles = [Line2D([], [], color=style[f][0], marker=style[f][1], linestyle="",
                       markersize=7, label=style[f][2]) for f in families]
    groups = [(task, mode) for task in ("recall", "binding")
              for mode in ("frozen_frontend", "joint")]
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.8))
    for ax, (task, mode) in zip(axes.flat, groups):
        means = [r for r in aggregate if (r["task"], r["mode"]) == (task, mode)]
        for row in means:
            color, marker, _ = style[row["family"]]
            seeds = [r for r in per_seed if (r["task"], r["mode"], r["family"])
                     == (task, mode, row["family"])]
            ax.scatter([r["profile_cpu_s_b1"] * 1000 for r in seeds],
                       [r["accuracy"] for r in seeds], color=color, marker=marker,
                       alpha=.28, s=28, linewidths=.6)
            ax.scatter(row["cpu_ms_b1_mean"], row["accuracy_mean"], color=color,
                       marker=marker, s=90, edgecolors="white", linewidths=.7, zorder=4)
        frontier = sorted([r for r in means if r["pareto_batch1"]],
                          key=lambda r: r["cpu_ms_b1_mean"])
        ax.plot([r["cpu_ms_b1_mean"] for r in frontier],
                [r["accuracy_mean"] for r in frontier], "--", color="#333333",
                linewidth=1.1, zorder=1)
        ax.set(xscale="log", xlabel="Warm end-to-end CPU per request (ms, batch 1)",
               ylabel="IID accuracy", title=f"{task.title()} · {mode.replace('_', ' ')}")
        ax.grid(alpha=.15)
        ax.set_ylim((.30, .75) if task == "recall" else (.48, .59))
    fig.suptitle("R12 quality and measured CPU cost", fontsize=19, y=.98)
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .935),
               ncol=4, frameon=False, fontsize=10)
    fig.text(.5, .035,
             "Large symbols: mean of 3 fits; small symbols: individual fits. Dashed: descriptive mean Pareto frontier.\n"
             "Fixed synthetic datasets; single-thread cached tensors; validation-shape timing. No stress-domain or energy claim.",
             ha="center", fontsize=9, color="#48515d")
    fig.subplots_adjust(top=.82, bottom=.13, hspace=.31, wspace=.20)
    save(fig, output / "quality_cpu")
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.8))
    for ax, (task, mode) in zip(axes.flat, groups):
        for family in families:
            rows = [r for r in amortized if (r["task"], r["mode"], r["family"])
                    == (task, mode, family)]
            counts = sorted({r["requests"] for r in rows})
            means = [np.mean([r["cpu_s_per_request"] for r in rows
                              if r["requests"] == n]) * 1000 for n in counts]
            color, marker, _ = style[family]
            ax.plot(counts, means, color=color, marker=marker, markersize=3.5,
                    linewidth=1.6 if family in ("analytic", "ordinary_dual", "transformer") else 1)
        ax.set(xscale="log", yscale="log", xlabel="Requests served per fitted candidate",
               ylabel="Training + warm inference CPU / request (ms)",
               title=f"{task.title()} · {mode.replace('_', ' ')}")
        ax.grid(alpha=.15, which="both")
    fig.suptitle("Measured training amortization", fontsize=19, y=.98)
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .935),
               ncol=4, frameon=False, fontsize=10)
    fig.text(.5, .035,
             "CPU/request = (full donor training + candidate fit/selection)/N + warm batch-1 request CPU; mean of 3 fits.\n"
             "One candidate trained and reused. Excludes unmeasured service startup; no quality conversion, tariff, price or joules.",
             ha="center", fontsize=9, color="#48515d")
    fig.subplots_adjust(top=.82, bottom=.13, hspace=.31, wspace=.20)
    save(fig, output / "training_amortization")


def save(figure, stem):
    for extension in ("png", "svg"):
        figure.savefig(Path(str(stem) + "." + extension), dpi=180, facecolor="white")
    plt.close(figure)
