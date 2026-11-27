"""Standard Matplotlib figures for completed Hepta report evidence."""

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

TASKS = ("selective_copy", "mqar")
ARMS = ("analytic", "matched_c1", "sigmoid", "ordinary", "frozen_flow")
REGIMES = ("cpu30", "updates384")


def figures(data, output):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "figure.dpi": 140,
        }
    )
    images = {}

    def retain(name, figure):
        figure.tight_layout(pad=1.6)
        buffer = io.BytesIO()
        figure.savefig(
            buffer,
            format="png",
            dpi=170,
            facecolor="white",
            metadata={"Software": "Hepta scientific report generator"},
        )
        plt.close(figure)
        images[name] = buffer.getvalue()

    fig, axes = plt.subplots(2, 2, figsize=(12.4, 7.6))
    colors = ("#1768a8", "#e08a24", "#66835c", "#8b65a8", "#8b9198")
    for row_index, task in enumerate(TASKS):
        for metric_index, metric in enumerate(("accuracy", "cross_entropy")):
            ax = axes[row_index, metric_index]
            for i, arm in enumerate(ARMS):
                groups = [
                    next(
                        r
                        for r in data["score_groups"]
                        if (r["task"], r["arm"], r["regime"]) == (task, arm, regime)
                    )
                    for regime in REGIMES
                ]
                xs = np.arange(2) + (i - 2) * 0.14
                means = [r["metrics"][metric]["mean"] for r in groups]
                errors = [r["metrics"][metric]["sample_sd"] for r in groups]
                ax.errorbar(
                    xs,
                    means,
                    yerr=errors,
                    fmt="o",
                    capsize=3,
                    color=colors[i],
                    label=arm,
                )
                for x, r in zip(xs, groups):
                    ax.scatter(
                        np.full(3, x),
                        r["metrics"][metric]["seed_values"],
                        s=12,
                        alpha=0.4,
                        color=colors[i],
                    )
            ax.set_xticks([0, 1], ["CPU <= 30 s", "<= 384 updates"])
            ax.set_title(task + " | " + metric)
            ax.grid(axis="y", alpha=0.18)
            if metric == "accuracy":
                ax.set_ylim(-0.02, 1.03)
                ax.axhline(0.9, color="#777", ls=":", lw=1)
    axes[0, 0].legend(fontsize=8, ncol=2, loc="lower right")
    retain("task_quality", fig)
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.2))
    comparisons = data["primary"]["comparisons"]
    for ax, metric in zip(axes, ("accuracy", "cross_entropy")):
        rows = [r for r in comparisons if r["metric"] == metric]
        for i, row in enumerate(rows):
            low, high = row["adjusted_ci"]
            color = "#197047" if row["metric_improvement_gate"] else "#596575"
            ax.plot([low, high], [i, i], color=color, lw=1.5)
            ax.scatter([row["mean"]], [i], color=color, s=20)
        ax.axvline(0, color="#b65837", ls="--", lw=1)
        ax.set_yticks(
            range(len(rows)),
            [f"{r['task'][:4]}/{r['regime']}/{r['comparator']}" for r in rows],
            fontsize=7,
        )
        ax.set_title(metric + ": adjusted paired-seed intervals")
        ax.set_xlabel("Positive favors analytic; n = 3")
    retain("comparison_intervals", fig)
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.4))
    for ax, batch in zip(axes, (1, 32)):
        rows = sorted(
            (r for r in data["runtime"]["aliases"] if r["case"]["batch_size"] == batch),
            key=lambda r: (
                r["alias"]["task"],
                r["alias"]["regime"],
                ARMS.index(r["alias"]["arm"]),
            ),
        )
        for i, row in enumerate(rows):
            stats = row["case"]["wall_seconds"]
            ax.plot(
                [stats["minimum"] * 1000, stats["maximum"] * 1000],
                [i, i],
                color="#a8b1bc",
            )
            ax.scatter(
                stats["median"] * 1000,
                i,
                color=colors[ARMS.index(row["alias"]["arm"])],
                s=18,
            )
        ax.set_yticks(
            range(len(rows)),
            [
                f"{r['alias']['task'][:4]}/{r['alias']['regime']}/{r['alias']['arm']}"
                for r in rows
            ],
            fontsize=6.5,
        )
        ax.set_title(f"Fresh-reset T=32, batch={batch}")
        ax.set_xlabel("Wall ms, median and min-max of 11 runs")
        ax.grid(axis="x", alpha=0.15)
    retain("inference_cost", fig)
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.1))
    coupling = data["diagnostics"]["coupling_diagnostic001"]["results"]["rows"]
    for ax, mode in zip(axes, ("analytic", "matched_c1")):
        for h, marker in ((0.0625, "o"), (0.03125, "s")):
            rows = sorted(
                (r for r in coupling if r["mode"] == mode and r.get("inner_step") == h),
                key=lambda r: r["outer_step"],
            )
            ax.loglog(
                [r["outer_step"] for r in rows],
                [r["memory_scaled_max_error"] for r in rows],
                marker=marker,
                label=f"M, h={h}",
            )
            ax.loglog(
                [r["outer_step"] for r in rows],
                [r["flow_scaled_max_error"] for r in rows],
                marker=marker,
                ls="--",
                alpha=0.6,
                label=f"flow, h={h}",
            )
        ax.set_title(mode + " | untrained coupling probe")
        ax.set_xlabel("Outer interval delta")
        ax.set_ylabel("max |error| / (1 + |reference|)")
        ax.grid(alpha=0.16)
        ax.legend(fontsize=8)
    retain("coupling_error", fig)
    images["phase_dynamics"] = data.pop("phase_figure_bytes")
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in images.items():
        (output / f"{name}.png").write_bytes(payload)
    return {
        name: "data:image/png;base64," + base64.b64encode(payload).decode()
        for name, payload in images.items()
    }
