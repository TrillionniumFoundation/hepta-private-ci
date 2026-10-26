"""Render unchanged actual summary values, with evidence review still separate."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def csv_file(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(originals, output):
    original, root = Path(originals), Path(output)
    root.mkdir(parents=True, exist_ok=True)
    source_names = {
        "summary.json": "summary.json",
        "harness-summary.json": "harness-summary.json",
        "execution.json": "execution.json",
    }
    sources = {}
    for destination, source in source_names.items():
        payload = (original / source).read_bytes()
        with (root / destination).open("xb") as stream:
            stream.write(payload)
        sources[destination] = {"original_name": source, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    summary = json.loads((root / "summary.json").read_bytes())
    harness = json.loads((root / "harness-summary.json").read_bytes())
    primary = []
    for name in ("base_main_effect", "gate_main_effect", "interaction"):
        item = summary["primary"][name]
        primary.append({"contrast": name, "estimate": item["estimate"],
            "lower": item["interval"][0], "upper": item["interval"][1],
            "direction": item["direction"], "main_effect_improvement": item["main_effect_improvement"],
            "scope": "registered future source-paired fixed-seed average"})
    csv_file(root / "tables/primary-contrasts.csv", list(primary[0]), primary)
    cells = [{"split": split, "arm": arm,
              **{k: row[k] for k in ("case_count", "joint_loss", "joint_fact_correct", "joint_loss_CVaR90")},
              "scope": "descriptive; no additional confidence interval"}
             for split in ("future", "retention") for arm, row in summary["secondary"][split].items()]
    csv_file(root / "tables/cell-summary.csv", list(cells[0]), cells)
    seeds = [{"split": key.split("-")[0], "seed": int(key.split("seed")[1]), **row["effects"],
              "scope": "descriptive fixed-seed effects; not seed-population inference"}
             for key, row in summary["per_seed"].items()]
    csv_file(root / "tables/per-seed-effects.csv", list(seeds[0]), seeds)
    costs = [{"stage": row["stage"], "wall_seconds": row["wall_ns_including_import_and_exit"] / 1e9,
              "cpu_seconds": row["cpu_ns_including_import_and_exit"] / 1e9,
              "maximum_sampled_child_rss_bytes": row["maximum_sampled_child_rss_bytes"],
              "cumulative_completed_child_peak_rss_bytes": row["cumulative_completed_child_peak_rss_bytes"],
              "returncode": row["returncode"], "failure": row["failure"],
              "scope": "outer child process including import/exit; RSS columns are different nonadditive measurements"}
             for row in harness["stages"]]
    csv_file(root / "tables/stage-costs.csv", list(costs[0]), costs)
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11, "svg.hashsalt": "ndu-fresh-factorial-001"}):
        fig, ax = plt.subplots(figsize=(8.8, 4.4))
        y = [2, 1, 0]
        estimates = [x["estimate"] for x in primary]
        error = [[x["estimate"] - x["lower"] for x in primary],
                 [x["upper"] - x["estimate"] for x in primary]]
        ax.errorbar(estimates, y, xerr=error, fmt="o", color="#174d71", ecolor="#174d71",
                    elinewidth=2, capsize=5, markersize=6)
        ax.axvline(0, color="#697786", linewidth=1, linestyle="--")
        ax.set_yticks(y, ["Base main effect", "Gate main effect", "Interaction"])
        ax.set_ylim(-.6, 2.6)
        ax.set_xlabel("Change in joint loss")
        ax.set_title("Registered NDU training-objective contrasts", loc="left", pad=14, weight="bold")
        ax.grid(axis="x", color="#e5e9ed", linewidth=.7)
        ax.set_axisbelow(True)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        fig.text(.03, .055, "60 future source pairs · fixed-seed average · 10,000 stratified paired bootstrap draws", fontsize=9, color="#465564")
        fig.text(.03, .012, "Three adjusted two-sided percentile intervals; every interval crosses zero. Interaction is not an improvement gate.", fontsize=8.7, color="#465564")
        fig.tight_layout(rect=(0, .13, 1, 1))
        plots = root / "figures"
        plots.mkdir(parents=True, exist_ok=True)
        fig.savefig(plots / "primary-contrasts.svg", metadata={"Date": None})
        fig.savefig(plots / "primary-contrasts.png", dpi=180)
        plt.close(fig)
    with (root / "derived-inputs.json").open("x") as stream:
        json.dump({"schema": "hepta.ndu-fresh.summary-derived-tables.v1", "inputs": sources,
                   "method": "Exact field projection and unit conversion; no new scientific analysis",
                   "full_row_seal_verification": "separate receipt required", "new_model_executed": False},
                  stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": str(root), "tables": 4, "figure_formats": ["svg", "png"], "original_bytes_preserved": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", required=True)
    parser.add_argument("--output", required=True)
    main(**vars(parser.parse_args()))
