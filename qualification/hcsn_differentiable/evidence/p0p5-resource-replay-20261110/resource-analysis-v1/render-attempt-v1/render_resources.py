"""Render the immutable descriptive resource result; no model execution."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter


NAMES = {"gru": "GRU", "cfc": "CfC", "snn_plif": "Surrogate PLIF",
         "event_time_lif": "Event-time LIF", "ssm_s4d": "S4D-Lin",
         "attention": "Causal attention", "hcsn": "HCSN (censored)"}
COLORS = ["#28689e", "#008778", "#755a9c", "#a4772b", "#60a3bd", "#3e526b", "#bd3d3a"]


def fmt(value, digits=4):
    return "Missing" if value is None else f"{value:,.{digits}f}"


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.result.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != "9a5ca0f21e3a881862eafd9e67e35793a9eaeb5a1d4dbcaebcaf6d3720e01367":
        raise ValueError("Unexpected analysis result")
    data = json.loads(raw)
    tables = data["views"]["original42_plus_separate_C1"]["tables"]
    final = tables["final"]
    arms = [r["arm"] for r in final]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "hcsn-resource-analysis-v1"})
    fig, axes = plt.subplots(1, 3, figsize=(16.4, 6.8), gridspec_kw={"width_ratios": [1.15, 1.1, 1]})
    fig.subplots_adjust(left=.055, right=.985, bottom=.26, top=.79, wspace=.5)
    fig.suptitle("HCSN real asynchronous task: quality and measured process cost", x=.055, ha="left", y=.96, fontsize=18, weight="bold")
    fig.text(.055, .904, "Development subject D · 31,952 events · CPU / FP64 · common frontend and head · 3 seeds × 2 learning rates", fontsize=11, color="#414952")
    for i, (arm, color) in enumerate(zip(arms, COLORS)):
        rows = [next(r for r in tables[str(cut)] if r["arm"] == arm) for cut in [300, 900, 1800]]
        available = [r for r in rows if r["selected_three_seed_mean"] is not None]
        axes[0].errorbar([r["budget_seconds"] for r in available],
                         [r["selected_three_seed_mean"] for r in available],
                         yerr=[r["selected_sample_standard_deviation"] for r in available],
                         color=color, marker="o", lw=1.7, capsize=3, label=NAMES[arm])
        row = final[i]
        axes[1].barh(i, row["selected_three_seed_mean"], xerr=row["selected_sample_standard_deviation"],
                     color=color, height=.64, capsize=3, hatch="///" if arm == "hcsn" else None,
                     edgecolor="#ffffff" if arm == "hcsn" else color)
        axes[1].text(.51, i, f"{row['selected_three_seed_mean']:.3f}", ha="right", va="center", fontsize=10)
        axes[2].barh(i, row["all_six_charged_wall_sum_seconds"], color=color, height=.64,
                     hatch="///" if arm == "hcsn" else None, edgecolor="#ffffff" if arm == "hcsn" else color)
        axes[2].text(row["all_six_charged_wall_sum_seconds"] * 1.13, i,
                     f"{row['all_six_charged_wall_sum_seconds']:,.0f}", va="center", fontsize=9)
    axes[0].set_xscale("log")
    axes[0].set_xticks([300, 900, 1800], labels=["300", "900", "1,800"])
    axes[0].set_xlim(245, 2150)
    axes[0].set_ylim(-.01, .49)
    axes[0].set_title("A   Best recorded quality within budget", loc="left", fontsize=11, weight="bold", pad=15)
    axes[0].set_xlabel("Per-fit active process wall ceiling (seconds)")
    axes[0].set_ylabel("D macro-F1, mean ± sample SD")
    axes[0].grid(axis="y", alpha=.16)
    axes[0].legend(loc="upper left", bbox_to_anchor=(-.02, -.22), ncol=2, frameon=False, fontsize=8.5)
    for ax in axes[1:]:
        ax.set_ylim(6.65, -.65)
        ax.set_yticks(range(7))
        ax.grid(axis="x", alpha=.15)
        ax.set_axisbelow(True)
    axes[1].set_yticklabels([NAMES[a] for a in arms], fontsize=9)
    axes[1].set_xlim(0, .53)
    axes[1].set_xlabel("Strict-best complete-epoch D macro-F1")
    axes[1].set_title("B   Terminal development outcome", loc="left", fontsize=11, weight="bold", pad=15)
    axes[2].set_yticklabels([])
    axes[2].set_xscale("log")
    axes[2].set_xlim(100, 220000)
    axes[2].set_xticks([100, 1000, 10000, 100000], labels=["100", "1,000", "10,000", "100,000"])
    axes[2].set_xlabel("All 6 candidate process-wall seconds (log scale)")
    axes[2].set_title("C   Both LRs, all seeds and C1 charged", loc="left", fontsize=11, weight="bold", pad=15)
    fig.text(.425, .185, "C1 is shown as a separate post-cap extension in the full report.\nHCSN: no completed evaluation at 300 s; all 6 terminal fits budget-exhausted.\nSelected baseline rosters: 3/3 adequate; HCSN: 0/3 adequate.\nD was used for selection. No confirmation, energy or GPU result.", fontsize=9.5, linespacing=1.55, color="#414952")
    args.output.mkdir(exist_ok=True, parents=True)
    for extension in ["png", "svg"]:
        fig.savefig(args.output / ("RESOURCE-COMPARISON." + extension), dpi=180, facecolor="white", metadata={"Date": None} if extension == "svg" else {})
    plt.close(fig)
    report = ["# Recorded training resources and development quality", "",
              "This is a post-terminal descriptive analysis of the original 42 attempts, with a separately identified view that adds seven C1 continuations. HCSN remains budget-censored; this is not a sufficiently trained seven-core benefit claim. Subject D was used for tuning. Subject E was not scored.", "",
              "The analysis binds all 49 report hashes to archived evidence, independently recomputes all 2,969 confusion matrices, and checks all 351 original C1 clock intervals. Accuracy is identical; the largest macro-F1 discrepancy is 1.11e-16. The producer performed no model execution.", "",
              "## Quality at the three originally declared resource cutoffs", "",
              "Each cell is the mean best recorded D macro-F1 over all three seeds at one common learning rate, selected among .001 and .003 at that cutoff. Explicitly timed before-training evaluations are eligible. Missing observations remain missing; no interpolation or zero filling is used. Diagnostics and startup consume the same budget.", ""]
    for key, title in [("original42_only", "Original 42 attempts only"), ("original42_plus_separate_C1", "Original 42 plus separate C1")]:
        report += ["### " + title, "", "| Core | 300 s | 900 s | 1,800 s |", "| --- | ---: | ---: | ---: |"]
        t = data["views"][key]["tables"]
        for arm in arms:
            values = [next(r for r in t[str(c)] if r["arm"] == arm)["selected_three_seed_mean"] for c in [300, 900, 1800]]
            report.append("| " + NAMES[arm] + " | " + " | ".join(fmt(v) for v in values) + " |")
        report.append("")
    report += ["HCSN has no completed evaluation for any of its six candidates by 300 s. At 900 s, the selected .003 roster includes two complete-epoch evaluations and one explicitly timed before-training evaluation. Those details remain visible in RESULT.json. All defined cells select LR .003.", "",
               "The cutoff is an at-most per-fit process-wall ceiling. Early-stopped fits consume less than the ceiling. C1 adds calendar time and is not retrospectively made part of the original 100-epoch protocol. These views do not claim matched physical energy, identical CPU grants, or simultaneous calendar completion.", "",
               "## Terminal quality, target crossing and complete candidate cost", "",
               "The table below uses the separate-C1 view. Quality is the first strict-best complete-epoch result; error bars are sample SD across three seeds, not confidence intervals. All common selected learning rates are .003.", "",
               "| Core | D macro-F1 mean ± SD | Selected adequate | Median first observed F1 ≥ .30 (s) | All 6 candidates + C1 wall (s) | Max complete-attempt RSS (GiB) |",
               "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in final:
        crossed = sum(x["crossing"] is not None for x in row["target_crossings"])
        target = fmt(row["median_first_observed_target_seconds_if_all_cross"], 3) if crossed == 3 else f"Censored ({crossed}/3 crossed)"
        report.append(f"| {NAMES[row['arm']]} | {row['selected_three_seed_mean']:.4f} ± {row['selected_sample_standard_deviation']:.4f} | {row['selected_adequate_count']}/3 | {target} | {row['all_six_charged_wall_sum_seconds']:,.3f} | {row['all_six_complete_attempt_max_RSS_bytes'] / 2**30:.3f} |")
    report += ["", "Target times use the first observed complete-epoch crossing and a uniform epoch-clock convention. They do not locate the crossing between evaluations. A median is reported only if all three selected seeds crossed. The earlier baseline table used some separate later report-clock samples; both versions and their differences are retained in RESULT.json.", "",
               "The wall-cost column charges both original LRs, every seed, failed memorization, partial interrupted work and C1. It sums overlapping processes and is not campaign calendar time. It excludes separately logged historical tuning, controller/preflight, independent audits, archiving and transfer costs; those remain separate in the evidence cost ledgers. Peak RSS is the maximum complete-attempt process RSS across all six candidates and C1. It is an upper bound for a prefix, not measured target-time memory or GPU VRAM.", "",
               "Original per-epoch CPU prefixes are measured. C1 cumulative CPU has only a lower bound because the complete original parent exit CPU was not captured. CPU is not substituted for the wall-budget axis. Energy is unmeasured.", "",
               "## Reproduction and retained scope", "",
               "[RESULT.json](RESULT.json) preserves both LR rosters, every seed, chosen evaluation, missing observation, censoring, report identities, validation and all costs used in each table. [POINTS.json](POINTS.json) preserves all 2,969 compact recorded points. [PLAN.json](../PLAN.json) was frozen after terminal scores were known and before this calculation; only the three resource cuts and target were prospective in the original campaign.", "",
               "The full original confusion matrices and clock fields are retained in the authenticated curves archive. The byte-split archive parts reconstruct the original ZIP without recompression. The independent resource review uses a separate implementation and exact rational confusion-matrix arithmetic. Whole-trajectory numerical qualification and independent scientific confirmation remain HOLD.", "",
               "![Quality and charged process cost](RESOURCE-COMPARISON.png)", ""]
    (args.output / "REPORT.md").write_text("\n".join(report))
    if args.result.read_bytes() != raw:
        raise ValueError("Rendering changed analysis input")
    files = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in args.output.iterdir() if p.name in ["REPORT.md", "RESOURCE-COMPARISON.png", "RESOURCE-COMPARISON.svg"]}
    (args.output / "RENDER-RECEIPT.json").write_text(json.dumps({"input_sha256": digest, "input_unchanged": True,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "matplotlib": matplotlib.__version__,
        "main_entry_wall_seconds": time.perf_counter() - wall, "process_CPU_sample_seconds": time.process_time() - cpu,
        "cost_scope": "Main entry through document/figure output; excludes imports and receipt write/exit.", "files": files}, indent=2) + "\n")


if __name__ == "__main__":
    main()
