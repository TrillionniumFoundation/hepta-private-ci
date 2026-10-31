"""Registered, read-only audit of sealed arms from training-001, with process cost."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback


REPO = Path("/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery")
AREA = REPO / "experiments/multimodal_output_portfolio"
TRAINING = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/training-001")
OUTPUT = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/training-audit-001")


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_pins(training):
    paths = [AREA / name for name in training["source_sha256"]]
    paths += [AREA / "abc_recovery/evidence_audit.py", AREA / "abc_recovery/evidence_audit_tests.py", Path(__file__).resolve()]
    return {str(path): file_sha(path) for path in paths}


def execute(registration_path):
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    registration = json.loads(Path(registration_path).read_text())
    training = json.loads((TRAINING / "registration.json").read_text())
    models, phases, wait_ns = [], {}, 0
    try:
        if source_pins(training) != registration["source_sha256"]:
            raise ValueError("Audit source code changed after registration")
        for name, sha in registration["input_file_sha256"].items():
            if file_sha(name) != sha:
                raise ValueError("Audit input file changed after registration: " + name)
        loaded_wall, loaded_cpu = time.perf_counter_ns(), time.process_time_ns()
        sys.path.insert(0, str(REPO))
        import torch
        from experiments.multimodal_output_portfolio.v6.neural import parameter_hash
        from experiments.multimodal_output_portfolio.v7.evaluation import load_reward
        from experiments.multimodal_output_portfolio.v7.sources import load_roles
        from experiments.multimodal_output_portfolio.abc_recovery.evidence_audit import audit_training_arm
        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(training["deterministic_algorithms"])
        paths = training["paths"]
        corpus = load_roles(paths["cache"], paths["manifest"], roles=("train",))
        observer, _ = load_reward(paths["primary"], training["files_sha256"]["primary"])
        if parameter_hash(observer) != registration["primary_parameter_sha256"] or set(corpus.splits) != {"train"}:
            raise ValueError("Unexpected observer identity or source role access")
        phases["imports_and_train_source_loading"] = {"wall_ns": time.perf_counter_ns() - loaded_wall,
                                                        "cpu_ns": time.process_time_ns() - loaded_cpu}
        expected = [(seed, arm) for seed in training["fine_tuning_census"]["training_seeds"]
                    for arm in training["fine_tuning_census"]["arms"]]
        done = set()
        previous_pending = None
        with (OUTPUT / "events.jsonl").open("x", encoding="utf-8") as events:
            while True:
                for seed, arm in expected:
                    if (seed, arm) in done:
                        continue
                    directory = TRAINING / f"seed-{seed}" / arm
                    summary_path = directory / "summary.json"
                    if not summary_path.exists():
                        continue
                    try:
                        summary = json.loads(summary_path.read_text())
                    except (json.JSONDecodeError, OSError):
                        # The final receipt itself may be in its brief write window.
                        continue
                    if summary.get("status") != "completed":
                        continue
                    if not all((directory / name).is_file() for name in summary.get("artifacts", {})):
                        continue
                    report = audit_training_arm(directory, corpus, observer)
                    report_path = OUTPUT / "arms" / f"seed-{seed}-{arm}.json"
                    write_json(report_path, report)
                    row = {"seed": seed, "arm": arm, "status": report["status"], "passed": report["passed"],
                           "audit_report": str(report_path), "audit_report_sha256": file_sha(report_path),
                           "input_summary_sha256": file_sha(summary_path),
                           "schedule_sha256": summary["schedule_sha256"],
                           "training_rows_sha256": summary["training_rows_sha256"],
                           "source_manifest_sha256": summary["source_manifest_sha256"],
                           "counts": report["counts"], "wall_ns": report["wall_ns"], "cpu_ns": report["cpu_ns"],
                           "unique_individual_sources": report.get("unique_individual_sources"),
                           "unique_unordered_source_pairs": report.get("unique_unordered_source_pairs"),
                           "errors": report["errors"]}
                    models.append(row)
                    done.add((seed, arm))
                    event = {"event": "arm_audited", "seed": seed, "arm": arm,
                             "passed": report["passed"], "rows_rescored": report["counts"].get("output_rows_rescored", 0),
                             "audited_arms": len(done), "expected_arms": len(expected), "wall_ns": report["wall_ns"],
                             "errors": report["errors"]}
                    events.write(json.dumps(event, sort_keys=True) + "\n")
                    events.flush()
                    os.fsync(events.fileno())
                    print(json.dumps(event, sort_keys=True), flush=True)
                pending = [f"{seed}/{arm}" for seed, arm in expected if (seed, arm) not in done]
                if len(done) == len(expected) and ((TRAINING / "result.json").exists() or (TRAINING / "failure.json").exists()):
                    break
                if (TRAINING / "failure.json").exists():
                    break
                if (TRAINING / "result.json").exists() and pending:
                    raise ValueError("Producer ended without sealing every registered arm: " + ", ".join(pending))
                if pending != previous_pending:
                    event = {"event": "pending_sealed_training_arms", "pending": pending,
                             "audited_arms": len(done), "expected_arms": len(expected), "whole_census_passed": False}
                    events.write(json.dumps(event, sort_keys=True) + "\n")
                    events.flush()
                    print(json.dumps(event, sort_keys=True), flush=True)
                    previous_pending = pending
                before_wait = time.perf_counter_ns()
                time.sleep(registration["poll_seconds"])
                wait_ns += time.perf_counter_ns() - before_wait
        if source_pins(training) != registration["source_sha256"]:
            raise ValueError("Audit code identities changed during execution")
        for name, sha in registration["input_file_sha256"].items():
            if file_sha(name) != sha:
                raise ValueError("Audit inputs changed during execution: " + name)
        if parameter_hash(observer) != registration["primary_parameter_sha256"]:
            raise ValueError("Observer changed during read-only audit")
        totals = Counter()
        for model in models:
            totals.update(model["counts"])
        paired = {str(seed): len({row["schedule_sha256"] for row in models if row["seed"] == seed}) == 1
                  and len([row for row in models if row["seed"] == seed]) == 3
                  for seed in training["fine_tuning_census"]["training_seeds"]}
        complete = len(models) == len(expected)
        all_passed = complete and all(row["passed"] for row in models) and all(paired.values()) and not (TRAINING / "failure.json").exists()
        producer = json.loads((TRAINING / "result.json").read_text()) if (TRAINING / "result.json").exists() else None
        result = {"schema": "hepta.abc.training-media-census-audit-result.v1",
                  "status": "passed" if all_passed else "failed", "all_15_arms_passed": all_passed,
                  "expected_arms": len(expected), "audited_arms": len(models),
                  "passed_arms": sum(row["passed"] for row in models), "failed_arms": sum(not row["passed"] for row in models),
                  "not_audited_arms": [f"{seed}/{arm}" for seed, arm in expected if (seed, arm) not in done],
                  "models": models, "total_counts": dict(totals), "paired_arm_batch_schedules_match_by_seed": paired,
                  "source_roles_read": ["train"], "training_seed_groups": len(paired), "arm_count_is_independent_n": False,
                  "claimed_independent_sample_size": None,
                  "dependence": "Actual output rows share conditions and model updates. Source images repeat within and across seed schedules. Three arms reuse each seed's batch schedule. Preserve the audited source/view/condition/scenario rows; do not sum them as independent observations.",
                  "raw_row_grouping_evidence": "All original row-stream digests and every source/view/scenario reconstruction were checked; the source grouping remains in the immutable training-output logs.",
                  "producer_result_sha256": file_sha(TRAINING / "result.json") if producer else None,
                  "producer_completed_models": producer.get("model_count") if producer else None,
                  "stage_times": phases, "auditor_stage_wall_ns": sum(row["wall_ns"] for row in models),
                  "auditor_stage_cpu_ns": sum(row["cpu_ns"] for row in models), "poll_wait_wall_ns": wait_ns,
                  "execution_wall_ns": time.perf_counter_ns() - start_wall, "execution_cpu_ns": time.process_time_ns() - start_cpu,
                  "new_outcomes_used_for_tuning": False, "training_outputs_modified": False,
                  "parallel_training_and_control_work_may_overlap": True, "torch_threads": torch.get_num_threads(),
                  "torch_version": str(torch.__version__), "auditor_registration_sha256": file_sha(registration_path)}
        write_json(OUTPUT / "result.json", result)
        print(json.dumps({"event": "audit_census_finished", "status": result["status"], "audited_arms": len(models),
                          "passed_arms": result["passed_arms"], "actual_output_rows_rescored": totals["output_rows_rescored"]}), flush=True)
        return 0 if all_passed else 1
    except BaseException as error:
        write_json(OUTPUT / "failure.json", {"status": "failed", "error": repr(error), "traceback": traceback.format_exc(),
                   "completed_model_reports": models, "stage_times": phases, "poll_wait_wall_ns": wait_ns,
                   "wall_ns": time.perf_counter_ns() - start_wall, "cpu_ns": time.process_time_ns() - start_cpu})
        raise


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(execute(Path(sys.argv[2])))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    training = json.loads((TRAINING / "registration.json").read_text())
    OUTPUT.mkdir(parents=True, exist_ok=False)
    expected_pins = {str(AREA / name): value for name, value in training["source_sha256"].items()}
    pins = source_pins(training)
    if any(pins[name] != value for name, value in expected_pins.items()):
        raise ValueError("Training dependencies differ before audit registration")
    paths = training["paths"]
    input_files = {str(TRAINING / "registration.json"): file_sha(TRAINING / "registration.json"),
                   paths["manifest"]: training["files_sha256"]["manifest"],
                   paths["primary"]: training["files_sha256"]["primary"],
                   paths["protocol"]: training["files_sha256"]["protocol"]}
    registration = {"schema": "hepta.abc.training-media-census-audit-registration.v1",
                    "registered_unix_ns": time.time_ns(), "source_sha256": pins, "input_file_sha256": input_files,
                    "training_directory": str(TRAINING), "output_directory": str(OUTPUT),
                    "source_roles_read": ["train"], "primary_parameter_sha256": training["primary_parameter_sha256"],
                    "expected_census": training["fine_tuning_census"], "python": sys.version, "executable": sys.executable,
                    "poll_seconds": 10, "torch_threads": 2, "audit_each_arm_once": True,
                    "unsealed_or_failed_producer_is_never_a_pass": True,
                    "read_only_training_and_observer": True, "rerun_generation_or_optimization": False,
                    "new_outcomes_used_for_tuning": False,
                    "cost_scope": "Whole process includes imports, train-role reconstruction, hashing, media decoding, frozen rescoring, waiting for sealed producers and all audit receipts.",
                    "parallel_training_and_control_work_may_overlap": True}
    write_json(OUTPUT / "registration.json", registration)
    with (OUTPUT / "process.log").open("x", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(OUTPUT / "registration.json")],
                                 cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write_json(OUTPUT / "whole-process-cost.json", {"schema": "hepta.abc.training-media-audit-process-cost.v1",
               "exit_code": code, "wall_ns": time.perf_counter_ns() - wall, "parent_cpu_ns": time.process_time_ns() - cpu,
               "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
               "child_peak_rss_bytes": after.ru_maxrss * 1024,
               "includes": "registration, child imports/loading, every audit and failed attempt, all child receipts, polling wait, process logging, child exit",
               "parallel_training_and_control_work_may_overlap": True})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
