"""Create measured content-cost heatmaps without overwriting any artifact.

Each cell is a ratio of arithmetic means across the same three training seeds.
The right panel measures a complete adapter worker; common donor training is
separate. This plot does not claim equal AV quality or measured energy savings.
"""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm
import numpy as np


TASKS = ("selective_copy", "mqar", "async_av", "av_binding")
LABELS = ("Selective Copy", "MQAR", "AV emotion*", "AV binding*")
STRATA = (("frozen_shared", "updates_256"), ("joint", "updates_256"),
          ("frozen_shared", "cpu_20.0"), ("joint", "cpu_20.0"))
COLUMNS = ("Frozen\n256 updates", "Joint\n256 updates", "Frozen\n20 CPU s", "Joint\n20 CPU s")
METRICS = ("single_request_p50_wall_seconds", "worker_cpu_total_sec")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def measured_mean(row, metric):
    statistic = row["statistics"][metric]
    values = np.asarray(statistic["values"], float)
    if statistic["n"] != 3 or values.shape != (3,) or not np.all(np.isfinite(values) & (values > 0)):
        raise ValueError(f"Three positive measured values required: {metric}")
    value = float(values.mean())
    if not np.isclose(value, statistic["mean"], atol=1e-12, rtol=1e-12):
        raise ValueError(f"Stored mean differs from seed measurements: {metric}")
    return value


