"""Export the measured mechanism contrasts and same-precision kernel costs."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot(source, output):
    data = json.loads(Path(source).read_text())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.7), gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(left=.19, right=.97, bottom=.31, top=.80, wspace=.38)
    rows = [("B-A", "Control effect\nordinary core"),
            ("D-C", "Control effect\nanalytic core"),
            ("D-B", "Analytic core effect\nsame value controller")]
    colors = {"matched": "#147D92", "hidden_refractory_mismatch": "#878D98"}
    for condition, offset, label in (("matched", -.11, "Matched process"),
                                      ("hidden_refractory_mismatch", .11, "Hidden refractory mismatch")):
        estimates = data["conditions"][condition]["estimates"]
        means = np.array([estimates[key]["task_utility"]["mean"] for key, _ in rows]) * 100
        ci = np.array([estimates[key]["task_utility"]["ci95"] for key, _ in rows]) * 100
        axes[0].errorbar(means, np.arange(3) + offset,
            xerr=np.stack((means - ci[:, 0], ci[:, 1] - means)), fmt="o", capsize=4,
            markersize=6, color=colors[condition], label=label, linewidth=1.6)
    axes[0].axvline(0, color="#30343B", linewidth=1)
    axes[0].set_yticks(range(3), [label for _, label in rows])
    axes[0].invert_yaxis()
    axes[0].set_ylim(2.6, -.6)
    axes[0].set_xlabel("Task utility difference x 100")
    axes[0].set_title("Controller gains; core advantage unresolved", loc="left", fontsize=12, pad=18)
    axes[0].grid(axis="x", alpha=.18)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(.19, .13),
               ncol=2, frameon=False, fontsize=9)
    aggregate = data["diagnostics"]["aggregate"]
    names = ["analytic_full_distribution", "matched_numerical_integral"]
    values = [aggregate[key]["cpu_seconds_per_query"] * 1000 for key in names]
    bars = axes[1].bar([0, 1], values, width=.54, color=["#147D92", "#D29443"])
    axes[1].set_xticks([0, 1], ["Analytic renewal", "Density quadrature"])
    axes[1].set_ylabel("CPU milliseconds / content query")
    axes[1].set_ylim(0, max(values) * 1.32)
    axes[1].set_title("Local kernel at matched precision", loc="left", fontsize=11, pad=18)
    for bar, value in zip(bars, values, strict=True):
        axes[1].text(bar.get_x() + bar.get_width() / 2, value + .02, f"{value:.3f} ms",
                     ha="center", fontsize=11)
    ratio = values[1] / values[0]
    axes[1].text(.5, .88, f"Quadrature / analytic = {ratio:.2f}x", transform=axes[1].transAxes,
                 ha="center", color="#30343B", fontsize=11)
    axes[1].grid(axis="y", alpha=.18)
    axes[1].set_axisbelow(True)
    fig.suptitle("HCSN mechanism study: what the measured gains belong to", x=.04, y=.96,
                 ha="left", fontsize=15, fontweight="bold")
    fig.text(.04, .04, "Utility = accuracy - 0.04 x READ count. 95% paired hierarchical bootstrap; 3 fitted seeds.\n"
             "384 local precision cases; probability error <= 1e-8. Kernel acceleration does not establish whole-network savings.",
             fontsize=9, color="#505764", linespacing=1.6)
    for extension in ("png", "svg"):
        fig.savefig(output / ("mechanism_attribution." + extension), dpi=170, facecolor="white")
    plt.close(fig)
    with (output / "PLOT_SOURCE.json").open("x") as stream:
        json.dump({"source": str(source), "data_are_measured": True,
                   "maximum_probability_error": data["diagnostics"]["maximum_probability_error"],
                   "local_cpu_ratio": ratio}, stream, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plot(args.source, args.output)
