"""All seed/candidate trajectories and prespecified comparison figures."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

import numpy as np

CONFIG_DIRECTORY = tempfile.TemporaryDirectory(prefix="hcsn-study002-matplotlib-")
os.environ.setdefault("MPLCONFIGDIR", CONFIG_DIRECTORY.name)

import matplotlib  # noqa: E402 - cache location must be fixed before import.

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - select the headless backend first.
from matplotlib.lines import Line2D  # noqa: E402


COLORS = {
    "hcsn": "#174f89",
    "single": "#9366a6",
    "no_adaptation": "#ba5473",
    "ordinary": "#cf7b2e",
    "continuous_rnn": "#707070",
    "lif_snn": "#aa6688",
    "two_gates": "#609b9b",
    "cfc": "#8e83bf",
    "mamba1": "#d58929",
    "transformer": "#26876a",
}
LABELS = {
    "hcsn": "HCSN",
    "continuous_rnn": "Cont. RNN",
    "lif_snn": "LIF SNN",
    "two_gates": "Two gates",
    "cfc": "CfC",
    "mamba1": "Mamba-1",
    "transformer": "Transformer",
    "single": "Single channel",
    "no_adaptation": "No adaptation",
    "ordinary": "Ordinary event",
}
ARCHITECTURES = [
    "hcsn",
    "lif_snn",
    "continuous_rnn",
    "two_gates",
    "cfc",
    "mamba1",
    "transformer",
]
CONTROLS = ["single", "no_adaptation", "ordinary", "continuous_rnn"]


def save_figure(figure, output, name, receipts):
    for suffix in ("png", "svg"):
        path = output / f"{name}.{suffix}"
        figure.savefig(path, dpi=170, facecolor="white", bbox_inches="tight")
        receipts.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    plt.close(figure)


def curve_groups(summary, stage):
    rows = [row for row in summary["runs"] if row["spec"]["stage"] == stage]
    keys = sorted(
        {row["spec"].get("configuration", row["spec"]["task"]) for row in rows}
    )
    return [
        (
            key,
            [
                row
                for row in rows
                if row["spec"].get("configuration", row["spec"]["task"]) == key
            ],
        )
        for key in keys
    ]


def curves(summary, stage, output, receipts, cumulative):
    groups = curve_groups(summary, stage)
    columns = 3 if stage == "scaling" else 2
    rows = math.ceil(len(groups) / columns)
    figure, axes = plt.subplots(
        rows, columns, figsize=(5.1 * columns, 3.6 * rows), squeeze=False
    )
    for axis, (key, runs) in zip(axes.flat, groups):
        for run in runs:
            spec = run["spec"]
            color = COLORS[spec["architecture"]]
            if cumulative:
                offset, best, x, y = 0.0, float("inf"), [], []
                for candidate in run["candidates"]:
                    for checkpoint in candidate["history"]:
                        best = min(best, checkpoint["validation_ce"])
                        x.append(offset + checkpoint["training_cpu_seconds"])
                        y.append(best)
                    offset += candidate["training_cpu_seconds"]
                axis.plot(
                    x,
                    y,
                    color=color,
                    alpha=0.65,
                    linewidth=1.15,
                    marker="o",
                    markersize=2.6,
                )
            else:
                for candidate in run["candidates"]:
                    x = [
                        point["training_cpu_seconds"] for point in candidate["history"]
                    ]
                    y = [point["validation_ce"] for point in candidate["history"]]
                    axis.plot(
                        x,
                        y,
                        color=color,
                        linestyle="-" if candidate["index"] == 0 else "--",
                        alpha=0.52,
                        linewidth=1.0,
                        marker="o",
                        markersize=2.3,
                    )
        first = runs[0]["spec"]
        title = str(key) if stage != "scaling" else f"Config {key:02d}: {first['axis']}"
        if stage == "scaling":
            title += f"\n{first['task']}; W{first['width']} D{first['depth']} N{first['train_size']} T{first['length']}"
        axis.set_title(title, fontsize=10)
        axis.set_xlabel(
            "Cumulative training CPU, both LR searches (s)"
            if cumulative
            else "Training CPU within one LR candidate (s)",
            fontsize=8,
        )
        axis.set_ylabel(
            "Best validation CE observed" if cumulative else "Validation cross-entropy",
            fontsize=9,
        )
        axis.grid(axis="both", alpha=0.18)
        axis.tick_params(labelsize=8)
        axis.spines[["top", "right"]].set_visible(False)
    for axis in list(axes.flat)[len(groups) :]:
        axis.set_visible(False)
    architectures = list(
        dict.fromkeys(run["spec"]["architecture"] for _, runs in groups for run in runs)
    )
    handles = [
        Line2D([0], [0], color=COLORS[arch], label=LABELS[arch], linewidth=2)
        for arch in architectures
    ]
    if not cumulative:
        handles += [
            Line2D([0], [0], color="black", linestyle="-", label="LR 0.001"),
            Line2D([0], [0], color="black", linestyle="--", label="LR 0.003"),
        ]
    figure.legend(
        handles=handles,
        loc="lower center",
        ncol=min(7, len(handles)),
        frameon=False,
        fontsize=9,
    )
    title = f"{stage.title()}: " + (
        "all seed-level search trajectories"
        if cumulative
        else "every learning-rate candidate and seed"
    )
    figure.suptitle(title, fontsize=14, fontweight="bold")
    figure.text(
        0.5,
        0.065 if rows == 1 else 0.045,
        "Training CPU excludes separately reported setup, validation and serialization; both LR candidates are charged. Lines join recorded checkpoints only.",
        ha="center",
        fontsize=8,
        color="#444444",
    )
    figure.tight_layout(rect=(0, 0.105 if rows == 1 else 0.08, 1, 0.95))
    save_figure(
        figure,
        output,
        stage + ("_search_trajectories" if cumulative else "_all_candidates"),
        receipts,
    )


def representation(summary, output, receipts):
    tasks = ["mnist", "fsdd", "multimodal_select", "long_memory"]
    figure, axes = plt.subplots(2, 2, figsize=(13.5, 8.5))
    for axis, task in zip(axes.flat, tasks, strict=True):
        for index, arch in enumerate(ARCHITECTURES):
            group = summary["representation"][task][arch]
            metric = group["test_metrics"]["accuracy"]
            axis.errorbar(
                index,
                100 * metric["mean"],
                yerr=100 * metric["sd"],
                fmt="o",
                color=COLORS[arch],
                linewidth=1.5,
                capsize=4,
                markersize=6,
            )
            scores = [
                100 * row["test"]["accuracy"]
                for row in summary["runs"]
                if row["spec"]["stage"] == "representation"
                and row["spec"]["task"] == task
                and row["spec"]["architecture"] == arch
            ]
            axis.scatter(
                index + np.linspace(-0.11, 0.11, len(scores)),
                scores,
                s=18,
                facecolors="white",
                edgecolors=COLORS[arch],
                linewidths=0.9,
                zorder=3,
            )
        chance = 25 if task == "long_memory" else 10
        axis.axhline(chance, color="#888888", linestyle=":", linewidth=1)
        axis.set_xticks(
            range(len(ARCHITECTURES)),
            [LABELS[arch] for arch in ARCHITECTURES],
            rotation=24,
            ha="right",
        )
        axis.set_ylim(0, 100)
        axis.set_title(task, fontsize=11)
        axis.set_ylabel("Heldout accuracy (%)")
        axis.grid(axis="y", alpha=0.18)
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle(
        "Representation at the same two-candidate CPU allowance",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.012,
        "Filled markers: seed means; error bars: sample SD; hollow markers: every seed. Dotted lines: class-balanced chance references.",
        ha="center",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.035, 1, 0.95))
    save_figure(figure, output, "representation_all_tasks", receipts)


def mechanism(summary, output, receipts):
    tasks = sorted(summary["mechanism_contrasts"])
    figure, axes = plt.subplots(1, len(tasks), figsize=(13.5, 4.9), squeeze=False)
    for axis, task in zip(axes.flat, tasks, strict=True):
        for index, control in enumerate(CONTROLS):
            row = summary["mechanism_contrasts"][task][control]
            point = 100 * row["mean"]
            low, high = [100 * value for value in row["ci"]]
            axis.errorbar(
                point,
                index,
                xerr=[[point - low], [high - point]],
                fmt="o",
                color=COLORS[control],
                linewidth=1.7,
                capsize=5,
                markersize=6,
            )
        axis.axvline(0, color="#777777", linewidth=1)
        axis.axvline(1, color="#222222", linewidth=1, linestyle="--")
        axis.set_yticks(range(len(CONTROLS)), [LABELS[control] for control in CONTROLS])
        axis.invert_yaxis()
        axis.set_title(task)
        axis.set_xlabel("HCSN minus control (percentage points)")
        axis.grid(axis="x", alpha=0.18)
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle(
        "All eight prespecified mechanism contrasts", fontsize=15, fontweight="bold"
    )
    figure.text(
        0.5,
        0.025,
        "Five paired training seeds; 98.75% t intervals adjust four contrasts per task. Dashed +1 pp line is a practical reference, not a new pass/fail gate.",
        ha="center",
        fontsize=8.5,
    )
    figure.tight_layout(rect=(0, 0.075, 1, 0.94))
    save_figure(figure, output, "mechanism_paired_intervals", receipts)


def render(summary_path, output):
    started = time.process_time(), time.perf_counter()
    summary_path, output = Path(summary_path), Path(output)
    summary = json.loads(summary_path.read_text())
    if summary["status"] != "complete":
        raise ValueError(
            "final scientific plots require the complete planned training matrix"
        )
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "svg.hashsalt": "hcsn-study002-fixed"}
    )
    receipts = []
    for stage in ("mechanism", "representation", "scaling"):
        for cumulative in (False, True):
            curves(summary, stage, output, receipts, cumulative)
    representation(summary, output, receipts)
    mechanism(summary, output, receipts)
    result = {
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "coverage": summary["coverage"],
        "result_sha256": summary["result_sha256"],
        "figures": receipts,
        "cpu_seconds": time.process_time() - started[0],
        "wall_seconds": time.perf_counter() - started[1],
        "scope": "all 430 LR candidates, all 215 searches and every recorded validation checkpoint; no seed/configuration selected by score",
    }
    (output / "FIGURE_MANIFEST.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary", default=str(Path(__file__).parent / "COMPARISON_SUMMARY.json")
    )
    parser.add_argument("--output", default=str(Path(__file__).parent / "figures"))
    args = parser.parse_args()
    print(json.dumps({"figures": len(render(args.summary, args.output)["figures"])}))
