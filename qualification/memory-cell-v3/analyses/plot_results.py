"""Render the frozen, independently audited v3 outcomes without model execution."""

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / "validation" / name).read_bytes())


def main():
    routing = read("formal-routing-audit.json")
    capacity = read("formal-capacity-audit.json")
    structure = read("formal-native-structure-audit.json")["stages"]["structure"]
    domains = ["co2", "temperature", "sunspots", "unemployment"]
    labels = ["CO2", "Temperature", "Sunspots", "Unemployment\n(held domain)"]

    def route(domain, key):
        return routing["across_seed"][domain][key]["mean"]

    exact = [
        route(d, "arms/lossless_codec_learned_semantic/exact_answer_rate")
        for d in domains
    ]
    parameters = [
        route(d, "arms/parameter_learned_semantic/exact_answer_rate") for d in domains
    ]
    ood = [route(d, "routing/semantic/unsupported_false_accept_rate") for d in domains]
    flows = ["heterogeneous", "convergent", "stable_lowrank", "random"]
    passes = [
        sum(r["strict_gate"] for r in structure["flows"] if r["flow"] == f)
        for f in flows
    ]
    storage = [
        r
        for r in capacity["compact"]["complete_storage"]
        if r["dataset_group"] in {"co2", "temperature", "sunspots", "digits-pixels"}
    ]
    storage_by_name = {r["dataset_group"]: r for r in storage}
    storage_order = ["co2", "temperature", "sunspots", "digits-pixels"]
    ratios = [
        storage_by_name[d]["minimum_audited_complete_bytes"]
        / storage_by_name[d]["strong_exact_complete_bytes"]
        for d in storage_order
    ]

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.6), constrained_layout=True)
    blue, orange, red = "#2468a0", "#e49c30", "#b74445"
    x = np.arange(4)
    a = axes[0, 0]
    a.bar(
        x - 0.18,
        100 * np.array(exact),
        0.36,
        color=blue,
        label="Model + explicit residual",
    )
    a.bar(
        x + 0.18,
        100 * np.array(parameters),
        0.36,
        color=orange,
        label="Pure parameter memory",
    )
    a.axhline(
        100,
        color="#58616b",
        linestyle="--",
        linewidth=1.3,
        label="Exact memory + oracle route",
    )
    a.set(
        xticks=x,
        xticklabels=labels,
        ylim=(0, 114),
        ylabel="Known-query exact answer (%)",
        title="A. End-to-end recall is limited by semantic routing",
    )
    for index, value in enumerate(exact):
        a.text(
            index - 0.18, value * 100 + 2, f"{value * 100:.1f}", ha="center", fontsize=9
        )
    a.legend(loc="upper left", fontsize=8)

    a = axes[0, 1]
    a.bar(
        x,
        100 * np.array(ood),
        color=[blue if v <= 0.05 else red for v in ood],
        width=0.56,
    )
    a.axhline(5, color=red, linestyle="--", label="Frozen maximum: 5%")
    a.set(
        xticks=x,
        xticklabels=labels,
        ylim=(0, 35),
        ylabel="Unsupported-query false acceptance (%)",
        title="B. Low false acceptance alone does not meet coverage",
    )
    for index, value in enumerate(ood):
        a.text(
            index,
            value * 50 if value <= 0.05 else value * 100 + 1,
            f"{value * 100:.2f}",
            ha="center",
            va="center" if value <= 0.05 else "baseline",
            color="white" if value <= 0.05 else "black",
        )
    a.legend(loc="upper left", fontsize=8)

    a = axes[1, 0]
    a.bar(x, passes, color=[blue if n else "#b5bec8" for n in passes], width=0.56)
    a.axhline(5, color="#58616b", linestyle="--", label="Required: all five seeds")
    a.set(
        xticks=x,
        xticklabels=["Heterogeneous", "Convergent", "Stable low rank", "Random"],
        ylim=(0, 5.8),
        yticks=range(6),
        ylabel="Strict quality + full-cost passes",
        title="C. Structural adaptation does not pass every stream",
    )
    for index, value in enumerate(passes):
        a.text(index, value + 0.15, f"{value}/5", ha="center")
    a.legend(loc="upper left", fontsize=8)

    a = axes[1, 1]
    a.bar(x, ratios, color=[blue if v < 1 else red for v in ratios], width=0.56)
    a.axhline(1, color="#58616b", linestyle="--", label="Best measured exact codec")
    a.set(
        xticks=x,
        xticklabels=["CO2", "Temperature", "Sunspots", "Digits pixels"],
        ylim=(0, 1.3),
        ylabel="Complete exact storage / strong exact codec",
        title="D. Include model, residual and common metadata",
    )
    for index, value in enumerate(ratios):
        a.text(index, value - 0.09, f"{value:.3f}x", ha="center", color="white")
    a.legend(loc="lower left", fontsize=8)
    fig.suptitle(
        "Hepta typed memory cells — frozen v3 qualification\nFive seeds: 307, 311, 313, 317, 331",
        fontsize=16,
    )
    output = ROOT / "analyses"
    fig.savefig(output / "formal-overview.png", dpi=180)
    fig.savefig(output / "formal-overview.svg", metadata={"Date": None})
    plt.close(fig)
    svg = output / "formal-overview.svg"
    svg.write_text(
        "\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n"
    )
    inputs = {
        name: hashlib.sha256((ROOT / "validation" / name).read_bytes()).hexdigest()
        for name in [
            "formal-routing-audit.json",
            "formal-capacity-audit.json",
            "formal-native-structure-audit.json",
        ]
    }
    data = {
        "input_audit_sha256": inputs,
        "mean_across_five_seeds": True,
        "domains": domains,
        "exact_lossless_actual_route": exact,
        "exact_pure_parameter_actual_route": parameters,
        "semantic_ood_false_accept": ood,
        "structure_flow_order": flows,
        "structure_strict_passes_out_of_five": passes,
        "complete_exact_storage": storage,
        "limits": [
            "Five-seed means are conditional on fixed template fixtures; no population reliability claim.",
            "Complete exact storage compares the best audited model-plus-residual archive to the best of 12 exact codec variants, including the same address/provenance metadata.",
            "Cold MiniLM routing and runtime footprints are reported separately; panel D is numeric storage only.",
        ],
    }
    (output / "formal-overview-data.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "files": [
                    "formal-overview.png",
                    "formal-overview.svg",
                    "formal-overview-data.json",
                ]
            }
        )
    )


if __name__ == "__main__":
    main()
