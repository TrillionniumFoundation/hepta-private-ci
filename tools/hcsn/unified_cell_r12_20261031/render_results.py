"""Render frozen numerical results; this is postprocessing, not model selection."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
summary = json.loads((ROOT / "evidence/SUMMARY.json").read_text())
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                     "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.1), layout="constrained")
colors = ["#2867ad", "#bd593a"]
for index, domain in enumerate(["iid", "ood"]):
    row = summary["domains"][domain]
    effect = row["contrasts"]["D_minus_B"]
    mean = effect["mean"]
    lo, hi = effect["ci95_student"]
    jitter = np.linspace(-0.13, 0.13, 8)
    axes[0].scatter(effect["paired_values"], index+jitter, color=colors[index], alpha=0.35, s=24)
    axes[0].errorbar(mean, index, xerr=[[mean-lo], [hi-mean]], fmt="o",
                     color=colors[index], capsize=5, linewidth=2, markersize=8)
    axes[0].annotate(f"{mean:+.4f}  |  Holm p={effect['holm_p']:.3f}",
                     xy=(0.03, index), xytext=(0.03, index+0.32),
                     ha="right", va="center", fontsize=10, color=colors[index])
    axes[1].bar(index-0.17, row["unique_actual_cost_ratio_D_over_B"], width=0.30,
                color=colors[index], alpha=0.4, label="Fit reused" if index == 0 else None)
    axes[1].bar(index+0.17, row["conservative_cost_ratio_D_over_B"], width=0.30,
                color=colors[index], label="Equal calibration charge" if index == 0 else None)
axes[0].axvline(0, color="#7b858e", linewidth=1)
axes[0].axvline(0.01, color="#508451", linestyle="--", linewidth=1, label="Required mean gain +0.01")
axes[0].axvline(-0.01, color="#bd593a", linestyle=":", linewidth=1, label="Noninferiority boundary -0.01")
axes[0].set(yticks=[0, 1], yticklabels=["IID", "OOD"], xlim=(-0.031, 0.032),
             ylim=(-0.5, 1.65), xlabel="Utility difference: D minus B",
             title="No confirmed gain over selected GRU")
axes[0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=9, frameon=False)
axes[1].axhline(0.9, color="#508451", linestyle="--", linewidth=1)
axes[1].text(1.5, 0.91, "Required ratio <= 0.90", ha="right", va="bottom", fontsize=9)
axes[1].set(xticks=[0, 1], xticklabels=["IID", "OOD"], ylim=(0, 1.17),
             ylabel="Amortized CPU ratio: D / B",
             title="Fit reuse is not kernel acceleration")
axes[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=9, frameon=False)
fig.suptitle("HCSN R12 | 8 paired fits per domain | frozen confirmation", fontsize=14)
destination = ROOT / "figures"
destination.mkdir(exist_ok=True)
fig.savefig(destination / "confirmation.png", dpi=180)
fig.savefig(destination / "confirmation.svg")
