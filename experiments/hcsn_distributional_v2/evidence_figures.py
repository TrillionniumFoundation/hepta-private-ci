"""Source-bound static research figures; no invented observations or fitted wins."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(figure, directory, name):
    figure.savefig(directory / (name + ".png"), dpi=190, bbox_inches="tight", facecolor="white")
    figure.savefig(directory / (name + ".pdf"), bbox_inches="tight", facecolor="white", metadata={"CreationDate": None, "ModDate": None})
    plt.close(figure)


def render(output, content=None):
    package = Path(__file__).resolve().parent
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = {"runtime": package / "results/runtime_review001/SUMMARY.json",
             "cost": package / "results/independent_execution_review001/SUMMARY.json"}
    runtime, cost = read(paths["runtime"]), read(paths["cost"])
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "figure.dpi": 130})
    names = ["distribution_free_dual", "distribution_conditional_dual", "distribution_free_ordinary",
             "active_mean_collapse_free_dual", "legacy_free", "two_gates", "transformer"]
    labels = ["Free boundary + dual", "Learned boundary + dual", "Free boundary + ordinary features",
              "Collapse active distribution", "Legacy mean model", "Ordinary two gates", "Transformer (PyTorch SDPA)"]
    colors = ["#bd4336", "#718293", "#718293", "#718293", "#718293", "#236ca3", "#236ca3"]
    cases = {row["model"]: row for row in runtime["cases"] if row["batch"] == 4 and row["length"] == 128}
    figure, axes = plt.subplots(1, 2, figsize=(12.8, 4.5), sharey=True)
    for axis, key, title in zip(axes, ("forward", "optimizer_step"), ("Forward inference", "Complete Adam training step")):
        for index, name in enumerate(names):
            values = np.array([row["cpu_seconds"] for row in cases[name][key]]) * 1000
            median = np.median(values)
            axis.barh(index, median, color=colors[index], alpha=.88)
            axis.errorbar(median, index, xerr=[[median-values.min()], [values.max()-median]],
                          fmt="none", color="#222222", capsize=3, lw=1)
            axis.text(max(values.max(), median) * 1.12, index, f"{median:.2f}", va="center", fontsize=9)
        axis.set_xscale("log")
        axis.set_xlim(.8, 2400)
        axis.set_title(title, loc="left", fontsize=12)
        axis.set_xlabel("CPU milliseconds / batch (log scale)")
        axis.grid(axis="x", alpha=.18)
        axis.set_axisbelow(True)
    axes[0].set_yticks(range(len(names)), labels)
    axes[0].invert_yaxis()
    figure.suptitle("Whole-model cost: the local solver optimization does not establish a speed advantage",
                    x=.02, ha="left", fontsize=14, fontweight="bold")
    figure.text(.02, -.01, "B=4, T=128; width32/depth1. Bars: median of 3 repetitions; whiskers: observed range, not a confidence interval.\nRandom-weight CPU benchmark on a shared host. Quality, energy and GPU performance are outside this comparison.", fontsize=9)
    figure.tight_layout(rect=[0, .045, 1, .91])
    save(figure, output, "whole_model_runtime")

    figure, axes = plt.subplots(1, 2, figsize=(12.5, 4.7))
    order = ["bellman_value_head", "ordinary_action_head", "tabular_bellman"]
    policy_labels = ["Learned value head", "Ordinary action head", "Direct tabular planner"]
    for offset, (scope, label, color) in enumerate((
            ("cached_counterfactual_128", "128 cached streams", "#467faf"),
            ("actual_native_16", "16 actual native streams", "#b95938"))):
        for index, name in enumerate(order):
            row = cost["paired_comparisons"][name][scope]
            lo, hi = row["nominal_percentile_interval_95"]
            axes[0].errorbar(row["mean"], index + (offset-.5)*.22,
                xerr=[[row["mean"]-lo], [hi-row["mean"]]], fmt="o", color=color,
                capsize=4, label=label if index == 0 else None)
    axes[0].axvline(0, color="#555555", lw=1)
    axes[0].set_yticks(range(len(order)), policy_labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Utility difference / three-task stream")
    axes[0].set_title("Paired reward versus the VAL-selected schedule", loc="left", fontsize=12)
    axes[0].legend(frameon=False, fontsize=9, loc="upper right")
    axes[0].grid(axis="x", alpha=.18)
    n = np.geomspace(1, 100000, 500)
    delta = cost["paired_comparisons"]["tabular_bellman"]["actual_native_16"]["mean"]
    setup = cost["costs"]["conservative_extra_setup_cpu_for_candidate"]
    runtime_delta = cost["costs"]["candidate_minus_reference_runtime_cpu_per_stream"]
    for rate, color in zip((0., .0001, .001, .01), ("#52616c", "#558f79", "#3584b0", "#bd4336")):
        net = delta - rate * (runtime_delta + setup / n)
        axes[1].plot(n, net, color=color, label=f"Price {rate:g} utility / CPU s", lw=2)
    axes[1].axhline(0, color="#555555", lw=1)
    axes[1].set_xscale("log")
    axes[1].set_xlim(1, 100000)
    axes[1].set_xlabel("Lifetime deployment streams (log scale)")
    axes[1].set_ylabel("Native planner minus schedule: net utility")
    axes[1].set_title("One-time setup can reverse a short deployment", loc="left", fontsize=12)
    axes[1].legend(frameon=False, fontsize=8, loc="lower right")
    axes[1].grid(alpha=.18)
    figure.suptitle("Task planning has a scoped positive result; the learned head does not inherit it",
                    x=.02, ha="left", fontsize=14, fontweight="bold")
    figure.text(.02, -.015, "Left: post-panel 95% percentile intervals, 19,999 paired whole-stream resamples, after averaging 3 prices. Native16 is a subset of cached128.\nRight: native point estimates and observed CPU, all measured campaign/prior/analysis setup charged to planner. No cost-uncertainty or energy claim; frozen v1 encoder.", fontsize=9)
    figure.tight_layout(rect=[0, .065, 1, .91])
    save(figure, output, "task_reward_and_cost")

    if content:
        paths["content"] = Path(content).resolve()
        data = read(paths["content"])
        if data["valid"] != data["expected"] or data["invalid"]:
            raise AssertionError("Do not render a complete-quality figure from an invalid matrix")
        tasks = ["selective_copy", "mqar", "irregular", "mnist", "fsdd", "multimodal_select"]
        task_labels = ["Selective copy", "MQAR", "Irregular time", "MNIST", "FSDD", "Modality selection"]
        matrix = np.array([[next(row["mean"] for row in data["core"] if row["task"] == task and row["model"] == name and row["split"] == "test")
                            for task in tasks] for name in names]) * 100
        figure, axis = plt.subplots(figsize=(10.5, 5.3))
        im = axis.imshow(matrix, vmin=0, vmax=100, cmap="Blues", aspect="auto")
        for row in range(len(names)):
            for col in range(len(tasks)):
                axis.text(col, row, f"{matrix[row,col]:.1f}", ha="center", va="center",
                          color="white" if matrix[row,col] > 58 else "#152c42", fontsize=11)
        axis.set_xticks(range(len(tasks)), task_labels)
        axis.set_yticks(range(len(names)), labels)
        axis.set_title("Registered content002: mean ID accuracy across three seeds (%)", loc="left", pad=14)
        figure.colorbar(im, ax=axis, fraction=.03, pad=.025, label="Accuracy (%)")
        figure.text(.02, .015, f"{data['valid']}/{data['expected']} integrity checks passed. Same training-CPU budget and ±3% backbone parameters; total worker costs differ.\nPreviously observed datasets; descriptive core panel. Small digit-based multimodal task, not a foundation-model evaluation.", fontsize=9)
        figure.tight_layout(rect=[0, .07, 1, 1])
        save(figure, output, "content_accuracy")
    manifest = dict(schema="hcsn-evidence-figures.v1", input_sha256={key: sha(value) for key, value in paths.items()},
                    source_sha256=sha(__file__), whole_self_cpu_seconds_through_render=time.process_time(),
                    outputs={path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()},
                    scope="Deterministic plots of recorded evidence; scientific scopes and uncertainty remain separate")
    (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"figures": len(manifest["outputs"]) // 2, "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--content", type=Path)
    args = parser.parse_args()
    render(args.output, args.content)
