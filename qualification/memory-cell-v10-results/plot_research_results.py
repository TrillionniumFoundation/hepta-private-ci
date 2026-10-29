"""Reproduce two descriptive V10 figures from the sealed analysis counts.

Usage (from the repository root):
  MPLCONFIGDIR=/tmp/hepta-v10-mpl python qualification/memory-cell-v10-results/plot_research_results.py

These plots contain pooled exact-match rates and individual optimization-seed
results. They do not contain confidence intervals or significance claims.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np


COUNTS_SHA256 = "47ecece56054bd7fd262ec001abacc2b00d0986d8f880cb1068cfb78585da016"
SEEDS, CAPACITIES = (1741, 1742, 1743), (32, 64, 128)
BLUE, ORANGE, GREEN, PURPLE = "#0072B2", "#D55E00", "#009E73", "#A45DA3"
BLACK, GRAY = "#303640", "#8A939E"


def style_axis(axis, ylabel=None):
    axis.set_ylim(-4, 105)
    axis.set_yticks([0, 25, 50, 75, 100])
    axis.grid(axis="y", color="#E1E5EA", linewidth=0.7)
    axis.set_axisbelow(True)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color("#A9B0B9")
        axis.spines[side].set_linewidth(0.7)
    axis.tick_params(length=3, colors=BLACK)
    if ylabel:
        axis.set_ylabel(ylabel)


def save_figure(figure, directory, name):
    figure.savefig(directory / f"{name}.png", dpi=180, facecolor="white",
                   metadata={"Software": "V10 frozen-results plotting script"})
    figure.savefig(directory / f"{name}.svg", facecolor="white",
                   metadata={"Date": None, "Creator": "V10 frozen-results plotting script"})
    plt.close(figure)


def capacity_figure(data, destination):
    figure, axes = plt.subplots(1, 3, figsize=(15.6, 6.0))
    figure.subplots_adjust(left=0.055, right=0.985, bottom=0.29, top=0.80, wspace=0.26)
    figure.suptitle("V10: capacity scaling of parameter memory and typed composition", x=0.055, y=0.97,
                   ha="left", fontsize=16, fontweight="bold", color=BLACK)
    figure.text(0.055, 0.89, "Frozen protocol: 32, 64 and 128 addresses per type; 3 optimization seeds on one authored task.",
                fontsize=10.5, color="#4B5563")
    plotted = {"panels": []}
    content_styles = [("linear", "Independent linear", BLUE, "s", "-"),
                      ("residual", "Rank-4 residual", ORANGE, "o", "-"),
                      ("untrained", "Untrained", GRAY, "x", ":"),
                      ("exact_sql", "Exact SQL", BLACK, "^", "--")]
    for axis, kind, title in zip(axes[:2], ("semantic", "procedure"),
                                 ("A  Canonical semantic readout", "B  Canonical procedure readout"), strict=True):
        panel = {"title": title, "series": []}
        for arm, label, color, marker, linestyle in content_styles:
            rows = [row for row in data["content"] if row["arm"] == f"{kind}-{arm}"]
            series = draw_capacity_series(axis, rows, "canonical_correct", "canonical_count", color, marker, linestyle, label)
            panel["series"].append({"arm": arm, **series})
        axis.set_title(title, loc="left", fontsize=11.5, fontweight="bold", pad=11)
        axis.legend(loc="lower left", bbox_to_anchor=(0, -0.30), ncol=2, frameon=False,
                    handlelength=2.3, columnspacing=1.1, fontsize=9)
        plotted["panels"].append(panel)
    axis = axes[2]
    panel = {"title": "C  Held-out execution without hold", "series": []}
    for arm, label, color, marker, linestyle in (
        ("typed", "Typed cells", GREEN, "o", "-"),
        ("joint", "Joint (equal size)", BLUE, "s", "-"),
        ("dense_joint", "Dense joint (larger)", PURPLE, "D", "-"),
        ("exact_sql", "Same-info SQL", BLACK, "^", "--")):
        rows = [row for row in data["composition"] if row["arm"] == arm]
        series = draw_capacity_series(axis, rows, "nonheld_exact", "nonheld_count", color, marker, linestyle, label)
        panel["series"].append({"arm": arm, **series})
    plotted["panels"].append(panel)
    axis.set_title(panel["title"], loc="left", fontsize=11.5, fontweight="bold", pad=11)
    axis.legend(loc="lower left", bbox_to_anchor=(0, -0.30), ncol=2, frameon=False,
                handlelength=2.3, columnspacing=0.8, fontsize=9)
    for axis in axes:
        style_axis(axis, "Exact-match accuracy (%)")
        axis.set_xlim(-0.12, 2.12)
        axis.set_xticks([0, 1, 2], [str(value) for value in CAPACITIES])
        axis.set_xlabel("Stored addresses per type")
    figure.text(0.055, 0.035,
                "Lines: pooled counts across seeds. Small points: individual seeds (slightly offset for visibility). No confidence intervals.\n"
                "Panel C uses held-out queries with hold=false; hold-triggered denials are excluded from its denominator.",
                fontsize=9, color="#4B5563", va="bottom", linespacing=1.5)
    save_figure(figure, destination, "figure_1_capacity")
    return plotted


def draw_capacity_series(axis, rows, correct_key, total_key, color, marker, linestyle, label):
    pooled, seeds = [], []
    for x, capacity in enumerate(CAPACITIES):
        group = sorted((row for row in rows if row["capacity"] == capacity), key=lambda row: row["seed"])
        if [row["seed"] for row in group] != list(SEEDS):
            raise ValueError("incomplete seed grid in plotted series")
        correct, total = sum(row[correct_key] for row in group), sum(row[total_key] for row in group)
        pooled.append({"capacity": capacity, "correct": correct, "total": total, "percent": 100 * correct / total})
        for offset, row in zip((-0.055, 0, 0.055), group, strict=True):
            rate = 100 * row[correct_key] / row[total_key]
            axis.scatter(x + offset, rate, s=24, marker=marker, c=color, alpha=0.38, linewidths=0.8, zorder=3)
            seeds.append({"capacity": capacity, "seed": row["seed"], "correct": row[correct_key],
                          "total": row[total_key], "percent": rate})
    axis.plot(range(3), [row["percent"] for row in pooled], color=color, marker=marker,
              linestyle=linestyle, linewidth=2.0, markersize=5.2, label=label, zorder=4)
    return {"pooled": pooled, "individual_seeds": seeds}


def maintenance_figure(data, destination):
    figure, axes = plt.subplots(1, 3, figsize=(16.2, 5.9), gridspec_kw={"width_ratios": [1.12, 1.12, 1]})
    figure.subplots_adjust(left=0.055, right=0.985, bottom=0.245, top=0.76, wspace=0.27)
    figure.suptitle("V10: updating the current record trades off with unmodified-address accuracy",
                   x=0.055, y=0.97, ha="left", fontsize=15.5, fontweight="bold", color=BLACK)
    figure.text(0.055, 0.90, "64-address maintenance; 32 cycles per seed. Sampled replay is reselected from the full active list each cycle.",
                fontsize=10.5, color="#4B5563")
    trajectories, tradeoffs = [], []
    for arm, label, color, marker in (("full_replay", "Full replay", BLUE, "o"),
                                      ("reservoir16", "Sampled replay (16)", ORANGE, "s")):
        entries = [row for row in data["maintenance_cycles"] if row["arm"] == arm]
        cycles, changed = [], []
        for seed in SEEDS:
            rows = sorted((row for row in entries if row["seed"] == seed), key=lambda row: row["cycle"])
            if [row["cycle"] for row in rows] != list(range(1, 33)):
                raise ValueError("incomplete lifecycle trajectory")
            axes[0].plot(range(1, 33), [100 * row["retained_correct"] / row["retained_count"] for row in rows],
                         color=color, alpha=0.19, linewidth=0.85, zorder=2)
        for cycle in range(1, 33):
            group = [row for row in entries if row["cycle"] == cycle]
            correct, total = sum(row["retained_correct"] for row in group), sum(row["retained_count"] for row in group)
            cycles.append({"cycle": cycle, "correct": correct, "total": total, "percent": 100 * correct / total,
                           "event": group[0]["event"]})
            ordinary = [row for row in group if row["changed_record_correct"] is not None]
            changed.append({"cycle": cycle, "correct": sum(row["changed_record_correct"] for row in ordinary),
                            "total": len(ordinary), "percent": 100 * sum(row["changed_record_correct"] for row in ordinary) / len(ordinary) if ordinary else None})
        axes[0].plot(range(1, 33), [row["percent"] for row in cycles], color=color, linewidth=2.1,
                     marker=marker, markersize=2.6, label=label, zorder=4)
        axes[1].plot(range(1, 33), [row["percent"] if row["percent"] is not None else np.nan for row in changed],
                     color=color, linewidth=1.9, marker=marker, markersize=3.7, label=label, zorder=4)
        ordinary = [row for row in entries if row["event"] != "delete_clean_rebuild"]
        correct = sum(row["retained_correct"] for row in ordinary)
        count = sum(row["retained_count"] for row in ordinary)
        updates = sum(row["changed_record_correct"] for row in ordinary)
        rate_x, rate_y = 100 * correct / count, 100 * updates / len(ordinary)
        individual = []
        for seed in SEEDS:
            rows = [row for row in ordinary if row["seed"] == seed]
            old_rate = 100 * sum(row["retained_correct"] for row in rows) / sum(row["retained_count"] for row in rows)
            new_rate = 100 * sum(row["changed_record_correct"] for row in rows) / len(rows)
            axes[2].scatter(old_rate, new_rate, marker=marker, s=34, color=color, alpha=0.42, linewidths=0.8, zorder=3)
            individual.append({"seed": seed, "unmodified_address_percent": old_rate, "current_change_percent": new_rate})
        axes[2].scatter(rate_x, rate_y, marker="D", s=100, facecolor="white", edgecolor=color, linewidth=2.1, zorder=5)
        text = f"{label}\n{rate_x:.2f}% unmodified\n{rate_y:.2f}% current"
        point = (33, 84) if arm == "reservoir16" else (56, 22)
        axes[2].annotate(text, xy=(rate_x, rate_y), xytext=point, color=color, fontsize=9.2,
                         ha="left", va="center", arrowprops={"arrowstyle": "-", "color": color, "lw": 0.8})
        trajectories.append({"arm": arm, "unmodified_addresses": cycles, "current_change": changed})
        tradeoffs.append({"arm": arm, "ordinary_update_observations": len(ordinary),
                          "unmodified_correct": correct, "unmodified_total": count,
                          "current_change_correct": updates, "current_change_total": len(ordinary),
                          "unmodified_address_percent": rate_x, "current_change_percent": rate_y, "individual_seeds": individual})
    for axis in axes[:2]:
        for cycle in (8, 16, 24, 32):
            axis.axvline(cycle, color=GRAY, linewidth=1.0, linestyle=(0, (2, 3)), zorder=1)
        axis.set_xlim(0.5, 32.5)
        axis.set_xticks([1, 4, 8, 12, 16, 20, 24, 28, 32])
        axis.set_xlabel("Maintenance cycle")
        style_axis(axis)
    axes[0].set_ylabel("Unmodified-address accuracy (%)")
    axes[1].set_ylabel("Current-change success (%)")
    axes[2].set_xlim(0, 100)
    axes[2].set_xticks([0, 25, 50, 75, 100])
    axes[2].set_xlabel("Unmodified-address accuracy (%)")
    style_axis(axes[2], "Current-change success (%)")
    for axis, title in zip(axes, ("A  All 32 cycles", "B  Correction / insertion events", "C  Ordinary-update tradeoff"), strict=True):
        axis.set_title(title, loc="left", fontsize=11.5, fontweight="bold", pad=11)
    handles = [Line2D([0], [0], color=BLUE, lw=2, marker="o", markersize=4, label="Full replay"),
               Line2D([0], [0], color=ORANGE, lw=2, marker="s", markersize=4, label="Sampled replay (16)"),
               Line2D([0], [0], color=GRAY, lw=1, linestyle=(0, (2, 3)), label="Deletion + clean rebuild (8, 16, 24, 32)")]
    figure.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.05, 0.12), ncol=3, frameon=False, fontsize=9.5)
    figure.text(0.055, 0.035,
                "A: thin lines = individual seeds; bold lines = pooled counts. Accuracy includes all unmodified addresses, even if previously wrong.\n"
                "B and C exclude the 4 deletion/rebuild cycles (84 ordinary updates across seeds). C: dots = seeds; diamonds = pooled counts.\n"
                "Cycle 32 rebuilds both arms identically. These are descriptive optimization repeats; no confidence intervals or significance tests.",
                fontsize=9, color="#4B5563", va="bottom", linespacing=1.5)
    save_figure(figure, destination, "figure_2_maintenance")
    return {"trajectories": trajectories, "ordinary_update_tradeoffs": tradeoffs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    parser.add_argument("--counts", type=Path, default=root / "analysis" / "COUNTS.json")
    parser.add_argument("--output-dir", type=Path, default=root / "figures")
    args = parser.parse_args()
    raw = args.counts.read_bytes()
    if hashlib.sha256(raw).hexdigest() != COUNTS_SHA256:
        raise ValueError("input differs from the sealed V10 count table")
    data = json.loads(raw)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.labelsize": 10,
                         "xtick.labelsize": 9, "ytick.labelsize": 9, "svg.fonttype": "none",
                         "svg.hashsalt": "hepta-memory-v10-dd727713", "axes.titlecolor": BLACK,
                         "text.color": BLACK, "axes.labelcolor": BLACK})
    plotted = {"schema": "hepta.memory.v10.figure-data.v1", "counts_sha256": COUNTS_SHA256,
               "figure_1": capacity_figure(data, args.output_dir),
               "figure_2": maintenance_figure(data, args.output_dir)}
    (args.output_dir / "plot_data.json").write_text(json.dumps(plotted, indent=2, allow_nan=False) + "\n")
    receipt = {"schema": "hepta.memory.v10.figure-reproduction.v1", "counts_sha256": COUNTS_SHA256,
               "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "matplotlib_version": matplotlib.__version__, "numpy_version": np.__version__, "python_version": sys.version,
               "confidence_intervals": False, "significance_tests": False,
               "artifacts": {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                             for path in sorted(args.output_dir.iterdir()) if path.suffix in (".png", ".svg")}}
    (args.output_dir / "REPRODUCTION.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"output_dir": str(args.output_dir), "figures": 2, "formats": ["png", "svg"], "counts_sha256": COUNTS_SHA256}))


if __name__ == "__main__":
    main()
