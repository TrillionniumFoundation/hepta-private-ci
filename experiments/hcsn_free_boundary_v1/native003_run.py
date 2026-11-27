"""Stdlib-only native003 orchestrator with complete worker wait4 accounting.

wait4 for an evaluator already includes its waited native descendants. Inner
native receipts are a breakdown, never added again to the evaluator total.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
PROTOCOL = PACKAGE / "NATIVE003_PROTOCOL.json"
FAMILIES = ("value_maxout", "ordinary_mlp", "risk_threshold")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def freeze(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = read(PACKAGE / "FREEZE.json")
    protocol = read(PROTOCOL)
    if original["identity_sha256"] != protocol["original_freeze_identity"]:
        raise ValueError("Wrong original study freeze")
    files = dict(original["files"])
    for name, expected in files.items():
        if sha(REPOSITORY / name) != expected:
            raise ValueError(f"Original frozen source/data changed: {name}")
    fresh = PACKAGE / "data/native003/fresh_mnist.npz"
    manifest = read(fresh.with_suffix(".json"))
    if sha(fresh) != manifest["sha256"] or manifest["model_inference_performed"]:
        raise ValueError("Fresh data identity or inference history differs")
    if any(row["image_source_overlap"] or row["episode_id_overlap"] for row in manifest["disjoint_from_original"].values()):
        raise ValueError("Fresh cohort overlaps old evidence")
    if not all(row["exact_equal"] for row in manifest["prefix_reproduction"].values()):
        raise ValueError("Original test prefix did not reproduce exactly")
    paths = list(PACKAGE.glob("native003_*.py")) + [PROTOCOL, PACKAGE / "FREEZE.json"]
    paths += [fresh, fresh.with_suffix(".json"), PACKAGE / "data/native003/generation_receipt.json"]
    training_run = PACKAGE / protocol["backbone"]["training_run"]
    paths += [training_run / name for name in ("selected.npz", "selection.json", "summary.json", "EXECUTION.json")]
    files.update({str(path.relative_to(REPOSITORY)): sha(path) for path in paths})
    record = {"schema": "hcsn-native003-code-data-freeze.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "files": files, "original_freeze_identity": original["identity_sha256"],
              "fresh_holdout_inference_performed": False, "head_training_performed": False}
    record["identity_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    write(output / "FREEZE.json", record)
    write(output / "REQUEST.json", {"protocol": protocol, "protocol_sha256": sha(PROTOCOL),
                                    "new_freeze_identity": record["identity_sha256"],
                                    "scope": "separate extension; preserves native002 and study001 unchanged"})
    return record


def check_frozen(output):
    record = read(Path(output) / "FREEZE.json")
    for name, expected in record["files"].items():
        if sha(REPOSITORY / name) != expected:
            raise ValueError(f"native003 frozen input changed: {name}")


def worker(module, output, label):
    env = dict(os.environ)
    env.update({name: "1" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", module, "--output", str(output)]
    start = time.perf_counter()
    with (Path(output) / f"{label}.process.log").open("x") as log:
        process = subprocess.Popen(command, cwd=REPOSITORY, env=env, stdout=log, stderr=subprocess.STDOUT)
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = {"pid": pid, "command": command, "returncode": process.returncode,
               "child_cpu_seconds": usage.ru_utime + usage.ru_stime,
               "child_user_cpu_seconds": usage.ru_utime, "child_system_cpu_seconds": usage.ru_stime,
               "wall_seconds": time.perf_counter() - start, "whole_child_peak_rss_kib": usage.ru_maxrss,
               "cpu_scope": "complete waited worker including imports, final reports and waited descendants",
               "waited_native_descendants_already_included": True}
    write(Path(output) / f"{label}_EXECUTION.json", receipt)
    if process.returncode != 0:
        raise RuntimeError(f"{label} worker failed with exit {process.returncode}; preserved process log")
    return receipt


def lock_head_selections(output, protocol):
    output = Path(output)
    summary = read(output / "TRAINING_SUMMARY.json")
    if summary["status"] != "completed" or summary["fresh_test_inference_performed"]:
        raise ValueError("Training completion or holdout isolation failed")
    prefixes = set()
    paths = [output / "TRAINING_SUMMARY.json", output / "traces/NORMALIZATION.json", output / "traces/TRACE_RECEIPTS.json"]
    for family in FAMILIES:
        result = summary["heads"][family]
        if len(result["candidates"]) != 2:
            raise ValueError("Both declared LR candidates must complete")
        for candidate in result["candidates"]:
            if candidate["updates"] != protocol["optimization"]["updates_per_learning_rate"]:
                raise ValueError("Unequal head training update budget")
            if candidate["parameters"] != protocol["heads"][family]["trainable_parameters"]:
                raise ValueError("Head parameter budget changed")
            prefixes.add(candidate["batch_prefix_sha256"])
        paths += [output / "head_search" / family / name for name in ("selected.npz", "selection.json", "SUMMARY.json")]
    if len(prefixes) != 1:
        raise ValueError("Head/LR minibatch streams were not paired")
    write(output / "TRAINING_LOCK.json", {"schema": "hcsn-native003-head-selection-lock.v1",
          "created_utc": datetime.now(timezone.utc).isoformat(), "fresh_test_predictions_available": False,
          "paired_batch_prefix_sha256": next(iter(prefixes)),
          "files": {str(path.relative_to(output)): sha(path) for path in paths}})


def summarize(output, protocol, train_execution, eval_execution):
    output = Path(output)
    training = read(output / "TRAINING_SUMMARY.json")
    evaluation = read(output / "EVALUATION_SUMMARY.json")
    data_receipt = read(PACKAGE / "data/native003/generation_receipt.json")
    family_cpu = {name: row["family_search_parent_cpu_seconds"] for name, row in training["heads"].items()}
    shared_train_cpu = train_execution["child_cpu_seconds"] - sum(family_cpu.values())
    native_cpu = (sum(row["native_child_cpu_seconds"] for cohort in evaluation["cohorts"]
                      for row in cohort["results"].values())
                  + sum(row["native_child_cpu_seconds"] for row in evaluation["recovery"].values()))
    policy_parent_cpu = (sum(row["parent_cpu_seconds"] for cohort in evaluation["cohorts"]
                              for row in cohort["results"].values())
                         + sum(row["parent_cpu_seconds"] for row in evaluation["recovery"].values()))
    shared_eval_cpu = eval_execution["child_cpu_seconds"] - native_cpu - policy_parent_cpu
    if min(shared_train_cpu, shared_eval_cpu) < -1e-5:
        raise ValueError("Nested complete-process CPU attribution is inconsistent")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    orchestrator_cpu = usage.ru_utime + usage.ru_stime
    data_cpu = data_receipt["child_total_cpu_seconds"]
    shared_setup = max(0.0, shared_eval_cpu) + data_cpu + orchestrator_cpu
    backbone_cpu = training["backbone"]["complete_training_child_cpu_seconds"]
    rows = []
    for cohort in evaluation["cohorts"]:
        for policy, result in cohort["results"].items():
            head_cpu = family_cpu.get(policy, 0.0)
            trace_cpu = max(0.0, shared_train_cpu) if policy in FAMILIES else 0.0
            recovery = evaluation["recovery"].get(policy, {})
            recovery_cpu = recovery.get("parent_cpu_seconds", 0.0) + recovery.get("native_child_cpu_seconds", 0.0)
            for n in protocol["cost_accounting"]["amortization_episode_counts"]:
                for cpu_price in protocol["cost_accounting"]["utility_units_per_cpu_second"]:
                    total = (backbone_cpu + head_cpu + trace_cpu + shared_setup + recovery_cpu) / n + result["execution_cpu_per_episode"]
                    rows.append({"policy": policy, "read_price": cohort["read_price"], "scenario_episodes": n,
                                 "utility_units_per_cpu_second": cpu_price,
                                 "accuracy": result["accuracy"], "mean_reads": result["mean_reads"],
                                 "read_only_utility": result["mean_utility"],
                                 "backbone_training_cpu_amortized": backbone_cpu / n,
                                 "head_full_search_cpu_amortized": head_cpu / n,
                                 "traces_and_shared_training_cpu_amortized": trace_cpu / n,
                                 "shared_setup_cpu_amortized": shared_setup / n,
                                 "recovery_verification_cpu_amortized": recovery_cpu / n,
                                 "measured_inference_cpu_per_episode": result["execution_cpu_per_episode"],
                                 "scenario_utility": result["mean_utility"] - cpu_price * total})
    costs = {"complete_training_worker_cpu_seconds": train_execution["child_cpu_seconds"],
             "complete_evaluation_worker_cpu_including_native_descendants_seconds": eval_execution["child_cpu_seconds"],
             "native_child_cpu_nested_breakdown_seconds": native_cpu,
             "family_search_cpu_seconds": family_cpu,
             "traces_and_shared_training_cpu_seconds": shared_train_cpu,
             "shared_evaluator_cpu_seconds": shared_eval_cpu,
             "data_generation_complete_child_cpu_seconds": data_cpu,
             "orchestrator_self_cpu_seconds_through_accounting_cutoff": orchestrator_cpu,
             "shared_setup_deployment_charge_seconds": shared_setup,
             "prior_backbone_training_cpu_seconds": backbone_cpu,
             "incremental_native003_cpu_seconds": train_execution["child_cpu_seconds"] + eval_execution["child_cpu_seconds"] + data_cpu + orchestrator_cpu,
             "no_nested_child_double_count": True,
             "scope": "Worker wait4 totals include imports/final worker report IO/native descendants. Orchestrator uses cumulative self CPU through this accounting cutoff; final two orchestrator report writes follow the cutoff. Prior backbone CPU is separate from incremental new work"}
    write(output / "COST_SCENARIOS.json", {"schema": "hcsn-native003-cpu-scenarios.v1", "costs": costs,
          "policy_scenarios_are_alternative_deployments_not_additive": True,
          "energy_measured": False, "rows": rows})
    result = {"status": "completed", "schema": "hcsn-native003-results.v1", "cohorts": evaluation["cohorts"],
              "recovery": evaluation["recovery"], "costs": costs,
              "head_selections": {name: row["selection"] for name, row in training["heads"].items()},
              "source_freeze_identity": read(output / "FREEZE.json")["identity_sha256"],
              "fresh_episodes": evaluation["fresh_episodes"],
              "limitations": protocol["interpretation"], "hardware_energy_measured": False}
    write(output / "SUMMARY.json", result)
    return result


def run(output):
    output = Path(output)
    freeze(output)
    protocol = read(PROTOCOL)
    try:
        train_execution = worker("experiments.hcsn_free_boundary_v1.native003_train", output, "TRAINING")
        check_frozen(output)
        lock_head_selections(output, protocol)
        eval_execution = worker("experiments.hcsn_free_boundary_v1.native003_eval", output, "EVALUATION")
        check_frozen(output)
        result = summarize(output, protocol, train_execution, eval_execution)
        print(json.dumps({"status": result["status"], "fresh_episodes": result["fresh_episodes"],
                          "incremental_cpu_seconds": result["costs"]["incremental_native003_cpu_seconds"],
                          "output": str(output)}, sort_keys=True))
        return result
    except Exception as error:
        write(output / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
                                       "traceback": traceback.format_exc(), "all_partial_results_preserved": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
