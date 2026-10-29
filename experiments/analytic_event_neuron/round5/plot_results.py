"""Render the frozen confirmation outcome; this script makes no selections."""

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    root = Path(__file__).resolve().parent
    source = root / "evidence/selection_registered_001/confirmation/RESULTS.json"
    result = json.loads(source.read_text())
    destination = root / "figures"
    destination.mkdir(exist_ok=True)
    arms = ["frozen", "replay_legacy", "gaussian_full_range", "mixture_legacy",
            "mixture_full_range", "moment_legacy", "moment_full_range", "same_weight_moment_full"]
    labels = ["Frozen anchor", "Replay Gaussian", "Online Gaussian", "Mixture / legacy grid",
              "Mixture / full grid", "Moment / legacy grid", "Moment / full grid", "Moment / same weight"]
    colors = ["#B4BDC6", "#7894A3", "#9CB0B8", "#7799BF", "#2563A6", "#AD9AC8", "#8060A7", "#C1B2D2"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.labelcolor": "#26364A", "text.color": "#17283C",
                         "xtick.color": "#526174", "ytick.color": "#26364A", "svg.hashsalt": "hepta-r5-confirmation"})
    fig = plt.figure(figsize=(15, 10), facecolor="white")
    grid = fig.add_gridspec(2, 2, height_ratios=[1.0, 2.0], hspace=.65, wspace=.23)
    ax = fig.add_subplot(grid[0, :])
    names = ["mixture_full_range_minus_mixture_legacy", "moment_full_range_minus_moment_legacy"]
    values = [result["comparisons"][name] for name in names]
    for y, row, color in zip([1, 0], values, [colors[4], colors[6]]):
        mean, interval = row["mean_difference"], row["interval"]
        ax.errorbar(mean, y, xerr=[[mean - interval[0]], [interval[1] - mean]],
                    fmt="o", markersize=8, capsize=6, elinewidth=2.5, color=color)
        ax.text(interval[1] + .00022, y, f"{mean:+.6f}", va="center", fontsize=11, weight="bold")
    ax.axvline(0, color="#7C8A98", ls="--", lw=1)
    ax.set(yticks=[1, 0], yticklabels=["Exact mixture", "Moment Gaussian"],
           xlim=(-.0008, .0105), ylim=(-.65, 1.65),
           xlabel="Full-grid minus legacy-grid density NLL  (positive = worse)")
    ax.set_title("A  |  Both registered range-expansion contrasts worsened", loc="left", fontsize=13, weight="bold", pad=15)
    ax.text(.99, 1.13, "Nominal 97.5% hierarchical intervals; family of two", transform=ax.transAxes,
            ha="right", fontsize=10, color="#526174")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#E8ECF0", zorder=0)

    left = fig.add_subplot(grid[1, 0])
    right = fig.add_subplot(grid[1, 1], sharey=left)
    y = np.arange(len(arms))
    ece = np.array([result["arms"][arm]["pooled_shifted_classwise_ece"] for arm in arms])
    coverage = np.array([result["arms"][arm]["pooled_shifted_coverage95"] for arm in arms])
    left.barh(y, ece, color=colors, height=.64, zorder=2)
    left.axvline(.04, color="#A64A44", lw=1.4, ls="--", zorder=3)
    left.set(yticks=y, yticklabels=labels, xlim=(0, .069), xlabel="Classwise ten-bin ECE")
    left.invert_yaxis()
    left.text(.04, -.8, "maximum .040", fontsize=10, ha="center", color="#A64A44")
    left.set_title("B  |  Calibration: 0 / 8 pass", loc="left", fontsize=13, weight="bold", pad=24)
    for index, value in enumerate(ece):
        left.text(value + .001, index, f"{value:.5f}", va="center", fontsize=9)
    right.axvspan(.92, .98, color="#E8F1EB", zorder=0)
    right.axvline(.92, color="#718A77", lw=1, ls=":")
    right.axvline(.98, color="#718A77", lw=1, ls=":")
    right.scatter(coverage, y, c=colors, s=80, edgecolors="white", linewidths=.5, zorder=2)
    right.set(xlim=(.88, 1.0), xlabel="Empirical coverage of 95% intervals")
    right.tick_params(axis="y", labelleft=False, length=0)
    right.set_title("C  |  Coverage has a separate gate", loc="left", fontsize=13, weight="bold", pad=24)
    right.text(.95, -.8, "acceptance band .92–.98", fontsize=10, ha="center", color="#526F59")
    for index, value in enumerate(coverage):
        right.text(value + .004, index, f"{100 * value:.2f}%", va="center", fontsize=10)
    for axis in (left, right):
        axis.grid(axis="x", color="#E8ECF0", zorder=0)
        axis.spines["left"].set_visible(False)
    fig.suptitle("Hepta analytic-event research · Round 5 confirmation", x=.05, y=.985,
                 ha="left", fontsize=20, weight="bold")
    fig.text(.05, .945, "5 training seeds  ·  16,640 independent query trajectories  ·  0 / 8 joint empirical gates passed",
             fontsize=12, color="#526174")
    fig.text(.05, .022, "Three horizons remain clustered within each query. ECE and coverage pool the six shifted windows.\n"
             "Five-cluster bootstrap intervals are nominal/approximate. No model or threshold was changed after confirmation.",
             fontsize=10, color="#526174", linespacing=1.6)
    fig.subplots_adjust(left=.19, right=.96, top=.84, bottom=.11)
    outputs = []
    for suffix in ("svg", "png"):
        path = destination / ("selection_results." + suffix)
        fig.savefig(path, dpi=180, facecolor="white", metadata={"Date": None} if suffix == "svg" else None)
        outputs.append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    plt.close(fig)
    (destination / "PROVENANCE.json").write_text(json.dumps({"results_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "outputs": outputs,
        "scientific_selection_or_gate_changes": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()
