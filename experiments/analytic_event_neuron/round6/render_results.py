"""Render the immutable summary without refitting or recomputing inference."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def render(results_path, output):
    results_path, output = Path(results_path).resolve(), Path(output).resolve()
    result = json.loads(results_path.read_text())
    if result["schema"] != "hepta.acquired-feedback.results.v6":
        raise ValueError("A frozen Round6 result is required")
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="r6_plot_cache_", dir=output.parent) as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        arms = ("event", "direct", "float", "gaussian", "probit", "analytic", "numeric", "history", "uncalibrated")
        domains = ("nominal", "drift", "student_t")
        seeds = sorted({int(re.search(r"seed_(\d+)", name).group(1))
                        for name in result["scope_identities"]})
        comparisons = ("analytic-numeric", "analytic-history")
        labels = ("Analytic minus original sparse", "Analytic minus history")
        colors = ("#007C83", "#AF5A13")
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                             "axes.spines.top": False, "axes.spines.right": False,
                             "axes.titleweight": "bold", "svg.fonttype": "none"})
        figure, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
        figure.suptitle("Round 6 | Held-out acquired-feedback study", fontsize=18, weight="bold")
        ax = axes[0, 0]
        for i, (key, label, color) in enumerate(zip(comparisons, labels, colors)):
            item = result["primary"][key]
            mean, (low, high) = item["mean_difference"], item["interval"]
            y = 1 - i
            ax.plot([low, high], [y, y], color=color, linewidth=3)
            ax.plot([low, high], [y, y], "|", color=color, markersize=12)
            ax.plot(mean, y, "o", color=color, markersize=8)
            passed = item["passes_registered_superiority"]
            ax.annotate(f"{mean:+.5f}   gate: {'PASS' if passed else 'NOT PASSED'}",
                        (mean, y), xytext=(0, 15), textcoords="offset points",
                        ha="center", fontsize=10)
        ax.axvline(0, color="#555555", linewidth=1)
        ax.axvline(.005, color="#777777", linestyle="--", linewidth=1,
                   label="Registered minimum mean gain: 0.005")
        ax.set(yticks=[1, 0], yticklabels=labels, ylim=(-.7, 1.65),
               xlabel="Paired utility difference; nominal 97.5% interval",
               title="A  Registered primary comparisons")
        ax.legend(loc="lower left", fontsize=9, frameon=False)
        ax.grid(axis="x", alpha=.18)
        ax = axes[0, 1]
        for key, label, color in zip(comparisons, labels, colors):
            values = result["primary"][key]["per_seed_mean_difference"]
            if len(values) != len(seeds):
                raise ValueError("Seed inventory differs from paired summary")
            ax.plot(range(len(seeds)), values, "o-", color=color, label=label, linewidth=1.4)
        ax.axhline(0, color="#555555", linewidth=1)
        ax.set(xticks=range(len(seeds)), xticklabels=seeds, xlabel="Independent training seed",
               ylabel="Mean paired utility difference", title="B  Primary effects by training seed")
        ax.grid(axis="y", alpha=.18)
        ax.legend(fontsize=9, frameon=False)
        for domain, color in zip(domains, ("#2E6FAD", "#C66B25", "#8054A3")):
            metrics = [result["domains"][domain][arm]["calibration"] for arm in arms]
            axes[1, 0].plot(range(len(arms)), [m["classwise_ece"] for m in metrics],
                            "o-", color=color, label=domain, linewidth=1.2, markersize=4)
            axes[1, 1].plot(range(len(arms)), [m["interval_95_coverage"] for m in metrics],
                            "o-", color=color, label=domain, linewidth=1.2, markersize=4)
        axes[1, 0].axhline(.04, color="#555555", linestyle="--", linewidth=1)
        axes[1, 0].set(ylabel="10-bin classwise ECE", title="C  First-stage calibration (gate: ECE <= 0.04)")
        axes[1, 0].set_ylim(bottom=0)
        axes[1, 1].axhspan(.92, .98, color="#CBD5DF", alpha=.35, label="Acceptance band")
        axes[1, 1].axhline(.95, color="#777777", linestyle=":", linewidth=1)
        axes[1, 1].set(ylabel="Empirical 95% interval coverage", title="D  Coverage (gate: 0.92 to 0.98)")
        for ax in axes[1]:
            ax.set_xticks(range(len(arms)), arms, rotation=40, ha="right")
            ax.grid(axis="y", alpha=.18)
            ax.legend(fontsize=9, frameon=False)
        figure.get_layout_engine().set(rect=(0, .06, 1, .94))
        figure.text(.02, .018,
            f"{result['independent_confirmation_trajectories']:,} independent trajectories; "
            f"{result['arm_executions']:,} paired arm executions; {len(seeds)} training clusters. "
            "Primary intervals: 4,000 hierarchical bootstrap draws.\n"
            "All calibration cells use the common first acquired stage; shifted domains are descriptive. "
            "This figure displays the frozen summary without refitting.", fontsize=9, color="#444444")
        for suffix in ("png", "svg"):
            figure.savefig(output / ("utility_and_calibration." + suffix), dpi=180,
                           facecolor="white", metadata={"Creator": "Hepta Round6 frozen-summary renderer"})
        plt.close(figure)
        receipt = {"schema": "hepta.round6.frozen-result-figure.v1",
                   "created_utc": datetime.now(timezone.utc).isoformat(),
                   "results_path": str(results_path), "results_sha256": sha(results_path),
                   "renderer_sha256": sha(__file__), "matplotlib": matplotlib.__version__,
                   "numpy": np.__version__, "training_or_statistical_inference_performed": False,
                   "source_fields": ["primary", "domains.*.*.calibration", "scope_identities"],
                   "figures": {p.name: sha(p) for p in sorted(output.iterdir())}}
        with (output / "FIGURE_SOURCE.json").open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2); stream.write("\n")
        return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.results, args.output)))
