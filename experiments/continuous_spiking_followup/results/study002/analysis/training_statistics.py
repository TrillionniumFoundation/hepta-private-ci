"""Descriptive seed summaries and the prespecified paired mechanism contrasts."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

from controller_receipts import controller_history


ARCHITECTURES = [
    "hcsn",
    "lif_snn",
    "continuous_rnn",
    "two_gates",
    "cfc",
    "mamba1",
    "transformer",
]
CONTROLS = ["single", "no_adaptation", "ordinary", "continuous_rnn"]


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def describe(values):
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": len(array),
        "mean": float(array.mean()) if len(array) else None,
        "sd": float(array.std(ddof=1)) if len(array) > 1 else None,
        "min": float(array.min()) if len(array) else None,
        "max": float(array.max()) if len(array) else None,
    }


def group_summary(rows):
    rows = sorted(rows, key=lambda row: row["spec"]["seed"])
    metrics = sorted({key for row in rows for key in row["test"] if key != "cases"})
    return {
        "n": len(rows),
        "seeds": [row["spec"]["seed"] for row in rows],
        "job_ids": [row["spec"]["id"] for row in rows],
        "test_metrics": {
            key: describe([row["test"][key] for row in rows if key in row["test"]])
            for key in metrics
        },
        "parameters": describe([row["parameters"]["total"] for row in rows]),
        "backbone_parameters": describe(
            [row["parameters"]["backbone"] for row in rows]
        ),
        "training_cpu_seconds_both_lrs": describe(
            [row["training_cpu_seconds"] for row in rows]
        ),
        "total_search_cpu_seconds": describe(
            [row["total_cpu_seconds"] for row in rows]
        ),
        "total_search_wall_seconds": describe(
            [row["total_wall_seconds"] for row in rows]
        ),
        "updates_both_lrs": describe(
            [sum(c["updates_completed"] for c in row["candidates"]) for row in rows]
        ),
        "examples_both_lrs": describe(
            [sum(c["examples_seen"] for c in row["candidates"]) for row in rows]
        ),
        "selected_checkpoint_update": describe(
            [row["selection"]["selected_update"] for row in rows]
        ),
        "selected_learning_rate_counts": dict(
            Counter(str(row["selection"]["learning_rate"]) for row in rows)
        ),
        "candidate_budget_exhausted": sum(
            c["budget_exhausted"] for row in rows for c in row["candidates"]
        ),
        "candidate_count": 2 * len(rows),
        "overshoot_seconds": describe(
            [
                c["cpu_budget_overshoot_seconds"]
                for row in rows
                for c in row["candidates"]
            ]
        ),
    }


def paired_contrasts(rows):
    groups, result = defaultdict(dict), {}
    for row in rows:
        spec = row["spec"]
        if spec["stage"] == "mechanism":
            groups[(spec["task"], spec["architecture"])][spec["seed"]] = row
    for task in sorted({key[0] for key in groups}):
        reference = groups[(task, "hcsn")]
        result[task] = {}
        for control in CONTROLS:
            other = groups[(task, control)]
            seeds = sorted(set(reference) & set(other))
            differences = [
                reference[seed]["test"]["accuracy"] - other[seed]["test"]["accuracy"]
                for seed in seeds
            ]
            summary = describe(differences)
            critical = (
                float(t.ppf(1 - 0.0125 / 2, len(seeds) - 1)) if len(seeds) > 1 else None
            )
            radius = (
                critical * summary["sd"] / np.sqrt(len(seeds))
                if critical is not None
                else None
            )
            result[task][control] = {
                **summary,
                "seeds": seeds,
                "paired_accuracy_differences": differences,
                "confidence_level": 0.9875,
                "ci": [summary["mean"] - radius, summary["mean"] + radius]
                if radius is not None
                else None,
                "reference": "HCSN minus control; per-task Bonferroni family of four",
                "practical_effect_reference": 0.01,
                "inference_scope": "training-seed variation conditional on fixed follow-up datasets and the frozen search recipe",
            }
    return result


def execution_ledger(results):
    receipts = []
    for stage in ("mechanism", "representation", "scaling"):
        for path in sorted((Path(results) / stage).rglob("EXECUTION_*.json")):
            receipts.append(
                {
                    **read(path),
                    "path": str(path.relative_to(results)),
                    "sha256": digest(path),
                }
            )
    successful = [
        row for row in receipts if row["exit_code"] == 0 and row["result_exists"]
    ]
    failed = [row for row in receipts if row not in successful]
    known = [row for row in receipts if row.get("child_cpu_seconds") is not None]
    return {
        "attempts": len(receipts),
        "successful_attempts": len(successful),
        "failed_attempts": failed,
        "all_attempt_known_child_cpu_seconds": sum(
            row["child_cpu_seconds"] for row in known
        ),
        "unknown_child_cpu_attempts": [
            row["path"] for row in receipts if row.get("child_cpu_seconds") is None
        ],
        "successful_child_cpu_seconds": sum(
            row["child_cpu_seconds"]
            for row in successful
            if row.get("child_cpu_seconds") is not None
        ),
        "failed_known_child_cpu_seconds": sum(
            row["child_cpu_seconds"]
            for row in failed
            if row.get("child_cpu_seconds") is not None
        ),
        "successful_cumulative_job_wall_seconds": sum(
            row["wall_seconds"] for row in successful
        ),
        "failed_cumulative_job_wall_seconds": sum(
            row["wall_seconds"] for row in failed
        ),
        "receipts": receipts,
        "controller_lifecycle": controller_history(results, receipts),
        "scope": "all retained training worker attempts; job wall may overlap; missing CPU remains unknown",
    }


def training_costs(rows, results):
    stage_rows = defaultdict(list)
    for row in rows:
        stage_rows[row["spec"]["stage"]].append(row)

    def totals(values):
        candidates = [candidate for row in values for candidate in row["candidates"]]
        return {
            "jobs": len(values),
            "candidates": len(candidates),
            "nominal_training_cpu_allowance_seconds": sum(
                candidate["cpu_budget_seconds"] for candidate in candidates
            ),
            "recorded_training_cpu_seconds": sum(
                row["training_cpu_seconds"] for row in values
            ),
            "recorded_total_search_cpu_seconds": sum(
                row["total_cpu_seconds"] for row in values
            ),
            "recorded_total_search_wall_seconds": sum(
                row["total_wall_seconds"] for row in values
            ),
            "updates": sum(candidate["updates_completed"] for candidate in candidates),
            "examples_seen": sum(
                candidate["examples_seen"] for candidate in candidates
            ),
            "candidates_hitting_update_safeguard": sum(
                candidate["termination"] == "max_updates" for candidate in candidates
            ),
            "total_final_step_overshoot_seconds": sum(
                candidate["cpu_budget_overshoot_seconds"] for candidate in candidates
            ),
        }

    return {
        "successful_jobs": totals(rows),
        "stages": {key: totals(value) for key, value in stage_rows.items()},
        "execution": execution_ledger(results),
        "scope": "training CPU is included in total search CPU; all LR candidates charged, not only the selected checkpoint; boundary and serial measurement are separate studies",
    }


def compact_run(row, result_sha):
    return {
        "spec": row["spec"],
        "test": row["test"],
        "parameters": row["parameters"],
        "selection": row["selection"],
        "training_cpu_seconds": row["training_cpu_seconds"],
        "total_cpu_seconds": row["total_cpu_seconds"],
        "total_wall_seconds": row["total_wall_seconds"],
        "result_sha256": result_sha,
        "candidates": [
            {
                "index": candidate["candidate_index"],
                "learning_rate": candidate["learning_rate"],
                "updates_completed": candidate["updates_completed"],
                "examples_seen": candidate["examples_seen"],
                "training_cpu_seconds": candidate["costs_seconds"]["training_cpu"],
                "total_cpu_seconds": candidate["total_cpu_seconds"],
                "termination": candidate["termination"],
                "selected_update": candidate["selected_update"],
                "selected_validation_ce": candidate["selected_validation_ce"],
                "history": [
                    {
                        "update": step["update"],
                        "training_cpu_seconds": step["training_cpu_seconds"],
                        "validation_ce": step["validation"]["cross_entropy"],
                        "validation_accuracy": step["validation"]["accuracy"],
                        "crossed_milestone_fractions": step[
                            "crossed_milestone_fractions"
                        ],
                    }
                    for step in candidate["history"]
                ],
            }
            for candidate in row["candidates"]
        ],
    }
