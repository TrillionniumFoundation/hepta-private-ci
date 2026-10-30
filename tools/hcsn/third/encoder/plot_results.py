"""Render the eight frozen primary contrasts without selecting outcomes."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent


def main():
    report = json.loads((HERE/"analysis.json").read_text())
    labels = ["AG News / clean", "AG News / word deletion",
              "CIFAR-10 / clean", "CIFAR-10 / occlusion"]
    pairs = [(dataset, split) for dataset in ("ag_news", "cifar10")
             for split in ("test", "corrupted_test")]
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.6), sharex=True, sharey=True)
    fig.patch.set_facecolor("white")
    for ax, regime, title in zip(axes, ("dynamic_head", "linear_plus_dynamic"),
                                 ("Dynamic head", "Frozen linear + dynamic head")):
        for index, (dataset, split) in enumerate(pairs):
            row = next(r for r in report["contrasts"] if r["primary_family"]
                       and (r["dataset"], r["regime"], r["split"]) == (dataset, regime, split))
            mean = 100*row["mean"]
            low, high = np.array(row["bonferroni_family95"])*100
            color = "#2563eb" if dataset == "ag_news" else "#7c3aed"
            ax.errorbar(mean, index, xerr=[[mean-low], [high-mean]], fmt="o", color=color,
                        ecolor=color, capsize=5, elinewidth=2, markersize=6)
        ax.axvline(0, color="#475569", linewidth=1, linestyle="--")
        ax.set_xlim(-6.3, 6.3)
        ax.set_xticks([-6, -3, 0, 3, 6])
        ax.set_yticks(range(4), labels, fontsize=10)
        ax.set_title(title, fontsize=13, pad=16)
        ax.grid(axis="x", color="#e2e8f0", linewidth=.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=8)
    axes[0].invert_yaxis()
    fig.suptitle("FullHX minus ordinary C1: no primary interval excludes zero", fontsize=15, y=.98)
    fig.supxlabel("Accuracy difference (percentage points; positive favors FullHX)", fontsize=11, y=.09)
    fig.text(.5, .015, "95% family-wise intervals: Bonferroni over 8 comparisons, 5 paired training seeds; fixed sample and budget",
             ha="center", fontsize=9, color="#475569")
    fig.subplots_adjust(left=.19, right=.98, top=.79, bottom=.24, wspace=.16)
    fig.savefig(HERE/"primary_contrasts.png", dpi=170, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
