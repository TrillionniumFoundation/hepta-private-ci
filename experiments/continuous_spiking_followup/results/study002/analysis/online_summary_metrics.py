"""Seed-level boundary and descriptive CPU-stream summaries from audited evidence."""

import json

import numpy as np
from scipy.stats import t

from online_audit_common import check, sha


POLICIES = ("fixed", "direct", "value", "full")


def describe(values):
    array = np.asarray(values, dtype=np.float64)
    return {
        "n": len(array),
        "mean": float(array.mean()),
        "sd": float(array.std(ddof=1)) if len(array) > 1 else None,
        "min": float(array.min()),
        "max": float(array.max()),
        "values": array.tolist(),
    }


def paired_interval(values):
    summary = describe(values)
    n = summary["n"]
    check(n == 5, "five prespecified paired actor seeds")
    critical = float(t.ppf(1 - 0.05 / (2 * 4), n - 1))
    half = critical * summary["sd"] / np.sqrt(n)
    return {
        **summary,
        "confidence": 0.9875,
        "degrees_of_freedom": n - 1,
        "critical_t": critical,
        "lower": summary["mean"] - half,
        "upper": summary["mean"] + half,
        "family": "four ID/OOD value-minus-fixed/direct net-utility contrasts",
        "pairing": "same actor seed and heldout episodes; five seed means, not pooled episode pseudo-replicates",
    }


def boundary_summary(study, audit):
    seeds = sorted(audit["boundary"], key=int)
    check(
        seeds == [str(x) for x in range(4401, 4406)], "complete boundary seed inventory"
    )
    sources, fits, counts = {}, [], {}
    for seed in seeds:
        directory = study / "boundary" / f"seed{seed}"
        check(
            sha(directory / "RESULT.json") == audit["boundary"][seed]["result_sha256"],
            "audited boundary result unchanged",
        )
        result = json.loads((directory / "RESULT.json").read_text())
        start = json.loads((directory / "START.json").read_text())
        sources[seed] = result
        policy = result["policy_fit"]
        fits.append(
            {
                "seed": int(seed),
                "shared_temperature": policy["temperature"],
                "fixed_threshold": policy["fixed"]["threshold"],
                "direct_parameters": policy["direct"]["parameters"],
                "temperature_cpu_seconds": policy["temperature_cpu_seconds"],
                "fixed_selection_cpu_seconds": policy["fixed_selection_cpu_seconds"],
                "direct_training_cpu_seconds": policy["direct_training_cpu_seconds"],
                "policy_fit_total_cpu_seconds": policy["total_cpu_seconds"],
                "actor_prefix_inference_cpu_seconds": result[
                    "fitting_prefix_cpu_seconds"
                ],
                "bellman_table_cpu_seconds": result["bellman_table_build_cpu_seconds"],
                "new_study_parent_cpu_seconds": result["total_cpu_seconds"],
                "new_study_wall_seconds": result["total_wall_seconds"],
                "historical_actor_training_cpu_seconds": start[
                    "historical_actor_training_cpu_seconds"
                ],
            }
        )
        for key, value in audit["boundary"][seed]["counts"].items():
            counts[key] = counts.get(key, 0) + value
    metrics = (
        "accuracy",
        "mean_observations",
        "mean_cost",
        "net_utility",
        "total_processed_rows",
        "total_avoided_model_steps",
        "loop_cpu_seconds",
        "loop_wall_seconds",
    )
    splits, contrasts = {}, {}
    for split in ("id", "ood"):
        splits[split] = {
            mode: {
                key: describe([sources[s]["metrics"][split][mode][key] for s in seeds])
                for key in metrics
            }
            for mode in POLICIES
        }
        for comparator in ("fixed", "direct"):
            differences = [
                sources[s]["metrics"][split]["value"]["net_utility"]
                - sources[s]["metrics"][split][comparator]["net_utility"]
                for s in seeds
            ]
            contrasts[f"{split}/value-minus-{comparator}"] = paired_interval(
                differences
            )
    calibration = {
        split: {
            kind: {
                metric: describe(
                    [
                        sources[s]["metrics"][split]["calibration"][kind][metric]
                        for s in seeds
                    ]
                )
                for metric in ("prefix_ce", "prefix_brier")
            }
            for kind in ("raw", "shared_temperature")
        }
        for split in ("id", "ood")
    }
    checks = [
        item
        for seed in audit["boundary"].values()
        for split in seed["splits"].values()
        for policy in split["native"].values()
        for item in policy["checks"]
    ]
    native_totals = {
        key: sum(item[key] for item in checks)
        for key in (
            "observations",
            "processes",
            "cold_recoveries",
            "policy_disagreements",
            "same_stop_as_python",
            "native_child_cpu_seconds",
            "parent_lifetime_cpu_seconds",
            "parent_lifetime_wall_seconds",
            "archive_cpu_seconds",
            "archive_wall_seconds",
            "archive_bytes",
            "archive_uncompressed_bytes",
        )
    }
    native_totals["episodes"] = len(checks)
    native_totals["counters"] = (
        {
            key: sum(item["counters"][key] for item in checks)
            for key in checks[0]["counters"]
        }
        if checks
        else {}
    )
    native_totals["quantized_disagreements"] = [
        item for case in checks for item in case["quantized_disagreements"]
    ]
    native_splits = {
        split: {
            mode: {
                "metrics": row["metrics"],
                "same_stop_count": row["same_stop_count"],
                "cold_resume_count": row["cold_resume_count"],
            }
            for mode, row in audit["boundary"]["4403"]["splits"][split][
                "native"
            ].items()
        }
        for split in ("id", "ood")
    }
    return {
        "seeds": [int(s) for s in seeds],
        "counts": counts,
        "splits": splits,
        "paired_utility_intervals": contrasts,
        "calibration": calibration,
        "fits": fits,
        "cost_totals": {
            key: sum(row[key] for row in fits)
            for key in fits[0]
            if key.endswith("seconds")
        },
        "native": {
            "totals": native_totals,
            "splits": native_splits,
            "scope": "Seed 4403, first 16 episodes per split/policy; fixed deterministic signed-score compilation using original sparse kernel and NDU. Parent lifetime overlaps task timing; native child CPU is separately measured. No whole-Python restart claim.",
        },
    }


