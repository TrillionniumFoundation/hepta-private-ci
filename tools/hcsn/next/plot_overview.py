"""Plot actual seed outcomes; failed per-seed targets stay visible."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FOLDER = Path(__file__).parent


def read(name):
    return json.loads((FOLDER / name).read_text())


def draw(ax, names, vectors, title, limits, threshold=None):
    colors = ["#126B8C", "#A87631", "#64568B", "#687E70", "#737373", "#424E70", "#8F8583"]
    for index, values in enumerate(vectors):
        values = np.array(values) * 100
        offsets = np.linspace(-.14, .14, len(values)) if len(values) > 1 else [0]
        ax.scatter(index + np.array(offsets), values, s=27, color=colors[index],
                   alpha=.85, zorder=4, edgecolors="white", linewidths=.4)
        ax.plot([index-.23, index+.23], [values.mean()]*2, color=colors[index], lw=2.1)
        if len(values) > 1:
            ax.errorbar(index, values.mean(), yerr=values.std(ddof=1),
                        color=colors[index], capsize=3, linewidth=1, zorder=2)
    if threshold is not None:
        ax.axhline(threshold, color="#B4473E", linestyle="--", lw=1.2)
        ax.text(len(names)-.6, threshold-2.3, f"every-seed target {threshold}%",
                ha="right", va="top", fontsize=8, color="#A13C35")
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=11)
    ax.set_xticks(range(len(names)), names, fontsize=8.5)
    ax.set_ylabel("Test accuracy (%)", fontsize=9)
    ax.set_ylim(*limits)
    ax.set_xlim(-.55, len(names)-.45)
    ax.grid(axis="y", alpha=.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", labelsize=8.5)


def main():
    ridge = read("ridge/results.json")
    assert ridge["complete"]
    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.6))
    kinds = ("full_hx", "hcsn", "sigmoid", "ridge_memory_only", "gru", "transformer", "snn")
    names = ["Full HX", "Toy\nHCSN", "Sigmoid", "Memory\nonly", "GRU", "Transformer", "LIF-SNN"]
    for ax, task, title, threshold in (
        (axes[0, 0], "memory", "A  Ridge v4: memory at length 128", 95),
        (axes[0, 1], "retrieval", "B  Ridge v4: four-item retrieval at length 128", 90)):
        vectors = [[r["metrics"]["test_128"]["accuracy"] for r in ridge["runs"]
                    if r["task"] == task and r["kind"] == kind] for kind in kinds]
        assert all(len(v) == 5 for v in vectors)
        draw(ax, names, vectors, title, (15, 115 if task == "memory" else 106), threshold)
    for ax, dataset, title, limits in (
        (axes[1, 0], "ag_news", "C  Frozen MiniLM: clean AG News", (80, 87)),
        (axes[1, 1], "cifar10", "D  Frozen MobileNetV2: clean CIFAR-10", (72, 84))):
        ablation = read(f"ablation/{dataset}_results.json")
        baseline = read(f"encoder/{dataset}_baseline_results.json")
        assert ablation["complete"] and baseline["complete"]
        assert ablation["metadata"]["feature_sha256"] == baseline["metadata"]["features_sha256"]
        vectors = [[r["metrics"]["test"]["accuracy"] for r in ablation["runs"]
                    if r["variant"] == kind] for kind in ("full", "full_sigmoid", "memory_only")]
        vectors += [[r["metrics"]["test"]["accuracy"] for r in baseline["runs"]
                     if r["kind"] == kind] for kind in ("gru", "transformer")]
        vectors += [[baseline["linear_reference"]["test"]["accuracy"]]]
        draw(ax, ["Full HX", "Full +\nsigmoid", "Memory\nonly", "GRU", "Transformer", "Linear"],
             vectors, title, limits)
    fig.suptitle("HCSN follow-up: capability gains and unresolved attribution",
                 fontsize=16, fontweight="bold", x=.075, ha="left", y=.98)
    fig.text(.075, .94, "Each dot is one training seed; bars show mean and sample SD. CPU research prototypes.",
             fontsize=10, color="#424242")
    fig.text(.075, .027, "Panels A/B use fresh sequence data; retrieval uses 8 fixed keys. Panels C/D share frozen features.\n"
             "Component deletions are width-matched; the linear reference is one separate fit. No equal-FLOP, energy, or scaling claim.",
             fontsize=9, color="#424242", linespacing=1.5)
    fig.subplots_adjust(left=.075, right=.98, top=.87, bottom=.13, wspace=.21, hspace=.4)
    for suffix in ("png", "svg"):
        fig.savefig(FOLDER / f"results_overview.{suffix}", dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
