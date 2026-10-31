"""Render three scientific panels from recorded JSON; never executes a model."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "hcsn_plot_cache"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


BASE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_inputs():
    paths = {
        "mechanism": BASE / "results/mechanism/formal001/RESULTS.json",
        "mechanism_protocol": BASE / "results/mechanism/formal001/PROTOCOL.json",
        "memory": BASE / "results/memory/RESULTS.json",
        "memory_protocol": BASE / "results/memory/PROTOCOL.json",
        "clock": BASE / "results/memory_clock_repair/RESULTS.json",
        "clock_protocol": BASE / "results/memory_clock_repair/PROTOCOL.json",
    }
    return {key: json.loads(path.read_text()) for key, path in paths.items()}, paths


def make_plot(output):
    data, inputs = read_inputs()
    mechanism, protocol = data["mechanism"], data["mechanism_protocol"]
    contrast = mechanism["findings"]["matched"]["contrasts"]["D-B"]["net_reward"]
    original_rows = [row for row in data["memory"]["rows"]
                     if row["task"] == "selective_copy" and row["family"] == "shared"
                     and not row["adapter_disabled"] and row["length"] in (32, 128)]
    capped_rows = [row for row in data["clock"]["rows"]
                   if row["task"] == "selective_copy" and row["length"] in (32, 128)]
    conditions = sorted({(r["length"], r["horizon"]) for r in original_rows}, key=lambda p: (p[1], p[0]))
    copy = []
    for length, horizon in conditions:
        group = {"length": length, "horizon": horizon}
        for variant, rows in (("original", original_rows), ("fixed_clock_cap", capped_rows)):
            chosen = sorted((r for r in rows if r["length"] == length and r["horizon"] == horizon),
                            key=lambda r: r["seed"])
            if len(chosen) != contrast["fit_groups"]:
                raise ValueError("Missing fitted-seed rows")
            exact = [float(row["exact_recall"]) for row in chosen]
            counts = [int(round(row["samples"] * row["exact_recall"])) for row in chosen]
            samples = [int(row["samples"]) for row in chosen]
            if not np.allclose(np.array(counts) / samples, exact, rtol=0, atol=1e-15):
                raise ValueError("Exact recall cannot be reconstructed from sequence counts")
            group[variant] = {
                "mean_exact_recall": float(np.mean(exact)), "mean_percent": float(100 * np.mean(exact)),
                "fitted_seeds": [row["seed"] for row in chosen], "seed_exact_recall": exact,
                "correct_sequences_per_seed": counts, "sequences_per_seed": samples,
                "predictions": [row["prediction"] for row in chosen],
                "aggregation": "arithmetic mean of fitted seeds on the same sequences; not independent datasets",
            }
        copy.append(group)
    costs = {arm: mechanism["costs"]["per_arm"][arm]["cpu_seconds"] for arm in ("B", "D")}
    reduction = 1 - costs["D"] / costs["B"]
    records = {
        "A_matched_D_minus_B_utility": contrast,
        "B_shared_Copy_exact_recall": copy,
        "C_complete_worker_CPU_seconds": costs,
        "C_D_vs_B_CPU_reduction_fraction": reduction,
        "C_episodes_per_arm": len(protocol["fit_seeds"]) * len(protocol["conditions"]) * protocol["episodes_per_group"],
        "C_episodes_per_fresh_worker": protocol["episodes_per_group"],
        "C_ordinary_training_once_CPU_seconds": mechanism["costs"]["ordinary_training_once_cpu_seconds"],
        "clock_caps": data["clock_protocol"]["caps"],
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
        "axes.titlesize": 13, "axes.labelsize": 10, "axes.edgecolor": "#B8C0CB",
        "xtick.color": "#425168", "ytick.color": "#425168", "text.color": "#17283E",
        "axes.labelcolor": "#35465C", "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "svg.fonttype": "none", "svg.hashsalt": "hcsn-v3-results"})
    blue, teal, purple, muted = "#466A96", "#13827D", "#9662AD", "#64748B"
    fig, axes = plt.subplots(1, 3, figsize=(16.6, 5.5), gridspec_kw={"width_ratios": [1.05, 1.55, 1.]})
    fig.subplots_adjust(left=.06, right=.985, top=.77, bottom=.265, wspace=.33)
    fig.suptitle("HCSN: causal evidence, content repair, and measured cost", x=.06, ha="left", y=.98,
                 fontsize=18, fontweight="bold")
    fig.text(.06, .91, "The analytic increment remains uncertain; the clock repair belongs to shared content.",
             fontsize=11, color=muted)
    for ax in axes:
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#E9EDF3", linewidth=.7)
    ax = axes[0]
    ax.set_title("A  |  Analytic increment", loc="left", pad=23, fontweight="bold")
    mean = contrast["mean"]
    low, high = contrast["descriptive_95"]
    ax.axvline(0, color="#9B5D57", linestyle=(0, (4, 3)), linewidth=1.2, zorder=1)
    ax.errorbar(mean, .68, xerr=[[mean - low], [high - mean]], fmt="o", markersize=9,
                color=blue, ecolor=blue, capsize=6, elinewidth=2, zorder=3)
    ax.set_ylim(0, 1.12)
    # Fixed visual axis covers both CI endpoints; it is not a data threshold.
    margin = (high - low) * .17
    ax.set_xlim(min(0, low) - margin, high + margin)
    ax.set_yticks([])
    ax.set_xticks([-.01, 0, .01, .02, .03])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("D − B task utility")
    ax.text(.5, .39, f"{mean:+.6f}", transform=ax.transAxes, ha="center", fontsize=20, fontweight="bold", color=blue)
    ax.text(.5, .26, f"95% CI  [{low:+.6f}, {high:+.6f}]", transform=ax.transAxes,
            ha="center", fontsize=9.5)
    ax.text(.5, .12, "Interval includes zero", transform=ax.transAxes, ha="center", color="#9B5D57", fontsize=11)
    ax.text(0, -.27, f"{contrast['fit_groups']} fits · {contrast['paired_episodes']} paired episodes\nControlled mechanism; descriptive interval",
            transform=ax.transAxes, color=muted, fontsize=10, va="top", linespacing=1.55)

    ax = axes[1]
    ax.set_title("B  |  Common Copy exact recall", loc="left", pad=23, fontweight="bold")
    x = np.arange(len(copy))
    width = .34
    for variant, label, color, shift in (("original", "Original clock", blue, -width / 2),
                                      ("fixed_clock_cap", "Fixed clock cap", purple, width / 2)):
        values = [row[variant]["mean_percent"] for row in copy]
        ax.bar(x + shift, values, width=width, color=color, alpha=.85, label=label, zorder=2)
        for i, row in enumerate(copy):
            seed_values = np.asarray(row[variant]["seed_exact_recall"]) * 100
            jitter = np.linspace(-width * .15, width * .15, len(seed_values))
            ax.scatter(i + shift + jitter, seed_values, s=12, color="#223046", alpha=.7,
                       linewidths=.4, edgecolors="white", zorder=4)
            ax.text(i + shift, max(values[i], float(seed_values.max())) + 4.4, f"{values[i]:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, 119)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("All four queries correct (%)")
    ax.set_xticks(x, [f"L{row['length']}\nT={row['horizon']:g}" for row in copy])
    ax.legend(loc="upper center", bbox_to_anchor=(.5, 1.135), frameon=False, ncol=2, fontsize=9,
              handlelength=1.2, columnspacing=1.1)
    ax.text(0, -.27, "Exploratory clock intervention; previously evaluated inputs\nShared content only; dots are three fitted seeds",
            transform=ax.transAxes, color=muted, fontsize=9.5, va="top", linespacing=1.55)

    ax = axes[2]
    ax.set_title("C  |  Complete worker CPU", loc="left", pad=23, fontweight="bold")
    bars = ax.bar([0, 1], [costs["B"], costs["D"]], width=.58, color=[blue, teal], zorder=2)
    for bar, arm in zip(bars, ("B", "D"), strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(costs.values()) * .04,
                f"{costs[arm]:.3f} s", ha="center", fontsize=11, fontweight="bold")
    ax.set_ylim(0, max(costs.values()) * 1.22)
    ax.set_xticks([0, 1], ["B\nOrdinary + value", "D\nAnalytic + value"])
    ax.set_ylabel("CPU seconds")
    ax.text(.98, .95, f"D: {100 * reduction:.2f}% lower", transform=ax.transAxes,
            ha="right", va="top", color=teal, fontweight="bold", fontsize=11)
    ax.text(0, -.27, "No quality noninferiority certificate\nShared host; training charged separately", transform=ax.transAxes,
            color=muted, fontsize=10, va="top", linespacing=1.55)
    fig.text(.06, .018,
             f"CPU: {records['C_episodes_per_arm']} episodes per arm; {records['C_episodes_per_fresh_worker']} per fresh worker. "
             "Includes imports, loading, inference and evidence output. Energy not measured.",
             fontsize=9, color=muted)
    png, svg = output / "hcsn_three_findings.png", output / "hcsn_three_findings.svg"
    fig.savefig(png, dpi=200, metadata={"Title": "HCSN three findings", "Description": "Recorded JSON only; source hashes in PLOT_SOURCE.json"})
    fig.savefig(svg, metadata={"Title": "HCSN three findings", "Date": None,
                              "Description": "Recorded JSON only; source hashes in PLOT_SOURCE.json"})
    plt.close(fig)
    csv_path = output / "PLOT_DATA.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["panel", "measure", "group", "variant", "seed", "value", "unit", "correct_sequences", "sequences"])
        for measure, value in (("mean", mean), ("descriptive_95_low", low), ("descriptive_95_high", high)):
            writer.writerow(["A", measure, "matched D-B", "", "", repr(value), "utility", "", ""])
        for row in copy:
            for variant in ("original", "fixed_clock_cap"):
                details = row[variant]
                writer.writerow(["B", "mean_exact_recall", f"L{row['length']}_T{row['horizon']}", variant,
                                 "", repr(details["mean_exact_recall"]), "fraction", "", ""])
                for seed, value, correct, count in zip(details["fitted_seeds"], details["seed_exact_recall"],
                                                      details["correct_sequences_per_seed"], details["sequences_per_seed"], strict=True):
                    writer.writerow(["B", "exact_recall", f"L{row['length']}_T{row['horizon']}", variant,
                                     seed, repr(value), "fraction", correct, count])
        for arm, value in costs.items():
            writer.writerow(["C", "complete_worker_CPU", arm, "", "", repr(value), "seconds", "", ""])
        writer.writerow(["C", "D_vs_B_CPU_reduction", "D/B", "", "", repr(reduction), "fraction", "", ""])
    provenance = {
        "schema": "hcsn-static-scientific-plot.v1", "plot_script": str(Path(__file__).relative_to(BASE)),
        "plot_script_sha256": digest(__file__),
        "inputs": {name: {"path": str(path.relative_to(BASE)), "sha256": digest(path)} for name, path in inputs.items()},
        "exact_plotted_data": records,
        "limitations": ["three fitted groups, controlled mechanism; descriptive intervals",
                        data["clock"]["scope"], "clock repair uses shared content only; no analytic-adapter attribution",
                        "no preregistered quality noninferiority certificate", "shared CPU host; energy not measured"],
        "rendering": {"library": "matplotlib", "version": matplotlib.__version__, "PNG_dpi": 200,
                      "mean_copy_aggregation": "unweighted arithmetic mean of exactly three recorded seed values",
                      "printed_precision": "six decimals utility; two decimals percent; three decimals CPU; exact values retained here and CSV"},
        "outputs": {path.name: {"sha256": digest(path), "bytes": path.stat().st_size} for path in (png, svg, csv_path)},
    }
    (output / "PLOT_SOURCE.json").write_text(json.dumps(provenance, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"PNG": str(png), "SVG": str(svg), "source": str(output / "PLOT_SOURCE.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE / "figures")
    make_plot(parser.parse_args().output)
