"""Presentation-only plots of the frozen supplemental summary; no fitting."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / "SUMMARY.json").read_text())
plt.rcParams.update({"font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "svg.fonttype": "none"})
fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.8), gridspec_kw={"width_ratios": [1, 1.3]})
panels = [
    [("primary_utility_contrasts", "B_minus_A", "Ordinary: B - A"),
     ("primary_utility_contrasts", "D_minus_C", "HX: D - C")],
    [("primary_utility_contrasts", "D_minus_B", "Primary: D - B"),
     ("secondary", "D_minus_free_value", "D - free generator"),
     ("secondary", "D_minus_factorized", "D - factorized belief"),
     ("secondary", "D_minus_memoryless", "D - memoryless recovery")],
]
for ax, panel in zip(axes, panels):
    for offset, domain, color, label in [(-.10, "iid", "#176b91", "IID intervals"),
                                         (.10, "ood", "#c66a25", "Extrapolated intervals")]:
        values = []
        for section, name, _ in panel:
            row = data["domains"][domain][section][name]
            values.append(row["utility"] if section == "secondary" else row)
        means = np.array([x["mean"] for x in values]) * 100
        bounds = np.array([x["t95_interval"] for x in values]).T * 100
        ax.errorbar(means, np.arange(len(panel)) + offset,
                    xerr=np.vstack([means - bounds[0], bounds[1] - means]),
                    fmt="o", markersize=6, capsize=4, linewidth=1.6, color=color, label=label)
    ax.axvline(0, color="#60666c", linewidth=1, linestyle="--")
    ax.set_yticks(np.arange(len(panel)), [x[2] for x in panel])
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=.18)
    ax.set_xlabel("Net utility change × 100 (percentage points)")
    ax.set_ylim(len(panel) - .5, -.5)
axes[0].set_title("Shared controller contribution", fontsize=13, pad=15)
axes[1].set_title("Core and mechanism increments", fontsize=13, pad=15)
axes[0].set_xlim(-.05, 4.5)
axes[1].set_xlim(-.25, .25)
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .89), ncol=2, frameon=False)
fig.suptitle("R15 supplemental confirmation: paired effects across 8 fitted seeds", y=.98, fontsize=16)
fig.text(.5, .055,
         "Descriptive t95% intervals. Primary D - B: Holm-adjusted p = 1.00 in both domains.\n"
         "Secondary contrasts are descriptive; the index-mean arm is invalid. Panel scales differ.",
         ha="center", va="bottom", fontsize=10, color="#46515d")
fig.subplots_adjust(top=.76, bottom=.23, left=.16, right=.98, wspace=.75)
for suffix in ("png", "svg"):
    fig.savefig(ROOT / f"contrast_forest.{suffix}", dpi=200, bbox_inches="tight", facecolor="white")
plt.close(fig)
