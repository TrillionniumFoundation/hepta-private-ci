"""Render the audited confirmation evidence; no experiments are rerun."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

PACKAGE = Path(__file__).resolve().parents[2]
LABELS = {
    "endogenous_renewal": "Endogenous renewal",
    "fixed_shared6": "Fixed shared6",
    "fixed_cross7": "Fixed cross7",
    "learned_threshold7": "Learned threshold7",
    "ordinary_first_event": "First-event value",
    "always_wait": "Always wait",
    "always_repair": "Always repair",
    "stop": "STOP",
}


def render(output, preview=None):
    source = PACKAGE / "evidence/CONFIRMATION_AUDIT.json"
    audit = json.loads(source.read_text())
    if not audit["ledger_pass"] or not audit["supplemental_checks"]["pass"]:
        raise ValueError("Only passed factual/native audits may be plotted")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "svg.fonttype": "none",
                         "svg.hashsalt": "hepta-first-passage-confirmation-v1"})
    fig, axes = plt.subplots(1, 2, figsize=(14.8, 7.8), gridspec_kw={"width_ratios": [1, 1]})
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.24, top=0.79, wspace=0.68)
    fig.suptitle("First-passage cell: frozen confirmation results", x=0.15, y=0.96,
                 ha="left", fontsize=18, fontweight="bold", color="#0F172A")
    fig.text(0.15, 0.905, "8 model seeds × 256 paired scenarios per arm · 8 policies · 16,384 executed episodes",
             fontsize=11, color="#475569")
    ax = axes[0]
    order = sorted(LABELS, key=lambda a: audit["arms"][a]["mean_total_reward"], reverse=True)
    means = [audit["arms"][a]["mean_total_reward"] for a in order]
    colors = ["#0F766E" if a == "endogenous_renewal" else "#94A3B8" for a in order]
    y = np.arange(len(order))
    ax.barh(y, means, color=colors, height=0.64)
    ax.set_yticks(y, [LABELS[a] for a in order])
    ax.invert_yaxis()
    ax.set_xlim(0, 0.93)
    ax.set_xticks(np.arange(0, 1.0, 0.2))
    ax.set_xlabel("Mean realized net utility (task units)", labelpad=10)
    ax.set_title("A   All registered policies", loc="left", pad=18, fontsize=12)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, pad=8)
    for pos, mean in zip(y, means):
        ax.text(mean + 0.012, pos, f"{mean:.4f}", va="center", fontsize=9.5, color="#334155")

    ax = axes[1]
    baselines = ["ordinary_first_event", "fixed_cross7", "learned_threshold7"]
    ypos = np.array([2, 1, 0])
    for y, baseline in zip(ypos, baselines):
        result = audit["primary_comparisons"]["endogenous_renewal-minus-" + baseline]
        mean = result["mean_gain"]
        lower, upper = result["empirical_family_adjusted_interval"]
        ax.scatter(result["per_seed_mean_gain"], y + np.linspace(-0.13, 0.13, 8),
                   s=24, color="#94A3B8", edgecolors="white", linewidths=0.4, zorder=3)
        ax.errorbar(mean, y, xerr=np.array([[mean - lower], [upper - mean]]), fmt="D",
                    color="#0F766E", markersize=6.2, capsize=5, elinewidth=2.2, zorder=4)
        ax.text(mean, y + 0.27, f"Δ = +{mean:.5f}", ha="center", va="center", fontsize=9.5,
                color="#0F766E", fontweight="bold")
    ax.axvline(0, color="#CBD5E1", linewidth=1.2, zorder=1)
    ax.axvline(0.005, color="#B45309", linestyle="--", linewidth=1.4, zorder=2)
    ax.set_xlim(-0.001, 0.069)
    ax.set_ylim(-0.55, 2.55)
    ax.set_xticks([0, 0.02, 0.04, 0.06])
    ax.set_yticks(ypos, ["vs First-event value", "vs Fixed cross7", "vs Learned threshold7"])
    ax.tick_params(axis="y", length=0, pad=10)
    ax.set_xlabel("Endogenous minus baseline (task units)", labelpad=10)
    ax.set_title("B   Three prespecified paired effects", loc="left", pad=18, fontsize=12)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.7)
    ax.set_axisbelow(True)
    handles = [Line2D([0], [0], marker="o", linestyle="", color="#94A3B8", markersize=5,
                      label="Eight seed means"),
               Line2D([0], [0], marker="D", color="#0F766E", linewidth=2, markersize=5,
                      label="Paired mean + empirical interval"),
               Line2D([0], [0], color="#B45309", linestyle="--", linewidth=1.4,
                      label="Registered gain gate: 0.005")]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.145, 0.135),
               ncol=3, frameon=False, fontsize=9, columnspacing=2.0, handlelength=2.5)
    fig.text(0.15, 0.104, "All three primary comparisons passed: adjusted lower bound > 0.005 and every seed mean > 0.",
             fontsize=10, fontweight="bold", color="#0F766E")
    fig.text(0.15, 0.061, "Intervals: 4,000 seed → paired-episode resamples; 98.3333% each, Bonferroni family α = 0.05. Empirical coverage only.",
             fontsize=8.8, color="#475569")
    fig.text(0.15, 0.031, "These are voluntary repair/reset boundaries; the fitted physical first-passage barrier is shared. No production-authority claim.",
             fontsize=8.8, color="#475569")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="svg", metadata={"Date": None,
        "Title": "Audited first-passage confirmation results",
        "Description": "CONFIRMATION_AUDIT.json SHA256=" + digest + "; source=" + audit["source_commit"],
        "Creator": "Matplotlib; evidence/audit_helpers/plot_results.py"})
    if preview:
        fig.savefig(preview, dpi=130)
    plt.close(fig)
    print(json.dumps({"output": str(output), "input_sha256": digest,
                      "svg_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PACKAGE / "evidence/confirmation_results.svg")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    render(args.output, args.preview)


if __name__ == "__main__":
    main()
