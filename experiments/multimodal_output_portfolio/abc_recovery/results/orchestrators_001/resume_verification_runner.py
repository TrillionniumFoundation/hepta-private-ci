"""Prospective three-arm seed-17 last-100-update recovery verification."""

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
OUTPUT = Path("/workspace/scratch/2b3c256bef7d/abc2-runs/resume-verification-001")


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def pins(training):
    paths = [AREA / name for name in training["source_sha256"]]
    paths += [AREA / "abc_recovery/resume_verify.py", AREA / "abc_recovery/resume_verify_tests.py", Path(__file__).resolve()]
    return {str(path): sha(path) for path in paths}


def child(registration_path):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    registration = json.loads(registration_path.read_text())
    training = json.loads((TRAINING / "registration.json").read_text())
    results = []
    try:
        if pins(training) != registration["source_sha256"]:
            raise ValueError("Recovery verification source changed")
        for path, expected in registration["input_sha256"].items():
            if sha(path) != expected:
                raise ValueError("Frozen recovery input changed: " + path)
        sys.path.insert(0, str(REPO))
        import torch
        from experiments.multimodal_output_portfolio.v7.sources import load_roles
        from experiments.multimodal_output_portfolio.v7.evaluation import load_reward
        from experiments.multimodal_output_portfolio.abc_recovery.resume_verify import verify_resume
        torch.set_num_threads(2)
        paths = training["paths"]
        corpus = load_roles(paths["cache"], paths["manifest"], roles=("train",))
        observer, _ = load_reward(paths["primary"], training["files_sha256"]["primary"])
        for arm in registration["arms"]:
            destination = OUTPUT / arm
            report = verify_resume(TRAINING / "seed-17" / arm, corpus, observer, destination, start_step=300)
            report_path = destination / ("result.json" if report["passed"] else "failure.json")
            entry = {"seed": 17, "arm": arm, "passed": report["passed"], "report": str(report_path),
                     "report_sha256": sha(report_path), "matched_suffix_steps": report["matched_suffix_steps"],
                     "checks": report["checks"], "work": report["work"], "wall_ns": report["wall_ns"], "cpu_ns": report["cpu_ns"]}
            results.append(entry)
            write(OUTPUT / f"completed-{len(results):02d}.json", entry)
            print(json.dumps({"event": "resume_arm_completed", **entry}), flush=True)
        if pins(training) != registration["source_sha256"]:
            raise ValueError("Recovery verification code changed during execution")
        for path, expected in registration["input_sha256"].items():
            if sha(path) != expected:
                raise ValueError("Frozen recovery input changed during execution: " + path)
        passed = len(results) == 3 and all(row["passed"] and row["matched_suffix_steps"] == 100 for row in results)
        report = {"schema": "hepta.abc.three-arm-resume-verification-result.v1", "status": "passed" if passed else "failed",
                  "all_three_arms_exact": passed, "models": results, "seed": 17, "from_completed_step": 300,
                  "through_completed_step": 400, "actual_replayed_optimizer_updates": sum(row["work"].get("optimizer_updates", 0) for row in results),
                  "exact_replayed_actual_output_rows": sum(row["checks"].get("exact_output_rows", 0) for row in results),
                  "source_roles_read": ["train"], "independent_training_seeds_added": 0,
                  "new_evaluation_outcomes_opened": False, "new_outcomes_used_for_tuning": False,
                  "original_gradient_probes_preserved": True, "training_artifacts_modified": False,
                  "scope": "Exact suffix recovery for these three seed-17 arms on the frozen runtime; no claim of universal cross-platform determinism.",
                  "registration_sha256": sha(registration_path), "wall_ns": time.perf_counter_ns() - wall,
                  "cpu_ns": time.process_time_ns() - cpu, "parallel_control_work_may_overlap": True}
        write(OUTPUT / "result.json", report)
        print(json.dumps({"event": "resume_census_completed", "passed": passed,
                          "updates": report["actual_replayed_optimizer_updates"], "rows": report["exact_replayed_actual_output_rows"]}), flush=True)
        return 0 if passed else 1
    except BaseException as error:
        write(OUTPUT / "failure.json", {"status": "failed", "error": repr(error), "traceback": traceback.format_exc(),
              "completed_arms": results, "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(child(Path(sys.argv[2])))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    training = json.loads((TRAINING / "registration.json").read_text())
    produced = json.loads((TRAINING / "result.json").read_text())
    OUTPUT.mkdir(parents=True, exist_ok=False)
    selected = [row for row in produced["models"] if row["seed"] == 17]
    arms = training["fine_tuning_census"]["arms"]
    if {row["arm"] for row in selected} != set(arms) or len(selected) != 3:
        raise ValueError("Wrong seed-17 producer census")
    input_hashes = {str(TRAINING / name): sha(TRAINING / name) for name in ("registration.json", "result.json", "whole-process-cost.json")}
    for name in ("manifest", "primary", "protocol"):
        input_hashes[training["paths"][name]] = training["files_sha256"][name]
    for row in selected:
        path = TRAINING / "seed-17" / row["arm"] / "summary.json"
        if sha(path) != row["summary_file_sha256"]:
            raise ValueError("Producer summary binding differs")
        input_hashes[str(path)] = row["summary_file_sha256"]
    source = pins(training)
    if any(source[str(AREA / name)] != value for name, value in training["source_sha256"].items()):
        raise ValueError("Original training code changed")
    registration = {"schema": "hepta.abc.three-arm-resume-verification-registration.v1", "registered_unix_ns": time.time_ns(),
                    "source_sha256": source, "input_sha256": input_hashes, "seed": 17, "arms": arms,
                    "start_step": 300, "end_step": 400, "torch_threads": 2, "source_roles_read": ["train"],
                    "target": "Every actual output row and final parameters, Adam state and RNG must match exactly.",
                    "new_evaluation_outcomes_opened": False, "new_outcomes_used_for_tuning": False,
                    "original_gradient_probes_preserved": True, "parallel_control_work_may_overlap": True,
                    "stop_after_three_successful_suffixes": True}
    write(OUTPUT / "registration.json", registration)
    with (OUTPUT / "process.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--child", str(OUTPUT / "registration.json")],
                                   cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
        code = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    write(OUTPUT / "whole-process-cost.json", {"schema": "hepta.abc.resume-verification-process-cost.v1", "exit_code": code,
          "wall_ns": time.perf_counter_ns() - wall, "parent_cpu_ns": time.process_time_ns() - cpu,
          "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
          "child_peak_rss_bytes": after.ru_maxrss * 1024,
          "includes": "registration, imports, train-role loading, verified checkpoint load, all 300 replay updates and actual media, state comparisons, receipts and child exit",
          "parallel_control_work_may_overlap": True})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