def plot(source_directory, output):
    source_directory, output = Path(source_directory), Path(output)
    paths = {name: source_directory / name for name in ("cost_aggregates.json", "aggregates.json", "jobs.json")}
    data = {name: json.loads(path.read_text()) for name, path in paths.items()}
    rows = data["cost_aggregates.json"]
    lookup = {(r["task"], r["family"], r["mode"], r["budget"]): r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError("Duplicate cost group")
    matrices = {metric: np.empty((4, 4)) for metric in METRICS}
    records = []
    for i, task in enumerate(TASKS):
        for j, (mode, budget) in enumerate(STRATA):
            a, b = (lookup[(task, family, mode, budget)] for family in ("analytic", "two_gate"))
            if a["seeds"] != b["seeds"] or a["seeds"] != [81031, 81032, 81033]:
                raise ValueError("Unexpected or unpaired training seeds")
            record = dict(task=task, mode=mode, budget=budget, metrics={})
            for metric in (*METRICS, "standalone_pipeline_worker_cpu_seconds"):
                am, bm = measured_mean(a, metric), measured_mean(b, metric)
                ratio = am / bm
                record["metrics"][metric] = dict(analytic_mean_seconds=am, two_gate_mean_seconds=bm,
                                                   ratio_of_means=ratio)
                if metric in matrices:
                    matrices[metric][i, j] = ratio
            records.append(record)
    if any(np.any((matrix < 1) | (matrix > 8)) for matrix in matrices.values()):
        raise ValueError("Measured ratios fall outside this figure's declared [1, 8] color scale")

    donors = [r for r in data["jobs.json"] if r["task"] == "async_av" and r["family"] == "shared"]
    binding = [r for r in data["aggregates.json"] if r["task"] == "av_binding"
               and r["family"] == "analytic" and r["condition"] == "test_length32_normal"]
    if len(donors) != 3 or any(r["selected_step"] != 0 for r in donors):
        raise ValueError("AV emotion quality caption disagrees with selection records")
    if len(binding) != 4 or any(r["query_accuracy"]["values"] != [.5, .5, .5] for r in binding):
        raise ValueError("AV binding quality caption disagrees with measured accuracy")

    output.mkdir(parents=True, exist_ok=True)
    destinations = [output / f"content_costs.{ext}" for ext in ("png", "svg", "json")]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Content-cost artifacts already exist; select a new output directory")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none",
                         "svg.hashsalt": "hcsn-content-costs-v1"})
    cmap = LinearSegmentedColormap.from_list("measured_cost", ["#fff8ef", "#f4b183", "#d5603b", "#922724"])
    norm = LogNorm(vmin=1, vmax=8)
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.25), sharey=True)
    fig.subplots_adjust(left=.145, right=.98, bottom=.35, top=.79, wspace=.13)
    titles = ("A  Batch-1 inference p50", "B  Complete adapter worker CPU")
    for ax, metric, title in zip(axes, METRICS, titles, strict=True):
        matrix = matrices[metric]
        image = ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=13)
        ax.set_xticks(range(4), COLUMNS, fontsize=10)
        ax.set_yticks(range(4), LABELS, fontsize=11)
        ax.tick_params(axis="both", length=0, pad=9)
        ax.set_xticks(np.arange(-.5, 4, 1), minor=True)
        ax.set_yticks(np.arange(-.5, 4, 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=2.5)
        ax.tick_params(which="minor", length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        for i in range(4):
            for j in range(4):
                value = matrix[i, j]
                ax.text(j, i, f"{value:.2f}×", ha="center", va="center", fontsize=13,
                        fontweight="bold", color="white" if value >= 3.1 else "#42231d")
    color_ax = fig.add_axes([.425, .245, .285, .022])
    colorbar = fig.colorbar(image, cax=color_ax, orientation="horizontal", ticks=[1, 2, 4, 8])
    colorbar.ax.set_xticklabels(["1×", "2×", "4×", "8×"])
    colorbar.ax.minorticks_off()
    colorbar.ax.tick_params(length=3, labelsize=9)
    colorbar.outline.set_visible(False)
    colorbar.set_label("Analytic / two-gate cost ratio (log color scale)", fontsize=9, labelpad=4)
    fig.suptitle("Whole content-model execution: the finite-grid adapter is more costly",
                 x=.035, y=.96, ha="left", fontsize=15, fontweight="bold")
    fig.text(.035, .897, "16 protocol strata  ·  3 seeds per cell  ·  ratios above 1 favor the ordinary two-gate adapter",
             fontsize=11, color="#4c535d")
    notes = [
        "Cell = arithmetic mean of analytic measurements / arithmetic mean of two-gate measurements. Latency averages per-seed validation p50s.",
        "CPU includes the entire fresh adapter worker. Common donor training is separate; adding the same donor cost preserves the direction.",
        "20 CPU s is a training-loop budget. Timing covers prepared-feature execution on CPU; raw media decoding and energy were not measured.",
        "* AV quality is insufficient: emotion donors selected step 0; analytic binding accuracy is 50%. These are not quality-matched AV savings."]
    for y, note in zip((.155, .114, .073, .032), notes, strict=True):
        fig.text(.035, y, note, fontsize=8.9, color="#4c535d")
    for path, extension in zip(destinations[:2], ("png", "svg"), strict=True):
        with path.open("xb") as target:
            fig.savefig(target, format=extension, dpi=180, facecolor="white")
    plt.close(fig)
    provenance = dict(schema="hcsn_content_cost_figure.v1", figure_script_sha256=digest(__file__),
        inputs=[dict(path=str(path), sha256=digest(path)) for path in paths.values()],
        rows=list(TASKS), columns=[dict(mode=m, budget=b) for m, b in STRATA],
        seeds=[81031, 81032, 81033], group_count=16,
        estimator="ratio of arithmetic means across three seeds; not arithmetic mean of seed ratios",
        plotted_metrics=list(METRICS), records=records,
        scope=dict(latency="batch-1 whole-sequence validation prepared-feature request p50, then mean across seeds",
                   cpu="complete fresh adapter worker including all imports, training, selection, inference and serialization",
                   donor="common training is separate; standalone pipeline ratios retained as supplementary data",
                   budget="20 CPU seconds caps training loop, not complete worker",
                   energy_measured=False, raw_media_decode_measured=False,
                   quality="AV emotion shared donors selected step 0; all analytic AV binding ID accuracies are 0.5"),
        outputs=[dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size) for path in destinations[:2]])
    with destinations[2].open("x") as target:
        json.dump(provenance, target, indent=2, allow_nan=False)
        target.write("\n")
    print(json.dumps({"outputs": [str(p) for p in destinations],
                      "latency_ratio_range": [float(matrices[METRICS[0]].min()), float(matrices[METRICS[0]].max())],
                      "worker_cpu_ratio_range": [float(matrices[METRICS[1]].min()), float(matrices[METRICS[1]].max())]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plot(args.source_directory, args.output)
