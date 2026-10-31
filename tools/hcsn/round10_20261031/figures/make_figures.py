"""Render descriptive figures from frozen R10 evidence; no fitting or testing."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
INPUTS = {}
MODELS = ["ordinary", "matched_c1", "analytic", "cfc_matched", "cfc_same_width"]
LABELS = ["Ordinary", "Matched C1", "Analytic", "CfC: matched", "CfC: width"]
COLORS = ["#2474A6", "#54963B", "#CE5831", "#9466AC", "#737373"]


def read(relative):
    raw = (ROOT / relative).read_bytes()
    INPUTS[relative] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def save(fig, name):
    for extension in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{extension}", dpi=170, bbox_inches="tight",
                    facecolor="white", metadata={"Creator": "HCSN R10 evidence renderer"})
    plt.close(fig)


def overview():
    dynamics = read("dynamics/results/moving_v1/summary.json")
    value = read("value/evidence/main/RESULTS.json")["results"]
    av = read("av/SUMMARY.json")["means"]
    memory = read("av/memory_followup/SUMMARY.json")["tables"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10.8))
    fig.subplots_adjust(hspace=0.50, wspace=0.25, top=0.89, bottom=0.16)
    fig.suptitle("HCSN R10 | measured components, unresolved network advantage",
                 fontsize=18, fontweight="bold", y=0.97)
    fig.text(0.5, 0.925, "Frozen results; descriptive means unless an interval is explicitly shown",
             ha="center", fontsize=10, color="#555555")

    ax = axes[0, 0]
    for case, color in zip(dynamics["cases"], COLORS):
        x = [row["cells"] for row in case["resolutions"]]
        y = [row["absolute_mc_differences"]["events"] for row in case["resolutions"]]
        ax.plot(x, y, "o-", color=color, label=case["case"].replace("_", " "))
    ax.set_xscale("log", base=2)
    ax.set_xticks([24, 48, 96, 192], ["24", "48", "96", "192"])
    ax.set_xlabel("Cells (phases and time steps jointly refined)")
    ax.set_ylabel("Absolute difference in expected event count")
    ax.set_title("A  Moving-boundary reference: 40,000 paths / case", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.text(0.02, -0.23, "MC is an independent reference, not exact continuum truth.",
            transform=ax.transAxes, fontsize=9, color="#555555")

    ax = axes[0, 1]
    categories = ["Stop", "Fixed", "Ordinary", "Matched C1", "Analytic", "Oracle"]
    x = np.arange(len(categories))
    for offset, (key, color, label) in zip([-0.19, 0.19],
            [("test_id", "#2474A6", "ID"), ("test_ood", "#D78B35", "OOD")]):
        row = value[key]
        y = [row["initial_stop"], row["fixed"], row["family_utility"]["ordinary"],
             row["family_utility"]["matched_c1"], row["family_utility"]["analytic"],
             row["optimal"]]
        ax.bar(x + offset, y, 0.36, color=color, label=label)
    ax.set_xticks(x, categories, rotation=22, ha="right")
    ax.set_ylabel("Expected task utility (quality minus declared costs)")
    ax.set_ylim(0, 0.82)
    ax.set_title("B  Exact finite task: value differs from gate shape", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=2)

    ax = axes[1, 0]
    for model, label, color in zip(MODELS, LABELS, COLORS):
        rows = [next(r for r in av if r["model"] == model and r["budget"] == b)
                for b in ["fixed", "cpu"]]
        x = [r["complete_cpu_seconds"] for r in rows]
        y = [100 * r["metrics"]["full"]["accuracy"] for r in rows]
        ax.plot(x, y, color=color, alpha=0.65, linewidth=1)
        ax.scatter(x[0], y[0], color=color, marker="o", s=40)
        ax.scatter(x[1], y[1], color=color, marker="s", s=48, label=label)
    ax.set_xlabel("Complete job CPU seconds (training + evaluation + I/O)")
    ax.set_ylabel("CREMA-D full-condition accuracy (%)")
    ax.set_ylim(14, 32)
    ax.set_title("C  Real AV: two executed budgets, mean of 3 seeds", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower center")
    ax.text(0.02, -0.24, "Circle: 384 updates. Square: 12 s training CPU. Lines connect observations only.",
            transform=ax.transAxes, fontsize=8.5, color="#555555")

    ax = axes[1, 1]
    x = np.arange(len(MODELS))
    by_model = {r["model"]: r for r in memory}
    old = [100 * by_model[m]["original_delay96_same_contract"] for m in MODELS]
    new = [100 * by_model[m]["accuracy"]["delay96"] for m in MODELS]
    zero = [100 * by_model[m]["accuracy"]["delay96_target_zero"] for m in MODELS]
    ax.bar(x - 0.18, old, 0.34, color="#A0A0A0", label="Old checkpoint replay")
    ax.bar(x + 0.18, new, 0.34, color=COLORS, label="Long-delay training")
    ax.scatter(x + 0.18, zero, color="black", marker="x", s=45, label="Target removed", zorder=4)
    ax.axhline(100 / 6, color="#555555", linestyle="--", linewidth=1, label="Uniform chance")
    ax.set_xticks(x, LABELS, rotation=22, ha="right")
    ax.set_ylim(0, 25)
    ax.set_ylabel("Recall96 accuracy (%)")
    ax.set_title("D  Exploratory memory follow-up: same test contract", loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper right")
    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.15)
        ax.set_axisbelow(True)
    fig.text(0.5, 0.015,
             "No measured energy, online media decoding, Transformer comparison or full coupled HX-network advantage.",
             ha="center", fontsize=10, color="#555555")
    save(fig, "evidence_overview")


def native_costs():
    report = read("native/evidence/qualification/REPORT.json")
    policies = ["stop", "fixed", "ordinary", "matched_c1", "analytic", "oracle"]
    labels = ["Stop", "Fixed", "Ordinary", "Matched C1", "Analytic", "Oracle"]
    rows = [report["means"]["ordinary/" + p] for p in policies]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.7))
    specifications = [
        ("reads", 1, "Mean charged read attempts", "quality", 100, "Accuracy (%)"),
        ("clock", 1, "Mean task ticks (declared 50 ms / tick)", "utility", 1, "Task utility"),
        ("cpu_seconds", 1000, "Whole-run CPU milliseconds", "utility", 1, "Task utility"),
    ]
    offsets = [(5, -13), (-22, 8), (-53, -17), (5, -5), (5, 9), (5, 5)]
    for panel, (ax, (xkey, xs, xlabel, ykey, ys, ylabel)) in enumerate(zip(axes, specifications)):
        for row, label, offset in zip(rows, labels, offsets):
            color = "#CE5831" if label == "Analytic" else "#2474A6"
            xy = (xs * row[xkey], ys * row[ykey])
            ax.scatter(*xy, color=color, s=40)
            arrow = None
            if panel == 0:
                if label == "Ordinary":
                    continue
                if label == "Oracle":
                    label, offset = "Ordinary / Oracle", (10, 22)
                    arrow = {"arrowstyle": "-", "color": "#666666", "linewidth": 0.6}
                elif label == "Analytic":
                    offset = (-57, 12)
                    arrow = {"arrowstyle": "-", "color": "#666666", "linewidth": 0.6}
                elif label == "Matched C1":
                    offset = (-20, -20)
            ax.annotate(label, xy, xytext=offset, textcoords="offset points", fontsize=8,
                        arrowprops=arrow)
        ax.set(xlabel=xlabel, ylabel=ylabel)
        ax.margins(x=0.25, y=0.2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=0.15)
    axes[0].set_xlim(-0.05, 1.6)
    axes[1].set_xlim(-0.1, 4.1)
    fig.suptitle("Native preread controller | 48 paired worlds, one physical family shown", fontsize=14)
    fig.tight_layout(rect=[0, 0.10, 1, 0.93])
    fig.text(0.5, 0.025,
             "The other physical family has identical task outcomes. CPU includes process start, validation, execution and commit; excludes preparation and training.",
             ha="center", fontsize=8.5)
    save(fig, "native_quality_cost")


if __name__ == "__main__":
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
    overview()
    native_costs()
    (OUT / "INPUTS.json").write_text(json.dumps({"input_sha256": INPUTS,
        "purpose": "Descriptive rendering of frozen results; not an additional statistical test",
        "energy_measured": False}, indent=2) + "\n")
    print(json.dumps({"figures": ["evidence_overview", "native_quality_cost"], "inputs": len(INPUTS)}))