def performance_summary(study, audit):
    checked = audit["performance"]["cases"]
    discovered = {}
    for path in study.rglob("MEASUREMENT.json"):
        if "failed_attempts" in path.relative_to(study).parts:
            continue
        result = json.loads(path.read_text())
        discovered[result["identity"]["spec"]["id"]] = (path, result)
    rows, cold = [], []
    for case, verification in sorted(checked.items()):
        path, result = discovered[case]
        check(
            sha(path) == verification["measurement_sha256"],
            "audited measurement unchanged",
        )
        spec, modes = result["identity"]["spec"], result["measurement"]
        train = json.loads((study / case / "RESULT.json").read_text())
        batch, stream = modes["batch"], modes["stream"]
        reset = [
            row["reset_with_identity_check"]["wall_seconds"]
            for row in result["raw_samples"]
            if row["phase"] == "measurement" and row["mode"] == "stream"
        ]
        row = {
            "id": case,
            "spec": spec,
            "test": train["test"],
            "parameters": train["parameters"],
            "batch_size": result["fixed_batch"]["batch_size"],
            "batch_wall_seconds": batch["wall_latency_seconds"],
            "stream_wall_seconds": stream["wall_latency_seconds"],
            "batch_process_cpu_seconds": batch["process_cpu_seconds_stats"],
            "stream_process_cpu_seconds": stream["process_cpu_seconds_stats"],
            "stream_over_batch_wall_median": stream["wall_latency_seconds"]["median"]
            / batch["wall_latency_seconds"]["median"],
            "batch_examples_per_second": batch["examples_per_second"]["median"],
            "stream_examples_per_second": stream["examples_per_second"]["median"],
            "stream_reset_wall_seconds": describe(reset),
            "stream_reset_plus_forward_wall_median": float(
                np.median(stream["reset_plus_forward_wall_seconds"])
            ),
            "state_bytes": result["parity"]["final_state_payload_bytes"],
            "state_bytes_initial": result["parity"][
                "state_payload_bytes_initial_and_after_each_step"
            ][0],
            "parity": {
                key: result["parity"][key]
                for key in (
                    "passed",
                    "max_abs_logit_error",
                    "tensor_entries_outside_tolerance",
                    "prefix_predicted_class_changes",
                    "final_predicted_class_changes",
                    "saved_training_predictions_within_tolerance",
                )
            },
            "setup_costs": result["setup_costs"],
            "preparation_costs": result["preparation_costs"],
            "measurement_sha256": verification["measurement_sha256"],
        }
        rows.append(row)
        replay = result["cross_process_replay"]
        if replay["status"] != "not_selected":
            cold.append(
                {
                    "id": case,
                    "architecture": spec["architecture"],
                    "passed": replay["passed"],
                    "distinct_process": replay["distinct_process"],
                    "exact_logits": replay["exact_logits"],
                    "exact_final_state": replay["exact_final_state"],
                    "split_step": replay["split_step"],
                    "parent_expected_final_state_sha256": replay[
                        "parent_expected_final_state_sha256"
                    ],
                    "external_process_cost_seconds": replay[
                        "external_process_cost_seconds"
                    ],
                    "state_receipt": replay["state_receipt"],
                    "child_costs_seconds": replay["child"]["costs_seconds"],
                    "child_module_total_wall_seconds": replay["child"][
                        "module_total_wall_seconds"
                    ],
                }
            )
    return {
        "cases": rows,
        "cold_replay": cold,
        "parity_failures": [r["id"] for r in rows if not r["parity"]["passed"]],
        "prefix_class_changes": sum(
            r["parity"]["prefix_predicted_class_changes"] for r in rows
        ),
        "final_class_changes": sum(
            r["parity"]["final_predicted_class_changes"] for r in rows
        ),
        "maximum_logit_error": max(
            (r["parity"]["max_abs_logit_error"] for r in rows), default=0
        ),
        "measurement_repeats": 7,
        "warmups": 2,
        "rtol": 3e-5,
        "atol": 3e-6,
        "scope": "Single-thread CPU float32, B16, same selected model and inputs. Full-sequence final-logit forward versus all T true incremental steps. Seven serial repeats are descriptive host samples, not confidence intervals; no GPU/optimized-kernel, FLOP, RSS or energy equivalence.",
    }
