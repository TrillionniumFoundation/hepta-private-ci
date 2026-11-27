"""Recreate descriptive summaries and the registered-primary figure from evidence."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    root = args.evidence
    evaluation = json.loads((root / "evaluation.json").read_text())
    math = json.loads((root / "math-analysis.json").read_text())
    summaries = []
    for control in math["fixed_seed_means"]:
        head, mask, policy = (control[key] for key in ("head", "mask", "policy"))
        rows = [row for row in evaluation["records"]
                if (row["head"], row["mask"], row["policy"]) == (head, mask, policy)]
        assert len(rows) == 9 and all(row["status"] == "completed" for row in rows)
        task = {role: {metric: mean(row[metric] for row in rows if row["role"] == role)
                      for metric in ("nll", "accuracy", "balanced_accuracy", "brier")}
                for role in ("old_test", "future_may", "future_june")}
        future = {metric: mean(task[role][metric] for role in ("future_may", "future_june"))
                  for metric in task["old_test"]}
        summaries.append({"head": head, "mask": mask, "policy": policy,
                          "fixed_seeds": [7, 17, 29], "task": task,
                          "future_equal_month": future, "control": control})
    payload = {"schema": "hepta.cell-retention-descriptive-results.v2",
               "scope": "Descriptive fixed-seed means; primary intervals are in evaluation.json.",
               "evaluation_sha256": hashlib.sha256((root / "evaluation.json").read_bytes()).hexdigest(),
               "all_heads_primary_criteria_met": evaluation["all_heads_primary_criteria_met"],
               "decisions": evaluation["decisions"], "summaries": summaries}
    (root / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.spines.left": False, "axes.labelcolor": "#374151",
                         "text.color": "#172033", "xtick.color": "#475569"})
    fig, axes = plt.subplots(2, 2, figsize=(13.8, 8.4))
    fig.subplots_adjust(left=0.095, right=0.975, top=0.80, bottom=0.17,
                        wspace=0.28, hspace=0.78)
    panels = [("future_equal_month_nll", "zero", "A  Future task vs zero", 1000, "NLL difference (millinats)"),
              ("future_equal_month_nll", "myopic", "B  Future task vs myopic", 1000, "NLL difference (millinats)"),
              ("old_test", "zero", "C  Retention vs zero", 1000, "NLL difference (millinats)"),
              ("old_test", "warmup", "D  Retention vs warmup", 1, "NLL difference (nats)")]
    for ax, (endpoint, comparator, title, scale, unit) in zip(axes.flat, panels):
        ax.axvline(0, color="#64748b", lw=1.1, linestyle="--", zorder=1)
        bounds = []
        for y, head in [(1, "linear"), (0, "gated")]:
            row = next(r for r in evaluation["primary_contrasts"]
                       if (r["head"], r["endpoint"], r["right"]) == (head, endpoint, comparator))
            val = scale * row["difference_left_minus_right"]
            lo, hi = [scale * v for v in row["bonferroni_percentile_interval"]]
            bounds.extend([lo, hi, 0])
            passed = row["criterion_met"]
            color = "#087f68" if passed else "#596579"
            ax.errorbar(val, y, xerr=[[val-lo], [hi-val]], fmt="o", ms=7,
                        color=color, ecolor=color, capsize=4, lw=2, zorder=3)
            label = f"{val:+.3f}  [{lo:+.3f}, {hi:+.3f}]"
            ax.text(0.98, y + 0.30, label, transform=ax.get_yaxis_transform(),
                    ha="right", va="bottom", fontsize=10, color=color)
        extent = max(bounds)-min(bounds)
        ax.set_xlim(min(bounds)-extent*0.10, max(bounds)+extent*0.10)
        ax.set_ylim(-0.45, 1.80)
        ax.set_yticks([1, 0], ["Linear", "Gated"])
        ax.tick_params(axis="y", length=0, pad=12)
        ax.grid(axis="x", color="#e8edf1", lw=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel(unit, labelpad=8)
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=12)
    fig.text(0.06, 0.94, "Future gains vs zero; no full success on either Head", fontsize=21, weight="bold")
    fig.text(0.06, 0.892, "Registered primary outcomes | All-mask Loss2 minus comparator | 72 completed conditions", fontsize=12, color="#475569")
    fig.text(0.06, 0.09, "Negative values favor Loss2. Green marks a passed criterion; gray marks a criterion not met.", fontsize=10.5)
    fig.text(0.06, 0.055, "Intervals: approximate source bootstrap with 8-comparison Bonferroni adjustment; 10,000 draws; fitted seeds 7, 17, 29 fixed.", fontsize=10.5, color="#475569")
    fig.savefig(root / "primary-results.png", dpi=170, facecolor="white")
    plt.close(fig)
    print(json.dumps({"summaries": len(summaries), "primary_contrasts": len(evaluation["primary_contrasts"]),
                      "all_heads_primary_criteria_met": evaluation["all_heads_primary_criteria_met"]}))


if __name__ == "__main__":
    main()
