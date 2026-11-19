"""Render descriptive scientific figures from retained, independently read data."""

import csv
import hashlib
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
COLORS = {"flow": "#087f8c", "flow_erlang4": "#d47b27"}
NAMES = {"flow": "Exact delay, learned boundary", "flow_fixed": "Exact delay, fixed boundary",
         "flow_mass": "Mass-only negative control", "flow_no_return": "No return within episode",
         "flow_erlang4": "Erlang-4 delay", "gate": "Ordinary gate", "gru": "GRU", "cfc": "CfC",
         "snn": "Surrogate-gradient LIF", "transformer": "Small causal Transformer"}


def save(figure, name):
    figure.savefig(OUT/(name+".png"), dpi=170, facecolor="white")
    figure.savefig(OUT/(name+".svg"), metadata={"Date": None}, facecolor="white")
    plt.close(figure)


def main():
    began, cpu = time.perf_counter(), time.process_time()
    paths = [ROOT/"evidence/benchmark-review/attempt001/REVIEW.json",
             ROOT/"evidence/length-review/attempt001/state_and_cost.csv",
             ROOT/"evidence/length-review/attempt001/approximation_differences.csv"]
    data = json.loads(paths[0].read_text())
    if data["fits_reviewed"] != 30 or data["status"] != "COMPLETE_ARITHMETIC_REVIEW":
        raise ValueError("complete frozen comparison required")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "bold",
                         "svg.fonttype": "none"})
    arms, markers = list(NAMES), {101: "o", 211: "^", 307: "s"}
    fig, (ax, state) = plt.subplots(1, 2, figsize=(13.6, 7.7), gridspec_kw={"width_ratios": [1.65, 1.]})
    for i, arm in enumerate(arms):
        rows = sorted((r for r in data["rows"] if r["arm"] == arm), key=lambda r: r["seed"])
        color = "#087f8c" if arm.startswith("flow") else "#515d73"
        values = np.array([r["accuracy"]*100 for r in rows])
        ax.errorbar(values.mean(), i, xerr=values.std(ddof=1), color=color, linewidth=2.4,
                    capsize=4, fmt="|", markersize=17, zorder=2)
        for shift, row in zip((-.14, 0., .14), rows):
            ax.scatter(100*row["accuracy"], i+shift, marker=markers[row["seed"]], s=32,
                       color=color, edgecolors="white", linewidths=.45, zorder=3)
        ax.text(103, i, f"{values.mean():.2f} +/- {values.std(ddof=1):.2f}", va="center", fontsize=9)
        payload = rows[0]["state_bytes"]
        if payload is None:
            state.text(1.2, i, "Streaming state not implemented", va="center", fontsize=9, color="#616975")
        else:
            kib = payload/1024
            state.scatter(kib, i, color=color, s=44)
            state.annotate(f"{kib:,.2f}", (kib, i), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9)
    ax.set(yticks=range(10), yticklabels=[NAMES[a] for a in arms], xlim=(0, 137), ylim=(9.65, -.65),
           xlabel="Test accuracy (%)", title="A  All three seeds; mean +/- sample SD")
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.grid(axis="x", color="#e8ebef", zorder=0)
    state.set(xscale="log", xlim=(1, 1500), ylim=(9.65, -.65), yticks=[],
              xlabel="Complete logical dynamic state (KiB, log scale)", title="B  Actual state at batch 64")
    state.set_xticks([1, 10, 100, 1000], ["1", "10", "100", "1000"])
    state.grid(axis="x", color="#e8ebef", zorder=0)
    for panel in (ax, state):
        panel.axhline(4.5, color="#cbd2db", linestyle="--", linewidth=.8)
    for seed, marker in markers.items():
        ax.scatter([], [], marker=marker, color="#515d73", s=32, label=f"seed {seed}")
    ax.legend(loc="lower right", frameon=False, ncol=3, fontsize=8, bbox_to_anchor=(1., 1.02))
    fig.suptitle("PenDigits: current HCSN prototype did not show a task advantage", x=.5, y=.98, fontsize=16, fontweight="bold")
    fig.text(.03, .075, "Same 3,498 independent-writer test records for every frozen model; seed SD is not independent-dataset uncertainty.", fontsize=9)
    fig.text(.03, .05, "60 s selection window on shared CPU resources; actual late-update and full-process costs are retained. FP64; 240-286 parameters.", fontsize=9)
    fig.text(.03, .025, "State: T=10, two-layer flow with eight content channels; weights/physics/autograd excluded. Logical payload is not peak memory.", fontsize=9)
    fig.subplots_adjust(left=.225, right=.98, top=.86, bottom=.17, wspace=.23)
    save(fig, "task-comparison")

    with paths[1].open() as handle:
        costs = list(csv.DictReader(handle))
    with paths[2].open() as handle:
        differences = list(csv.DictReader(handle))
    fig, axs = plt.subplots(2, 2, figsize=(12.5, 9.3))
    for arm, label in (("flow", "Exact deterministic delay"), ("flow_erlang4", "Erlang-4 delay")):
        rows = sorted((r for r in costs if r["case"].rsplit("-T", 1)[0] == arm), key=lambda r: int(r["steps"]))
        steps = [int(r["steps"]) for r in rows]
        axs[0, 0].plot(steps, [int(r["logical_state_bytes"])/1024 for r in rows], "o-", color=COLORS[arm], label=label)
        axs[0, 1].plot(steps, [int(r["autograd_saved_payload_bytes_with_repeats"])/1024**2 for r in rows], "o-", color=COLORS[arm], label=label)
        total = [float(r["forward_including_conservation_wall_seconds"])+float(r["backward_wall_seconds"]) for r in rows]
        axs[1, 0].plot(steps, total, "o-", color=COLORS[arm], label=label)
    for observable, label, marker, color in (("logits", "Logits", "o", "#087f8c"),
                                            ("parameter_gradient", "Parameter gradient", "^", "#515d73"),
                                            ("input_gradient", "Input gradient", "s", "#d47b27")):
        rows = sorted((r for r in differences if r["observable"] == observable), key=lambda r: int(r["steps"]))
        axs[1, 1].plot([int(r["steps"]) for r in rows], [100*float(r["relative_l2"]) for r in rows], marker+"-", color=color, label=label)
    axs[0, 0].set(title="A  Complete dynamic-state payload", ylabel="KiB (log scale)", yscale="log")
    axs[0, 1].set(title="B  Autograd saved payload, with repeats", ylabel="MiB (log scale)", yscale="log")
    axs[1, 0].set(title="C  Observed forward + backward time", ylabel="Seconds (log scale)", yscale="log")
    axs[1, 1].set(title="D  Erlang-4 approximation deviation", ylabel="Relative L2 difference (%)")
    for ax in axs.ravel():
        ax.set(xticks=[10, 20, 40, 80], xlabel="Sequence steps")
        ax.grid(color="#e8ebef", zorder=0)
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle("Exact delayed flow retains growing history; Erlang-4 changes the delay law", fontsize=15, fontweight="bold", y=.98)
    fig.text(.05, .085, "One seeded synthetic prefix, B=1, dt=0.05, no optimizer. Same-weight/input support is seed + source provenance; raw values were not saved.", fontsize=8.6)
    fig.text(.05, .059, "Erlang-4 has mean delay 0.2 and variance 0.01. Deviations use the full exact-flow observable as denominator; no accuracy gate was invented.", fontsize=8.6)
    fig.text(.05, .033, "Timing includes conservation reads in forward; single timings do not establish a speedup. Saved payload with repeats is not peak allocation.", fontsize=8.6)
    fig.subplots_adjust(left=.085, right=.98, top=.90, bottom=.17, hspace=.38, wspace=.22)
    save(fig, "length-tradeoff")
    manifest = {"inputs": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir()) if p.suffix in (".png", ".svg")},
                "matplotlib": matplotlib.__version__, "numpy": np.__version__,
                "body_wall_seconds": time.perf_counter()-began, "body_cpu_seconds": time.process_time()-cpu,
                "body_excludes_imports_and_manifest_write": True,
                "new_model_calls": 0, "new_optimizer_calls": 0, "new_matrix_actions": 0}
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")


if __name__ == "__main__":
    main()
