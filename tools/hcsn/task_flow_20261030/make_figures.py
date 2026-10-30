"""Render descriptive paired-seed evidence, without model or endpoint selection."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent


def main():
    source = HERE / "memory" / "results.json"
    result = json.loads(source.read_text())
    if not result["complete"] or len(result["runs"]) != 30:
        raise RuntimeError("Plot only the complete frozen matrix")
    conditions = [
        ("memory", "test512", "Memory\nlength 512"),
        ("retrieval", "test512", "Retrieval\nlength 512"),
        ("retrieval", "capacity8_512", "8 associations\nlength 512"),
        ("retrieval", "overwrite128", "Latest-value overwrite\nlength 128"),
        ("retrieval", "interference128", "Filler interference\nlength 128"),
    ]
    variants = [
        ("full_fixed", "Fixed ridge", "#405d80"),
        ("full_mass", "Mass ridge*", "#39958b"),
        ("full_delta", "Bounded residual write", "#df8b29"),
    ]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(12.6, 5.7))
    records = []
    for index, (variant, label, color) in enumerate(variants):
        x = np.arange(len(conditions)) + (index - 1) * 0.25
        samples = []
        for task, split, _ in conditions:
            rows = sorted((r for r in result["runs"] if r["task"] == task and r["variant"] == variant),
                          key=lambda r: r["seed"])
            values = [100 * r["metrics"][split]["accuracy"] for r in rows]
            samples.append(values)
            records.append(dict(task=task, split=split, variant=variant,
                                seeds=[r["seed"] for r in rows], accuracy_percent=values))
        samples = np.asarray(samples)
        means = samples.mean(axis=1)
        ax.bar(x, means, width=0.22, color=color, alpha=0.88, label=label, zorder=2)
        for seed_index in range(3):
            ax.scatter(x + (seed_index - 1) * 0.045, samples[:, seed_index], s=20,
                       facecolors="white", edgecolors=color, linewidths=1.2, zorder=3)
        for center, mean in zip(x, means):
            ax.text(center, mean + 2.4, f"{mean:.1f}", ha="center", va="bottom", fontsize=8.5)
    ax.set_ylim(0, 112)
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_ylabel("Accuracy (%)")
    ax.set_xticks(np.arange(len(conditions)), [c[2] for c in conditions])
    ax.grid(axis="y", color="#e5e9ed", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.13), frameon=False)
    fig.suptitle("Overwrite improves while retention and interference robustness decline",
                 x=0.075, y=0.99, ha="left", fontsize=16, fontweight="bold")
    fig.text(0.075, 0.065, "Bars: mean of 3 paired seeds. Open circles: individual seeds. All five declared challenges are shown.", fontsize=9)
    fig.text(0.075, 0.027, "* Mass ridge retains 11 failed logit-replay checks; all 135 classification accuracies reproduce exactly. The joint quality gate failed.", fontsize=9, color="#555555")
    fig.subplots_adjust(left=0.075, right=0.99, bottom=0.20, top=0.81)
    folder = HERE / "figures"
    folder.mkdir(exist_ok=True)
    fig.savefig(folder / "memory_tradeoffs.png", dpi=180)
    fig.savefig(folder / "memory_tradeoffs.svg")
    plt.close(fig)
    record = dict(source="memory/results.json", source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  matplotlib=matplotlib.__version__, records=records,
                  interpretation="Descriptive paired-seed comparison, not population inference or an equal-cost claim")
    (folder / "memory_tradeoffs.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
