"""Render registered contrasts and all confirmation parameter endpoints."""

from pathlib import Path
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/hepta-adaptive-v2-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    root = Path(__file__).resolve().parents[4]
    source = (
        root.parent / "deliverables/hepta-adaptive-v2-batch001-preserved/scientific001"
    )
    destination = Path(__file__).resolve().parent / "figures"
    destination.mkdir(exist_ok=True)
    statistics = json.loads((source / "statistics/STATISTICS.json").read_text())
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "savefig.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(
        1, 2, figsize=(13, 5.3), gridspec_kw={"width_ratios": [1, 1.2]}
    )
    contrast_names = [
        "Joint meta vs fixed theta\n(same live credit)",
        "Live vs frozen credit\n(same joint-meta SNN)",
    ]
    ax = axes[0]
    for i, item in enumerate(statistics["primary_contrasts"]):
        value = item["mean_difference"]
        ax.errorbar(
            value,
            1 - i,
            xerr=[[value - item["lower"]], [item["upper"] - value]],
            fmt="o",
            color="#1e5671",
            capsize=6,
            linewidth=2,
        )
        ax.text(
            value,
            1 - i + 0.13,
            f"{value:+.5f}  [{item['lower']:+.5f}, {item['upper']:+.5f}]",
            ha="center",
            fontsize=9,
        )
    ax.axvline(0, color="#7a7a7a", linewidth=1)
    ax.axvline(
        0.005,
        color="#b45b26",
        linestyle="--",
        linewidth=1.3,
        label="Required lower bound > 0.005",
    )
    ax.set_yticks([1, 0], contrast_names)
    ax.set_ylim(-0.45, 1.55)
    ax.set_xlim(-0.09, 0.23)
    ax.set_xlabel("OOD utility difference; paired 97.5% CI")
    ax.set_title(
        "A. Neither primary superiority criterion passed",
        loc="left",
        fontsize=11,
        pad=15,
    )
    ax.grid(axis="x", alpha=0.15)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    variants = [
        "fixed_off",
        "fixed_frozen",
        "fixed_live",
        "meta_off",
        "meta_frozen",
        "meta_live",
        "standard_live",
        "raw_dp_live",
        "raw_myopic_live",
    ]
    labels = [
        "Fixed / off",
        "Fixed / frozen",
        "Fixed / live",
        "Meta / off",
        "Meta / frozen",
        "Meta / live",
        "Logistic SG / live",
        "Raw-belief DP",
        "Raw-belief myopic",
    ]
    ax = axes[1]
    for split, offset, color, label in [
        ("id_test", -0.16, "#267d9b", "ID"),
        ("ood_test", 0.16, "#d47f3b", "OOD"),
    ]:
        values = [
            next(
                row["means"]["utility"]
                for row in statistics["descriptive_summaries"]
                if row["split"] == split and row["variant"] == variant
            )
            for variant in variants
        ]
        ax.barh(
            np.arange(len(variants)) + offset, values, 0.28, color=color, label=label
        )
    ax.set_yticks(np.arange(len(variants)), labels)
    ax.invert_yaxis()
    ax.set_xlabel("Mean task utility per episode")
    ax.set_xlim(0, 0.62)
    ax.set_title(
        "B. All registered policies (descriptive)", loc="left", fontsize=11, pad=15
    )
    ax.legend(frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.15)
    fig.suptitle(
        "Adaptive SNN owner: frozen confirmation batch",
        fontsize=15,
        y=1.01,
        fontweight="bold",
    )
    fig.text(
        0.5,
        -0.015,
        "10 independent confirmation seeds; 16 episodes per seed, domain and policy. Error bars are seed-level, not episode-level.\nTask utility = observed reward − base observation cost. Resource work is not measured energy.",
        ha="center",
        fontsize=9,
        color="#505050",
    )
    fig.tight_layout(w_pad=3, rect=(0, 0.06, 1, 1))
    fig.savefig(destination / "registered_results.png", dpi=180, bbox_inches="tight")
    fig.savefig(destination / "registered_results.svg", bbox_inches="tight")
    plt.close(fig)
    training = [
        json.loads(path.read_text())
        for path in (source / "learning/confirmation").rglob("TRAINING.json")
    ]
    meta = sorted(
        (row for row in training if row["arm"] == "meta_theta"),
        key=lambda row: row["seed"],
    )
    fig, axes = plt.subplots(1, 3, figsize=(12.3, 3.7))
    for ax, parameter, title in zip(
        axes,
        ("mu", "sigma", "lambda"),
        (r"Drift $\mu$", r"Noise $\sigma$", r"SG cancellation $\lambda$"),
    ):
        values = [row["final_theta"][parameter] for row in meta]
        initial = meta[0]["initial_theta"][parameter]
        ax.axhline(
            initial,
            color="#888888",
            linestyle="--",
            linewidth=1.2,
            label=f"Initial: {initial:g}",
        )
        ax.vlines(np.arange(len(meta)), initial, values, color="#92bac9", linewidth=2)
        ax.scatter(np.arange(len(meta)), values, s=30, color="#185876", zorder=3)
        ax.set_xticks(
            np.arange(len(meta)), [str(row["seed"]) for row in meta], rotation=45
        )
        ax.set_title(title, loc="left")
        ax.set_xlabel("Confirmation seed")
        ax.grid(axis="y", alpha=0.15)
        ax.legend(frameon=False, fontsize=9)
    fig.suptitle(
        "All three parameters changed in every joint-meta confirmation fit",
        fontsize=14,
        y=1.02,
        fontweight="bold",
    )
    fig.text(
        0.5,
        -0.025,
        "Final checkpoint after exactly 128 updates; no checkpoint or seed selection. These are SG parameters, distinct from the resource price.",
        ha="center",
        fontsize=9,
        color="#505050",
    )
    fig.tight_layout(w_pad=2)
    fig.savefig(destination / "joint_parameters.png", dpi=180, bbox_inches="tight")
    fig.savefig(destination / "joint_parameters.svg", bbox_inches="tight")
    plt.close(fig)
    print(
        json.dumps(
            {
                "figures": [str(path) for path in sorted(destination.iterdir())],
                "source_statistics_sha256": __import__("hashlib")
                .sha256((source / "statistics/STATISTICS.json").read_bytes())
                .hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
