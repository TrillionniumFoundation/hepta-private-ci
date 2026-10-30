"""Render scientific figures directly from retained confirmation evidence."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent


def main():
    value = json.loads((HERE / "value_evidence/CONFIRMATION.json").read_text())
    network = json.loads((HERE / "network_evidence/CONFIRMATION_SUMMARY.json").read_text())
    control = json.loads((HERE / "control_evidence/CONTROL_CONFIRMATION.json").read_text())
    output = HERE / "figures"
    output.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 10, "font.family": "DejaVu Sans", "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none", "figure.dpi": 150})
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.9), gridspec_kw={"width_ratios": [1, 1.45, 1.15]})
    ax = axes[0]
    colors = ["#1d6996", "#38a6a5", "#5f4690"]
    x = np.arange(3)
    for offset, (metric, label) in zip((-0.17, 0.17), (("moment_rmse", "Moment RMSE"),
                                                   ("value_rmse_unit_l2_payoff", "Payoff-value RMSE"))):
        y = [r[metric] for r in value["results"]]
        ax.bar(x + offset, y, width=0.30, color=colors[0] if offset < 0 else colors[1], label=label)
    ax.axhline(0.035, color=colors[0], ls="--", lw=1, label="Moment gate: 0.035")
    ax.axhline(0.05, color=colors[1], ls=":", lw=1.4, label="Value gate: 0.05")
    ax.set(xticks=x, xticklabels=[str(r["seed"]) for r in value["results"]], ylim=(0, 0.058),
           xlabel="Training seed", ylabel="Held-out RMSE", title="A  Value learning: 3 / 3 gates pass")
    ax.legend(loc="upper right", fontsize=8, frameon=True, facecolor="white", edgecolor="white", framealpha=1)
    ax.text(0, -0.21, "1,024 held-out contexts. Mean-error gates only.\nWorst-case transition TV reaches 0.586.",
            transform=ax.transAxes, fontsize=8.5, va="top")

    ax = axes[1]
    rows = network["comparisons"]
    labels = [r["task"].replace("_", " ") + " / " + r["baseline"].upper() for r in rows]
    for i, row in enumerate(rows):
        mean = row["loss_improvement"]
        low, high = row["simultaneous_empirical_interval"]
        ax.errorbar(mean, i, xerr=[[mean - low], [high - mean]], fmt="o", color="#b44939", capsize=3, ms=5)
    ax.axvline(0, color="#536171", lw=1)
    ax.set(yticks=range(len(rows)), yticklabels=labels, xlabel="Baseline BCE minus first-passage BCE",
           title="B  Cross-task advantage: 0 / 6 gates pass", xlim=(-0.73, 0.09))
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.17)
    ax.text(0, -0.21, "Positive favors the first-passage network.\nRegistered simultaneous empirical intervals; 3 seeds.",
            transform=ax.transAxes, fontsize=8.5, va="top")

    ax = axes[2]
    laws = ["nominal", "fast_decay", "noisy"]
    arms = ["learned_operator_bellman", "analytic_operator_bellman", "wait_after_current"]
    for i, (arm, label) in enumerate(zip(arms, ("Learned operator", "Analytic operator", "Wait-plan forecast"))):
        values = [[r["mean_utility"] for r in control["rows"] if r["arm"] == arm and r["law"] == law] for law in laws]
        positions = np.arange(3) + (i - 1) * 0.23
        ax.bar(positions, np.mean(values, axis=1), width=0.21, color=colors[i], alpha=0.82, label=label)
        for position, seed_values in zip(positions, values):
            ax.scatter(np.full(3, position), seed_values, color="#172a3a", s=8, zorder=3)
    ax.set(xticks=range(3), xticklabels=["Nominal", "Fast decay", "Noisy"], ylim=(0, 1.05),
           ylabel="Actual mean net utility", title="C  Control: mixed returns")
    ax.legend(loc="upper right", fontsize=8, frameon=True, facecolor="white", edgecolor="white", framealpha=1)
    ax.text(0, -0.21, "3,456 episodes; paired starts and shared information.\nDots: individual seeds. One exact fallback.",
            transform=ax.transAxes, fontsize=8.5, va="top")
    fig.suptitle("Frozen confirmation outcomes — regenerative operators and sampled spiking networks", x=0.05,
                 ha="left", fontsize=15, fontweight="bold", y=0.99)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.86, bottom=0.27, wspace=0.63)
    fig.savefig(output / "confirmation_overview.svg", metadata={"Date": None})
    fig.savefig(output / "confirmation_overview.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
