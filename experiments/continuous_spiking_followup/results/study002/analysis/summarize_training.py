"""Complete, nonselective tables for the frozen CPU-budget follow-up matrix."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

from training_statistics import (
    ARCHITECTURES,
    CONTROLS,
    compact_run,
    digest,
    group_summary,
    paired_contrasts,
    read,
    training_costs,
)


def summarize(package, results):
    package, results = Path(package), Path(results)
    start = time.process_time(), time.perf_counter()
    inventory, rows, missing = read(package / "RUNS.json"), [], []
    identities = {}
    for spec in inventory:
        path = results / spec["id"] / "RESULT.json"
        if not path.exists():
            missing.append(spec["id"])
            continue
        row = read(path)
        if row["spec"] != spec:
            raise ValueError("saved run differs from frozen inventory: " + spec["id"])
        rows.append(row)
        identities[spec["id"]] = digest(path)
    groups = defaultdict(list)
    for row in rows:
        spec = row["spec"]
        key = (
            spec["stage"],
            spec.get("configuration", spec["task"]),
            spec["architecture"],
        )
        groups[key].append(row)
    mechanism, representation = {}, {}
    for stage, destination in (
        ("mechanism", mechanism),
        ("representation", representation),
    ):
        tasks = sorted({spec["task"] for spec in inventory if spec["stage"] == stage})
        architectures = ["hcsn"] + CONTROLS if stage == "mechanism" else ARCHITECTURES
        for task in tasks:
            destination[task] = {
                arch: group_summary(groups[(stage, task, arch)])
                for arch in architectures
            }
    scaling = []
    for config in sorted(
        {spec["configuration"] for spec in inventory if spec["stage"] == "scaling"}
    ):
        original = next(
            spec
            for spec in inventory
            if spec.get("configuration") == config and spec["stage"] == "scaling"
        )
        scaling.append(
            {
                "configuration": config,
                **{
                    key: original[key]
                    for key in (
                        "axis",
                        "task",
                        "width",
                        "depth",
                        "train_size",
                        "length",
                    )
                },
                "architectures": {
                    arch: group_summary(groups[("scaling", config, arch)])
                    for arch in ("hcsn", "mamba1", "transformer")
                },
            }
        )
    audit_path = results / "TRAINING_AUDIT.json"
    measurement_path = results / "MEASUREMENT_AUDIT.json"
    audit, measurement = (
        read(audit_path) if audit_path.exists() else None,
        read(measurement_path) if measurement_path.exists() else None,
    )
    return {
        "schema": "hcsn-followup-training-comparison-v1",
        "status": "complete" if not missing else "partial",
        "coverage": {
            "planned_jobs": len(inventory),
            "completed_jobs": len(rows),
            "completed_lr_candidates": sum(len(row["candidates"]) for row in rows),
            "missing": missing,
        },
        "protocol_sha256": digest(package / "PROTOCOL.json"),
        "source_seals": [
            json.loads(value)
            for value in sorted(
                {json.dumps(row["source_seals"], sort_keys=True) for row in rows}
            )
        ],
        "result_sha256": identities,
        "mechanism": mechanism,
        "mechanism_contrasts": paired_contrasts(rows),
        "representation": representation,
        "scaling": scaling,
        "cost_ledger": training_costs(rows, results),
        "runs": [compact_run(row, identities[row["spec"]["id"]]) for row in rows],
        "training_audit": None
        if audit is None
        else {
            "sha256": digest(audit_path),
            **{
                key: audit[key]
                for key in (
                    "status",
                    "audited_jobs",
                    "audited_candidates",
                    "replayed_checkpoints",
                    "replayed_examples",
                    "replay_max_abs_error",
                    "issues",
                )
            },
        },
        "measurements": measurement,
        "methods": {
            "mechanism_intervals": "paired training seeds; 98.75% Student-t interval per task's four controls; fixed dataset and search recipe",
            "representation_scaling": "descriptive seed mean and sample SD; no architecture-optimal tuning claim",
            "selection": "both prespecified learning rates and all recorded CPU milestones; validation CE only; all candidate costs charged",
            "quality_cost_curves": "validation CE at actual measured training CPU, with both LR searches charged; unrecorded overhead timing cannot be interpolated to individual checkpoints",
            "data": "episode seed8123; raw MNIST/FSDD populations may overlap study001; no source-population independence claim",
            "historical_comparison": "study001-to-study002 differences are not controlled causal effects because data episodes, budget and selection recipe changed",
            "hardware": "shared-host single-thread CPU; no GPU, energy or universal scaling-law conclusion",
            "scope": "215 classification/search jobs; boundary/native task studies are reported separately",
        },
        "analysis_source_sha256": {
            name: digest(Path(__file__).parent / name)
            for name in (
                "summarize_training.py",
                "training_statistics.py",
                "controller_receipts.py",
            )
        },
        "analysis_cpu_seconds": time.process_time() - start[0],
        "analysis_wall_seconds": time.perf_counter() - start[1],
    }


def number(value, digits=3):
    return "NA" if value is None else f"{value:.{digits}f}"


def mean_sd(group, key, factor=1.0):
    metric = group.get("test_metrics", {}).get(key)
    if metric is None or metric["mean"] is None:
        return "NA"
    return f"{metric['mean'] * factor:.3f} ± {number(None if metric['sd'] is None else metric['sd'] * factor)}"


def format_tables(summary):
    coverage = summary["coverage"]
    lines = [
        "# Study002: all CPU-budget training comparisons",
        "",
        f"Status: **{summary['status']}**. Completed **{coverage['completed_jobs']}/{coverage['planned_jobs']}** searches and **{coverage['completed_lr_candidates']}** LR candidates.",
        "",
        "Each search uses two prespecified learning rates and the same 12 process-CPU-second allowance per candidate. The final indivisible update can overshoot; a 4,096-update safeguard can leave allowance unused. Both are recorded. Validation/checkpoint/setup costs are additional and included in full search CPU. All means/SDs use training seeds; partial groups retain their actual n.",
        "",
        "## Mechanism",
        "",
        "| Task | Architecture | n | Accuracy % | CE | Parameters | All-LR updates, mean | Training CPU, mean s | Full search CPU, mean s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for task, architectures in summary["mechanism"].items():
        for arch, row in architectures.items():
            lines.append(
                f"| {task} | {arch} | {row['n']} | {mean_sd(row, 'accuracy', 100)} | {mean_sd(row, 'cross_entropy')} | {number(row['parameters']['mean'], 0)} | {number(row['updates_both_lrs']['mean'], 1)} | {number(row['training_cpu_seconds_both_lrs']['mean'])} | {number(row['total_search_cpu_seconds']['mean'])} |"
            )
    lines += [
        "",
        "### All prespecified mechanism contrasts",
        "",
        "HCSN minus control, percentage points. 98.75% intervals adjust four contrasts within each task. The one-percentage-point reference is not converted into a new Boolean success rule.",
        "",
        "| Task | Control | Paired n | Difference, pp | 98.75% CI, pp |",
        "|---|---|---:|---:|---:|",
    ]
    for task, controls in summary["mechanism_contrasts"].items():
        for control in CONTROLS:
            row = controls[control]
            interval = (
                "NA"
                if row["ci"] is None
                else f"[{100 * row['ci'][0]:.3f}, {100 * row['ci'][1]:.3f}]"
            )
            lines.append(
                f"| {task} | {control} | {row['n']} | {number(None if row['mean'] is None else row['mean'] * 100)} | {interval} |"
            )
    lines += [
        "",
        "## Representation",
        "",
        "Same frontend/data/head and width; parameter counts need not match. Accuracy is percent, with sample SD. Each task uses the common two-LR CPU allowance, not architecture-specific optimal tuning.",
        "",
        "| Architecture | MNIST | FSDD | Multimodal query | Long memory |",
        "|---|---:|---:|---:|---:|",
    ]
    for arch in ARCHITECTURES:
        entries = [
            mean_sd(summary["representation"][task][arch], "accuracy", 100)
            for task in ("mnist", "fsdd", "multimodal_select", "long_memory")
        ]
        lines.append("| " + " | ".join([arch] + entries) + " |")
    lines += [
        "",
        "### Representation cross-entropy and actual cost",
        "",
        "| Task | Architecture | n | CE | Parameters | All-LR examples, mean | Full search CPU, mean s |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for task, architectures in summary["representation"].items():
        for arch in ARCHITECTURES:
            row = architectures[arch]
            lines.append(
                f"| {task} | {arch} | {row['n']} | {mean_sd(row, 'cross_entropy')} | {number(row['parameters']['mean'], 0)} | {number(row['examples_both_lrs']['mean'], 1)} | {number(row['total_search_cpu_seconds']['mean'])} |"
            )
    lines += [
        "",
        "### Modality query subsets",
        "",
        "These are test subsets, not independently trained encoders or input-masking interventions.",
        "",
        "| Architecture | Image-query accuracy % | Spoken-query accuracy % | Conflicting-class accuracy % |",
        "|---|---:|---:|---:|",
    ]
    for arch in ARCHITECTURES:
        row = summary["representation"]["multimodal_select"][arch]
        values = [
            mean_sd(row, key, 100)
            for key in ("image_accuracy", "spoken_accuracy", "conflict_accuracy")
        ]
        lines.append("| " + " | ".join([arch] + values) + " |")
    lines += [
        "",
        "## Scaling",
        "",
        "Accuracy %, mean ± sample SD across three seeds when complete. Capacity/data/history axes are separate. The joint multimodal configuration uses null-step length stress; long_memory adds genuine distractors.",
        "",
        "| Config | Axis | Task | W/D/N/T | HCSN | Mamba-1 | Transformer |",
        "|---:|---|---|---|---:|---:|---:|",
    ]
    for row in summary["scaling"]:
        shape = f"{row['width']}/{row['depth']}/{row['train_size']}/{row['length']}"
        values = [
            mean_sd(row["architectures"][arch], "accuracy", 100)
            for arch in ("hcsn", "mamba1", "transformer")
        ]
        lines.append(
            "| "
            + " | ".join(
                [str(row["configuration"]), row["axis"], row["task"], shape] + values
            )
            + " |"
        )
    lines += [
        "",
        "### Scaling CE, parameters and exposure",
        "",
        "| Config | Architecture | n | CE | Parameters | All-LR updates, mean | All-LR examples, mean | Full search CPU, mean s |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for config in summary["scaling"]:
        for arch, row in config["architectures"].items():
            lines.append(
                f"| {config['configuration']} | {arch} | {row['n']} | {mean_sd(row, 'cross_entropy')} | {number(row['parameters']['mean'], 0)} | {number(row['updates_both_lrs']['mean'], 1)} | {number(row['examples_both_lrs']['mean'], 1)} | {number(row['total_search_cpu_seconds']['mean'])} |"
            )
    lines += [
        "",
        "## Learning-rate choices and allowance exhaustion",
        "",
        "| Stage | Group | Architecture | Selected LR counts | Exhausted candidate allowances | Total candidate count | Mean final-step overshoot s |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    collections = [
        (stage, task, arch, row)
        for stage in ("mechanism", "representation")
        for task, groups in summary[stage].items()
        for arch, row in groups.items()
    ]
    collections += [
        ("scaling", str(config["configuration"]), arch, row)
        for config in summary["scaling"]
        for arch, row in config["architectures"].items()
    ]
    for stage, group, arch, row in collections:
        choices = (
            ", ".join(
                f"{rate}: {count}"
                for rate, count in sorted(row["selected_learning_rate_counts"].items())
            )
            or "NA"
        )
        lines.append(
            f"| {stage} | {group} | {arch} | {choices} | {row['candidate_budget_exhausted']} | {row['candidate_count']} | {number(row['overshoot_seconds']['mean'])} |"
        )
    lines += [
        "",
        "## Cost ledger",
        "",
        "Training CPU is a subset of full search CPU. Discarded LR candidates and later updates beyond the selected checkpoint are fully charged. Per-job wall totals can overlap and are not calendar elapsed.",
        "",
        "| Stage | Searches | LR candidates | Training CPU s | Full search CPU s | Updates | Examples | Candidates capped by max_updates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    ledger = summary["cost_ledger"]
    for stage, row in list(ledger["stages"].items()) + [
        ("TOTAL", ledger["successful_jobs"])
    ]:
        lines.append(
            f"| {stage} | {row['jobs']} | {row['candidates']} | {row['recorded_training_cpu_seconds']:.3f} | {row['recorded_total_search_cpu_seconds']:.3f} | {row['updates']} | {row['examples_seen']} | {row['candidates_hitting_update_safeguard']} |"
        )
    execution = ledger["execution"]
    lines += [
        "",
        f"External executions: {execution['attempts']} attempts, {execution['successful_attempts']} successful, {len(execution['failed_attempts'])} failed. Known child CPU: {execution['all_attempt_known_child_cpu_seconds']:.3f} s; unknown-CPU attempts: {len(execution['unknown_child_cpu_attempts'])}. Failed job wall: {execution['failed_cumulative_job_wall_seconds']:.3f} s.",
        "",
        "External worker CPU includes full search CPU and interpreter/import/setup overhead, so these columns must not be added together. Controller self-CPU remains unmeasured. Controller pauses are lifecycle events and do not themselves count as failed scientific jobs.",
        "",
        "| Controller | Lifecycle status | Worker receipts | Known worker CPU s |",
        "|---|---|---:|---:|",
    ]
    for controller in execution["controller_lifecycle"]["invocations"]:
        lines.append(
            f"| {controller['invocation']} | {controller['status']} | {controller['worker_attempts_with_receipts']} | {controller['worker_child_cpu_seconds']:.3f} |"
        )
    lines.append("")
    measurement = summary["measurements"]
    lines += ["## Serial full-batch versus incremental measurements", ""]
    if measurement is None:
        lines += [
            "No measurement audit is available yet. No timing values are inferred.",
            "",
        ]
    else:
        lines += [
            f"Audit status: {measurement['status']}; {measurement['audited']}/{measurement['expected']} cases, {measurement['parity_passing']} parity passes, {measurement['exact_cross_process_replays']} exact separate-process replays.",
            "",
            "Batch=16, two warmups, seven alternating timed repeats. Latencies exclude reset/model hashing, which have separate receipts. Persistent state bytes are not RSS or peak allocations. Measurement is shared-host CPU, not GPU/energy evidence.",
            "",
            "| Job | Batch median ms | Stream median ms | Batch p95 ms | Stream p95 ms | Stream/batch median | Persistent state bytes | Parity |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for row in measurement["measurements"]:
            batch, stream = row["modes"]["batch"], row["modes"]["stream"]
            lines.append(
                f"| {row['id']} | {batch['median_ms']:.3f} | {stream['median_ms']:.3f} | {batch['p95_ms']:.3f} | {stream['p95_ms']:.3f} | {stream['median_ms'] / batch['median_ms']:.3f} | {row['persistent_state_payload_bytes']} | {row['parity']['passed']} |"
            )
    lines += ["", "## Interpretation boundaries", ""]
    lines.extend("- " + value for value in summary["methods"].values())
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", default=str(Path(__file__).resolve().parents[3]))
    parser.add_argument("--results", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    summary = summarize(args.package, args.results)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "COMPARISON_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (output / "COMPARISON_TABLES.md").write_text(format_tables(summary))
    print(json.dumps(summary["coverage"]))
