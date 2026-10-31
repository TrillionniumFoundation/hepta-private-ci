"""Render scientific figures from the completed, independently audited studies."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


LABELS = {
    "value_jg": "HCSN J/G", "two_gates": "Two gates",
    "transformer": "Transformer", "lif_snn": "LIF SNN", "mamba1": "Mamba-1",
    "freeze_content": "Freeze content", "freeze_dynamics": "Freeze dynamics",
    "freeze_boundary": "Freeze cost / boundary path", "freeze_reset": "Freeze reset",
    "freeze_refractory": "Freeze refractory time", "fixed_jg": "Fixed boundary + J/G",
    "learned_jg": "Learned threshold + J/G", "value_margin": "Margin features",
    "value_j": "J-only features", "value_g": "G-only features",
    "value_fh": "First-event F/H", "value_ordinary": "Ordinary state features",
    "fixed_ordinary": "Fixed boundary + ordinary", "learned_ordinary": "Learned + ordinary"
}
COLORS = {"value_jg": "#b35a22", "two_gates": "#117b78", "transformer": "#3959a8",
          "lif_snn": "#82619b", "mamba1": "#56616b"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def label(arm):
    return LABELS.get(arm, arm.replace("_", " "))


def save(fig, output, name):
    fig.savefig(output / (name + ".png"), dpi=170, facecolor="white", bbox_inches="tight")
    fig.savefig(output / (name + ".svg"), facecolor="white", bbox_inches="tight")
    plt.close(fig)


def forest(ax, rows, names, minimum, title, bootstrap=False):
    for index, row in enumerate(rows):
        center = 100 * row["mean"]
        lo, hi = [100 * x for x in row["ci95"]]
        passed = row["passes"] if bootstrap else row["positive_gate"]
        color = "#117b78" if passed else "#56616b"
        ax.hlines(index, lo, hi, color=color, linewidth=1.7)
        ax.plot([lo, hi], [index, index], "|", color=color, markersize=6)
        ax.plot(center, index, "o", color=color, markersize=4.5)
        if bootstrap:
            ax.plot(100 * row["one_sided_bonferroni_lower"], index, "|",
                    color="#b35a22", markersize=10, markeredgewidth=1.8)
    ax.axvline(0, color="#202d36", linewidth=.9)
    ax.axvline(minimum, color="#b35a22", linestyle="--", linewidth=.9)
    ax.set_yticks(range(len(rows)), names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Accuracy difference (percentage points)")
    ax.set_title(title, loc="left", fontweight="bold", fontsize=11)
    ax.grid(axis="x", alpha=.16)
    ax.spines[["top", "right"]].set_visible(False)


def content_figures(data, output):
    mechanism, names = [], []
    for family, rows in data["mechanism_families"].items():
        for row in rows:
            name = ("Interaction: " + row["boundary_control"]
                    if family == "boundary_channel_interaction" else label(row["control"]))
            mechanism.append(row)
            names.append(name)
    external = data["equal_cpu_external"]
    ext_names = [f"{'Copy' if row['task'] == 'selective_copy' else 'MQAR'} / "
                 f"{'ID' if row['split'] == 'test' else '2x length'} / {label(row['control'])}"
                 for row in external]
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.9), gridspec_kw={"width_ratios": [1, 1.05]})
    forest(axes[0], mechanism, names, .5,
           f"Mechanism: {data['mechanism_positive_count']}/{len(mechanism)} positive gates")
    forest(axes[1], external, ext_names, 2,
           f"Equal training CPU: {data['external_positive_count']}/{len(external)} positive gates")
    fig.suptitle("HCSN content study | predeclared contrasts", x=.03, ha="left",
                 fontsize=16, fontweight="bold")
    fig.text(.03, .015,
             "Bars: 95% paired-seed t intervals, conditional on fixed data. Teal: all contrast gates pass. "
             "Dashed lines: predeclared effect minima.\n"
             "Holm adjustment is separate for each mechanism family and for the 12 external contrasts. "
             "Equal training CPU is not equal total worker cost.", fontsize=8, color="#56616b")
    fig.tight_layout(rect=[0, .075, 1, .92], w_pad=3)
    save(fig, output, "content_contrasts")

    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.5))
    for column, task in enumerate(("selective_copy", "mqar")):
        for row_index, stage in enumerate(("fixed", "equal_cpu")):
            ax = axes[row_index, column]
            chosen = data["selected_equal_cpu_arms"][task][0]
            arms = (("value_jg", "two_gates", "transformer", "lif_snn", "mamba1")
                    if stage == "fixed" else (chosen, "two_gates", "transformer", "lif_snn"))
            for arm in arms:
                result = next(x for x in data["summaries"]
                              if (x["stage"], x["task"], x["arm"]) == (stage, task, arm))
                x = result["mean_whole_process_cpu_seconds"]
                y = 100 * result["evaluation"]["test"]["accuracy"]["mean"]
                color = COLORS.get(arm, COLORS["value_jg"])
                ax.scatter(x, y, color=color, s=42, zorder=3)
                ax.annotate(label(arm), (x, y), xytext=(5, 5), textcoords="offset points", fontsize=8)
            ax.set_xscale("log")
            ax.set_title(("Copy" if task == "selective_copy" else "MQAR") +
                         (" | 96 updates" if stage == "fixed" else " | 60 training CPU seconds"),
                         loc="left", fontsize=11, fontweight="bold")
            ax.set_xlabel("Mean whole-worker CPU seconds (log scale)")
            ax.set_ylabel("Mean ID test accuracy (%)")
            ax.margins(x=.3, y=.3)
            ax.grid(alpha=.18)
            ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Quality and measured worker cost", x=.03, ha="left", fontsize=16, fontweight="bold")
    fig.text(.03, .014,
             "Eight paired seeds; point estimates only. Worker CPU includes imports, construction, training, "
             "validation, test, checkpoints and exit.\n"
             "Shared preparation/search, pipeline overhead and energy are separate. Equal-CPU HCSN arm was selected using development validation only.",
             fontsize=8, color="#56616b")
    fig.tight_layout(rect=[0, .06, 1, .94], h_pad=3)
    save(fig, output, "content_quality_cost")


def av_figure(data, output):
    rows = data["primary_contrasts"]
    # AV uses percentile bootstrap intervals; the reporting field is explicit.
    normalized = [{**row, "ci95": row["percentile95"]} for row in rows]
    names = [("256 updates" if row["stage"] == "fixed" else "60 training CPU s")
             + " / " + label(row["control"]) for row in rows]
    fig, ax = plt.subplots(figsize=(10.3, 5.8))
    forest(ax, normalized, names, 2,
           f"Fresh actors: {sum(row['passes'] for row in rows)}/8 positive gates", bootstrap=True)
    fig.suptitle("Audiovisual encoder study | HCSN J/G minus control", x=.03, ha="left",
                 fontsize=15, fontweight="bold")
    fig.text(.03, .015,
             "Bars: 95% crossed seed-by-actor bootstrap intervals. Orange ticks: one-sided Bonferroni lower bounds.\n"
             "Eight heldout actors and eight paired seeds; 192 clips are not 192 independent actors. "
             "Small offline feature encoders, not foundation models.", fontsize=8, color="#56616b")
    fig.tight_layout(rect=[0, .10, 1, .91])
    save(fig, output, "audiovisual_contrasts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-analysis", required=True, type=Path)
    parser.add_argument("--av-analysis", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cpu0 = time.process_time()
    content = json.loads(args.content_analysis.read_text())
    av = json.loads(args.av_analysis.read_text())
    if not (content["complete"] is True and not content["errors"] and content["valid_results"] == 444
            and av["complete"] is True and not av["errors"] and av["valid_jobs"] == 90):
        raise ValueError("Figures require complete studies; incomplete results must not be silently omitted")
    args.output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                         "axes.labelcolor": "#202d36", "text.color": "#202d36"})
    content_figures(content, args.output)
    av_figure(av, args.output)
    receipt = {
        "schema": "hcsn-scientific-figure-provenance.v1",
        "content_analysis_sha256": sha(args.content_analysis),
        "av_analysis_sha256": sha(args.av_analysis), "source_sha256": sha(__file__),
        "render_cpu_seconds": time.process_time() - cpu0,
        "files": [{"path": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
                  for p in sorted(args.output.iterdir()) if p.is_file()],
        "scope": "Visualization of verified reported quantities; not additional experiments or statistical tests."
    }
    (args.output / "PLOT_PROVENANCE.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"figures": 3, "files": len(receipt["files"])}))


if __name__ == "__main__":
    main()
