"""Render saved confirmation summaries; no training or new statistical tests."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform

os.environ.setdefault("MPLCONFIGDIR", "/tmp/hepta-free-boundary-mpl")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    study = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=study / "results/learning/confirmation_summary.json",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parent
    )
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    png = output / "confirmation_results.png"
    svg = output / "confirmation_results.svg"
    receipt_path = output / "FIGURE_RECEIPT.json"
    for path in (png, svg, receipt_path):
        if path.exists():
            raise FileExistsError(f"Use a new output directory: {path}")

    result_path = args.summary.parent / "confirmation.json"
    seal_path = study / "results/SOURCE_SEAL.json"
    summary = json.loads(args.summary.read_text())
    if summary["phase"] != "confirmation":
        raise ValueError("Expected a confirmation summary")
    if sha256(result_path) != summary["results_sha256"]:
        raise ValueError("Saved confirmation result does not match the summary")
    if sha256(seal_path) != summary["source"]["seal_sha256"]:
        raise ValueError("Source-seal identity does not match the summary")
    primary = summary["registered_primary"]["primary_comparisons"]
    if [p["gradient"] for p in primary] != ["standard", "first_passage"]:
        raise ValueError("Unexpected registered contrast order")
    if any(
        p["n_independent_seeds"] != 10 or p["minimum_practical_effect"] != 0.005
        for p in primary
    ):
        raise ValueError("Unexpected registered seed count or practical threshold")

    colors = {"standard": "#235b77", "first_passage": "#c46a36"}
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.labelcolor": "#263b48",
            "text.color": "#20323f",
            "xtick.color": "#344d5c",
            "ytick.color": "#344d5c",
            "axes.edgecolor": "#a8b6bf",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "svg.hashsalt": "hepta-free-boundary-confirmation-v1",
        }
    )
    fig, (left, right) = plt.subplots(
        1, 2, figsize=(13.6, 6.2), gridspec_kw={"width_ratios": [1.25, 1.0]}
    )
    fig.patch.set_facecolor("#ffffff")
    fig.subplots_adjust(left=0.072, right=0.976, bottom=0.245, top=0.765, wspace=0.43)
    fig.suptitle(
        "Confirmation: stopping boundaries and surrogate gradients",
        x=0.072,
        y=0.970,
        ha="left",
        fontsize=19,
        fontweight="bold",
    )
    fig.text(
        0.072,
        0.907,
        "10 independent confirmation seeds  |  1,024 OOD episodes per seed  |  Synthetic evidence task",
        fontsize=11.5,
        color="#506674",
    )

    arm_order = [
        "fixed:standard",
        "fixed:first_passage",
        "direct:standard",
        "direct:first_passage",
        "free:standard",
        "free:first_passage",
    ]
    xs = [0.0, 0.70, 1.75, 2.45, 3.50, 4.20]
    means = summary["arm_means"]["ood_test"]
    labels = []
    for x, arm in zip(xs, arm_order):
        boundary, gradient = arm.split(":")
        mean = means[arm]["mean_utility"]
        left.scatter(
            x,
            mean,
            s=82,
            marker="o" if gradient == "standard" else "D",
            color=colors[gradient],
            edgecolor="white",
            linewidth=0.8,
            zorder=4,
        )
        left.annotate(
            f"{mean:.4f}",
            (x, mean),
            xytext=(0, 11),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10.3,
            color=colors[gradient],
        )
        labels.append(
            boundary.title()
            + "\n"
            + ("standard" if gradient == "standard" else "first\npassage")
        )
    dp = summary["same_information_model_informed_references"]["ood_test"][
        "raw_belief_dp"
    ]["mean_utility"]
    left.axhline(dp, color="#597368", linestyle=(0, (5, 3)), linewidth=1.5, zorder=2)
    left.text(
        4.54,
        dp + 0.006,
        f"Same-information raw-belief DP  {dp:.4f}",
        ha="right",
        va="bottom",
        fontsize=10.2,
        color="#3c5d4b",
    )
    left.set_title(
        "A   Six-arm OOD utility", loc="left", pad=17, fontsize=14, fontweight="bold"
    )
    left.set_ylabel("Mean net utility per episode", labelpad=10)
    left.set_xticks(xs, labels, fontsize=9.8)
    left.set_xlim(-0.45, 4.65)
    left.set_ylim(0.15, 0.318)
    left.set_yticks([0.15, 0.20, 0.25, 0.30])
    left.grid(axis="y", color="#e4eaee", linewidth=0.8, zorder=0)
    left.tick_params(axis="x", length=0, pad=10)

    threshold = primary[0]["minimum_practical_effect"]
    right.axvline(0, color="#cbd3d8", linewidth=1.0)
    right.axvline(threshold, color="#7a6675", linestyle=(0, (3, 3)), linewidth=1.5)
    right.text(
        0.010, 1.50, "Minimum practical effect = 0.005", fontsize=10.1, color="#6a5866"
    )
    for y, item in zip([1.0, 0.0], primary):
        mean = item["mean_difference"]
        low, high = item["family_adjusted_97_5_ci"]
        color = colors[item["gradient"]]
        right.errorbar(
            mean,
            y,
            xerr=[[mean - low], [high - mean]],
            fmt="o" if item["gradient"] == "standard" else "D",
            markersize=8.4,
            color=color,
            ecolor=color,
            capsize=5,
            elinewidth=2.1,
            capthick=1.6,
            zorder=3,
        )
        right.text(
            mean,
            y - 0.235,
            f"{mean:+.5f}  [{low:+.5f}, {high:+.5f}]",
            ha="center",
            va="top",
            fontsize=9.7,
            color=color,
        )
    right.set_title(
        "B   Registered free − direct effects",
        loc="left",
        pad=17,
        fontsize=14,
        fontweight="bold",
    )
    right.set_xlabel("Difference in mean net utility", labelpad=10)
    right.set_yticks([1.0, 0.0], ["Standard SG", "First-passage SG"], fontsize=10.5)
    right.set_xlim(-0.003, 0.123)
    right.set_ylim(-0.65, 1.75)
    right.set_xticks(
        [0, 0.025, 0.050, 0.075, 0.100, 0.125],
        ["0", "0.025", "0.050", "0.075", "0.100", "0.125"],
    )
    right.grid(axis="x", color="#edf0f3", linewidth=0.8)
    right.tick_params(axis="y", length=0, pad=10)

    fig.text(
        0.072,
        0.112,
        "Known task dynamics inform the free boundary and raw-belief DP; surrogate drift, volatility and cancellation parameters remain fixed.",
        fontsize=10.0,
        color="#506674",
    )
    fig.text(
        0.072,
        0.065,
        "Panel A: saved seed-averaged utilities.  Panel B: registered paired effects with adjusted 97.5% intervals for two comparisons.",
        fontsize=10.0,
        color="#506674",
    )
    fig.savefig(
        png,
        dpi=180,
        facecolor="white",
        metadata={
            "Software": f"Matplotlib {matplotlib.__version__}",
            "Description": "Saved confirmation means and registered intervals; synthetic task only.",
        },
    )
    fig.savefig(
        svg,
        facecolor="white",
        metadata={
            "Date": None,
            "Creator": f"Matplotlib {matplotlib.__version__}",
            "Description": "Saved confirmation means and registered intervals; synthetic task only.",
        },
    )
    plt.close(fig)
    for path in (png, svg):
        if path.stat().st_size >= 512000:
            raise ValueError(f"Artifact exceeds registered blob size: {path}")
    inputs = {}
    for label, path in [
        ("confirmation_summary", args.summary),
        ("confirmation_results", result_path),
        ("source_seal", seal_path),
    ]:
        inputs[label] = {
            "path": str(path.relative_to(study)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    receipt = {
        "schema": "hepta.free-boundary.confirmation-figure.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": summary["source"],
        "inputs": inputs,
        "renderer": {
            "path": "results/figures/render_confirmation.py",
            "sha256": sha256(Path(__file__)),
            "science_source_seal_scope": "Renderer is an evidence artifact under results; it changes no sealed scientific source or protocol.",
        },
        "plotting_versions": {
            "matplotlib": matplotlib.__version__,
            "numpy": np.__version__,
            "python": platform.python_version(),
        },
        "outputs": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in (png, svg)
        },
        "figure_size_inches": [13.6, 6.2],
        "png_dpi": 180,
        "plotted_inputs": {
            "ood_utility": {arm: means[arm]["mean_utility"] for arm in arm_order},
            "raw_belief_dp_ood_utility": dp,
            "registered_primary": primary,
        },
        "interpretation": "All means and adjusted intervals are read from the verified saved summary. No new statistical comparison, training or data generation is performed.",
        "scope": "Synthetic known-model stopping comparison with fixed surrogate parameters; no claim of first-passage SG superiority, native trained-SNN deployment or hardware energy savings.",
    }
    with receipt_path.open("x") as output_file:
        json.dump(receipt, output_file, indent=2, sort_keys=True, allow_nan=False)
        output_file.write("\n")
    print(
        json.dumps(
            {"outputs": receipt["outputs"], "receipt": str(receipt_path)}, indent=2
        )
    )


if __name__ == "__main__":
    main()
