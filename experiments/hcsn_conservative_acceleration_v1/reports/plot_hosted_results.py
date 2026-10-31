"""Render the published hosted results; no training or result-file mutation.

Run from the repository root with Python + matplotlib. The source analysis must
be the exact published artifact. PNG is an optional local visual-QA export.
"""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", type=Path)
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    source = package / "results/comparison002_hosted_analysis/ANALYSIS.json"
    raw = source.read_bytes()
    expected = "82c773d6d289477fbb723969d5169cc507d193aa3c3413f06266ddab927931ad"
    assert hashlib.sha256(raw).hexdigest() == expected
    analysis = json.loads(raw)
    assert analysis["complete"] and analysis["valid_jobs"] == 70
    models = ["hcsn_reference", "hcsn_accelerated", "two_gates", "transformer", "lif_snn"]
    names = ["HCSN reference", "HCSN accelerated", "Ordinary two gates", "Transformer", "LIF control"]
    colors = ["#8B98A7", "#087F8C", "#376FA3", "#765CB3", "#AA7C39"]
    lookup = {(row["family"], row["task"], row["model"]): row for row in analysis["aggregation"]}
    primary = [row for row in analysis["fixed_update_pairs"] if row["task"] in ("selective_copy", "mqar")]
    assert len(primary) == 6
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "svg.hashsalt": "hcsn-hosted-41059620366"})
    fig = plt.figure(figsize=(14.0, 8.5), facecolor="white")
    grid = fig.add_gridspec(2, 2, height_ratios=[1.45, 0.85], hspace=0.76, wspace=0.42)
    for column, (task, title) in enumerate((("selective_copy", "Selective copy"), ("mqar", "MQAR"))):
        ax = fig.add_subplot(grid[0, column])
        means = [100 * lookup[("cpu", task, m)]["accuracy"]["mean"] for m in models]
        sds = [100 * lookup[("cpu", task, m)]["accuracy"]["sample_sd"] for m in models]
        y = np.arange(len(models))
        ax.barh(y, means, xerr=sds, color=colors, height=.60,
                error_kw={"elinewidth": 1.2, "capsize": 3, "ecolor": "#333333"})
        ax.set_yticks(y, names)
        ax.invert_yaxis()
        ax.set_xlim(0, 112)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xlabel("Test accuracy (%) at ~30 training CPU seconds")
        ax.set_title(title, loc="left", pad=15)
        ax.axvline(12.5, color="#B5B8BB", ls=":", lw=1, zorder=0)
        for i, (mean, sd) in enumerate(zip(means, sds)):
            ax.text(min(mean + sd + 1.8, 102.2), i, f"{mean:.2f}", va="center", fontsize=9)
        ax.grid(axis="x", alpha=.13)
        ax.set_axisbelow(True)
    ax = fig.add_subplot(grid[1, :])
    keys = ["training_cpu_speedup", "whole_worker_cpu_speedup", "inference_cpu_speedup"]
    labels = ["Training CPU", "Whole-worker CPU", "Inference CPU"]
    for i, key in enumerate(keys):
        ratios = np.asarray([row[key] for row in primary])
        gm = np.exp(np.log(ratios).mean())
        ax.scatter(ratios, np.full(6, i) + np.linspace(-.13, .13, 6),
                   s=38, facecolor="#7CB5BA", edgecolor="#087F8C", linewidth=.8, zorder=3)
        ax.scatter([gm], [i], s=85, marker="D", color="#163E48", zorder=4)
        ax.text(2.19, i, f"Geometric mean {gm:.3f}x", va="center", fontsize=11, color="#163E48")
    ax.set_yticks(range(3), labels)
    ax.invert_yaxis()
    ax.set_ylim(2.55, -.55)
    ax.set_xlim(.9, 2.85)
    ax.set_xticks([1, 1.25, 1.5, 1.75, 2, 2.25])
    ax.axvline(1, color="#777777", linestyle="--", lw=1)
    ax.set_xlabel("Reference CPU time / accelerated CPU time (fixed 32 updates)")
    ax.set_title("Same HCSN: six paired implementation comparisons", loc="left", pad=14)
    ax.grid(axis="x", alpha=.15)
    fig.suptitle("Faithful implementation speedup; content advantage not established",
                 x=.05, ha="left", y=.98, fontsize=17, weight="bold", color="#193343")
    fig.text(.05, .925, "70 completed jobs | CPU-only | common learning rate | matched effective parameters (within 3%)",
             fontsize=11, color="#53606B")
    fig.text(.05, .055, "Upper panels: 3 seeds, mean +/- sample SD; dotted line = 8-class chance. These are short-budget controls, not tuned optima.",
             fontsize=9, color="#53606B")
    fig.text(.05, .032, "Lower panel: each circle is one paired seed/task, diamond is geometric mean. Internal speedup is not a speedup over Transformer.",
             fontsize=9, color="#53606B")
    fig.text(.05, .010, "Source: published ANALYSIS.json (SHA-256 82c773d6...931ad), run 41059620366. Engineering replication after prior test exposure.",
             fontsize=8, color="#707780")
    fig.subplots_adjust(left=.17, right=.96, top=.84, bottom=.16)
    target = package / "reports/hosted_results.svg"
    fig.savefig(target, metadata={"Date": None, "Description": "Measured HCSN hosted engineering replication; no energy or foundation-model claim."})
    if args.png:
        fig.savefig(args.png, dpi=150)
    plt.close(fig)
    print(target)


if __name__ == "__main__":
    main()
