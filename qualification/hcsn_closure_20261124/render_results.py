"""Render audited measurements; never construct data, train or select models."""

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
INPUT = HERE/"evidence/companion_results"
OUT = HERE/"figures"


def main():
    names = ("DECISION_SUMMARY.json", "MAIN_COMPACT_SUMMARY.json",
             "FAST_SUMMARY.json", "BASELINE_WALL_SUMMARY.json")
    data = {name: json.loads((INPUT/name).read_text()) for name in names}
    baseline = data[names[0]]["baselines"]
    main_groups = data[names[1]]["groups"]
    fast = data[names[2]]["groups"]
    wall = {(g["kind"], g["reference_neurons"]): g["complete_fit_wall_seconds"]
            for g in data[names[3]]["groups"]}
    widths = (8, 32, 64)
    families = ("HCSN", "GRU", "surrogate_LIF", "causal_Transformer")
    labels = ("HCSN (QVI / mixed)", "GRU", "LIF (surrogate BP)", "Causal Transformer")
    colors = ("#245ab5", "#14856f", "#bb6b16", "#8b5b9d")
    records = []
    for family in families:
        for n in widths:
            if family == "HCSN":
                group = main_groups[f"n{n}/qvi/value_risk/mixed"]
                accuracy, cost = group["accuracy"], group["full_wall"]
                sd = accuracy["sample_sd"]
            else:
                accuracy = baseline[f"{family}/N{n}"]["accuracy"]
                cost, sd = wall[family, n], accuracy["sd"]
            records.append({"family": family, "width_reference": n,
                "accuracy_mean": accuracy["mean"], "accuracy_sample_sd": sd,
                "full_fit_wall_mean": cost["mean"], "full_fit_wall_sample_sd": cost["sample_sd"]})
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.labelcolor": "#25344a", "text.color": "#25344a",
        "axes.titleweight": "bold", "figure.facecolor": "white"})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    x, bar_width = np.arange(3), .19
    for i, (family, label, color) in enumerate(zip(families, labels, colors)):
        rows = [r for r in records if r["family"] == family]
        pos = x+(i-1.5)*bar_width
        axes[0].bar(pos, [100*r["accuracy_mean"] for r in rows], bar_width,
            yerr=[100*r["accuracy_sample_sd"] for r in rows], capsize=2.5,
            color=color, label=label, error_kw={"linewidth": .9})
        axes[1].bar(pos, [r["full_fit_wall_mean"] for r in rows], bar_width,
            color=color)
        for point, row in zip(pos, rows):
            axes[1].text(point, row["full_fit_wall_mean"]*1.07,
                f'{row["full_fit_wall_mean"]:.1f}', ha="center", va="bottom", fontsize=7)
    axes[0].set(title="A  Test quality", ylabel="Accuracy (%)", ylim=(65, 106))
    axes[0].axhline(100, color="#697489", linewidth=.7, linestyle=":")
    axes[1].set(title="B  Complete training cost", ylabel="Launch-to-exit wall time (seconds)",
                yscale="log", ylim=(4, 1100))
    for ax in axes:
        ax.set_xticks(x, [f"N{n}" for n in widths])
        ax.set_xlabel("Approximate parameter-capacity reference")
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=.16)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncols=4,
               frameon=False, bbox_to_anchor=(.5, .07))
    fig.suptitle("Frozen short-task comparison: same data and 512 updates", y=.98, fontsize=14, weight="bold")
    fig.text(.5, .035, "Three seeds per condition; quality bars show sample SD. Parameter counts are approximately matched.",
             ha="center", fontsize=9)
    fig.subplots_adjust(top=.85, bottom=.24, wspace=.28)
    for extension in ("png", "svg"):
        fig.savefig(OUT/("quality_cost."+extension), dpi=160, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.2, 4.7))
    efficiency_records = []
    for i, n in enumerate(widths):
        original = fast[f"n{n}/original"]["cost"]["fit_full_wall_seconds"]
        candidate = fast[f"n{n}/fast"]["cost"]["fit_full_wall_seconds"]
        ratios = np.array(candidate["values"])/np.array(original["values"])
        mean_ratio = candidate["mean"]/original["mean"]
        efficiency_records.append({"width": n, "original_wall": original,
            "fast_wall": candidate, "paired_wall_ratios": ratios.tolist(),
            "ratio_of_wall_means": mean_ratio})
        ax.bar(i, mean_ratio, .5, color="#245ab5", alpha=.85)
        ax.scatter(i+np.array([-.11, 0, .11]), ratios, s=38,
            color="#172e4b", edgecolor="white", linewidth=.7, zorder=3)
        ax.text(i, .14, f'{original["mean"]:.1f} s → {candidate["mean"]:.1f} s\n'
            f'{(1-mean_ratio)*100:.1f}% less wall time', ha="center", va="center", fontsize=10)
    ax.axhline(1, color="#697489", linestyle="--", linewidth=1)
    ax.text(2.37, 1.015, "Original = 1", ha="right", color="#697489", fontsize=9)
    ax.set(xticks=range(3), xticklabels=[f"N{n}" for n in widths], ylim=(0, 1.1),
        ylabel="Fast / original complete fit wall time", title="Paired kernel acceleration on a separate frozen sample")
    ax.grid(axis="y", alpha=.15); ax.set_axisbelow(True)
    fig.text(.5, .025, "9 pairs, 512 updates each. Selected test accuracy and Brier match in all pairs. Dots are paired seeds.",
             ha="center", fontsize=8.7)
    fig.subplots_adjust(bottom=.16, top=.87)
    for extension in ("png", "svg"):
        fig.savefig(OUT/("kernel_acceleration."+extension), dpi=160, bbox_inches="tight")
    plt.close(fig)
    receipt = {"schema": "hcsn-audited-figure-data-v1", "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "inputs": {name: hashlib.sha256((INPUT/name).read_bytes()).hexdigest() for name in names},
        "quality_cost": records, "kernel_acceleration": efficiency_records,
        "new_data_or_model_selection": False,
        "scope": "Synthetic T12 task only. Cost is full fit, with final holdout evaluation accounted separately. No GPU or joule claim."}
    (OUT/"FIGURE_DATA.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"files": [p.name for p in OUT.iterdir()], "conditions": len(records)}))


if __name__ == "__main__":
    main()
