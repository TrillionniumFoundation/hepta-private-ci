"""Publication-style figures from saved exact and measured execution evidence."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).parent
EVIDENCE = HERE / "evidence"
MODES = ("direct", "continuous", "clocked", "first_passage")
LABELS = ("Direct Q", "Projected Gaussian", "Clocked", "First passage (finite CTMC)")
STAGES = ("baseline", "readout", "content_readout")
COLORS = ("#163a5f", "#6c7892", "#d48724", "#008c83")


def render():
    target = EVIDENCE / "figures"
    target.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "savefig.facecolor": "white"})
    heldout = json.loads((EVIDENCE / "heldout_exact.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for panel, ax in enumerate(axes):
        for mode, label, color in zip(MODES, LABELS, COLORS, strict=True):
            if panel == 0:
                fits = [json.loads((EVIDENCE / f"calibration_{mode}_{seed}.json").read_text())
                        for seed in range(11, 16)]
                values = np.asarray([[fit["audits"][stage]["optimal_minus_greedy_mean"]
                                      for stage in STAGES] for fit in fits])
            else:
                values = np.asarray([[next(row["optimality_gap"] for row in heldout["records"]
                                      if row["mode"] == mode and row["fit_seed"] == seed and row["stage"] == stage)
                                      for stage in STAGES] for seed in range(11, 16)])
            means = values.mean(0)
            ax.plot(range(3), means, color=color, marker="o", lw=2.1, label=label, zorder=4)
            offsets = np.linspace(-0.045, 0.045, 5)
            for stage in range(3):
                ax.scatter(stage + offsets, values[:, stage], color=color, s=13, alpha=.35, zorder=3)
        ax.set_xticks(range(3), ("R7 baseline", "Readout only", "Content + readout"))
        ax.set_xlim(-.15, 2.25)
        ax.set_title(("Original task configurations", "Unseen parameter combinations")[panel], loc="left", pad=15)
        ax.grid(axis="y", color="#e6eaf0", zorder=0)
        ax.set_ylim(0, .047)
        ax.tick_params(axis="both", length=0)
    axes[0].set_ylabel("Exact finite-model optimality gap (lower is better)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(.5, -.005))
    fig.suptitle("Controller calibration improves the original task; the full heldout matrix remains mixed",
                 x=.07, y=.995, ha="left", fontsize=13, fontweight="bold")
    fig.text(.07, .065, "Large markers: five-fit mean. Small dots: all five fits. Frozen cell dynamics in both calibration stages.",
             fontsize=9, color="#485566")
    fig.subplots_adjust(left=.075, right=.98, top=.84, bottom=.22, wspace=.13)
    fig.savefig(target / "exact_control_gaps.png", dpi=190)
    fig.savefig(target / "exact_control_gaps.svg")
    plt.close(fig)

    reused = json.loads((EVIDENCE / "native_reuse_cost01/REPORT.json").read_text())
    deployment = np.asarray([reused["baseline_deployment_cpu_seconds"], reused["measured_deployment_cpu_seconds"]])
    campaign = np.asarray([reused["baseline_campaign_cpu_seconds"],
                           reused["campaign_parent_cpu_seconds"] + reused["campaign_child_cpu_seconds"]])
    wall = [reused["baseline_deployment_wall_seconds"], reused["measured_deployment_wall_seconds"]]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    names = ("New broker per episode", "One broker reused")
    axes[0].bar(range(2), deployment, color=["#7a8799", "#008c83"], label="Deployment CPU")
    axes[0].bar(range(2), campaign - deployment, bottom=deployment, color="#cad3df", label="Driver / evidence overhead")
    axes[0].set_ylabel("Total process CPU seconds")
    axes[0].set_title("All CPU is charged", loc="left", pad=14)
    for i, value in enumerate(campaign):
        axes[0].text(i, value + .5, f"{value:.2f} s", ha="center", fontweight="bold")
    axes[0].set_ylim(0, 29)
    axes[0].legend(frameon=False, fontsize=9, loc="upper right")
    axes[1].bar(range(2), wall, color=["#7a8799", "#008c83"])
    axes[1].set_ylabel("Deployment wall seconds")
    axes[1].set_title("Same 240 fixed executions", loc="left", pad=14)
    for i, value in enumerate(wall):
        axes[1].text(i, value + .5, f"{value:.2f} s", ha="center", fontweight="bold")
    axes[1].set_ylim(0, 30)
    for ax in axes:
        ax.set_xticks(range(2), names)
        ax.grid(axis="y", color="#e6eaf0")
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
    fig.suptitle("Broker reuse removes startup cost while preserving every action and artifact",
                 x=.075, y=.99, ha="left", fontsize=12.5, fontweight="bold")
    fig.text(.075, .04, "240/240 exact action, final-state and artifact matches. Independent native owners remain. First startup and final close included.",
             fontsize=8.4, color="#485566")
    fig.subplots_adjust(left=.075, right=.98, top=.83, bottom=.19, wspace=.25)
    fig.savefig(target / "native_cost_reuse.png", dpi=190)
    fig.savefig(target / "native_cost_reuse.svg")
    plt.close(fig)
    return {"figures": [str(path) for path in sorted(target.iterdir())]}


if __name__ == "__main__":
    print(json.dumps(render()))
