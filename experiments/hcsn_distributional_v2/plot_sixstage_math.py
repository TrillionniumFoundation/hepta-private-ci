"""Plot only recorded numerical audit evidence, with a complete source manifest."""

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    package = Path(__file__).resolve().parent
    repo = package.parent.parent
    results = package / "results"
    output = results / "sixstage_20261030_math_figure" / "figures_final"
    output.mkdir(parents=True, exist_ok=False)
    old_path = results / "sixstage_20261030_math" / "central_float32.npz"
    stable_path = results / "sixstage_20261030_stable_probability" / "long_central_float32.npz"
    dynamic_path = results / "sixstage_20261030_dynamics_comparison" / "RESULTS.json"
    risk_path = results / "sixstage_20261030_risk_independent" / "RESULTS.json"
    old = np.load(old_path, allow_pickle=False)["trace"]
    stable = np.load(stable_path, allow_pickle=False)["trace"]
    assert np.array_equal(old[:, 0], stable[:, 0])
    # Both probability vectors were stored losslessly as float64 representations
    # of their actual float32 entries. Use the identical reduction for both.
    old_error = np.abs(old[:, 6:].sum(-1, dtype=np.float64) - 1)
    stable_error = np.abs(stable[:, 8:].sum(-1, dtype=np.float64) - 1)
    old_maximum = np.maximum.accumulate(old_error)
    stable_maximum = np.maximum.accumulate(stable_error)
    dynamics = json.loads(dynamic_path.read_text())
    risk = json.loads(risk_path.read_text())
    assert dynamics["passed"] and risk["passed"]
    order = ["absorbing_no_reset", "end_window_probability_reset", "instant_reset_ctmc", "erlang2_refractory_ctmc"]
    names = ["Absorbing, no reset", "Reset at window end", "Immediate reset (m=0)", "Erlang refractory (m=2)"]
    colors = ["#6A737D", "#D55E00", "#0072B2", "#8E5DA2"]
    dt = np.asarray([.0625, .25, 1.])
    counts = np.asarray([[next(row["expected_events"] for row in dynamics["records"]
                              if row["model"] == model and row["horizon"] == 16. and row["observation_dt"] == duration)
                          for duration in dt] for model in order])
    risk_rows = [next(row for row in risk["records"]["dense_and_monte_carlo"]
                     if row["case"] == name and row["input_dtype"] == "torch.float64")
                 for name in ("repeated_event_window", "self_reset")]
    probabilities = np.asarray([row["risk"] for row in risk_rows])
    repeated_counts = np.asarray([row["expected_event_count"] for row in risk_rows])
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.titlesize": 12, "axes.labelsize": 10,
                         "legend.fontsize": 8.8, "svg.fonttype": "none",
                         "axes.spines.top": False, "axes.spines.right": False})
    figure, axes = plt.subplots(1, 3, figsize=(15.3, 6.1))
    figure.subplots_adjust(left=.062, right=.985, bottom=.30, top=.775, wspace=.37)
    figure.suptitle("HCSN finite-state audit: stability and event semantics", x=.062, ha="left", y=.97, fontsize=17, weight="bold")
    figure.text(.062, .895, "Recorded CPU diagnostics · 8 active cells · finite reflecting domain · 0 or 2 Erlang phases", fontsize=11, color="#43515C")

    ax = axes[0]
    x = old[:, 0]
    ax.plot(x, np.where(old_maximum > 0, old_maximum, np.nan), color="#D55E00", lw=2, label="Original recurrence")
    ax.plot(x, np.where(stable_maximum > 0, stable_maximum, np.nan), color="#0072B2", lw=2, label="Bounded mass correction")
    checked_guard = 256 * np.finfo(np.float32).eps
    ax.axhline(checked_guard, color="#66727D", ls="--", lw=1, label="Original input mass guard")
    ax.set_yscale("log")
    ax.set_ylim(1e-9, 1e-2); ax.set_xlim(0, 4096)
    ax.set_xticks([0, 1024, 2048, 3072, 4096])
    ax.set_xlabel("Observation steps")
    ax.set_ylabel("Maximum |total mass − 1| so far")
    ax.set_title("A   Long recurrence in float32", loc="left", pad=12)
    ax.grid(axis="y", color="#DDE3E8", lw=.7, alpha=.7)
    ax.legend(loc="center left", bbox_to_anchor=(.01, .42), frameon=False)
    ax.text(.98, .11, f"New: {stable_maximum[-1]:.2e}", transform=ax.transAxes, ha="right", color="#0072B2", fontsize=9)
    ax.text(.98, .76, f"Old: {old_maximum[-1]:.2e}", transform=ax.transAxes, ha="right", color="#D55E00", fontsize=9)

    ax = axes[1]
    for row, label, color in zip(counts, names, colors):
        ax.plot(dt, row, "o-", color=color, lw=2, ms=5, label=label)
    ax.set_xscale("log", base=4)
    ax.set_xticks(dt, ["1/16", "1/4", "1"])
    ax.set_ylim(0, 16)
    ax.set_xlabel("Observation interval Δt (model time)")
    ax.set_ylabel("Expected cumulative events at T = 16")
    ax.set_title("B   Reset timing changes dynamics", loc="left", pad=12)
    ax.grid(axis="y", color="#DDE3E8", lw=.7, alpha=.7)
    ax.legend(loc="center left", bbox_to_anchor=(.01, .38), frameon=False)
    ax.text(.99, .88, "13.796", transform=ax.transAxes, ha="right", color="#0072B2", fontsize=9)
    ax.text(.99, .70, "10.992", transform=ax.transAxes, ha="right", color="#8E5DA2", fontsize=9)

    ax = axes[2]
    positions = np.arange(len(probabilities)); width = .33
    bars_a = ax.bar(positions - width / 2, probabilities, width, color="#009E73", label="P(at least one event)")
    bars_b = ax.bar(positions + width / 2, repeated_counts, width, color="#0072B2", label="Expected event count")
    ax.axhline(1, color="#66727D", lw=1, ls="--")
    for bars in (bars_a, bars_b):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + .08,
                    f"{bar.get_height():.3f}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(positions, ["m = 2\nΔt = 7.31", "m = 0, self reset\nΔt = 3.2"])
    ax.set_ylim(0, 6.2)
    ax.set_ylabel("Probability or expected number of events")
    ax.set_title("C   First event ≠ repeated count", loc="left", pad=12)
    ax.grid(axis="y", color="#DDE3E8", lw=.7, alpha=.7); ax.set_axisbelow(True)
    ax.legend(loc="upper left", frameon=False)

    figure.text(.062, .155,
                "A: both mass sums evaluated in float64 from saved float32 states; zero errors omitted on the log axis.\n"
                "B: identical constant drive μ=0.45, σ=0.60, b=0.55, reset=0.05; refractory mean τ=0.30.\n"
                "C: each probability/count pair uses the same initial state and time window; killed survival is never normalized.",
                fontsize=9.1, color="#43515C", linespacing=1.6, va="top")
    figure.text(.062, .023, "Scope: numerical and event semantics only; no content-quality, biological-fidelity, GPU or energy advantage is established.",
                fontsize=9.1, color="#43515C")
    png, svg = output / "sixstage_math_audit.png", output / "sixstage_math_audit.svg"
    figure.savefig(png, dpi=180, facecolor="white")
    figure.savefig(svg, facecolor="white", metadata={"Date": None})
    plt.close(figure)
    extracted = output / "plot_data.npz"
    np.savez_compressed(extracted, observations=x, old_mass_error=old_error,
                        new_mass_error=stable_error, old_running_max=old_maximum,
                        new_running_max=stable_maximum, durations=dt,
                        expected_counts_at_T16=counts,
                        first_event_probability=probabilities, expected_repeat_count=repeated_counts)
    source_copy = output / "plot_source.py"
    source_copy.write_bytes(Path(__file__).read_bytes())
    sources = [old_path, stable_path, dynamic_path, risk_path, Path(__file__)]
    artifacts = [png, svg, extracted, source_copy]
    manifest = dict(schema="hcsn-three-panel-math-figure.v1",
                    sources=[dict(path=str(path.relative_to(repo)), sha256=digest(path)) for path in sources],
                    artifacts=[dict(path=str(path.relative_to(repo)), sha256=digest(path), bytes=path.stat().st_size) for path in artifacts],
                    panel_A=dict(state_dtype="float32", mass_reduction_dtype="float64",
                                 statistic="running maximum of absolute total-mass error",
                                 old_final_max=float(old_maximum[-1]), new_final_max=float(stable_maximum[-1]),
                                 original_checked_mass_guard=float(checked_guard),
                                 zero_errors="omitted from logarithmic display; retained in plot_data.npz"),
                    panel_B=dict(order=order, model_time_horizon=16, durations=dt.tolist(), counts=counts.tolist()),
                    panel_C=dict(cases=[row["case"] for row in risk_rows], input_dtype="float64",
                                 risk=probabilities.tolist(), expected_events=repeated_counts.tolist()),
                    illustrative_or_fabricated_plot_data=False,
                    data_origin="Recorded numerical simulations and kernel audits; no invented illustrative data",
                    scope="Finite-grid numerical and event semantics; no task-quality or hardware-efficiency inference")
    (output / "FIGURE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(png=str(png), svg=str(svg), manifest=str(output / "FIGURE_MANIFEST.json"))))


if __name__ == "__main__":
    main()
