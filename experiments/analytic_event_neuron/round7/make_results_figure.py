"""Render the sealed study's descriptive result figure; no model execution."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    root = Path(__file__).resolve().parent
    source = root / "evidence/confirmation_001/SUMMARY.json"
    summary = json.loads(source.read_text())
    output = root / "figures"
    output.mkdir(exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11,
        "axes.spines.top": False, "axes.spines.right": False,
        "svg.fonttype": "none", "savefig.facecolor": "white",
    })
    fig, (left, right) = plt.subplots(1, 2, figsize=(15, 6.3),
                                     gridspec_kw={"width_ratios": [1.35, 1]})
    fig.subplots_adjust(left=.20, right=.97, top=.78, bottom=.22, wspace=.34)
    fig.text(.035, .94, "Round 7 | All three primary promotion gates failed",
             fontsize=20, weight="bold", color="#172b3a")
    fig.text(.035, .885,
             "Frozen models; 108,800 paired trajectory records; five fitted seeds. "
             "Research profile remains unpromoted.", color="#4b5c68")

    names = ["B-A", "D-B", "interaction"]
    labels = ["B - A\nValue controller package", "D - B\nFirst-passage cell increment",
              "(D - C) - (B - A)\nInteraction"]
    for y, name in zip([2, 1, 0], names):
        row = summary["contrasts"][name]
        mean = row["mean"]
        lo, hi = row["bootstrap_interval"]
        left.errorbar(mean, y, xerr=[[mean-lo], [hi-mean]], fmt="o", ms=8,
                      color="#a74039", lw=2, capsize=5)
        left.scatter([row["practical_threshold"]], [y+.18], marker="|",
                     s=170, color="#bb8129", linewidth=2)
        left.text(.081, y, "FAIL", va="center", color="#a74039", fontsize=10,
                  weight="bold")
    left.axvline(0, color="#62717a", ls="--", lw=1)
    left.set(yticks=[2, 1, 0], yticklabels=labels, ylim=(-.55, 2.6),
             xlim=(-.022, .095), xlabel="Paired registered-utility difference")
    left.grid(axis="x", color="#e8edf0")
    left.set_axisbelow(True)
    left.set_title("Primary comparisons | 98.333% intervals", loc="left",
                   fontsize=12, weight="bold", pad=17)
    left.text(0, -.18, "Gold tick: required lower-bound threshold (0.005 / 0.005 / 0)",
              transform=left.transAxes, fontsize=9, color="#76613d")

    style = {
        "A": ("#9aa7af", "A", (7, 1)),
        "B": ("#286a9c", "B: clocked + value", (8, 7)),
        "C": ("#b59895", "C", (-15, 8)),
        "D": ("#a74039", "D: first passage + value", (8, -12)),
        "continuous": ("#62717a", "Continuous mass", (-58, -19)),
        "direct_Q": ("#2c7a63", "Direct Q", (8, 4)),
    }
    for arm, (color, label, offset) in style.items():
        row = summary["arms"]["nominal/"+arm]
        xy = (row["process_cpu_ns"] / 1e6, row["registered_return"])
        right.scatter(*xy, s=65, color=color, zorder=3)
        right.annotate(label, xy, xytext=offset, textcoords="offset points",
                       fontsize=9, color=color)
    right.set(xlabel="Measured process CPU per episode (ms)",
              ylabel="Registered utility (nominal mean)", xlim=(2.0, 6.6),
              ylim=(.599, .658))
    right.grid(color="#e8edf0")
    right.set_axisbelow(True)
    right.set_title("Quality-cost comparison | observed means", loc="left",
                    fontsize=12, weight="bold", pad=17)
    fig.text(.035, .075,
             "Utility subtracts declared task and decision/event proxy fees; "
             "it does not price measured CPU or energy. Lower CPU and higher utility are preferable.",
             fontsize=9, color="#4b5c68")
    fig.text(.035, .038,
             "Intervals: paired whole-episode bootstrap within fitted-seed clusters, "
             "10,000 replicates; three-comparison Bonferroni adjustment. "
             "Five seeds limit inference on retraining variability.",
             fontsize=9, color="#4b5c68")
    for ext in ["svg", "png"]:
        fig.savefig(output / ("round7_results."+ext), dpi=160)
    plt.close(fig)
    provenance = {
        "source": str(source.relative_to(root)),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "classification": "Post-confirmation visualization of existing summaries; no new inference",
        "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(output.glob("round7_results.*"))},
    }
    (output / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2)+"\n")


if __name__ == "__main__":
    main()
