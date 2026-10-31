"""Aggregate frozen test evidence; do not run until the owner releases test analysis.

Importing this module does not read data. It never fits a model or chooses a seed.
All four families and three registered widths are retained, with seed min/max
ranges rather than confidence intervals or claims about an optimal frontier.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.special import logsumexp


TASKS = ("associative_recall", "multimodal_evidence", "digits_rows")
FAMILIES = ("ordinary", "analytic", "lif_surrogate", "transformer")
WIDTHS, SEEDS = (16, 32, 64), (11, 23, 37)
CONDITIONS = ("iid", "long_delay", "clock_shift")
TASK_LABELS = ("Associative recall", "Noisy multimodal evidence", "Handwritten digit rows")
FAMILY_LABELS = {"ordinary": "Ordinary recurrent gate", "analytic": "Renewal-flow gate",
                 "lif_surrogate": "Hard-spike LIF (SG)", "transformer": "Compact causal Transformer"}
CONDITION_LABELS = {"iid": "IID", "long_delay": "Long sequence / delay", "clock_shift": "Clock shift"}


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def list_digest(values):
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def stats(values):
    a = np.asarray(values, dtype=float)
    if not len(a) or not np.all(np.isfinite(a)):
        raise ValueError("summary needs nonempty finite observations")
    return {"mean": float(a.mean()), "min": float(a.min()), "max": float(a.max()), "n": len(a)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def collect(base):
    """Read exactly 108 registered fits and independently recompute 324 test scores."""
    rows, runs, diagnostics, missing = [], [], [], []
    train_identity, test_identity, label_identity = {}, {}, {}
    checked_sources = {}
    digit_test_count = read_json(base / "evidence/content/digits_dataset_identity.json")["split_counts"]["test"]
    for task in TASKS:
        for family in FAMILIES:
            namespace = "content" if family in ("ordinary", "analytic") else "comparison"
            for width in WIDTHS:
                for seed in SEEDS:
                    run = base / "evidence" / namespace / "runs" / task / f"{family}_w{width}_s{seed}"
                    config = read_json(run / "run_config.json")
                    receipt = read_json(run / "FINAL_CHECKPOINT_RECEIPT.json")
                    metric = read_json(run / "evaluation_test" / "metrics.json")
                    identity = (task, family, width, seed)
                    require(tuple(config[k] for k in ("task", "family", "width", "seed")) == identity,
                            f"run config identity mismatch: {run}")
                    require(tuple(metric[k] for k in ("task", "family", "width", "seed")) == identity,
                            f"test metric identity mismatch: {run}")
                    require(metric.get("data_partition") == "test", f"not a test partition: {run}")
                    checkpoint = digest(run / "final.npz")
                    require(checkpoint == receipt["checkpoint_sha256"] == metric["checkpoint_sha256"],
                            f"checkpoint identity mismatch: {run}")
                    require(digest(run / "training_steps.jsonl") == receipt["training_log_sha256"],
                            f"training log changed: {run}")
                    for name, sha in config["source_sha256"].items():
                        current = checked_sources.setdefault(name, digest(base / name))
                        require(current == sha, f"source differs from training: {name} in {run}")
                    with np.load(run / "final.npz", allow_pickle=False) as weights:
                        count = sum(weights[key].size for key in weights.files if key != "metadata_json")
                    require(count == config["parameter_count"], f"parameter count mismatch: {run}")
                    steps = [json.loads(line) for line in (run / "training_steps.jsonl").read_text().splitlines()]
                    require([s["step"] for s in steps] == list(range(1, 301)), f"incomplete training log: {run}")
                    train_hashes = [s["batch_sha256"] for s in steps]
                    train_key = (task, seed)
                    prior = train_identity.setdefault(train_key, train_hashes)
                    require(prior == train_hashes, f"training input mismatch across models: {run}")
                    require(steps[-1]["examples_seen"] == 9600, f"training budget differs: {run}")
                    require(receipt["training_cpu_seconds"] > 0, f"invalid training CPU time: {run}")
                    for condition in CONDITIONS:
                        measured = metric["splits"][condition]
                        require(measured["n"] == (digit_test_count if task == "digits_rows" else 2048),
                                f"test example count differs from registration: {run}/{condition}")
                        hashes = measured["batch_sha256"]
                        test_key = (task, condition)
                        prior = test_identity.setdefault(test_key, hashes)
                        require(prior == hashes, f"test input mismatch across models: {run}/{condition}")
                        payload = run / "evaluation_test" / (condition + "_predictions.npz")
                        with np.load(payload, allow_pickle=False) as saved:
                            logits, labels = saved["logits"], saved["labels"]
                            predictions = saved["predictions"]
                            require(np.array_equal(predictions, logits.argmax(axis=1)), f"prediction mismatch: {payload}")
                            require(len(labels) == measured["n"] and np.all(np.isfinite(logits)),
                                    f"invalid prediction payload: {payload}")
                            accuracy = float(np.mean(predictions == labels))
                            nll = float(np.mean(logsumexp(logits, axis=1) - logits[np.arange(len(labels)), labels]))
                            label_hash = hashlib.sha256(np.asarray(labels, dtype="<i8").tobytes()).hexdigest()
                            require(label_identity.setdefault(test_key, label_hash) == label_hash,
                                    f"saved test labels differ across models: {payload}")
                        require(abs(accuracy - measured["accuracy"]) < 1e-12 and abs(nll - measured["nll"]) < 1e-10,
                                f"reported score does not match raw predictions: {payload}")
                        rows.append({"task": task, "family": family, "width": width, "seed": seed,
                                     "condition": condition, "n": measured["n"], "parameter_count": count,
                                     "accuracy": accuracy, "nll": nll,
                                     "training_cpu_seconds": receipt["training_cpu_seconds"],
                                     "training_wall_seconds": receipt["training_wall_seconds"],
                                     "test_cpu_seconds": measured["cpu_seconds"], "test_wall_seconds": measured["wall_seconds"],
                                     "gradient_kind": "surrogate" if family == "lif_surrogate" else "exact",
                                     "checkpoint_sha256": checkpoint, "predictions_sha256": digest(payload),
                                     "training_batches_sha256": list_digest(train_hashes),
                                     "test_batches_sha256": list_digest(hashes), "run": str(run.relative_to(base))})
                    run_record = {"task": task, "family": family, "width": width, "seed": seed,
                                  "run": str(run.relative_to(base)), "checkpoint_sha256": checkpoint,
                                  "parameter_count": count, "receipt": receipt}
                    runs.append(run_record)
                    if namespace == "content":
                        path = run / "diagnostics" / "summary.json"
                        if not path.exists():
                            missing.append(str(path.relative_to(base)))
                            continue
                        diag = read_json(path)
                        require(diag["checkpoint_sha256"] == checkpoint, f"diagnostic checkpoint differs: {path}")
                        require(tuple(diag[k] for k in ("task", "family", "width", "seed")) == identity,
                                f"diagnostic run identity differs: {path}")
                        hashes = diag["raw_batch_sha256"]
                        require(hashes == metric["splits"]["iid"]["batch_sha256"][:len(hashes)],
                                f"diagnostic inputs are not the declared IID prefix: {path}")
                        full = diag["metrics"]["full_history"]["accuracy"]
                        last = diag["metrics"]["last_observation_only"]["accuracy"]
                        require(abs(full - last - diag["full_minus_last_accuracy"]) < 1e-12,
                                f"diagnostic difference inconsistent: {path}")
                        require(abs(diag["prefix_metrics"][-1]["accuracy"] - full) < 1e-12,
                                f"last prefix does not equal full history: {path}")
                        diagnostics.append(diag)
    require(len(runs) == 108 and len(rows) == 324, "registered fit/condition count incomplete")
    validation = {"fits": len(runs), "metric_rows": len(rows), "training_fairness_groups": len(train_identity),
                  "test_fairness_groups": len(test_identity), "matching_recorded_raw_batch_hashes": True,
                  "raw_prediction_scores_recomputed": True, "checkpoint_and_source_identity_checked": True,
                  "remote_commit_proof": "owned by run_study/secondary_study orchestration receipts, not inferred here",
                  "source_sha256": checked_sources}
    return rows, runs, diagnostics, missing, validation


def summarize(rows, diagnostics):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["task"], row["family"], row["width"], row["condition"])].append(row)
    grouped = []
    for (task, family, width, condition), items in groups.items():
        require(sorted(i["seed"] for i in items) == list(SEEDS), "missing or duplicate model seed")
        require(len({i["parameter_count"] for i in items}) == 1, "parameter count varies within a model")
        grouped.append({"task": task, "family": family, "width": width, "condition": condition,
                        "parameter_count": items[0]["parameter_count"], "test_examples_per_seed": items[0]["n"],
                        **{key: stats([i[key] for i in items]) for key in
                           ("accuracy", "nll", "training_cpu_seconds", "training_wall_seconds", "test_cpu_seconds")}})
    lookup = {(r["task"], r["family"], r["width"], r["seed"], r["condition"]): r for r in rows}
    pairs = []
    for task in TASKS:
        for width in WIDTHS:
            for seed in SEEDS:
                for condition in CONDITIONS:
                    ordinary = lookup[(task, "ordinary", width, seed, condition)]
                    analytic = lookup[(task, "analytic", width, seed, condition)]
                    require(ordinary["parameter_count"] == analytic["parameter_count"], "primary pair capacity differs")
                    require(ordinary["test_cpu_seconds"] > 0, "nonpositive test CPU denominator")
                    pairs.append({"task": task, "width": width, "seed": seed, "condition": condition,
                                  "accuracy_difference": analytic["accuracy"] - ordinary["accuracy"],
                                  "nll_difference": analytic["nll"] - ordinary["nll"],
                                  "training_cpu_ratio": analytic["training_cpu_seconds"] / ordinary["training_cpu_seconds"],
                                  "test_cpu_ratio": analytic["test_cpu_seconds"] / ordinary["test_cpu_seconds"]})
    paired_groups = defaultdict(list)
    for pair in pairs:
        paired_groups[(pair["task"], pair["width"], pair["condition"])].append(pair)
    paired_summary = [{"task": t, "width": w, "condition": c,
                       **{key: stats([i[key] for i in items]) for key in
                          ("accuracy_difference", "nll_difference", "training_cpu_ratio", "test_cpu_ratio")}}
                      for (t, w, c), items in paired_groups.items()]
    diag_groups = defaultdict(list)
    for diag in diagnostics:
        diag_groups[(diag["task"], diag["family"], diag["width"])].append(diag)
    diag_summary = []
    for (task, family, width), items in diag_groups.items():
        lengths = {len(i["prefix_metrics"]) for i in items}
        require(len(lengths) == 1, "different diagnostic prefix lengths in same group")
        diag_summary.append({"task": task, "family": family, "width": width,
            "seeds_present": sorted(i["seed"] for i in items), "complete_three_seeds": len(items) == 3,
            "examples_per_seed": [i["examples"] for i in items],
            "full_history": stats([i["metrics"]["full_history"]["accuracy"] for i in items]),
            "last_observation_only": stats([i["metrics"]["last_observation_only"]["accuracy"] for i in items]),
            "initial_state": stats([i["metrics"]["initial_state"]["accuracy"] for i in items]),
            "full_minus_last_accuracy": stats([i["full_minus_last_accuracy"] for i in items]),
            "prefix_accuracy": [stats([i["prefix_metrics"][step]["accuracy"] for i in items]) for step in range(next(iter(lengths)))],
            "cached_forward_median_cpu": {str(batch): stats([next(t for t in i["timing"] if t["batch"] == batch)
                ["median_cpu_seconds_per_forward"] for i in items]) for batch in (1, 64)}})
    return grouped, pairs, paired_summary, diag_summary


def format_stats(value, scale=1.0, digits=2):
    return f"{value['mean'] * scale:.{digits}f} [{value['min'] * scale:.{digits}f}, {value['max'] * scale:.{digits}f}]"


def markdown(summary):
    missing = summary["diagnostics"]["missing"]
    lines = ["# Registered model comparison results", "",
             "All values below are descriptive means and observed min–max ranges across initialization seeds 11, 23 and 37. These ranges are not confidence intervals. No pooled p-value, architecture selection or optimal Pareto claim is made.", "",
             "## Evidence and fairness", "",
             "108 frozen fits and all 324 test-condition rows are retained. Recorded training-batch hashes match across all families and widths for each task/seed. Recorded test-batch hashes match across all models for each task/condition. Scores were recomputed from saved predictions; checkpoint, parameter-count, log and source identities were checked.", "",
             "The primary ordinary/renewal pair has equal parameter counts. The LIF and Transformer baselines have different counts. All fits use the same 300-update data budget; this is not an equal-compute or optimally tuned comparison.", "",
             "## IID quality, parameter count and fit cost", "",
             "Accuracy is percent. CPU is total recorded training CPU seconds, including batch generation and per-update evidence writing. Brackets contain the observed seed minimum and maximum.", "",
             "| Task | Family | Width | Parameters | Accuracy % | Training CPU s |",
             "| --- | --- | ---: | ---: | ---: | ---: |"]
    for item in summary["model_groups"]:
        if item["condition"] == "iid":
            lines.append(f"| {item['task']} | {item['family']} | {item['width']} | {item['parameter_count']} | {format_stats(item['accuracy'], 100)} | {format_stats(item['training_cpu_seconds'], digits=3)} |")
    lines += ["", "All IID, longer-sequence/delay and clock-shift rows remain in `model_results.csv` and `summary.json`. The long condition adds distractors for recall, adds blank rows after digit images, and adds informative observations for the synthetic multimodal task; these are different stress conditions.", "",
              "## Matched primary pairs", "",
              "Each row summarizes three paired seeds. Accuracy difference is renewal minus ordinary in percentage points. CPU ratios are renewal/ordinary, averaged over the three per-seed ratios. A positive accuracy difference favors renewal; a ratio above one is more CPU cost. All 81 individual paired rows are in `paired_differences.csv`.", "",
              "| Task | Width | Condition | Accuracy difference pp | Training CPU ratio | Test CPU ratio |",
              "| --- | ---: | --- | ---: | ---: | ---: |"]
    for item in summary["primary_paired_groups"]:
        lines.append(f"| {item['task']} | {item['width']} | {item['condition']} | {format_stats(item['accuracy_difference'], 100)} | {format_stats(item['training_cpu_ratio'])} | {format_stats(item['test_cpu_ratio'])} |")
    lines += ["", "## Frozen-content ablations and prefixes", ""]
    if missing:
        lines += [f"**PARTIAL: {len(missing)} of the 54 registered diagnostic reports are missing. The full diagnostic analysis is not complete.**", "",
                  "Missing reports:", ""] + [f"- `{path}`" for path in missing] + [""]
    else:
        lines += ["All 54 primary diagnostic reports are present and linked to the frozen checkpoints.", ""]
    lines += ["These are interventions on the same frozen models, not separately trained last-observation baselines. Synthetic diagnostics use the first 512 IID examples; digit diagnostics use the full test partition. Their scores must not be substituted for the main synthetic 2048-example scores. Prefix curves and all repeated timing observations are retained in `summary.json`.", "",
              "| Task | Family | Width | Seeds present | Full history % | Last observation % | Full minus last pp |",
              "| --- | --- | ---: | --- | ---: | ---: | ---: |"]
    for item in summary["diagnostics"]["groups"]:
        lines.append(f"| {item['task']} | {item['family']} | {item['width']} | {','.join(map(str, item['seeds_present']))} | {format_stats(item['full_history'], 100)} | {format_stats(item['last_observation_only'], 100)} | {format_stats(item['full_minus_last_accuracy'], 100)} |")
    lines += ["", "## Interpretation limits", "",
              "- Widths 16/32/64 are small classification models; no large-model scaling or generative-model result is established.",
              "- The renewal distance is a local gate feature of a vector content state. This experiment does not implement the full He–Xiong equity/default endogenous free boundary.",
              "- LIF uses hard forward spikes and surrogate gradients; its upstream surrogate is not the derivative of the hard-forward loss.",
              "- Timings describe these NumPy CPU implementations, including their implementation overhead. They establish neither GPU performance nor energy use, and the Transformer does not use FlashAttention.",
              "- Figure lines connect increasing registered widths within a family. They are not fitted scaling laws or an asserted optimal frontier.", ""]
    return "\n".join(lines)


def plot_groups(groups, out, xkey, iid_only=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    conditions = ("iid",) if iid_only else CONDITIONS
    colors = {"ordinary": "#3066BE", "analytic": "#D66A25", "lif_surrogate": "#32835B", "transformer": "#8656A0"}
    markers = {"ordinary": "o", "analytic": "s", "lif_surrogate": "^", "transformer": "D"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11})
    fig, axes = plt.subplots(len(conditions), 3, figsize=(17.4, 4.5 if iid_only else 12.2), squeeze=False)
    lookup = {(g["task"], g["family"], g["width"], g["condition"]): g for g in groups}
    for row, condition in enumerate(conditions):
        for col, task in enumerate(TASKS):
            ax = axes[row, col]
            for family in FAMILIES:
                items = [lookup[(task, family, width, condition)] for width in WIDTHS]
                ys = np.array([g["accuracy"]["mean"] for g in items])
                yerr = np.array([[g["accuracy"]["mean"] - g["accuracy"]["min"] for g in items],
                                 [g["accuracy"]["max"] - g["accuracy"]["mean"] for g in items]])
                yerr = np.maximum(yerr, 0.0)
                if xkey == "parameter_count":
                    xs, xerr = [g[xkey] for g in items], None
                else:
                    xs = np.array([g[xkey]["mean"] for g in items])
                    xerr = np.array([[g[xkey]["mean"] - g[xkey]["min"] for g in items],
                                     [g[xkey]["max"] - g[xkey]["mean"] for g in items]])
                    xerr = np.maximum(xerr, 0.0)
                ax.errorbar(xs, ys, yerr=yerr, xerr=xerr, color=colors[family], marker=markers[family],
                            linewidth=1.3, markersize=5, capsize=3, label=FAMILY_LABELS[family])
                for x, y, width in zip(xs, ys, WIDTHS):
                    ax.annotate(str(width), (x, y), textcoords="offset points", xytext=(4, 5), fontsize=7,
                                color=colors[family], alpha=0.85)
            ax.axhline((1 / 3, 0.5, 0.1)[col], color="#777777", linestyle=":", linewidth=0.8)
            ax.set_xscale("log")
            ax.set_ylim(-0.02, 1.06)
            ax.yaxis.set_major_formatter(PercentFormatter(1.0))
            ax.grid(True, alpha=0.18)
            ax.set_title(TASK_LABELS[col] + " — " + CONDITION_LABELS[condition])
            ax.set_xlabel("Parameters (log scale)" if xkey == "parameter_count" else "Training CPU seconds (log scale)")
            if col == 0:
                ax.set_ylabel("Test accuracy")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.0))
    fig.text(0.5, 0.012, "Means over 3 seeds; bars show observed seed min–max, not confidence intervals. Labels mark widths 16/32/64. Dotted lines: chance.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04 if iid_only else 0.025, 1, 0.92 if iid_only else 0.96), h_pad=2.2)
    fig.savefig(out, dpi=180, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    base = args.base.resolve()
    out = base / "analysis" if args.out is None else args.out.resolve()
    names = ("model_results.csv", "paired_differences.csv", "summary.json", "MODEL_RESULTS.md",
             "quality_cost.png", "quality_parameters.png", "quality_cost_iid.png")
    require(not any((out / name).exists() for name in names), "analysis target already exists; preserve prior evidence and choose a new --out")
    rows, runs, diagnostics, missing, validation = collect(base)
    groups, pairs, paired_groups, diag_groups = summarize(rows, diagnostics)
    summary = {"validation": validation, "statistic": "arithmetic mean and observed seed min/max; not confidence intervals",
               "model_groups": groups, "primary_pairs": pairs, "primary_paired_groups": paired_groups,
               "runs": runs, "diagnostics": {"status": "complete" if not missing else "partial",
                    "expected": 54, "present": len(diagnostics), "missing": missing,
                    "groups": diag_groups, "raw_reports": diagnostics},
               "aggregation_source_sha256": digest(Path(__file__))}
    out.mkdir(parents=True, exist_ok=True)
    for name, records in (("model_results.csv", rows), ("paired_differences.csv", pairs)):
        with (out / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (out / "MODEL_RESULTS.md").write_text(markdown(summary))
    plot_groups(groups, out / "quality_cost.png", "training_cpu_seconds")
    plot_groups(groups, out / "quality_parameters.png", "parameter_count")
    plot_groups(groups, out / "quality_cost_iid.png", "training_cpu_seconds", iid_only=True)
    print(json.dumps({"output": str(out), "fits": 108, "rows": 324, "paired_rows": 81,
                      "diagnostics_status": summary["diagnostics"]["status"], "diagnostics_present": len(diagnostics)}))


if __name__ == "__main__":
    main()
