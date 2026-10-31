"""Scientific figures from the completed aggregate only; never raw test tuning.

All seeds contribute. Error bars show across-seed standard deviations, not
confidence intervals. Noninferiority markers come from the registered analysis.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from .analysis_audit import digest


SYNTHETIC = ("selective_copy", "mqar", "delayed_recall")
ARMS = ("value_dual", "two_gates", "transformer", "lif_snn")
COLORS = dict(value_dual="#0072B2", two_gates="#D55E00", transformer="#009E73", lif_snn="#CC79A7")
LABELS = dict(value_dual="HCSN value + dual", two_gates="Two gates", transformer="Transformer", lif_snn="LIF SNN")
TASKS = dict(selective_copy="Selective copy", mqar="MQAR", delayed_recall="Delayed recall", async_av="Decoded asynchronous AV")


def same_condition(a, b):
    return a == b


def figure_data(report):
    """Extract the full prespecified slices, without looking for best seeds."""
    curves, points, cells = [], [], []
    for row in report["arm_summaries"]:
        c = row["condition"]
        if c["width"] != 16:
            continue
        if row["arm"] in ARMS:
            base = dict(task=c["task"], arm=row["arm"], condition=c, seeds=row["seeds"],
                        n=row["accuracy"]["n"], accuracy_mean=row["accuracy"]["mean"],
                        accuracy_sd=row["accuracy"]["sd"], cross_entropy_mean=row["cross_entropy"]["mean"],
                        actual_updates=row["actual_updates"], allocated_parameters=row["allocated_parameters"],
                        trainable_parameters=row["trainable_parameters"])
            if c["task"] in SYNTHETIC and c["training_cpu_budget"] is None and row["case"].startswith("length"):
                curves.append(dict(base, length=int(row["case"].removeprefix("length"))))
            if row["case"] == "length32":
                qualified = [p for p in report["comparisons"] if p["case"] == row["case"]
                             and p["candidate"] == row["arm"] and p["baseline"] in ARMS
                             and same_condition(c, p["condition"]) and p["quality_noninferiority_qualified"]]
                points.append(dict(base, training_cpu_mean=row["costs"]["training_cpu_seconds"]["mean"],
                    training_cpu_sd=row["costs"]["training_cpu_seconds"]["sd"],
                    whole_worker_cpu_mean=row["costs"]["child_cpu_seconds"]["mean"],
                    quality_noninferiority_vs=[p["baseline"] for p in qualified],
                    qualified_whole_worker_cpu_advantage_vs=[p["baseline"] for p in qualified
                                                             if p["qualified_whole_worker_cpu_advantage"]],
                    parameter_matched_vs=[p["baseline"] for p in qualified if p["parameter_budget_matched"]],
                    training_cpu_matched_vs=[p["baseline"] for p in qualified if p["training_cpu_matched"]]))
        if c["task"] == "selective_copy" and c["training_cpu_budget"] is None:
            parts = row["arm"].split("_")
            if len(parts) == 2 and parts[0] in ("value", "fixed", "direct") and parts[1] in ("dual", "single", "ordinary"):
                cells.append(dict(boundary=parts[0], channel=parts[1], case=row["case"],
                                  seeds=row["seeds"], n=row["accuracy"]["n"],
                                  accuracy_mean=row["accuracy"]["mean"], accuracy_sd=row["accuracy"]["sd"]))
    return dict(length_curves=curves, cost_points=points, factorial_cells=cells,
                expected_seeds=report["expected_seeds"], thresholds=report["analysis_thresholds"],
                uncertainty="Across-seed mean +/- sample SD; the report separately gives paired t confidence intervals",
                cost_scope="Scatter x is inner training CPU; a CPU-advantage qualification refers to whole worker CPU",
                omissions="Failed/unverified runs cannot contribute points; n and omissions remain explicit in aggregate.json",
                no_best_seed_selection=True)


def save_figure(fig, output, name):
    for extension in ("png", "svg"):
        path = output/(name+"."+extension)
        if path.exists():
            raise FileExistsError("Refuse to overwrite figure: "+str(path))
        fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def length_plot(data, output):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)
    for ax, task in zip(axes, SYNTHETIC, strict=True):
        for arm in ARMS:
            rows = sorted((r for r in data["length_curves"] if r["task"] == task and r["arm"] == arm), key=lambda r: r["length"])
            if not rows:
                continue
            ax.errorbar([r["length"] for r in rows], [r["accuracy_mean"] for r in rows],
                        yerr=[r["accuracy_sd"] or 0 for r in rows], color=COLORS[arm],
                        marker="o", markersize=4, capsize=3, linewidth=1.5, label=LABELS[arm])
            for r in rows:
                if r["n"] != len(data["expected_seeds"]):
                    ax.annotate(f"n={r['n']}", (r["length"], r["accuracy_mean"]), fontsize=7)
        ax.set(title=TASKS[task], xlabel="Test sequence length", xticks=[32, 64, 128], ylim=(-.03, 1.03))
        ax.grid(alpha=.2)
    axes[0].set_ylabel("Test accuracy")
    handles = [Line2D([0], [0], color=COLORS[a], marker="o", label=LABELS[a]) for a in ARMS]
    fig.legend(handles=handles, loc="lower center", ncol=4, bbox_to_anchor=(.5, .01), frameon=False)
    fig.suptitle("Fixed updates, width 16: all registered seeds, mean ± SD", fontsize=13)
    fig.text(.5, -.015, "SD bars describe seed variation on the same test cohort; they are not paired-effect confidence intervals.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .10, 1, .94))
    save_figure(fig, output, "accuracy_by_length")


def cost_plot(data, output):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), sharey=True)
    for ax, task in zip(axes.flat, (*SYNTHETIC, "async_av"), strict=True):
        rows = [r for r in data["cost_points"] if r["task"] == task]
        notes = []
        for r in rows:
            cap = r["condition"]["training_cpu_budget"]
            marker = "o" if cap is None else "s"
            fill = COLORS[r["arm"]] if cap is None else "white"
            x, y = r["training_cpu_mean"], r["accuracy_mean"]
            ax.errorbar(x, y, xerr=r["training_cpu_sd"] or 0, yerr=r["accuracy_sd"] or 0,
                        marker=marker, markerfacecolor=fill, markeredgecolor=COLORS[r["arm"]],
                        markersize=7, color=COLORS[r["arm"]], capsize=3, linestyle="none", alpha=.85)
            if r["quality_noninferiority_vs"]:
                ax.scatter([x], [y], s=180, facecolors="none", edgecolors="#111111", linewidths=1.5)
                family = "fixed" if cap is None else f"CPU{cap:g}s"
                names = ", ".join(LABELS[v] for v in r["quality_noninferiority_vs"])
                notes.append(f"{family} HCSN NI vs: {names}")
                wins = r["qualified_whole_worker_cpu_advantage_vs"]
                if wins:
                    ax.annotate("*", (x, y), xytext=(5, 5), textcoords="offset points", fontsize=15)
                    notes.append("* Whole-worker CPU advantage vs: "+", ".join(LABELS[v] for v in wins))
            if r["n"] != len(data["expected_seeds"]):
                ax.annotate(f"n={r['n']}", (x, y), fontsize=7)
        if not notes:
            notes = ["No plotted HCSN comparison passes the registered NI gate."]
        ax.text(.02, .98, "\n".join(notes), transform=ax.transAxes, va="top", fontsize=7.5,
                bbox=dict(facecolor="white", alpha=.8, edgecolor="none"))
        ax.set(title=TASKS[task], xlabel="Inner training CPU (seconds, logarithmic scale)",
               xscale="log", ylim=(-.03, 1.03))
        ax.grid(alpha=.2)
    axes[0, 0].set_ylabel("Test accuracy")
    axes[1, 0].set_ylabel("Test accuracy")
    handles = [Line2D([0], [0], color=COLORS[a], marker="o", linestyle="none", label=LABELS[a]) for a in ARMS]
    handles += [Line2D([0], [0], color="grey", marker="o", linestyle="none", label="Fixed updates"),
                Line2D([0], [0], color="grey", marker="s", markerfacecolor="white", linestyle="none", label="15s training CPU cap")]
    fig.legend(handles=handles, loc="lower center", ncol=3, bbox_to_anchor=(.5, .01), frameon=False)
    fig.suptitle("Measured cost and quality: equality is not presumed", fontsize=14)
    fig.text(.5, -.01, "Width 16; all seeds mean ± SD. Black ring: registered quality NI against named baseline(s), not universal superiority.\n"
             "An asterisk additionally requires the whole-worker CPU ratio CI upper bound < 1. Parameter/CPU matches remain separate in JSON.",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .11, 1, .95))
    save_figure(fig, output, "quality_cost_scatter")


def factorial_plot(data, output):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4), sharey=True)
    boundaries, channels = ("value", "fixed", "direct"), ("dual", "single", "ordinary")
    image = None
    for ax, length in zip(axes, (32, 64, 128), strict=True):
        grid = np.full((3, 3), np.nan)
        cells = {(r["boundary"], r["channel"]): r for r in data["factorial_cells"] if r["case"] == f"length{length}"}
        for bi, b in enumerate(boundaries):
            for ci, c in enumerate(channels):
                row = cells.get((b, c))
                if row:
                    grid[bi, ci] = row["accuracy_mean"]
        image = ax.imshow(grid, vmin=0, vmax=1, cmap="viridis")
        for bi, b in enumerate(boundaries):
            for ci, c in enumerate(channels):
                row = cells.get((b, c))
                if row:
                    sd = "n/a" if row["accuracy_sd"] is None else f"{100*row['accuracy_sd']:.1f}"
                    label = f"{100*row['accuracy_mean']:.1f} ± {sd}%\nn={row['n']}"
                    color = "black" if row["accuracy_mean"] > .6 else "white"
                else:
                    label, color = "unavailable", "black"
                ax.text(ci, bi, label, ha="center", va="center", color=color, fontsize=9)
        ax.set(title=f"Test length {length}", xlabel="Channel", xticks=range(3), xticklabels=channels,
               yticks=range(3), yticklabels=boundaries)
    axes[0].set_ylabel("Boundary policy")
    fig.suptitle("Selective copy, width 16: full 3 × 3 factorial, mean accuracy ± SD", fontsize=13)
    fig.subplots_adjust(left=.07, right=.90, bottom=.19, top=.80, wspace=.16)
    colorbar = fig.add_axes((.925, .20, .015, .58))
    fig.colorbar(image, cax=colorbar, label="Mean accuracy")
    fig.text(.5, .02, "All registered seeds; common 0–1 color range. Main-effect and interaction confidence intervals are in the report.", ha="center", fontsize=9)
    save_figure(fig, output, "boundary_channel_factorial")


def plot(aggregate, output):
    aggregate, output = Path(aggregate), Path(output)
    report = json.loads(aggregate.read_text())
    if report.get("schema") != "hcsn-paired-study-analysis.v1" or not report.get("integrity", {}).get("execution", {}).get("complete"):
        raise ValueError("Figures require the completed registered analysis")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Figure outputs must be new; previous evidence is retained")
    output.mkdir(parents=True, exist_ok=True)
    data = figure_data(report)
    data.update(created_at_utc=datetime.now(timezone.utc).isoformat(),
                aggregate_sha256=digest(aggregate), plot_source_sha256=digest(__file__))
    (output/"plot_data.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
    length_plot(data, output)
    cost_plot(data, output)
    factorial_plot(data, output)
    print(json.dumps(dict(output=str(output), figures=3, all_seeds=True)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, default=Path(__file__).parent/"results/study001/analysis/aggregate.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plot(args.aggregate, args.output or args.aggregate.parent/"figures")
