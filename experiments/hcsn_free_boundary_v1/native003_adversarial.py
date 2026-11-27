"""Posthoc adversarial audit: VAL-selected fixed prefix per public read price.

This does not amend the registered native003 result. It deliberately challenges
that result using a simple ordinary controller. Only saved VAL traces select
prefixes; a small independent worker executes fixed1 once on the fresh cohort.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
MAIN = PACKAGE / "results/native003"
PREFIXES = (1, 8, 16, 24, 32)


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


def select_using_validation(output):
    import numpy as np
    started = time.process_time()
    prices = read(PACKAGE / "NATIVE003_PROTOCOL.json")["execution"]["read_prices"]
    trace_path = MAIN / "traces/val.npz"
    with np.load(trace_path, allow_pickle=False) as source:
        correct = np.array(source["correct"], dtype=np.float64, copy=True)
    if correct.shape != (128, 32):
        raise ValueError("Require the saved original-VAL first128 prefix traces")
    choices, table = {}, {}
    for price in prices:
        rows = [{"prefix": prefix, "accuracy": float(correct[:, prefix - 1].mean()),
                 "mean_utility": float((correct[:, prefix - 1] - price * prefix).mean())}
                for prefix in PREFIXES]
        winner = min(rows, key=lambda item: (-item["mean_utility"], item["prefix"]))
        choices[str(price)] = winner["prefix"]
        table[str(price)] = rows
    record = {"schema": "native003-posthoc-fixed-prefix-selection.v1",
              "selected_at_utc": datetime.now(timezone.utc).isoformat(),
              "label": "posthoc adversarial baseline, not a registered native003 arm",
              "candidate_prefixes": list(PREFIXES), "choices": choices, "validation": table,
              "selection_rule": "maximum original-VAL utility independently per price; ties choose smaller prefix",
              "source_val_trace_sha256": sha(trace_path), "selection_uses_fresh_outcomes": False,
              "family_was_proposed_after_main_fresh_results": True,
              "selection_parent_cpu_seconds": time.process_time() - started}
    write(Path(output) / "SELECTION.json", record)
    write(Path(output) / "SELECTION_LOCK.json", {"selection_sha256": sha(Path(output) / "SELECTION.json"),
          "audit_source_sha256": sha(__file__), "main_summary_sha256": sha(MAIN / "SUMMARY.json"),
          "main_freeze_sha256": sha(MAIN / "FREEZE.json"), "fresh_reexecution_started": False})
    return record


def fixed1_worker(output):
    import numpy as np
    import torch
    from .native003_common import load_backbone, verify_freeze

    output = Path(output)
    lock = read(output / "SELECTION_LOCK.json")
    if sha(__file__) != lock["audit_source_sha256"] or sha(output / "SELECTION.json") != lock["selection_sha256"]:
        raise ValueError("Audit code/validation selection changed")
    verify_freeze(MAIN)
    if sha(MAIN / "SUMMARY.json") != lock["main_summary_sha256"]:
        raise ValueError("Original native003 result changed")
    torch.set_num_threads(1)
    model, backbone = load_backbone(read(PACKAGE / "NATIVE003_PROTOCOL.json"))
    path = PACKAGE / "data/native003/fresh_mnist.npz"
    metadata = read(path.with_suffix(".json"))
    with np.load(path, allow_pickle=False) as source:
        x = torch.from_numpy(np.array(source["test_x"][:, 0], copy=True))
        dt = torch.from_numpy(np.array(source["test_dt"][:, 0], copy=True))
        labels = np.array(source["test_y"][:, -1], copy=True)
    ids = metadata["splits"]["test"]["episode_ids"]
    rows, calls = [], 0
    started = time.process_time(), time.perf_counter()
    for index in range(len(x)):
        clock = time.process_time()
        with torch.no_grad():
            logits, _, _ = model.step(x[index:index + 1], dt[index:index + 1], state=None)
            calls += 1
        prediction = int(logits.argmax(-1).item())
        row = {"episode": ids[index], "prediction": prediction, "correct": int(prediction == int(labels[index])),
               "actual_reads": 1, "actual_model_steps": 1, "head_steps": 0, "native_owner_used": False,
               "model_cpu_seconds": time.process_time() - clock,
               "logits_sha256": hashlib.sha256(logits.numpy().tobytes()).hexdigest()}
        write(output / "fixed1" / f"fresh{index:05d}.json", row)
        rows.append(row)
    loop_cpu, loop_wall = time.process_time() - started[0], time.perf_counter() - started[1]
    matches = 0
    for price in (0.005, 0.02, 0.05):
        directory = MAIN / "evaluation" / ("price_" + format(price, ".3f").replace(".", "p")) / "ordinary_mlp"
        for index, row in enumerate(rows):
            old = read(directory / f"fresh{index:05d}/RESULT.json")
            if old["actual_reads"] != 1 or old["prediction"] != row["prediction"]:
                raise ValueError("New fixed1 computation does not match original MLP's first-prefix result")
            matches += 1
    assert calls == len(x) == 128
    result = {"status": "completed", "episodes": len(rows), "actual_model_step_calls": calls,
              "accuracy": sum(row["correct"] for row in rows) / len(rows), "mean_reads": 1,
              "inference_loop_parent_cpu_seconds": loop_cpu, "inference_loop_wall_seconds": loop_wall,
              "inference_cpu_per_episode": loop_cpu / len(rows),
              "sum_model_cpu_seconds": sum(row["model_cpu_seconds"] for row in rows),
              "same_predictions_as_main_allstop1_mlp_cases_checked": matches,
              "dataset_sha256": sha(path), "backbone": backbone, "rows": rows,
              "reuse_contract": "Fixed1 genuinely executed once for each of128 images; same observed predictions and CPU reused across price-only accounting scenarios"}
    write(output / "FIXED1_SUMMARY.json", result)


def run_worker(output):
    env = dict(os.environ)
    env.update({name: "1" for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.native003_adversarial", "--worker", "--output", str(output)]
    start = time.perf_counter()
    with (Path(output) / "WORKER.log").open("x") as log:
        process = subprocess.Popen(command, cwd=REPOSITORY, env=env, stdout=log, stderr=subprocess.STDOUT)
        pid, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    receipt = {"pid": pid, "returncode": process.returncode, "command": command,
               "complete_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
               "wall_seconds": time.perf_counter() - start,
               "whole_child_peak_rss_kib": usage.ru_maxrss,
               "cpu_scope": "wait4 complete fixed1 worker including Python/Torch imports, validation and reports; no native child used"}
    write(Path(output) / "EXECUTION.json", receipt)
    if process.returncode:
        raise RuntimeError("Fixed1 audit worker failed; all evidence preserved")
    return receipt


def aggregate(output, selected, execution):
    main = read(MAIN / "SUMMARY.json")
    main_grid = read(MAIN / "COST_SCENARIOS.json")
    fixed1 = read(Path(output) / "FIXED1_SUMMARY.json")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    parent_cpu = usage.ru_utime + usage.ru_stime
    audit_shared = execution["complete_child_cpu_seconds"] - fixed1["inference_loop_parent_cpu_seconds"] + parent_cpu
    # Conservative: assign the entire saved TRAIN+VAL trace/shared-training
    # pipeline to this VAL-only baseline, plus original setup and new audit setup.
    saved_trace_charge = main["costs"]["traces_and_shared_training_cpu_seconds"]
    shared_setup = main["costs"]["shared_setup_deployment_charge_seconds"] + audit_shared
    by_price, scenarios = [], []
    for cohort in main["cohorts"]:
        price = cohort["read_price"]
        prefix = selected["choices"][str(price)]
        if prefix == 1:
            accuracy, inference_cpu = fixed1["accuracy"], fixed1["inference_cpu_per_episode"]
            provenance = "new actual fixed1 execution, shared across prices because fixed1 has no price-dependent model computation"
        else:
            key = "read_all" if prefix == 32 else f"fixed{prefix}"
            reference = cohort["results"][key]
            accuracy, inference_cpu = reference["accuracy"], reference["execution_cpu_per_episode"]
            provenance = f"reused actual native003 {key} execution at this price; no new full-prefix computation"
        utility = accuracy - price * prefix
        value_head = cohort["results"]["value_maxout"]
        by_price.append({"read_price": price, "validation_selected_prefix": prefix,
                         "ordinary_accuracy": accuracy, "ordinary_mean_reads": prefix,
                         "ordinary_utility": utility, "ordinary_inference_cpu_per_episode": inference_cpu,
                         "value_head_accuracy": value_head["accuracy"], "value_head_mean_reads": value_head["mean_reads"],
                         "value_head_utility": value_head["mean_utility"],
                         "value_minus_ordinary_utility": value_head["mean_utility"] - utility,
                         "execution_provenance": provenance})
        for original in main_grid["rows"]:
            if original["policy"] != "value_maxout" or original["read_price"] != price:
                continue
            n, cpu_price = original["scenario_episodes"], original["utility_units_per_cpu_second"]
            baseline_cpu = (main["costs"]["prior_backbone_training_cpu_seconds"] + saved_trace_charge + shared_setup) / n + inference_cpu
            baseline_scenario = utility - cpu_price * baseline_cpu
            scenarios.append({"read_price": price, "scenario_episodes": n,
                              "utility_units_per_cpu_second": cpu_price,
                              "ordinary_read_only_utility": utility,
                              "ordinary_scenario_utility": baseline_scenario,
                              "ordinary_cpu_charge_per_episode": baseline_cpu,
                              "value_head_scenario_utility": original["scenario_utility"],
                              "value_minus_ordinary_scenario_utility": original["scenario_utility"] - baseline_scenario})
    ordinary_macro = sum(row["ordinary_utility"] for row in by_price) / len(by_price)
    value_macro = sum(row["value_head_utility"] for row in by_price) / len(by_price)
    result = {"schema": "native003-posthoc-adversarial-results.v1", "status": "completed",
              "classification": "posthoc adversarial audit; does not replace registered native003 results",
              "selected_using_original_val_only": True, "selection": selected,
              "by_price": by_price, "ordinary_macro_utility": ordinary_macro,
              "value_head_macro_utility": value_macro, "value_minus_ordinary_macro_utility": value_macro - ordinary_macro,
              "costs": {"new_fixed1_actual_model_steps": fixed1["actual_model_step_calls"],
                        "complete_fixed1_worker_cpu_seconds": execution["complete_child_cpu_seconds"],
                        "fixed1_inference_cpu_per_episode": fixed1["inference_cpu_per_episode"],
                        "audit_orchestrator_cumulative_self_cpu_seconds": parent_cpu,
                        "incremental_audit_cpu_seconds": execution["complete_child_cpu_seconds"] + parent_cpu,
                        "saved_trace_setup_conservatively_charged_seconds": saved_trace_charge,
                        "original_plus_new_audit_setup_charged_seconds": shared_setup,
                        "no_other_head_training_charged": True,
                        "scope": "Reuse of original traces/references is explicit; deployment charge conservatively includes full saved trace setup plus original and new audit setup. Incremental audit CPU counts only new worker and parent work. Final orchestrator serialization follows the self accounting cutoff"},
              "scenario_rows": scenarios, "main_summary_sha256": sha(MAIN / "SUMMARY.json"),
              "limitation": "Baseline family was requested after fresh native003 results were known. VAL-only choice and locked code prevent fresh fitting, but do not turn this into a preregistered fresh-holdout confirmation. Use it to challenge claims of advantage over strong ordinary controllers"}
    write(Path(output) / "SUMMARY.json", result)
    return result


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, output / "SOURCE_SNAPSHOT.py")
    write(output / "REQUEST.json", {"scope": "posthoc adversarial audit", "source_sha256": sha(__file__),
                                    "candidate_prefixes": list(PREFIXES),
                                    "fresh_predictions_used_to_select_prefix": False,
                                    "baseline_family_requested_after_native003_results": True})
    try:
        selected = select_using_validation(output)
        execution = run_worker(output)
        result = aggregate(output, selected, execution)
        print(json.dumps({"status": result["status"], "selected_prefixes": selected["choices"],
                          "ordinary_macro_utility": result["ordinary_macro_utility"],
                          "value_head_macro_utility": result["value_head_macro_utility"],
                          "value_minus_ordinary_macro_utility": result["value_minus_ordinary_macro_utility"]}, sort_keys=True))
    except Exception as error:
        write(output / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
                                       "traceback": traceback.format_exc(), "partial_results_preserved": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    fixed1_worker(args.output) if args.worker else run(args.output)
