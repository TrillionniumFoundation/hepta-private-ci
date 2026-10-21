"""Plot existing local-pilot summaries without training or policy selection.

The three panels show equal-weight means of per-seed measurements. Connecting
lines only join measured budget points; nondominance is descriptive, without
confidence intervals or a claim about a global efficient frontier.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


ARMS = (
    "validation_selected_fixed_portfolio",
    "risk_neutral_dp",
    "fixed_risk_dp",
    "ndu_recursive_dp",
    "ndu_myopic",
    "best_single_candidate",
    "ndu_independent_error_ablation",
)
LABELS = (
    "Fixed portfolio",
    "Risk-neutral DP",
    "Fixed-risk DP",
    "NDU recursive",
    "NDU myopic",
    "Best single",
    "Independent-error ablation",
)
COLORS = ("#0072B2", "#E69F00", "#009E73", "#6B359C",
          "#CC79A7", "#666666", "#56B4E9")
MARKERS = ("s", "v", "P", "o", "D", "X", "^")
SCENARIOS = ("test_iid", "correlation_shift", "all_shared_wrong")
METRICS = ("mean_loss", "cvar90", "mean_quality", "mean_linear_macs")


def read_summary(path):
    content = path.read_bytes()
    report = json.loads(content)
    seeds = report["seeds"]
    if len(seeds) != 3 or len(set(seeds)) != 3 or report["smoke_only"]:
        raise ValueError("a completed three-seed local preflight summary is required")
    if report["execution_tier"] != "local-preflight":
        raise ValueError("this figure template is explicitly labeled local CPU preflight")
    groups = defaultdict(list)
    for row in report["rows"]:
        key = (row["scenario"], row["budget"], row["arm"])
        if any(not np.isfinite(row[metric]) for metric in METRICS):
            raise ValueError("nonfinite summary metric")
        groups[key].append(row)
    budgets = sorted({key[1] for key in groups})
    if budgets != [2, 4, 7]:
        raise ValueError("expected the three registered budgets: 2, 4, 7")
    means = {}
    for scenario in SCENARIOS:
        for budget in budgets:
            for arm in ARMS:
                key = (scenario, budget, arm)
                rows = groups[key]
                if len(rows) != len(seeds) or {row["seed"] for row in rows} != set(seeds):
                    raise ValueError(f"missing or duplicate seed results: {key}")
                means[key] = {metric: float(np.mean([row[metric] for row in rows]))
                              for metric in METRICS}
    expected_count = len(SCENARIOS) * len(budgets) * len(ARMS) * len(seeds)
    if len(report["rows"]) != expected_count:
        raise ValueError("unexpected extra rows in summary")
    return report, means, budgets, hashlib.sha256(content).hexdigest()


def observed_nondominated(points):
    """Minimize both coordinates, preserving ties as one plotted location."""
    points = np.unique(np.asarray(points, dtype=np.float64), axis=0)
    chosen = []
    for index, point in enumerate(points):
        dominates = np.all(points <= point + 1e-12, axis=1) & np.any(
            points < point - 1e-12, axis=1)
        dominates[index] = False
        if not dominates.any():
            chosen.append(point)
    return np.asarray(chosen)


def plot(summary_path, output_prefix, study_label="measured local pilot outcomes",
         show_primary_efficacy=False):
    report, means, budgets, source_hash = read_summary(summary_path)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.titlesize": 12, "axes.titleweight": "semibold",
        "axes.labelsize": 10, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#BBBBBB", "axes.labelcolor": "#303030",
        "xtick.color": "#444444", "ytick.color": "#333333",
        "svg.fonttype": "none", "savefig.facecolor": "white",
    })
    fig = plt.figure(figsize=(20.5, 8.0), facecolor="white")
    grid = fig.add_gridspec(1, 3, left=0.117, right=0.972, top=0.77, bottom=0.30,
                           width_ratios=(1.0, 1.18, 1.12), wspace=0.56)
    ax_loss, ax_frontier, ax_shift = [fig.add_subplot(grid[0, i]) for i in range(3)]
    fig.suptitle(f"Multimodal output portfolios: {study_label}",
                 x=0.04, y=0.962, ha="left", fontsize=20, fontweight="semibold", color="#20262D")
    fig.text(0.04, 0.906,
             "Synthetic closed world  |  Local CPU  |  3 training seeds  |  Not a dedicated-cloud result",
             fontsize=12.5, color="#4B5563")
    if show_primary_efficacy:
        contrast = report["primary_budget4_iid_contrasts"]["validation_selected_fixed_portfolio"]["cvar90"]
        protocol = json.loads(summary_path.with_name("protocol.json").read_text())
        required_reduction = protocol["primary_comparison"]["minimum_reduction"]
        efficacy_gates = ("cvar_reduction_at_least_0_02", "cvar_95pct_interval_below_zero",
                          "quality_noninferior_within_0_02", "linear_mac_ratio_at_most_1_05")
        status = ("Local statistical criteria passed" if all(report["primary_gates"][key]
                  for key in efficacy_gates) else "Primary efficacy not confirmed")
        headline = (f"{status}  |  NDU minus fixed portfolio: "
                    f"ΔCVaR90 = {contrast['estimate']:+.4f}; "
                    f"95% CI [{contrast['ci_low']:+.4f}, {contrast['ci_high']:+.4f}]; "
                    f"required reduction ≥{required_reduction:.3f}.")
        fig.text(0.04, 0.858, headline, fontsize=10.5, color="#8A3A15", fontweight="semibold")
    else:
        fig.text(0.04, 0.858,
                 "Equal-weight seed means; no uncertainty intervals shown. Lower loss/risk is better; higher output quality is better.",
                 fontsize=10.5, color="#59616D")

    # A: Mean and tail loss remain separate quantities, not interval endpoints.
    ypos = np.arange(len(ARMS))
    for index, (arm, color) in enumerate(zip(ARMS, COLORS)):
        row = means[("test_iid", 4, arm)]
        mean_loss, tail_loss = row["mean_loss"], row["cvar90"]
        ax_loss.plot(mean_loss, index - 0.13, "o", markersize=7,
                     markerfacecolor="white", markeredgecolor=color, markeredgewidth=1.7)
        ax_loss.plot(tail_loss, index + 0.13, "D", color=color, markersize=6)
        ax_loss.text(mean_loss + 0.032, index - 0.13, f"{mean_loss:.3f}",
                     va="center", fontsize=9, color="#444444")
        ax_loss.text(tail_loss + 0.032, index + 0.13, f"{tail_loss:.3f}",
                     va="center", fontsize=9, color="#444444")
    ax_loss.set_title("A  IID loss at budget 4", loc="left", pad=14)
    ax_loss.set_yticks(ypos, LABELS, fontsize=10)
    ax_loss.set_ylim(len(ARMS) - 0.5, -0.5)
    ax_loss.set_xlim(0, 1.19)
    ax_loss.set_xticks(np.arange(0, 1.21, 0.2))
    ax_loss.set_xlabel("External loss / CVaR90")
    ax_loss.grid(axis="x", color="#E7E9ED", linewidth=0.7)
    ax_loss.set_axisbelow(True)
    ax_loss.tick_params(axis="y", length=0)
    ax_loss.legend(handles=[
        Line2D([], [], marker="o", markerfacecolor="white", markeredgecolor="#333333",
               linestyle="none", label="Mean loss"),
        Line2D([], [], marker="D", color="#333333", linestyle="none", label="CVaR90"),
    ], loc="upper left", bbox_to_anchor=(-0.02, -0.14), ncol=2, frameon=False,
       fontsize=9, handletextpad=0.5)

    # B: All budgets for all arms. No jitter; coincident measurements coincide.
    all_points, legend_handles = [], []
    for arm, label, color, marker in zip(ARMS, LABELS, COLORS, MARKERS):
        rows = [means[("test_iid", budget, arm)] for budget in budgets]
        x = np.array([row["mean_linear_macs"] / 1000 for row in rows])
        y = np.array([row["cvar90"] for row in rows])
        all_points.extend(zip(x, y))
        is_myopic = arm == "ndu_myopic"
        line, = ax_frontier.plot(
            x, y, color=color, marker=marker, linewidth=1.3, markersize=9 if is_myopic else 6,
            markerfacecolor="none" if is_myopic else color,
            markeredgewidth=1.3, alpha=0.9,
            linestyle="--" if is_myopic else "-", label=label,
        )
        legend_handles.append(line)
    nondominated = observed_nondominated(all_points)
    ax_frontier.scatter(nondominated[:, 0], nondominated[:, 1], s=170, facecolors="none",
                        edgecolors="#111111", linewidths=0.8, zorder=8)
    ax_frontier.set_title("B  IID risk versus neural compute proxy", loc="left", pad=14)
    ax_frontier.set_xlabel("Mean standalone Linear MAC / world (thousands)")
    ax_frontier.set_ylabel("Mean per-seed CVaR90 of external loss")
    # Retain the original view where possible, expanding to include amendments.
    x_values = np.asarray(all_points)[:, 0]
    ax_frontier.set_xlim(min(345, x_values.min() - 10), max(605, x_values.max() + 10))
    ax_frontier.set_ylim(0.59, 1.31)
    ax_frontier.grid(color="#E7E9ED", linewidth=0.7)
    ax_frontier.text(0.45, 0.98,
                     "Budgets: 2, 4, 7 after initial text\nRings: nondominated observations",
                     transform=ax_frontier.transAxes, va="top", fontsize=9,
                     color="#303030", bbox={"facecolor": "white", "alpha": 0.9,
                                              "edgecolor": "none", "pad": 3})

    # C: Raw generated-output semantic quality, independent of controller scores.
    qualities = np.array([[means[(scenario, 4, arm)]["mean_quality"]
                           for scenario in SCENARIOS] for arm in ARMS])
    heat = ax_shift.imshow(qualities, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    for row in range(qualities.shape[0]):
        for col in range(qualities.shape[1]):
            value = qualities[row, col]
            ax_shift.text(col, row, f"{100 * value:.2f}%", ha="center", va="center",
                          fontsize=10, color="#202020" if value > 0.55 else "white")
    ax_shift.set_title("C  Generated-output quality at budget 4", loc="left", pad=14)
    ax_shift.set_xticks(range(3), ("IID", "Correlation\nshift", "All sensors\nwrong"))
    ax_shift.set_yticks(ypos, LABELS, fontsize=9)
    ax_shift.tick_params(axis="both", length=0)
    ax_shift.set_xticks(np.arange(-0.5, 3, 1), minor=True)
    ax_shift.set_yticks(np.arange(-0.5, len(ARMS), 1), minor=True)
    ax_shift.grid(which="minor", color="white", linewidth=1.5)
    ax_shift.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(heat, ax=ax_shift, fraction=0.045, pad=0.04)
    colorbar.set_label("Fraction of four outputs with correct semantic class", fontsize=9)
    colorbar.ax.tick_params(labelsize=8)
    colorbar.outline.set_visible(False)

    fig.legend(handles=legend_handles, labels=LABELS, loc="lower center",
               bbox_to_anchor=(0.57, 0.185), ncol=4, frameon=False,
               fontsize=9.5, handlelength=2.1, columnspacing=1.5)
    seeds = ", ".join(map(str, report["seeds"]))
    scenario_sizes = {scenario: sorted({row["n"] for row in report["rows"]
                                       if row["scenario"] == scenario}) for scenario in SCENARIOS}
    if any(len(sizes) != 1 for sizes in scenario_sizes.values()):
        raise ValueError("different world counts within a scenario require explicit plot labeling")
    world_counts = "; ".join(f"{label} {scenario_sizes[scenario][0]:,}" for scenario, label in
                            zip(SCENARIOS, ("IID", "correlation shift", "all-shared-wrong")))
    notes = [
        f"Equal-weight means over seeds {seeds}. Worlds per seed: {world_counts}. CVaR90 is computed within each seed, then averaged; no arm-wise CI plotted.",
        "Panel B counts neural dense-linear MACs only, not total cost: controller, activations, backward, optimizer, I/O and other costs are excluded. Lines only connect observed budgets.",
        "At budget 4, NDU recursive and NDU myopic coincide. Stress cases expose the shared-error limit; no reliable sensor remains in the all-wrong case.",
        f"Source: existing {summary_path.parent.name}/summary.json (SHA256 {source_hash[:16]}). Observed nondominance is descriptive, not a global or statistically certified efficient frontier.",
    ]
    for y, note in zip((0.151, 0.119, 0.087, 0.055), notes):
        fig.text(0.04, y, note, fontsize=9, color="#4B5563")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    description = (f"Study: {study_label}. Synthetic closed-world local CPU experiment, not dedicated-cloud evidence. "
                   "Equal-weight three-seed summary means without plotted confidence intervals. "
                   f"Input summary SHA256: {source_hash}.")
    for suffix in (".png", ".svg"):
        metadata = {"Title": "Multimodal output portfolio local pilot",
                    "Description": description, "Creator": "plot_results.py"}
        if suffix == ".svg":
            metadata["Date"] = None
        fig.savefig(output_prefix.with_suffix(suffix), dpi=220, metadata=metadata)
    plt.close(fig)
    return {"png": str(output_prefix.with_suffix(".png")),
            "svg": str(output_prefix.with_suffix(".svg")),
            "summary_sha256": source_hash, "seeds": report["seeds"],
            "observed_nondominated_points": nondominated.tolist(),
            "data_or_model_changes": False, "new_training_or_parameter_selection": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path,
                        default=Path(__file__).resolve().parents[1] / "evidence" / "local_preflight_v1")
    parser.add_argument("--study-label", default="measured local pilot outcomes")
    parser.add_argument("--show-primary-efficacy", action="store_true")
    args = parser.parse_args()
    print(json.dumps(plot(args.summary, args.output_prefix, args.study_label,
                          args.show_primary_efficacy), sort_keys=True))
