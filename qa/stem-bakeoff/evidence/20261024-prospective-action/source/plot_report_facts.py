"""Plot saved fixed-seed means and existing paired intervals, without refitting."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


FACTS_SHA = "1139b79df97554b6cac94e925579154ad01ab97c6cae48d847bc45e82e4b46be"
NATIVE = "granite_clean_field770"
BUDGETS = [8, 32, 64]
COLORS = {"linear": "#125A9D", "gated": "#D75B28", "residual": "#8759A2",
          "selected": "#087F6C", "hash": "#7E8792"}


def plot(facts, output):
    payload = Path(facts).read_bytes()
    if hashlib.sha256(payload).hexdigest() != FACTS_SHA:
        raise ValueError("facts differ from frozen arithmetic extraction")
    data = json.loads(payload)
    rows = {(row["condition"], row["budget"], row["arm"]): row
            for row in data["fixed_seed_means"]}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "svg.hashsalt": FACTS_SHA})
    fig, axes = plt.subplots(2, 2, figsize=(13.0, 9.4), constrained_layout=True)
    for arm in ("linear", "gated", "residual", "selected"):
        label = "Tuning-selected" if arm == "selected" else arm.capitalize()
        values = [rows[(NATIVE, budget, arm)] for budget in BUDGETS]
        axes[0, 0].plot(BUDGETS, [v["semantic"]["balanced_accuracy"] for v in values],
                        "o-", color=COLORS[arm], label=label, linewidth=2)
        axes[0, 1].plot(BUDGETS, [v["top_k"]["1"]["known_positive_hit_rate"] for v in values],
                        "o-", color=COLORS[arm], label=label, linewidth=2)
    for ax, metric in zip(axes[0], ("balanced_accuracy", "known_positive_hit_rate")):
        values = [rows[("identifier_hash770", budget, "linear")] for budget in BUDGETS]
        y = ([v["semantic"][metric] for v in values] if metric == "balanced_accuracy" else
             [v["top_k"]["1"][metric] for v in values])
        ax.plot(BUDGETS, y, "s--", color=COLORS["hash"], label="Hash770 linear")
        ax.set_xscale("log", base=2)
        ax.set_xticks(BUDGETS, [str(n) for n in BUDGETS])
        ax.set_xlabel("Distinct bugs used for gradient fitting")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(axis="y", color="#DDE3E8", linewidth=.7)
    axes[0, 0].axhline(.5, color="#9BA3AD", linestyle=":", linewidth=1)
    axes[0, 0].set_ylim(.47, .66)
    axes[0, 0].set_title("A  Forced balanced accuracy · 47 valid bugs", loc="left")
    axes[0, 0].legend(frameon=False, ncols=2, fontsize=9, loc="upper left")
    jaccard = data["ranking_controls"]["raw_jaccard"]["top_k"]["1"]["known_positive_hit_rate"]
    axes[0, 1].axhline(jaccard, color="#404B5A", linestyle=":", label="Raw Jaccard (64.58%)")
    axes[0, 1].set_ylim(.32, .84)
    axes[0, 1].set_title("B  First action hits a known positive · 48 bugs", loc="left")
    axes[0, 1].annotate("Raw Jaccard 64.58%", (64, jaccard), xytext=(-6, 5),
                        textcoords="offset points", ha="right", color="#404B5A", fontsize=9)
    comparisons = [
        ([NATIVE, "gated"], [NATIVE, "linear"], "balanced_accuracy",
         "C  Granite gated minus linear · BA"),
        ([NATIVE, "selected"], [None, "raw_jaccard"], "known_positive_top1",
         "D  Tuning-selected minus raw Jaccard · top1"),
    ]
    for ax, (left, right, metric, title) in zip(axes[1], comparisons):
        for pos, budget in enumerate(BUDGETS):
            matches = [item for item in data["fixed_contrasts"]
                       if item["definition"] == {"budget": budget, "left": left, "right": right}]
            if len(matches) != 1:
                raise ValueError("missing unique predeclared contrast: " + str((left, right, budget)))
            value = matches[0]["metrics"][metric]
            delta = 100 * value["difference"]
            for field, offset, color, label in (
                ("project_cluster_ci95", -.10, "#8EABC7", "Whole-project 95% interval"),
                ("whole_bug_ci95", .10, "#173D63", "Whole-bug 95% interval"),
            ):
                lo, hi = [100 * bound for bound in value[field]]
                ax.plot([lo, hi], [pos+offset]*2, color=color, linewidth=2,
                        label=label if pos == 0 else None)
                ax.plot(delta, pos+offset, "o", color=color, markersize=5)
            ax.text(delta, pos+.30, f"{delta:+.2f}", fontsize=9, ha="center")
        ax.axvline(0, color="#727C86", linewidth=1, linestyle=":")
        ax.set_yticks(range(3), [f"n = {n}" for n in BUDGETS])
        ax.set_ylim(-.55, 2.65)
        ax.invert_yaxis()
        ax.set_xlabel("Paired difference (percentage points)")
        ax.set_title(title, loc="left")
        ax.legend(frameon=False, fontsize=9, loc="lower left")
        ax.grid(axis="x", color="#E4E9EE", linewidth=.7)
    fig.suptitle("Shared Granite features: ranking signal, no established gating advantage\n"
                 "3 fixed seeds · 1 task · 5 heldout projects · no holdout model selection", fontsize=16)
    fig.supxlabel("Curves are fixed-seed means, not independent trials.  Intervals are descriptive and unadjusted.\n"
                  "All selected runs recommend 0/48 positive actions at p(positive) >= 0.7; n=128 is unavailable.",
                  fontsize=10, color="#344453")
    target = Path(output)
    if target.exists():
        raise ValueError("fresh plot destination required")
    fig.savefig(target, dpi=180, facecolor="white", metadata={"Software": "Hepta sealed-result plotting"})
    plt.close(fig)
    print(json.dumps({"path": str(target), "bytes": target.stat().st_size,
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plot(args.facts, args.output)
