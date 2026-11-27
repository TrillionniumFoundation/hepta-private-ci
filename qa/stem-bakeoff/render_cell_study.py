"""Render descriptive learning and resource figures from sealed study receipts."""

import argparse
import json
from pathlib import Path


def render(comparison, granite, eg2, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams.update({"font.size": 10, "svg.fonttype": "none"})
    analysis = json.loads(Path(comparison).read_bytes())
    features = [json.loads(Path(path).read_bytes()) for path in (granite, eg2)]
    names = [("granite97m", "Granite 97M"), ("embeddinggemma2_740m", "EmbeddingGemma 2 (text)")]
    arms = [("prototype", "Prototype", "#0072B2"), ("linear", "Linear Head", "#777777"),
            ("gated", "Gated Head", "#D55E00")]
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3), sharey=True)
    for ax, (candidate, title) in zip(axes, names):
        for arm, label, color in arms:
            values = []
            for budget in (8, 32, 128):
                row = next(row for row in analysis["aggregate"] if row["candidate"] == candidate
                           and row["arm"] == arm and row["budget"] == budget and row["control"] == "trained")
                values.append(100 * row["metrics"]["balanced_accuracy"]["macro_mean"])
            ax.plot((0, 1, 2), values, marker="o", color=color, label=label, linewidth=2)
            offset = -8 if arm == "linear" else 7 if arm == "gated" else 0
            ax.annotate(f"{values[-1]:.2f}%", (2, values[-1]), xytext=(7, offset),
                        textcoords="offset points", va="center", fontsize=8, color=color)
        ax.axhline(50, color="#999999", linestyle=":", linewidth=1)
        ax.set(title=title, xlabel="Distinct labelled source groups per Cell", xlim=(-0.12, 2.55), ylim=(49.5, 55.6))
        ax.set_xticks((0, 1, 2), ("8", "32", "128"))
        ax.grid(axis="y", alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Macro balanced accuracy (%)")
    axes[0].legend(loc="upper left", frameon=False)
    fig.suptitle("More examples produce modest gains; gating has no demonstrated accuracy edge", fontsize=12)
    fig.text(0.5, 0.02, "32 correlated repair-shape targets; 456 heldout issues; mean of 3 training seeds.\n"
             "Descriptive curves; paired source-group confidence intervals are reported separately.",
             ha="center", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.10, 1, 0.92))
    for extension in ("svg", "png"):
        fig.savefig(root / ("learning-curves." + extension), dpi=180, facecolor="white")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9.8, 3.9))
    labels = [name[1] for name in names]
    measurements = [([r["encoding"]["wall_ns"] / 1e9 for r in features], "Shared encoding wall time (s)"),
                    ([r["load"]["loaded_model"]["resident_tensor_storage_bytes"] / 1e6 for r in features],
                     "Model tensor storage (MB)")]
    for ax, (values, title) in zip(axes, measurements):
        ax.barh(labels, values, color=("#0072B2", "#D55E00"), height=0.5)
        ax.invert_yaxis()
        ax.set(title=title, xlim=(0, max(values) * 1.23))
        for i, value in enumerate(values):
            ax.text(value + max(values) * 0.02, i, f"{value:,.1f}", va="center", fontsize=9)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.grid(axis="x", alpha=0.15)
        ax.set_axisbelow(True)
    fig.suptitle("Both encoders: 2,271 events, 142 forwards, one shared owner", fontsize=12)
    fig.text(0.5, 0.02, "CPU FP32, 4 Torch threads, batch 16, maximum 192 tokens.\n"
             "Decimal MB; tensor storage is not process RSS. Timings include feature export overhead.",
             ha="center", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.10, 1, 0.91))
    for extension in ("svg", "png"):
        fig.savefig(root / ("encoder-cost." + extension), dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("comparison", "granite", "eg2", "output"):
        parser.add_argument("--" + name, required=True)
    render(**vars(parser.parse_args()))
