"""Render descriptive figures from explicitly registered, completed Cell studies.

This reporting tool performs no fitting, selection, testing or quality promotion.
Each task is averaged across its fixed seeds before the family mean is taken.
All arms and parameter controls remain in the JSON table; plots are declared
separately by the caller and never combine different task families.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def collect(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("schema") != "hepta.local-cell-result-presentation.v1":
        raise ValueError("explicit presentation manifest required")
    bindings = {str(manifest_path): hashlib.sha256(manifest_raw).hexdigest()}
    records, selection, studies = [], [], []
    seen = set()

    def load(path):
        path = Path(path).resolve()
        raw = path.read_bytes()
        bindings[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    for spec in manifest["studies"]:
        if spec["id"] in seen:
            raise ValueError("duplicate condition")
        seen.add(spec["id"])
        root = Path(spec["path"])
        root = root if root.is_absolute() else manifest_path.parent / root
        summary = load(root / "summary.json")
        plan = load(root / "study-plan.json")
        seal = load(root / "selection-seal.json")
        if (summary["selection_seal_sha256"] != digest(root / "selection-seal.json")
                or not seal["all_declared_tasks_frozen_before_any_evaluation"]
                or set(summary["tasks_evaluated"]) | set(summary["unavailable_tasks"]) != set(plan["tasks"])):
            raise ValueError("incomplete or differently sealed study")
        studies.append({"condition": spec["id"], "label": spec["label"],
                        "holdout_use": plan["holdout_use"],
                        "tasks": summary["tasks_evaluated"],
                        "unavailable_budgets": summary["unavailable_budgets"]})
        for task in summary["tasks_evaluated"]:
            report = load(root / task / "evaluation" / "report.json")
            if not report["prepared_artifacts_unchanged"]:
                raise ValueError("prepared artifacts changed during evaluation")
            family = report["plan"]["family_id"]
            for run in report["runs"]:
                selection.append({"condition": spec["id"], "family": family, "task": task,
                                  "budget": run["budget"], "seed": run["seed"],
                                  "selected_arm": run["selected_arm"]})
                for arm, result in run["arms"].items():
                    controls = {"trained": result, **result.get("controls", {})}
                    for control, item in controls.items():
                        metrics = {k: item["semantic"][k] for k in (
                            "balanced_accuracy", "forced_accuracy", "positive_recall", "nll",
                            "brier_multiclass_sum", "ece10_equal_width", "coverage", "overall_success")}
                        metrics.update(item.get("secondary_discrimination", {}))
                        records.append({"condition": spec["id"], "family": family, "task": task,
                            "budget": run["budget"], "seed": run["seed"], "arm": arm,
                            "control": control, "metrics": metrics})
                chosen = run["arms"][run["selected_arm"]]
                records.append({"condition": spec["id"], "family": family, "task": task,
                    "budget": run["budget"], "seed": run["seed"], "arm": "tuning_selector",
                    "control": "trained", "metrics": {
                        **{k: chosen["semantic"][k] for k in (
                            "balanced_accuracy", "forced_accuracy", "positive_recall", "nll",
                            "brier_multiclass_sum", "ece10_equal_width", "coverage", "overall_success")},
                        **chosen.get("secondary_discrimination", {})}})
    grouped = defaultdict(lambda: defaultdict(list))
    for row in records:
        for metric, value in row["metrics"].items():
            if value is not None:
                key = tuple(row[k] for k in ("condition", "family", "budget", "arm", "control")) + (metric,)
                grouped[key][row["task"]].append(float(value))
    means = []
    for key, tasks in sorted(grouped.items()):
        condition, family, budget, arm, control, metric = key
        means.append({"condition": condition, "family": family, "budget": budget, "arm": arm,
            "control": control, "metric": metric,
            "mean": statistics.mean(statistics.mean(values) for values in tasks.values()),
            "tasks": len(tasks), "task_seed_observations": sum(map(len, tasks.values()))})
    return manifest, {"schema": "hepta.local-cell-descriptive-results.v1", "studies": studies,
        "artifact_bindings": bindings, "records": records, "family_means": means,
        "tuning_selections": selection, "quality_qualified": False,
        "scope": "Fixed declared task/seed means. Correlated tasks and seeds are not independent trials. No cross-family mean; paired uncertainty is a separate artifact."}


def render(manifest_path, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    implementation = digest(__file__)
    manifest, data = collect(manifest_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "svg.fonttype": "none", "svg.hashsalt": "hepta-local-next-v1",
                         "axes.spines.top": False, "axes.spines.right": False})
    for chart in manifest["figures"]:
        panels = chart["panels"]
        fig, axes = plt.subplots(len(panels), 2, figsize=(13, 3.3 * len(panels)), squeeze=False)
        for index, panel in enumerate(panels):
            for column, metric in enumerate(("balanced_accuracy", "nll")):
                ax = axes[index][column]
                for line in panel["lines"]:
                    rows = [row for row in data["family_means"] if
                        row["condition"] in line["conditions"] and row["family"] == panel["family"]
                        and row["arm"] == line["arm"] and row["control"] == "trained"
                        and row["metric"] == metric]
                    rows.sort(key=lambda row: row["budget"])
                    if not rows or len({row["budget"] for row in rows}) != len(rows):
                        raise ValueError("plot line missing or duplicates a gradient budget")
                    ax.plot([row["budget"] for row in rows], [row["mean"] for row in rows],
                            label=line["label"], color=line["color"],
                            linestyle=line.get("style", "-"), marker=line.get("marker", "o"),
                            linewidth=1.7, markersize=4)
                ax.set_xscale("log", base=2)
                ax.set_xticks(panel["budgets"], [str(n) for n in panel["budgets"]])
                ax.set_xlabel("Selected gradient-training groups")
                ax.set_ylabel("Balanced accuracy" if metric == "balanced_accuracy" else "Negative log likelihood")
                ax.set_title(panel["title"])
                ax.grid(alpha=.18)
                if metric == "balanced_accuracy":
                    ax.set_ylim(0, 1.02)
                else:
                    ax.set_ylim(bottom=0)
                ax.legend(loc="best", fontsize=8, frameon=False)
        fig.suptitle(chart["title"], fontsize=15, y=.998)
        fig.text(.5, .005,
            "Fixed task/seed means; no independence assumption. Calibration/selection sealed before scoring.\n"
            "Budget excludes additional tuning/calibration labels; 122 is a separate declared supplement.",
            ha="center", fontsize=9, color="#475569")
        fig.tight_layout(rect=(0, .035, 1, .98))
        fig.savefig(output / (chart["id"] + ".svg"), metadata={"Date": None})
        fig.savefig(output / (chart["id"] + ".png"), dpi=160, metadata={"Software": "Hepta fixed-result renderer"})
        plt.close(fig)
    if digest(__file__) != implementation or any(digest(path) != value for path, value in data["artifact_bindings"].items()):
        raise ValueError("reporting source changed during rendering")
    data["renderer_sha256"] = implementation
    data["rendering_runtime"] = {"matplotlib": matplotlib.__version__}
    data["figures"] = {p.name: digest(p) for p in sorted(output.iterdir())}
    (output / "descriptive-results.json").write_bytes(canonical(data) + b"\n")
    return {"studies": len(data["studies"]), "task_seed_arm_control_records": len(data["records"]),
            "figures": len(data["figures"]), "quality_qualified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", dest="manifest_path", required=True)
    parser.add_argument("--output", required=True)
    print(json.dumps(render(**vars(parser.parse_args()))))
