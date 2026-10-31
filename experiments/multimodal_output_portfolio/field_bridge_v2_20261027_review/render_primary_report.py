"""Render published, already-computed V2 estimates without fitting or inference."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source, out = Path(args.result), Path(args.out)
    result = json.loads(source.read_text())
    out.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.facecolor": "white"})
    colors = {"reward": "#2563a6", "audit": "#c86622"}
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 7.2), gridspec_kw={"width_ratios": [1.25, 1]})
    for ax, key, title, threshold in (
        (axes[0], "primary_contrasts", "Six primary gains", 0),
        (axes[1], "retention_vs_frozen", "Retention versus A", -0.01),
    ):
        entries = result[key]
        for i, entry in enumerate(entries):
            for observer, shift in (("reward", -.12), ("audit", .12)):
                estimate = entry["observers"][observer]
                mean = estimate["mean_net_return_difference"]
                lo, hi = estimate["paired_cluster_interval"]
                ax.errorbar(mean, i + shift, xerr=[[mean - lo], [hi - mean]],
                            fmt="o", markersize=5, capsize=3, color=colors[observer],
                            label=observer.capitalize() if i == 0 else None)
        ax.axvline(threshold, color="#a42828", linestyle="--", linewidth=1.3,
                   label="Gain threshold" if threshold == 0 else "NI margin = -0.01")
        if threshold != 0:
            ax.axvline(0, color="#888888", linewidth=.7)
        ax.set_yticks(range(len(entries)), [x["candidate"][0] + " - " + x["control"][0] for x in entries])
        ax.invert_yaxis()
        ax.set_title(title, weight="bold", pad=14)
        ax.set_xlabel("Difference in mean net utility")
        ax.grid(axis="x", alpha=.18)
    axes[0].set_xlim(-.014, .043)
    axes[1].set_xlim(-.016, .020)
    fig.suptitle("Parameter field x Hepta: complete V2 evaluation", fontsize=17, weight="bold", y=.98)
    handles, labels = axes[0].get_legend_handles_labels()
    observers = [(h, label) for h, label in zip(handles, labels) if label in {"Reward", "Audit"}]
    fig.legend([x[0] for x in observers], [x[1] for x in observers], loc="lower center",
               bbox_to_anchor=(.5, .081), ncol=2, frameon=False, fontsize=11)
    fig.text(.5, .025, "Paired source-pair bootstrap; 3 fixed historical models; 512 pairs per split.\n"
             "Intervals: primary 99.1667%, retention 99.4444%. Dashed lines: gain 0, NI margin -0.01.\n"
             "All six combined acceptance gates failed; positive test gain alone is insufficient.",
             ha="center", fontsize=10, color="#444444")
    fig.tight_layout(rect=(0, .145, 1, .94))
    for suffix in ("png", "svg"):
        fig.savefig(out / ("primary_and_retention." + suffix), dpi=180)
    plt.close(fig)

    lines = ["## 六项主要比较", "", "| 比较 | Reward 平均差及校正区间 | Audit 平均差及校正区间 | 联合验收 |",
             "|---|---|---|---|"]
    for entry in result["primary_contrasts"]:
        cells = []
        for observer in ("reward", "audit"):
            x = entry["observers"][observer]
            a, b = x["paired_cluster_interval"]
            cells.append(f"{x['mean_net_return_difference']:+.6f} [{a:+.6f}, {b:+.6f}]")
        passed = "通过" if entry["accepted_with_retention"] else "未通过"
        lines.append(f"| {entry['candidate'][0]}−{entry['control'][0]} | {cells[0]} | {cells[1]} | {passed} |")
    lines += ["", "## 保留能力", "", "| 实验臂 | Reward 平均差 | Reward 校正下界 | Audit 平均差 | Audit 校正下界 | 双观察器非劣性 |",
              "|---|---:|---:|---:|---:|---|"]
    for entry in result["retention_vs_frozen"]:
        r, a = (entry["observers"][o] for o in ("reward", "audit"))
        passed = "通过" if entry["both_observers_noninferior"] else "未确立"
        lines.append(f"| {entry['candidate'][0]} | {r['mean_net_return_difference']:+.6f} | {r['paired_cluster_interval'][0]:+.6f} | "
                     f"{a['mean_net_return_difference']:+.6f} | {a['paired_cluster_interval'][0]:+.6f} | {passed} |")
    lines += ["", "## 十一臂实测均值", "", "| 实验臂 | Reward 净效用 | Audit 净效用 | Reward CE | Audit CE | 平均 refinement | 决策 wall / μs |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for key, summary in result["summaries"].items():
        if key.startswith("test/"):
            r, a = (summary["observers"][o] for o in ("reward", "audit"))
            lines.append(f"| {key[5]} | {r['mean_net_return']:.6f} | {a['mean_net_return']:.6f} | {r['pooled_ce']:.6f} | "
                         f"{a['pooled_ce']:.6f} | {summary['mean_actual_refinements']:.6f} | "
                         f"{summary['descriptive_resources']['decision_wall_ns']['mean']/1000:.2f} |")
    (out / "TABLES.md").write_text("\n".join(lines) + "\n")
    receipt = {"input_result_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "inference_recomputed": False, "inference_changed": False,
               "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())
                         if p.name in {"primary_and_retention.png", "primary_and_retention.svg", "TABLES.md"}}}
    (out / "RENDER_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
