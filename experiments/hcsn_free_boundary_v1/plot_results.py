"""Render recorded content and CPU evidence, without running new experiments."""

import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
MODELS = ["free_dual", "legacy_hcsn", "two_gates", "continuous_rnn", "cfc",
          "mamba1", "transformer", "lif_snn"]
LABELS = ["Free-boundary HCSN", "Legacy HCSN", "Two-gate RNN", "Continuous RNN",
          "CfC", "Mamba-1 CPU", "Transformer", "LIF SNN"]
TASKS = ["selective_copy", "mqar", "irregular", "mnist", "fsdd", "multimodal_select"]


def main():
    content_path = ROOT / "results/study001/analysis001/CORE_TABLE.csv"
    speed_path = ROOT / "results/scaling002/performance.json"
    with content_path.open(newline="") as source:
        rows = list(csv.DictReader(source))
    lookup = {(r["model"], r["task"]): r for r in rows}
    assert all(lookup[m, t]["status"] == "complete" for m in MODELS for t in TASKS)
    values = np.array([[100 * float(lookup[m, t]["test_accuracy_mean"])
                        for t in TASKS] for m in MODELS])
    speed = {r["model"]: r for r in json.loads(speed_path.read_text())
             if r["batch"] == 16 and r["length"] == 128
             and r["width"] == 32 and r["depth"] == 1}
    forward = [1000 * speed[m]["forward"]["cpu_median_seconds"] for m in MODELS]
    training = [1000 * speed[m]["train_step"]["cpu_median_seconds"] for m in MODELS]

    plt.rcParams.update({"font.size": 10, "axes.titleweight": "bold",
                         "font.family": "DejaVu Sans"})
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14.7, 7.3),
                                gridspec_kw={"width_ratios": [1.5, 1]})
    fig.subplots_adjust(left=.15, right=.98, bottom=.25, top=.79, wspace=.13)
    ax.imshow(values, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(6), ["Selective\ncopy", "MQAR", "Irregular\ntime", "MNIST",
                            "FSDD", "Image/audio\nselection"], fontsize=9)
    ax.set_yticks(range(8), LABELS)
    ax.set_title("Heldout accuracy (%)", loc="left", pad=15)
    for i in range(8):
        for j in range(6):
            ax.text(j, i, f"{values[i, j]:.1f}", ha="center", va="center",
                    color="white" if values[i, j] > 60 else "#182b41",
                    fontweight="bold" if i == 0 else "normal")
    ax.set_xticks(np.arange(-.5, 6, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 8, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    y = np.arange(8)
    bx.barh(y - .16, forward, height=.29, color="#78a4c9", label="Forward")
    bx.barh(y + .16, training, height=.29, color="#184b75", label="Train step")
    bx.set_ylim(7.5, -.5)
    bx.set_yticks(y, [""] * 8)
    bx.set_xscale("log")
    bx.set_xlim(2, 750)
    bx.set_xticks([5, 10, 50, 100, 500], ["5", "10", "50", "100", "500"])
    bx.set_xlabel("CPU milliseconds / sequence batch (log scale)")
    bx.set_title("Measured CPU time", loc="left", pad=15)
    bx.grid(axis="x", alpha=.18)
    bx.set_axisbelow(True)
    for i, value in enumerate(training):
        bx.text(value * 1.06, i + .16, f"{value:.1f}", va="center", fontsize=8)
    bx.legend(loc="upper right", bbox_to_anchor=(1, 1.10), frameon=False, ncol=2,
              fontsize=8)
    bx.tick_params(axis="y", length=0)
    bx.spines[["left", "right", "top"]].set_visible(False)

    fig.suptitle("Hepta free-boundary prototype: measured content and runtime", x=.15,
                 ha="left", y=.96, fontsize=17, fontweight="bold", color="#18334b")
    fig.text(.15, .89,
             "Content: 3 seeds, 2 learning rates, 20 training CPU seconds per candidate; "
             "validation selects the checkpoint.\n"
             "The free-boundary model misses the declared 2-point content screen on all six tasks.",
             fontsize=10, color="#34495b", linespacing=1.65)
    fig.text(.15, .095,
             "Runtime: separate synthetic timing probe; B=16, T=128, width=32, depth=1, "
             "12 inputs, 8 outputs; median of 3 repeats.\n"
             "CPU PyTorch references, one thread. These are matched-size timings, not "
             "matched-quality or GPU/energy comparisons.\n"
             "FSDD uses a small speaker-disjoint subset; image/audio selection uses literal "
             "queries. Results do not establish foundation-model performance.",
             fontsize=9, color="#4b5e6d", linespacing=1.65)
    output = ROOT / "figures"
    output.mkdir(exist_ok=True)
    fig.savefig(output / "content_and_runtime.png", dpi=160, facecolor="white")
    fig.savefig(output / "content_and_runtime.svg", facecolor="white",
                metadata={"Date": None})
    plt.close(fig)
    record = {"inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (content_path, speed_path)},
              "accuracy_percent": values.tolist(), "models": MODELS, "tasks": TASKS,
              "forward_cpu_ms": forward, "training_cpu_ms": training,
              "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in output.glob("content_and_runtime.*")}}
    (output / "SOURCES.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
