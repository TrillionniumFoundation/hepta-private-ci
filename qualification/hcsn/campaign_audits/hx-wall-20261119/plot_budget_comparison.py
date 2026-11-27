"""Plot every retained seed from the fixed-update and filled-wall HX studies.

This reporting script is added after both frozen experiments. It imports no
model code, reruns no fits, and excludes the separately identified diagnostic.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import tarfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import LogFormatterMathtext, LogLocator, NullLocator


MODELS = ("hx_dual", "hx_dual_prepared", "matched_gate", "hx_call", "hx_risk", "gru")
TASKS = ("delayed_recall", "adding")
SEEDS = (101, 211, 307)
LABELS = ("HX dual", "HX dual\nprepared", "Matched\ngate", "Call only", "Risk only", "GRU")
COLORS = ("#186a82", "#4d9db0", "#d2932b", "#aa7796", "#50916c", "#64718c")
MARKERS = ("o", "s", "^")
OFFSETS = (-0.16, 0.0, 0.16)


def main():
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed", type=Path, default=directory.parent / "hx-small-20261119/FIXED_UPDATES.json")
    parser.add_argument("--wall", type=Path, default=directory / "WALL_BUDGET.json")
    parser.add_argument("--fixed-archive", type=Path)
    parser.add_argument("--output-prefix", type=Path, default=directory / "budget-comparison")
    args = parser.parse_args()
    fixed, wall = [json.loads(path.read_text()) for path in (args.fixed, args.wall)]
    points = []
    for row in fixed["rows"]:
        if row["final_status"] != "completed":
            raise ValueError("fixed-update input has an incomplete fit; do not silently drop it")
        points.append(dict(protocol="fixed_updates", task=row["task"], model=row["model"],
                           seed=row["seed"], test_mse=row["test_mse"],
                           actual_updates=row["training_steps_completed"], selected_step=None,
                           initial_checkpoint=False, original_status=row["original_status"],
                           bounded_recovery=row["original_status"] != "completed"))
    for row in wall["selected_runs"]:
        points.append(dict(protocol="filled_wall", task=row["task"], model=row["model"],
                           seed=row["seed"], test_mse=row["test_mse"],
                           actual_updates=row["actual_steps"], selected_step=row["selected_step"],
                           initial_checkpoint=row["selected_step"] == 0,
                           original_status="completed", bounded_recovery=False))
    expected = {(protocol, task, model, seed) for protocol in ("fixed_updates", "filled_wall")
                for task in TASKS for model in MODELS for seed in SEEDS
                if not (protocol == "fixed_updates" and model == "hx_dual_prepared")}
    identities = [(p["protocol"], p["task"], p["model"], p["seed"]) for p in points]
    if len(identities) != len(set(identities)) or set(identities) != expected:
        raise ValueError("input identities differ from the complete 30 + 36 retained-fit matrix")
    if any(not math.isfinite(p["test_mse"]) or p["test_mse"] <= 0 for p in points):
        raise ValueError("log-MSE plotting requires finite positive observations; none may be hidden")
    baselines = {task: next(p["constant_predictor_test_mse"] for p in wall["selected_runs"]
                            if p["task"] == task) for task in TASKS}
    archive_path = args.fixed_archive or args.fixed.parent / "fixed-updates-originals.tar.gz"
    verified_fixed = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.name.endswith("/RESULT.json"):
                continue
            receipt = json.load(archive.extractfile(member))
            if len(receipt.get("runs", [])) != 1:
                continue
            fit = receipt["runs"][0]
            for attempt in fit["attempts"]:
                dataset = attempt["dataset"]
                if (dataset["split_sha256"] != wall["independent_split_sha256"][fit["task"]]
                        or dataset["constant_predictor_test_mse"] != baselines[fit["task"]]):
                    raise ValueError("fixed/wall test split or actual test predictor baseline differs")
            verified_fixed.add(("fixed_updates", fit["task"], fit["model"], fit["seed"]))
    if verified_fixed != {identity for identity in expected if identity[0] == "fixed_updates"}:
        raise ValueError("baseline verification did not cover all 30 fixed-update fits")
    groups = []
    for protocol in ("fixed_updates", "filled_wall"):
        for task in TASKS:
            for model in MODELS:
                rows = [p for p in points if (p["protocol"], p["task"], p["model"]) == (protocol, task, model)]
                groups.append(dict(protocol=protocol, task=task, model=model, observations=len(rows),
                                   arithmetic_mean_mse=statistics.mean(p["test_mse"] for p in rows) if rows else None,
                                   status="observed" if rows else "not_run"))
    data = dict(schema="hepta.hx-budget-figure.v1", points=points, groups=groups,
                constant_predictor_test_mse=baselines, seeds=SEEDS,
                input_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (args.fixed, args.wall, archive_path)},
                baseline_provenance=dict(fixed_raw_reports_verified=len(verified_fixed),
                                         split_sha256=wall["independent_split_sha256"],
                                         field="attempt.dataset.constant_predictor_test_mse; actual same test split"),
                source_commits=dict(fixed=fixed["source_commit"], wall=wall["source_commit"]),
                excluded="the one post-hoc first-fit diagnostic is not one of the 36 main observations",
                uncertainty="three initialization/minibatch seeds on one independent test split per task",
                rendering="log y; every seed shown; arithmetic mean bars; no standard-deviation bars",
                matplotlib_version=matplotlib.__version__)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    data_path = args.output_prefix.with_name(args.output_prefix.name + "-data.json")
    data_path.write_text(json.dumps(data, indent=2) + "\n")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "hepta-hx-budget-comparison-v1"})
    figure, axes = plt.subplots(2, 2, figsize=(13.4, 9.6), sharey=True)
    figure.subplots_adjust(left=0.075, right=0.975, bottom=0.17, top=0.81,
                           hspace=0.48, wspace=0.14)
    figure.suptitle("HX feature cells: equal updates and equal wall time", x=0.075, y=0.965,
                   ha="left", fontsize=21, fontweight="bold", color="#173042")
    figure.text(0.075, 0.926, "Existing synthetic tasks · 3 seeds on one shared independent test split per task · eager FP32 CPU",
                ha="left", fontsize=11, color="#536474")
    handles = [Line2D([], [], color="#55616b", marker=marker, linestyle="None", markersize=6,
                      label=f"Seed {seed}") for seed, marker in zip(SEEDS, MARKERS)]
    handles += [Line2D([], [], color="#17232b", lw=2.4, label="Arithmetic mean"),
                Line2D([], [], color="#a2abb2", lw=1.1, linestyle="--", label="Training-mean predictor")]
    figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.068, 0.899),
                  frameon=False, ncol=5, handlelength=1.5, columnspacing=2.0, fontsize=10)
    lower = 10 ** math.floor(math.log10(min(p["test_mse"] for p in points)))
    upper = 1.8 * 10 ** math.ceil(math.log10(max(p["test_mse"] for p in points)))
    for row_index, protocol in enumerate(("fixed_updates", "filled_wall")):
        for column_index, task in enumerate(TASKS):
            axis = axes[row_index, column_index]
            axis.set_yscale("log")
            axis.set_ylim(lower, upper)
            axis.set_xlim(-0.55, len(MODELS) - 0.45)
            axis.yaxis.set_major_locator(LogLocator(base=10))
            axis.yaxis.set_major_formatter(LogFormatterMathtext(base=10))
            axis.yaxis.set_minor_locator(NullLocator())
            axis.grid(axis="y", which="major", color="#e5e9ed", linewidth=0.8)
            axis.set_axisbelow(True)
            axis.axhline(baselines[task], color="#a2abb2", lw=1.1, linestyle="--", zorder=1)
            for model_index, (model, color) in enumerate(zip(MODELS, COLORS)):
                rows = [p for p in points if (p["protocol"], p["task"], p["model"]) == (protocol, task, model)]
                if not rows:
                    axis.axvspan(model_index - 0.38, model_index + 0.38, color="#eef1f3", zorder=0)
                    axis.text(model_index, 0.47, "N/A\nnot run", transform=axis.get_xaxis_transform(),
                              ha="center", va="center", fontsize=10, color="#7e8b94")
                    continue
                for seed, marker, offset in zip(SEEDS, MARKERS, OFFSETS):
                    observation = next(p for p in rows if p["seed"] == seed)
                    axis.scatter(model_index + offset, observation["test_mse"], marker=marker,
                                 s=48, color=color, edgecolors="white", linewidths=0.5, zorder=4)
                    if observation["initial_checkpoint"]:
                        axis.annotate("Initial checkpoint retained\n(late validation rejected)",
                                      xy=(model_index + offset, observation["test_mse"]),
                                      xytext=(0.97, 1.16), textcoords="axes fraction", ha="right", va="top",
                                      fontsize=8.6, color="#8b3f46",
                                      arrowprops=dict(arrowstyle="->", color="#8b3f46", lw=1.0))
                average = statistics.mean(p["test_mse"] for p in rows)
                axis.plot([model_index - 0.30, model_index + 0.30], [average, average],
                          color="#17232b", linewidth=2.3, zorder=3)
            axis.set_xticks(range(len(MODELS)), LABELS, fontsize=9.5)
            axis.tick_params(axis="x", length=0, pad=8)
            axis.tick_params(axis="y", colors="#5b6770", labelsize=9)
            title_task = "Delayed recall" if task == "delayed_recall" else "Adding"
            title_budget = "160 updates" if protocol == "fixed_updates" else "20 s wall budget"
            letter = "ABCD"[row_index * 2 + column_index]
            axis.set_title(f"{letter}   {title_task} · {title_budget}", loc="left", fontsize=12,
                           fontweight="bold", color="#173042", pad=13)
            if column_index == 0:
                axis.set_ylabel("Test MSE · lower is better", fontsize=10, labelpad=8)
    footer = [
        "Every retained seed is shown; horizontal bars are arithmetic means. Shared log scale; no SD bars.",
        "Fixed updates: 30 fits after one bounded recovery. Filled wall time: all 36 original fits; the separate diagnostic repeat is excluded.",
        "Shared CPU host; feature-cell study only. No convergence, GPU or multimodal claim. Later tail-stability fix excluded.",
        "Frozen experiment source: 456c0d56bd (160 updates) / 7f86d02273a (20 seconds). Prepared equity has no fixed-update observations.",
    ]
    for index, line in enumerate(footer):
        figure.text(0.075, 0.104 - index * 0.0205, line, ha="left", fontsize=8.8, color="#536474")
    for suffix in (".png", ".svg"):
        metadata = {"Creator": "Hepta HX qualification", "Date": None} if suffix == ".svg" else None
        destination = args.output_prefix.with_suffix(suffix)
        figure.savefig(destination, dpi=200, facecolor="white", metadata=metadata)
        if suffix == ".svg":
            destination.write_text("\n".join(line.rstrip() for line in destination.read_text().splitlines()) + "\n")
    plt.close(figure)
    print(json.dumps(dict(points=len(points), fixed_points=30, wall_points=36, data=str(data_path),
                          png=str(args.output_prefix.with_suffix(".png")),
                          svg=str(args.output_prefix.with_suffix(".svg")))))


if __name__ == "__main__":
    main()
