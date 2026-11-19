"""Post-seal scientific figures; requires all 229 planned RESULT receipts.

Uses every planned configuration and every scheduled checkpoint. No training,
model selection, interpolation to a favorable budget, or winner assignment.
All writes are derived artifacts under the explicitly chosen output directory.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
from scipy.stats import t as student_t


LABELS = {
    "hcsn": "HCSN", "lif_snn": "LIF SNN", "continuous_rnn": "Continuous RNN",
    "two_gates": "Two gates", "cfc": "CfC", "mamba1": "Mamba-1 CPU",
    "transformer": "Transformer (SDPA)", "single": "Single channel",
    "no_adaptation": "No adaptation", "ordinary": "Ordinary dual gate",
}
TASKS = {"mnist": "MNIST", "fsdd": "FSDD", "multimodal_select": "Constructed multimodal selection",
         "long_memory": "Long-memory associations", "synthetic": "Synthetic associations"}
COLORS = {"hcsn": "#0072B2", "lif_snn": "#666666", "continuous_rnn": "#56B4E9",
          "two_gates": "#E69F00", "cfc": "#CC79A7", "mamba1": "#D55E00", "transformer": "#009E73"}
FILE_LIMIT = 500000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def require_complete(study, protocol):
    inventory = read_json(study / "RUNS.json")
    planned = inventory["runs"]
    if len(planned) != 229 or len({item["run_id"] for item in planned}) != 229:
        raise ValueError("This renderer expects exactly the 229 distinct study001 jobs")
    missing = [item["run_id"] for item in planned if not (study / item["run_id"] / "RESULT.json").is_file()]
    if missing:
        raise ValueError(f"Refusing partial figures: {len(planned) - len(missing)}/229 RESULT receipts present; "
                         f"missing {len(missing)} jobs, including {missing[:8]}")
    records, input_hashes = {}, {}
    counts = {key: 0 for key in ("mechanism", "representation", "scaling", "boundary")}
    for item in planned:
        run_id, spec = item["run_id"], item["spec"]
        path = study / run_id / "RESULT.json"
        result = read_json(path)
        actual = {"stage": "boundary", "seed": result["seed"]} if spec["stage"] == "boundary" else result["spec"]
        if actual != spec or result["source_seal"] != inventory["source_seal"]:
            raise ValueError(f"Specification/source seal mismatch: {run_id}")
        counts[spec["stage"]] += 1
        entry = {"result": result, "spec": spec}
        if spec["stage"] != "boundary":
            manifest = study / run_id / "checkpoint" / "manifest.json"
            if digest(manifest) != result["checkpoint_manifest_sha256"] or result["checkpoint_reload_max_error"] != 0:
                raise ValueError(f"Checkpoint receipt mismatch: {run_id}")
            entry["classes"] = read_json(manifest)["config"]["classes"]
        records[run_id] = entry
        input_hashes[run_id] = digest(path)
    if counts != {"mechanism": 50, "representation": 84, "scaling": 90, "boundary": 5}:
        raise ValueError(f"Unexpected stage coverage: {counts}")
    if len(protocol["scaling"]["configurations"]) != 10:
        raise ValueError("Expected all ten scaling configurations")
    return inventory, records, input_hashes


def collect_plot_data(records, protocol):
    representation, mechanism, scaling = [], [], []
    for task in protocol["representation"]["tasks"]:
        for architecture in protocol["representation"]["architectures"]:
            entries = [records[f"representation/{task}/{architecture}/seed{seed}"]
                       for seed in protocol["representation_seeds"]]
            classes = {entry["classes"] for entry in entries}
            if len(classes) != 1:
                raise ValueError("Inconsistent class count")
            values = np.array([entry["result"]["test"]["accuracy"] for entry in entries]) * 100
            representation.append({"task": task, "architecture": architecture,
                                   "seed_values_percent": values.tolist(), "mean": float(values.mean()),
                                   "sd": float(values.std(ddof=1)), "chance_percent": 100 / classes.pop()})
    for task in protocol["mechanism"]["tasks"]:
        for comparator in protocol["mechanism"]["architectures"]:
            if comparator == "hcsn":
                continue
            differences = []
            for seed in protocol["mechanism_seeds"]:
                first = records[f"mechanism/{task}/hcsn/seed{seed}"]
                second = records[f"mechanism/{task}/{comparator}/seed{seed}"]
                if first["spec"]["data_seed"] != second["spec"]["data_seed"]:
                    raise ValueError("Mechanism pairing uses different data seeds")
                if first["result"]["split_sources_sha256"] != second["result"]["split_sources_sha256"]:
                    raise ValueError("Mechanism pairing uses different source receipts")
                differences.append(100 * (first["result"]["test"]["accuracy"] - second["result"]["test"]["accuracy"]))
            values = np.array(differences)
            half = float(student_t.ppf((1 + .9875) / 2, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values)))
            mechanism.append({"task": task, "comparator": comparator, "seed_differences_pp": differences,
                              "mean": float(values.mean()), "half_interval": half,
                              "lower": float(values.mean() - half), "upper": float(values.mean() + half)})
    for index, configuration in enumerate(protocol["scaling"]["configurations"]):
        for architecture in protocol["scaling"]["architectures"]:
            curves, class_counts, updates = [], set(), None
            for seed in protocol["scaling_seeds"]:
                entry = records[f"scaling/config{index:02d}/{architecture}/seed{seed}"]
                if any(entry["spec"][key] != configuration[key] for key in ("task", "width", "depth", "length", "train_size")):
                    raise ValueError("Scaling configuration differs from protocol")
                history = entry["result"]["history"]
                expected = [entry["spec"]["updates"] // 4, entry["spec"]["updates"] // 2, entry["spec"]["updates"]]
                observed = [point["update"] for point in history]
                if observed != expected or (updates is not None and observed != updates):
                    raise ValueError("Missing or unplanned validation checkpoint")
                updates = observed
                cpu = [point["training_cpu_seconds"] for point in history]
                ce = [point["validation"]["cross_entropy"] for point in history]
                if not np.isfinite(cpu + ce).all() or min(cpu) <= 0 or np.any(np.diff(cpu) <= 0):
                    raise ValueError("Invalid CPU/validation curve")
                curves.append({"seed": seed, "cpu_seconds": cpu, "validation_ce": ce})
                class_counts.add(entry["classes"])
            if len(class_counts) != 1:
                raise ValueError("Inconsistent scaling class counts")
            scaling.append({"index": index, "configuration": configuration, "architecture": architecture,
                            "updates": updates, "chance_ce": math.log(class_counts.pop()), "seed_curves": curves,
                            "mean_cpu": np.mean([c["cpu_seconds"] for c in curves], axis=0).tolist(),
                            "mean_ce": np.mean([c["validation_ce"] for c in curves], axis=0).tolist()})
    if (len(representation), len(mechanism), len(scaling)) != (28, 8, 30):
        raise ValueError("Plot data do not cover every planned combination")
    return {"representation": representation, "mechanism": mechanism, "scaling": scaling}


def clean_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=.15, linewidth=.6)
    ax.set_axisbelow(True)


def representation_figure(plt, data, protocol):
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True, sharey=True)
    architectures = protocol["representation"]["architectures"]
    y = np.arange(len(architectures))
    left = min(0, min(item["mean"] - item["sd"] for item in data) - 1)
    right = max(100, max(item["mean"] + item["sd"] for item in data) + 1)
    for ax, task in zip(axes.flat, protocol["representation"]["tasks"], strict=True):
        rows = {item["architecture"]: item for item in data if item["task"] == task}
        chance = next(iter(rows.values()))["chance_percent"]
        ax.axvline(chance, color="#777777", linestyle="--", linewidth=1)
        for position, architecture in enumerate(architectures):
            row = rows[architecture]
            ax.scatter(row["seed_values_percent"], position + np.linspace(-.10, .10, 3),
                       s=12, color=COLORS[architecture], alpha=.35, zorder=2)
            ax.errorbar(row["mean"], position, xerr=row["sd"], fmt="o", markersize=5,
                        capsize=3, color=COLORS[architecture], linewidth=1.4, zorder=3)
        ax.set_yticks(y, [LABELS[name] for name in architectures])
        ax.set_xlim(left, right)
        ax.set_xticks(np.arange(0, 101, 20))
        ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
        ax.set_title(f"{TASKS[task]} | chance {chance:.0f}%", loc="left", fontsize=11, pad=12)
        clean_axes(ax)
    axes[0, 0].invert_yaxis()
    fig.suptitle("Representation benchmarks: all planned architectures", fontsize=17, y=.98)
    fig.text(.5, .93, "Test accuracy: mean +/- sample SD across three training seeds; faint dots show every seed", ha="center", fontsize=10)
    fig.supxlabel("Held-out test accuracy", y=.08, fontsize=11)
    fig.text(.5, .035, "Common frontend, readout and data. Equal width does not imply equal parameter count or compute.", ha="center", fontsize=9, color="#444444")
    fig.subplots_adjust(left=.19, right=.98, top=.86, bottom=.15, hspace=.42, wspace=.17)
    return fig


def mechanism_figure(plt, data, protocol):
    from matplotlib.lines import Line2D
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharex=True, sharey=True)
    controls = [name for name in protocol["mechanism"]["architectures"] if name != "hcsn"]
    lower, upper = min(0, min(row["lower"] for row in data)), max(1, max(row["upper"] for row in data))
    pad = max(.6, .07 * (upper - lower))
    for ax, task in zip(axes, protocol["mechanism"]["tasks"], strict=True):
        ax.axvline(0, color="#555555", linewidth=1)
        ax.axvline(100 * protocol["mechanism"]["minimum_practical_effect"], color="#B67622", linestyle="--", linewidth=1.2)
        rows = {item["comparator"]: item for item in data if item["task"] == task}
        for position, comparator in enumerate(controls):
            row = rows[comparator]
            ax.scatter(row["seed_differences_pp"], position + np.linspace(-.12, .12, 5), s=14,
                       color=COLORS["hcsn"], alpha=.28, zorder=2)
            ax.errorbar(row["mean"], position, xerr=row["half_interval"], fmt="o", color=COLORS["hcsn"],
                        markersize=6, linewidth=1.6, capsize=4, zorder=3)
        ax.set_yticks(range(len(controls)), [f"HCSN - {LABELS[name]}" for name in controls])
        ax.set_xlim(lower - pad, upper + pad)
        ax.set_title(TASKS[task], loc="left", fontsize=11, pad=10)
        clean_axes(ax)
    axes[0].invert_yaxis()
    fig.suptitle("Mechanism contrasts on held-out accuracy", fontsize=17, y=.98)
    fig.legend(handles=[Line2D([0], [0], color="#555555", label="Zero difference"),
                        Line2D([0], [0], color="#B67622", linestyle="--", label="+1 percentage-point reference")],
               loc="upper center", bbox_to_anchor=(.60, .925), ncol=2, frameon=False, fontsize=9)
    fig.supxlabel("HCSN - comparator accuracy (percentage points)", y=.16, fontsize=11)
    fig.text(.5, .08, "Five paired seeds; 98.75% Student-t intervals for four comparisons per task. Faint dots: all paired differences.", ha="center", fontsize=9)
    fig.text(.5, .035, "Conditional on the fixed held-out sources. Reference lines are not an automatic winner or pass/fail classification.", ha="center", fontsize=9, color="#444444")
    fig.subplots_adjust(left=.265, right=.98, top=.79, bottom=.29, wspace=.18)
    return fig


def validation_cpu_figure(plt, data, protocol):
    from matplotlib.lines import Line2D
    fig, axes = plt.subplots(2, 5, figsize=(17, 8), sharey=True)
    maximum_ce = max(value for row in data for curve in row["seed_curves"] for value in curve["validation_ce"])
    for index, ax in enumerate(axes.flat):
        rows = [row for row in data if row["index"] == index]
        config = protocol["scaling"]["configurations"][index]
        for row in rows:
            color = COLORS[row["architecture"]]
            for curve in row["seed_curves"]:
                ax.plot(curve["cpu_seconds"], curve["validation_ce"], color=color, alpha=.18, linewidth=.7)
            ax.plot(row["mean_cpu"], row["mean_ce"], "o-", color=color, linewidth=1.8, markersize=3.8, zorder=3)
        ax.axhline(rows[0]["chance_ce"], color="#999999", linestyle=":", linewidth=.9)
        ax.set_xscale("log")
        ax.set_ylim(0, max(maximum_ce * 1.05, 2.4))
        task = "Multimodal" if config["task"] == "multimodal_select" else "Long memory"
        ax.set_title(f"{index:02d} | {config['axis'].capitalize()} | {task}\nW={config['width']}, D={config['depth']}, T={config['length']}, N={config['train_size']}", fontsize=8.5, loc="left", pad=9)
        ax.tick_params(labelsize=8)
        clean_axes(ax)
    handles = [Line2D([0], [0], marker="o", color=COLORS[name], label=LABELS[name], linewidth=1.8)
               for name in protocol["scaling"]["architectures"]]
    handles.append(Line2D([0], [0], color="#999999", linestyle=":", label="Chance cross-entropy"))
    fig.suptitle("Validation quality versus measured training CPU: all ten configurations", fontsize=16, y=.98)
    fig.text(.5, .936, "Finite fixed-budget study; no scaling-law fit or extrapolation", ha="center", fontsize=11)
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .907), ncol=4, frameon=False, fontsize=9)
    fig.supxlabel("Cumulative training process CPU seconds (log scale; panel-specific ranges)", y=.095, fontsize=11)
    fig.supylabel("Validation cross-entropy (nats; lower is better)", x=.01, fontsize=11)
    fig.text(.5, .045, "Bold: seed means at the same scheduled updates (40, 80, 160). Thin: every seed. Lines connect measured checkpoints only.", ha="center", fontsize=9)
    fig.text(.5, .018, "Training CPU excludes validation and other end-to-end costs. W: width; D: depth; T: length; N: available training episodes.", ha="center", fontsize=9, color="#444444")
    fig.subplots_adjust(left=.055, right=.99, top=.82, bottom=.18, wspace=.25, hspace=.58)
    return fig


def save_figure(fig, output, stem):
    svg = output / f"{stem}.svg"
    fig.savefig(svg, format="svg", facecolor="white")
    if svg.stat().st_size >= FILE_LIMIT:
        raise ValueError(f"SVG exceeds the requested file-size target: {svg}")
    png = output / f"{stem}.png"
    for dpi in (170, 150, 130, 110):
        fig.savefig(png, dpi=dpi, facecolor="white", pil_kwargs={"optimize": True})
        if png.stat().st_size < FILE_LIMIT:
            break
    if png.stat().st_size >= FILE_LIMIT:
        raise ValueError(f"PNG exceeds the requested file-size target: {png}")
    return {"stem": stem, "png_dpi": dpi, "files": [{"name": path.name, "bytes": path.stat().st_size,
                                                       "sha256": digest(path)} for path in (png, svg)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    study = Path(args.study).resolve()
    package = study.parent.parent
    protocol = read_json(package / "PROTOCOL.json")
    try:
        inventory, records, hashes = require_complete(study, protocol)
        data = collect_plot_data(records, protocol)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"{error}\nNo figures were generated.\n")
    # Import the renderer only after the complete-data gate has succeeded.
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "hcsn_figure_cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none",
                         "axes.edgecolor": "#777777", "axes.labelcolor": "#222222",
                         "xtick.color": "#333333", "ytick.color": "#333333"})
    output = Path(args.output_dir).resolve() if args.output_dir else study / "analysis" / "figures"
    output.mkdir(parents=True, exist_ok=True)
    receipts = []
    for key, builder, stem in (("representation", representation_figure, "representation_all_tasks"),
                               ("mechanism", mechanism_figure, "mechanism_paired_intervals"),
                               ("scaling", validation_cpu_figure, "validation_cpu_all_configs")):
        fig = builder(plt, data[key], protocol)
        receipts.append(save_figure(fig, output, stem))
        plt.close(fig)
    manifest = {"planned_and_present_jobs": 229, "source_seal": inventory["source_seal"],
                "script_sha256": digest(__file__), "runs_sha256": digest(study / "RUNS.json"),
                "protocol_sha256": digest(package / "PROTOCOL.json"), "result_hashes": hashes,
                "figures": receipts, "plot_data": data,
                "selection": "Every planned representation, mechanism and scaling configuration; every scheduled validation checkpoint; no winner selection."}
    (output / "FIGURE_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "figures": receipts}, indent=2))


if __name__ == "__main__":
    main()
