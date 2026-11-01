"""Export scientific figures from all completed fixed-budget fits."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(path.read_text()) for path in args.run.glob("*/result.json")]
    if len(records) != 75 or any(r["status"] != "completed" for r in records):
        raise ValueError("All 75 fixed fits must be present")
    args.out.mkdir(parents=True, exist_ok=True)
    tasks = ["dynamics", "mqar", "selective", "binding", "avt"]
    labels = ["Dynamics", "Four-query recall", "Selective overwrite", "Bridge binding", "Real AV + text"]
    arms = ["flow", "diagonal", "gru", "snn", "transformer"]
    names = ["Marked flow", "Diagonal memory", "Time-aware GRU", "LIF + surrogate", "Causal Transformer"]
    colors = ["#166c80", "#bd7737", "#6673a7", "#a96383", "#477b55"]
    figure, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    for task, label, ax in zip(tasks, labels, axes.flat):
        means, low, high = [], [], []
        for arm in arms:
            values = np.array([r["evaluations"]["test__base"]["accuracy"]
                               for r in records if r["task"] == task and r["arm"] == arm]) * 100
            if len(values) != 3:
                raise ValueError("Expected all three seeds")
            means.append(values.mean())
            low.append(values.mean() - values.min())
            high.append(values.max() - values.mean())
        ax.bar(np.arange(5), means, color=colors, yerr=[low, high], capsize=3)
        for i, mean in enumerate(means):
            ax.text(i, min(mean + high[i] + 2, 98), f"{mean:.1f}", ha="center", fontsize=9)
        ax.set_title(label, fontweight="bold")
        ax.set_xticks(np.arange(5), ["Flow", "Diag", "GRU", "LIF", "Attn"])
        ax.set_ylim(0, 104)
        ax.set_ylabel("Confirmation accuracy (%)")
        ax.grid(axis="y", alpha=.15)
        ax.set_axisbelow(True)
        if task == "avt":
            ax.axhline(100 * 5 / 6, color="#555555", ls="--", lw=1)
            ax.text(.03, .81, "Two-modality oracle: 83.3%", transform=ax.transAxes, fontsize=9)
    ax = axes.flat[-1]
    ax.axis("off")
    ax.text(0, .95, "Frozen 75-fit study", fontsize=17, fontweight="bold", va="top")
    ax.text(0, .81, "5 tasks × 5 models × 3 seeds\n600 steps × 24 episodes per fit\nFinal checkpoints; confirmation opened afterwards\n\nBars: mean of three seeds\nWhiskers: seed range (not confidence intervals)\nAV/text uses weighted accuracy\n\nSame inputs and update count; unequal compute\nShared CPU, fixed frontend; energy unmeasured\nSmall controlled tasks, not foundation models",
            fontsize=11, linespacing=1.6, va="top")
    figure.suptitle("Hepta continuous marked flow: quality after a fixed training budget", fontsize=17)
    figure.savefig(args.out / "quality.png", dpi=180)
    figure.savefig(args.out / "quality.svg")
    plt.close(figure)

    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    x = np.arange(len(tasks))
    for i, (arm, name, color) in enumerate(zip(arms, names, colors)):
        costs = [np.mean([r["training"]["cpu_seconds"] for r in records
                          if r["task"] == task and r["arm"] == arm]) for task in tasks]
        latency = [1000 * np.median([r["inference"]["median_seconds"] for r in records
                                    if r["task"] == task and r["arm"] == arm]) for task in tasks]
        axes[0].plot(x, costs, "o-", label=name, color=color)
        axes[1].plot(x, latency, "o-", label=name, color=color)
    axes[0].set_ylabel("CPU seconds per 600-step fit")
    axes[1].set_ylabel("ms per complete 24-episode batch")
    axes[0].set_title("Measured training cost")
    axes[1].set_title("Prepared-feature inference on shared CPU")
    for ax in axes:
        ax.set_xticks(x, ["Dyn", "Recall", "Select", "Bind", "AVT"])
        ax.set_yscale("log")
        ax.grid(alpha=.2)
    axes[1].legend(fontsize=9, loc="best")
    figure.suptitle("CPU time is not energy; offline media decoding is accounted separately", fontsize=12)
    figure.savefig(args.out / "cost.png", dpi=180)
    figure.savefig(args.out / "cost.svg")
    plt.close(figure)


if __name__ == "__main__":
    main()
