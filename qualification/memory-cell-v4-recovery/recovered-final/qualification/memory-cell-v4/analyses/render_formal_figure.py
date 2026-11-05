"""Render static qualification figures from the reproducible measured summary."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def main():
    raw = (ROOT / "MEASURED_SUMMARY.json").read_bytes()
    data = json.loads(raw)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.16,
            "axes.axisbelow": True,
            "svg.hashsalt": "hepta-memory-v4-6206dfba",
        }
    )
    blue, red, orange, teal = "#356FAC", "#B83B41", "#DA9A32", "#338A75"
    fig, axes = plt.subplots(2, 3, figsize=(15.5, 9.2))
    x = np.arange(5)
    labels = [str(seed) for seed in data["seeds"]]
    language = data["domains"]["co2"]["routing"]

    ax = axes[0, 0]
    correct = np.asarray(language["known_correct_accepted_rate"]["values"]) * 100
    ax.bar(x, correct, color=blue, width=0.62)
    ax.axhline(80, color=red, linestyle="--", linewidth=1.3, label="80% required")
    for index, value in enumerate(correct):
        ax.text(index, value + 2, f"{value:.2f}%", ha="center", fontsize=8)
    ax.set(
        title="A  Correctly accepted known queries",
        ylabel="Percent of 144 known expressions",
        ylim=(0, 92),
    )
    ax.set_xticks(x, labels)
    ax.legend(loc="upper right", frameon=False)
    ax.set_xlabel("Frozen training seed; same result in all six domains")

    ax = axes[0, 1]
    ood = np.asarray(language["unsupported_false_accept_rate"]["values"]) * 100
    ax.bar(x, ood, color=[red if value > 5 else blue for value in ood], width=0.62)
    ax.axhline(5, color=red, linestyle="--", linewidth=1.3, label="5% maximum")
    for index, value in enumerate(ood):
        ax.text(index, value + 0.18, f"{value:.2f}%", ha="center", fontsize=8)
    ax.set(
        title="B  Unsupported requests accepted",
        ylabel="Percent of 72 unsupported expressions",
        ylim=(0, 7.3),
    )
    ax.set_xticks(x, labels)
    ax.legend(loc="upper right", frameon=False)
    ax.set_xlabel("Seed 401 fails both language requirements")

    ax = axes[0, 2]
    domain = data["domains"]["co2"]
    edge_gain = (
        np.minimum(
            domain["parameter_edge_gain_removed"]["values"],
            domain["parameter_edge_gain_permuted"]["values"],
        )
        * 100
    )
    ax.bar(
        x,
        edge_gain,
        color=[teal if value >= 10 else red for value in edge_gain],
        width=0.62,
    )
    ax.axhline(10, color=red, linestyle="--", linewidth=1.3, label="10 pp required")
    for index, value in enumerate(edge_gain):
        ax.text(index, value + 0.35, f"{value:.2f}", ha="center", fontsize=8)
    ax.set(
        title="C  Pure-parameter composition edge gain",
        ylabel="Minimum gain over two edge ablations (pp)",
        ylim=(0, max(18, max(edge_gain) + 4)),
    )
    ax.set_xticks(x, labels)
    ax.legend(loc="upper right", frameon=False)
    ax.set_xlabel("120 composed requests/domain; actual routing; 18/30 pass")

    ax = axes[1, 0]
    flow_names = [
        "convergent",
        "recurrent_regimes",
        "heterogeneous",
        "stable_lowrank",
        "random",
    ]
    quality, cost = [], []
    for name in flow_names:
        flow = data["structure"]["flows"][name]
        quality.append(
            float(
                np.mean(
                    np.asarray(flow["adaptive_hidden_mse"]["values"])
                    / np.asarray(flow["best_fixed_hidden_mse"]["values"])
                )
            )
        )
        cost.append(flow["natural_priced_loss_ratio"]["mean"])
    y = np.arange(len(flow_names))
    ax.scatter(quality, y - 0.12, s=38, color=blue, label="Hidden MSE ratio")
    ax.scatter(
        cost,
        y + 0.12,
        s=35,
        marker="D",
        color=orange,
        label="Natural priced-loss ratio",
    )
    ax.set_yticks(
        y, ["Convergent", "Recurrent", "Heterogeneous", "Stable low-rank", "Random"]
    )
    ax.set_xscale("log")
    ax.set_xlim(0.008, 2.1)
    ax.axvline(1, color=red, linestyle="--", linewidth=1.1)
    ax.invert_yaxis()
    ax.set(
        title="D  Adaptation on synthetic numeric flows",
        xlabel="Five-seed mean ratios; lower is better (log scale)",
    )
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.26),
        ncol=2,
        frameon=False,
        fontsize=8,
    )

    ax = axes[1, 1]
    arms = data["transfer"]["arms"]
    rank_two = next(name for name in arms if name != "full_rank")
    sizes = [
        data["transfer"]["strong_exact_event_bytes"]["mean"],
        arms[rank_two]["parameter_event_bytes"]["mean"],
        arms[rank_two]["residual_event_bytes"]["mean"],
        arms["full_rank"]["parameter_event_bytes"]["mean"],
        arms["full_rank"]["residual_event_bytes"]["mean"],
    ]
    values = np.asarray(sizes) / 1000
    ax.bar(np.arange(5), values, color=[teal, orange, orange, blue, blue], width=0.67)
    for index, value in enumerate(values):
        ax.text(index, value + 1.7, f"{value:.1f}", ha="center", fontsize=8)
    ax.set_xticks(
        np.arange(5),
        [
            "Strong\nexact",
            "Rank 2\nparams",
            "Rank 2\n+ residual",
            "Full rank\nparams",
            "Full rank\n+ residual",
        ],
    )
    ax.set(
        title="E  Event storage: actual bytes including metadata",
        ylabel="Decimal kB",
        ylim=(0, 103),
    )
    ax.set_xlabel("Rank-2 parameter text recall is 0%; full-rank is 100%")

    ax = axes[1, 2]
    names = ["co2", "temperature", "sunspots", "unemployment"]
    values = [data["numeric_rank_comparison"][name] for name in names]
    locations = np.arange(4)
    ax.bar(
        locations - 0.18,
        [
            row["rank_control"]["all_written_coordinate_exact_fraction"]["mean"] * 100
            for row in values
        ],
        width=0.34,
        color=orange,
        label="Rank 4 control",
    )
    ax.bar(
        locations + 0.18,
        [
            row["primary"]["all_written_coordinate_exact_fraction"]["mean"] * 100
            for row in values
        ],
        width=0.34,
        color=blue,
        label="Rank 12 primary",
    )
    ax.set_xticks(locations, ["CO2", "Temperature", "Sunspots", "Unemployment"])
    ax.tick_params(axis="x", labelsize=8)
    ax.set(
        title="F  Numeric capacity and distortion",
        ylabel="Exact readout of all written coordinates (%)",
        ylim=(0, 116),
    )
    ax.legend(loc="upper center", ncol=2, frameon=False, fontsize=8)
    ax.set_xlabel("Higher rank uses larger parameter artifacts")

    fig.suptitle(
        "Hepta memory cells V4 — frozen five-seed qualification",
        fontsize=17,
        fontweight="bold",
        y=0.98,
    )
    fig.text(
        0.5,
        0.943,
        "Exact oracle-routed answers: 100%  |  New-type maintenance: 5/5 pass  |  Overall blockers closed: FALSE",
        ha="center",
        fontsize=11,
    )
    fig.text(
        0.035,
        0.035,
        "Language: 216 authored expressions reused across six domains and five seeds; these are not 6,480 independent language observations.\nStructure: natural prices include actual training and retained state; static bounded regret is distinct from strict improvement.\nSource 6206dfba0a3219534dd1a0274431bf48fd23673c  |  Data: sealed formal artifacts and independent audits; no held-out tuning.",
        fontsize=8.5,
        linespacing=1.5,
    )
    fig.subplots_adjust(
        left=0.09, right=0.985, top=0.88, bottom=0.20, wspace=0.40, hspace=0.55
    )
    targets = [
        ROOT / "analyses/formal-overview.png",
        ROOT / "analyses/formal-overview.svg",
    ]
    fig.savefig(targets[0], dpi=180, facecolor="white")
    fig.savefig(targets[1], facecolor="white", metadata={"Date": None})
    plt.close(fig)
    receipt = {
        "schema": "memory-cell-v4.figure-inputs.v1",
        "measured_summary_sha256": hashlib.sha256(raw).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "figures": {
            str(path.relative_to(ROOT)): {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in targets
        },
        "model_training_or_evidence_mutation": False,
    }
    (ROOT / "analyses/figure-inputs.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
