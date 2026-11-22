"""Post-hoc verification only: never trains, evaluates a network, or edits source.

Usage: python validate_flow_study.py STUDY_ROOT --source-root FROZEN_REPO
Writes only summary.json and verification.json under --output (default POSTHOC).
Requires completed LAUNCH, CPU Torch and NumPy; checkpoint loads are weights-only.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

import numpy as np
import torch

from validate_flow_details import (
    Checks,
    array_digest,
    check_p4,
    close,
    digest,
    load_checkpoint,
    portfolio_choice,
    read,
    tensor_digest,
)

SOURCE_SHA = "1953148571aa943cc20ad531c2268626acd523cf57cb6adb87e700399b7e3be1"
PLAN_SHA = {
    "stream": "85abd3934cbf3c17bada724154378134fefcf227e7d8b7294b88b315d25af5f8",
    "adaptation": "aa92a1684d22e20a4d86785f66c4ecd0c6bc79619e5f39b92df8f674e7cdc545",
}
HCSN = (
    "hcsn_feedback",
    "hcsn_no_feedback",
    "hcsn_drop_value_risk",
    "hcsn_ordinary_tanh",
)


def check_stream(directory, entry, plan, checks):
    prefix = f"stream/{entry['arm']}/{entry['seed']}"
    check = lambda value, label: checks.check(value, prefix + "/" + label)
    result = read(directory / "RESULT.json")
    check(
        result["state"] == "completed"
        and result["arm"] == entry["arm"]
        and result["seed"] == entry["seed"],
        "complete_identity",
    )
    check(
        read(directory / "PLAN.json") == plan
        and digest(directory / "PLAN.json") == result["plan_sha256"],
        "saved_plan_hash",
    )
    check(
        result["data"]["source_sha256"]
        == "c090ee5c94b61762bfec9d22767864490b51030f98cca030f02822468db25d9c",
        "source_csv",
    )
    runtime = result["runtime"]
    check(
        runtime["torch_threads"] == runtime["torch_interop_threads"] == 1
        and runtime["deterministic_algorithms"]
        and runtime["model_parameter_devices"] == ["cpu"]
        and runtime["model_parameter_dtypes"] == ["torch.float64"],
        "actual_runtime",
    )
    curve, updates = result["curve"], result["updates"]
    check(
        [row["step"] for row in curve] == plan["checkpoints"] == [0, 32, 64],
        "evaluation_schedule",
    )
    check(
        [row["step"] for row in updates] == list(range(1, plan["steps"] + 1))
        and result["updates_completed"] == len(updates) == 64,
        "all_64_updates",
    )
    check(all(math.isfinite(row["dev_probe_mse"]) for row in curve), "finite_dev_curve")
    best = curve[0]
    for row in curve[1:]:
        if row["dev_probe_mse"] < best["dev_probe_mse"] - 1e-12:
            best = row
    check(
        result["selected_step"] == best["step"]
        and close(result["selected_dev_mse"], best["dev_probe_mse"]),
        "dev_only_checkpoint_selection",
    )
    check(
        result["adoption"] == ("NoUpdate" if best["step"] == 0 else "Candidate"),
        "no_update_outcome",
    )
    train_ids = result["data"]["train_ids"]
    generator = torch.Generator().manual_seed(entry["seed"] ^ 0x539)
    for update in updates:
        indices = torch.randperm(len(train_ids), generator=generator)[
            : plan["batch_size"]
        ].tolist()
        check(
            update["batch_ids"] == [train_ids[i] for i in indices],
            f"declared_batch/{update['step']}",
        )
    with np.load(directory / "predictions.npz", allow_pickle=False) as artifact:
        prediction, targets, ids = (
            artifact["prediction"],
            artifact["targets"],
            artifact["ids"],
        )
    check(
        prediction.shape == targets.shape
        and len(ids) == len(targets) == result["final"]["windows"]
        and np.isfinite(prediction).all()
        and np.isfinite(targets).all(),
        "saved_prediction_shape_values",
    )
    mse = float(np.square(prediction - targets).mean())
    accuracy = float((prediction.argmax(-1) == targets.argmax(-1)).mean())
    check(
        close(mse, result["final"]["mse"])
        and close(accuracy, result["final"]["accuracy"])
        and result["test_evaluations"] == 1,
        "independent_saved_prediction_metrics",
    )
    checkpoint = load_checkpoint(directory / "checkpoint.pt")
    check(
        checkpoint["plan"] == plan
        and checkpoint["plan_sha256"] == result["plan_sha256"]
        and checkpoint["identity"] == result["model"]
        and checkpoint["runtime"] == runtime,
        "checkpoint_binding",
    )
    check(
        checkpoint["selected"]["step"] == best["step"]
        and close(checkpoint["selected"]["dev_mse"], best["dev_probe_mse"]),
        "saved_selected_checkpoint",
    )
    check(
        torch.equal(checkpoint["generator_state"], generator.get_state()),
        "saved_batch_generator",
    )
    identity = result["model"]
    count = identity["parameters"]
    state_bytes = identity["persistent_state_bytes_per_stream"]
    probe_count = checkpoint["selected"]["probe"]["weights"].numel()
    check(
        probe_count == result["selected_probe_parameters"]
        and result["selected_total_parameters"] == count + probe_count,
        "total_parameters_include_probe",
    )
    check(
        abs(count - plan["parameter_target"]) / plan["parameter_target"]
        <= plan["parameter_relative_tolerance"]
        and state_bytes <= plan["persistent_state_cap_bytes"],
        "capacity_band_and_state_cap",
    )
    if entry["arm"] in HCSN:
        names = identity["trainable_names"]
        cfg = identity["config"]
        check(
            tensor_digest(
                {name: checkpoint["selected"]["model"][name] for name in names}
            )
            == best["parameters_sha256"],
            "selected_parameter_hash",
        )
        check(
            sum(checkpoint["selected"]["model"][name].numel() for name in names)
            == count,
            "saved_parameter_count",
        )
        check(
            state_bytes
            == ((cfg["width"] + 1) * (cfg["bins"] + cfg["stages"] + 1) + 1) * 8,
            "physical_state_bytes",
        )
    check(
        0 <= result["wall_seconds"] <= entry["cold_wall_seconds"]
        and close(result["work_wall_seconds"], result["wall_seconds"]),
        "complete_cold_cost",
    )
    check(
        close(
            result["budget_overrun_seconds"],
            max(0.0, result["wall_seconds"] - plan["arm_wall_cap_seconds"]),
        ),
        "budget_overrun_account",
    )
    for target in plan["quality_targets_dev_mse"]:
        expected = next(
            (p["elapsed_seconds"] for p in curve if p["dev_probe_mse"] <= target), None
        )
        actual = result["quality_target_first_seconds"][str(target)]
        check(
            actual is None if expected is None else close(actual, expected),
            "recorded_quality_target/" + str(target),
        )
    return {
        "study": "stream",
        "arm": entry["arm"],
        "seed": entry["seed"],
        "state": result["state"],
        "adoption": result["adoption"],
        "selected_step": best["step"],
        "selected_dev_mse": best["dev_probe_mse"],
        "initial_dev_mse": curve[0]["dev_probe_mse"],
        "dev_improvement": curve[0]["dev_probe_mse"] - best["dev_probe_mse"],
        "test_mse": mse,
        "test_accuracy": accuracy,
        "test_next_sensor_mse": result["final"]["next_sensor_mse"],
        "cold_wall_seconds": entry["cold_wall_seconds"],
        "work_wall_seconds": result["wall_seconds"],
        "cpu_seconds": result["cpu_seconds"],
        "parameters": count,
        "probe_parameters": probe_count,
        "total_parameters": count + probe_count,
        "state_bytes": state_bytes,
        "updates_completed": len(updates),
        "backward_evaluations": len(updates),
        "initial_parameters_sha256": result["initial_parameters_sha256"],
        "batch_trace_sha256": hashlib.sha256(
            json.dumps([p["batch_ids"] for p in updates]).encode()
        ).hexdigest(),
        "test_data_digest": array_digest({"ids": ids, "targets": targets}),
    }


def aggregate(rows, plans):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["study"], row["arm"])].append(row)
    result = []
    for (study, arm), items in sorted(groups.items()):
        metrics = {}
        for key in sorted(set().union(*(item.keys() for item in items))):
            values = [
                item[key]
                for item in items
                if type(item.get(key)) in (int, float) and key != "seed"
            ]
            if values:
                metrics[key] = {
                    "n": len(values),
                    "mean": statistics.mean(values),
                    "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
                    "median": statistics.median(values),
                }
        result.append(
            {
                "study": study,
                "arm": arm,
                "planned_seeds": len(plans[study]["seeds"]),
                "reported_seeds": len(items),
                "adoption_counts": dict(
                    Counter(item.get("adoption", "unavailable") for item in items)
                ),
                "selected_step_counts": dict(
                    Counter(
                        str(item["selected_step"])
                        for item in items
                        if "selected_step" in item
                    )
                ),
                "metrics": metrics,
            }
        )
    return result


def validate(root, source_root, output):
    began = time.perf_counter()
    checks = Checks()
    rows = []
    launch = read(root / "LAUNCH.json")
    if launch.get("state") == "running" or "active_trial" in launch:
        raise RuntimeError(
            "study is still running; partial results are deliberately not inspected"
        )
    source = read(root / "SOURCE_MANIFEST.json")
    plans = {name: read(root / (name.upper() + "_PLAN.json")) for name in PLAN_SHA}
    checks.check(
        digest(root / "SOURCE_MANIFEST.json")
        == SOURCE_SHA
        == launch["source_manifest_sha256"],
        "frozen_source_manifest",
    )
    checks.check(len(source["files"]) == 119, "source_file_count")
    source_map = {}
    for item in source["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            checks.check(False, "unsafe_source_path", str(relative))
            continue
        path = source_root / relative
        checks.check(
            path.is_file()
            and digest(path) == item["sha256"]
            and path.stat().st_size == item["bytes"],
            "source/" + str(relative),
        )
        source_map[str(relative)] = item["sha256"]
    for name, plan in plans.items():
        checks.check(
            digest(root / (name.upper() + "_PLAN.json"))
            == PLAN_SHA[name]
            == launch["plans_sha256"][name],
            "frozen_plan/" + name,
        )
    declared = [
        {"study": name, "arm": arm, "seed": seed}
        for name, plan in plans.items()
        for seed in plan["seeds"]
        for arm in plan["arms"]
    ]
    random.Random(76129).shuffle(declared)
    keys = [(p["study"], p["arm"], p["seed"]) for p in launch["trials"]]
    checks.check(
        len(declared) == len(keys) == len(set(keys)) == 45
        and launch["declared_order"] == declared,
        "all_45_unique_declared_trials",
    )
    checks.check(
        keys == [(p["study"], p["arm"], p["seed"]) for p in declared],
        "declared_serial_order",
    )
    checks.check(
        launch["state"] == "completed"
        and launch["concurrent_children"] == 1
        and launch["no_automatic_retries"] is True,
        "complete_serial_no_retry_ledger",
    )
    for i, entry in enumerate(launch["trials"]):
        before = len(checks.rows)
        label = f"{entry['study']}/{entry['arm']}/{entry['seed']}"
        try:
            checks.check(
                entry["index"] == i
                and entry["exit_code"] == 0
                and entry["state"] == "completed",
                label + "/process_exit",
            )
            directory = root / entry["study"] / f"{entry['arm']}-{entry['seed']}"
            report_path = directory / (
                "RESULT.json" if entry["study"] == "stream" else "STUDY.json"
            )
            checks.check(
                digest(report_path) == entry["report_sha256"]
                and read(report_path)["state"] == entry["reported_state"],
                label + "/launcher_report_hash",
            )
            checks.check(
                all((root / entry[key]).is_file() for key in ("stdout", "stderr")),
                label + "/complete_logs",
            )
            checks.check(
                math.isfinite(entry["cold_wall_seconds"])
                and entry["cold_wall_seconds"] >= 0,
                label + "/finite_cold_cost",
            )
            row = (
                check_stream(directory, entry, plans["stream"], checks)
                if entry["study"] == "stream"
                else check_p4(directory, entry, plans["adaptation"], source_map, checks)
            )
        except Exception as error:
            checks.check(
                False,
                label + "/read_or_validation_error",
                type(error).__name__ + ": " + str(error),
            )
            row = {
                "study": entry["study"],
                "arm": entry["arm"],
                "seed": entry["seed"],
                "state": entry["state"],
                "cold_wall_seconds": entry.get("cold_wall_seconds"),
                "validation_error": str(error),
            }
        row["verified"] = all(p["passed"] for p in checks.rows[before:])
        rows.append(row)
    for seed in plans["stream"]["seeds"]:
        stream = [
            row for row in rows if row["study"] == "stream" and row["seed"] == seed
        ]
        checks.check(
            len(stream) == 10
            and len({p.get("batch_trace_sha256") for p in stream}) == 1
            and all(p.get("batch_trace_sha256") for p in stream),
            f"shared_batch_ids/{seed}",
        )
        group = [p for p in stream if p["arm"] in HCSN]
        checks.check(
            len(group) == 4
            and len(
                {
                    (
                        p.get("initial_parameters_sha256"),
                        p.get("parameters"),
                        p.get("state_bytes"),
                    )
                    for p in group
                }
            )
            == 1
            and all(p.get("initial_parameters_sha256") for p in group),
            f"hcsn_four_equal_initialization_capacity/{seed}",
        )
        p4 = [p for p in rows if p["study"] == "adaptation" and p["seed"] == seed]
        checks.check(
            len(p4) == 5
            and len({p.get("initial_state_digest") for p in p4}) == 1
            and all(p.get("initial_state_digest") for p in p4),
            f"p4_common_incumbent/{seed}",
        )
        checks.check(
            len({p.get("prepared_data_digest") for p in p4}) == 1
            and all(p.get("prepared_data_digest") for p in p4),
            f"p4_common_inputs/{seed}",
        )
    tests = [p.get("test_data_digest") for p in rows if p["study"] == "stream"]
    checks.check(
        len(tests) == 30 and all(tests) and len(set(tests)) == 1,
        "common_stream_test_targets_ids",
    )
    cold = sum(float(p["cold_wall_seconds"]) for p in launch["trials"])
    checks.check(
        launch["elapsed_seconds"] + 1e-6 >= cold
        and launch["launcher_setup_seconds"] >= 0,
        "cold_lifecycle_total_accounting",
    )
    portfolios = portfolio_choice(rows, plans["adaptation"])
    checks.check(
        all(row["status"] == "recorded" for row in portfolios),
        "three_verified_portfolio_choices",
    )
    summary = {
        "schema": "hcsn-flow-posthoc-summary-v1",
        "verification_passed": checks.ok,
        "per_seed": rows,
        "portfolio_choice": portfolios,
        "aggregates": aggregate(rows, plans),
        "cold_cost": {
            "children_seconds": cold,
            "launcher_elapsed_seconds": launch["elapsed_seconds"],
            "launcher_setup_seconds": launch["launcher_setup_seconds"],
            "launcher_accounted_total_seconds": launch["elapsed_seconds"]
            + launch["launcher_setup_seconds"],
        },
        "scope": "stream test scores are recomputed from saved predictions; P4 scores are recorded next-sensor development/preservation only",
        "no_update_cost": "all cold process cost retained even when step zero or KEEP wins",
    }
    verification = {
        "passed": checks.ok,
        "check_count": len(checks.rows),
        "failures": [p for p in checks.rows if not p["passed"]],
        "checks": checks.rows,
        "launch_sha256": digest(root / "LAUNCH.json"),
        "source_manifest_sha256": SOURCE_SHA,
        "validator_sources": {
            name: digest(Path(__file__).with_name(name))
            for name in ("validate_flow_study.py", "validate_flow_details.py")
        },
        "verification_seconds": time.perf_counter() - began,
        "limits": [
            "No network forward or training rerun; P4 gates replay recorded scores, not independent score predictions.",
            "Stream initial tensors were not saved; common initial parameter hashes and persisted selected counts are cross-checked.",
            "P4 parses the full source including test rows but performs zero test scoring; preservation covers only its declared sensor windows.",
            "Three-seed sample SD is descriptive; no population superiority or global knowledge-preservation inference.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("summary.json", summary), ("verification.json", verification)):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    return verification


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("studyroot", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(
        args.studyroot.resolve(),
        args.source_root.resolve(),
        (args.output or args.studyroot / "POSTHOC").resolve(),
    )
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "checks": result["check_count"],
                "failures": len(result["failures"]),
            },
            allow_nan=False,
        )
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
