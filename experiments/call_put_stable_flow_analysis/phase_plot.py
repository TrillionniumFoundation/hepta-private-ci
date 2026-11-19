"""Render the retained, untrained phase diagnostic from its raw arrays."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with np.load(args.input / "raw_arrays.npz", allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    times = arrays["times"]
    qstar = -np.log(0.5)
    colors = {"restoring": "#276581", "regenerative_recovery": "#bf5239"}
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), constrained_layout=True)
    for name, label in (
        ("restoring", "Restoring (gain 1.5)"),
        ("regenerative_recovery", "Regenerative + recovery (gain 3.0)"),
    ):
        ref = arrays[name + "_reference_qz"]
        axes[0, 0].plot(
            times, qstar - ref[:, 0], color=colors[name], label=label, lw=1.6
        )
    axes[0, 0].set(
        xlabel="Time",
        ylabel="Safety margin x",
        title="A  Different regimes in the same continuous flow",
    )
    axes[0, 0].axhline(0, color="#8c8f95", lw=0.7, ls="--")
    axes[0, 0].legend(frameon=False, fontsize=9, loc="upper right")
    tail = times >= 90
    ref = arrays["regenerative_recovery_reference_qz"]
    axes[0, 1].plot(
        qstar - ref[tail, 0],
        ref[tail, 1] - 1.5,
        color=colors["regenerative_recovery"],
        lw=1.8,
    )
    axes[0, 1].scatter(
        [0], [0], color="#333333", s=25, zorder=3, label="Unstable reference point"
    )
    axes[0, 1].set(
        xlabel="Safety margin x",
        ylabel="Recovery displacement z - z*",
        title="B  Late trajectory in phase space",
    )
    axes[0, 1].legend(frameon=False, fontsize=9)
    for step, color in ((0.0625, "#bf5239"), (0.03125, "#276581")):
        obs = arrays[f"regenerative_recovery_h{step}_qz"]
        err = np.max(np.abs(obs - ref) / (1 + np.abs(ref)), axis=1)
        axes[1, 0].plot(
            times, err, color=color, lw=1.1, label=f"h = 1/{round(1 / step)}"
        )
    axes[1, 0].axhline(
        0.005, color="#333333", ls="--", lw=1, label="Declared diagnostic tolerance"
    )
    axes[1, 0].set(
        xlabel="Time",
        ylabel="Scaled state error vs. DOP853",
        title="C  Long-horizon phase error accumulates",
    )
    axes[1, 0].legend(frameon=False, fontsize=9)
    x = np.linspace(-2.5, 2.5, 1001)
    a = np.where(x > 0, 1 - 1 / np.cosh(x), 0)
    p = np.where(
        x > 0, 0.5 * np.exp(-np.maximum(x, 0)), 1 - 0.5 * np.exp(np.minimum(x, 0))
    )
    axes[1, 1].plot(x, a, color="#276581", label="Call C / (K + C)", lw=1.8)
    axes[1, 1].plot(x, p, color="#bf5239", label="Put P / K", lw=1.8)
    axes[1, 1].axvline(0, color="#8c8f95", lw=0.7, ls="--")
    axes[1, 1].set(
        xlabel="Safety margin x",
        ylabel="Normalized operator",
        title="D  Shared C1 boundary at x = 0; kappa = 1",
        ylim=(-0.03, 1.03),
    )
    axes[1, 1].legend(frameon=False, fontsize=9)
    fig.suptitle(
        "Untrained mechanism diagnostic — no task-performance or energy claim",
        fontsize=14,
        weight="bold",
    )
    outputs = []
    for suffix in ("png", "svg", "pdf"):
        path = args.output / ("hepta_phase_dynamics." + suffix)
        fig.savefig(path, dpi=180)
        outputs.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    plt.close(fig)
    receipt = {
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "raw_arrays_sha256": hashlib.sha256(
            (args.input / "raw_arrays.npz").read_bytes()
        ).hexdigest(),
        "outputs": outputs,
        "interpretation": "Selected untrained parameters; continuous oscillations and actual numerical failures retained",
    }
    (args.output / "figure_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
