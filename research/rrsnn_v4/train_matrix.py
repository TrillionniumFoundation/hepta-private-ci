"""Run the frozen matrix, pairing equal-CPU controls to each completed RR fit."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
import time

from .train import ROOT, atomic_json, check_disk, completed_receipt, memory_snapshot, verify_protocol


def run_matrix(workers=2, cpus=None):
    if not 1 <= workers <= 4:
        raise ValueError("one to four training workers supported")
    protocol, protocol_hash = verify_protocol()
    allowed = sorted(os.sched_getaffinity(0))
    cpus = allowed[:workers] if cpus is None else cpus
    if len(cpus) != workers or len(set(cpus)) != workers or any(x not in allowed for x in cpus):
        raise ValueError("worker CPUs must be distinct and allowed")
    if 8 in cpus:
        raise ValueError("CPU 8 is reserved for the native integration work")
    free = Queue()
    for cpu in cpus:
        free.put(cpu)
    (ROOT / "results").mkdir(exist_ok=True)
    jobs = [(variant, seed) for variant in protocol["variants"] for seed in protocol["seeds"]]
    initial_resources, begin = memory_snapshot(), time.perf_counter()
    errors, completed = [], []

    def execute(variant, seed, cpu):
        destination = ROOT / "results" / variant / f"seed_{seed}"
        destination.mkdir(parents=True, exist_ok=True)
        if (destination / "training.json").exists():
            return completed_receipt(variant, seed, protocol_hash)
        check_disk()
        environment = os.environ.copy()
        environment.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        command = ["taskset", "-c", str(cpu), sys.executable, "-m", "rrsnn_v4.train",
                   "--variant", variant, "--seed", str(seed)]
        with (destination / "run.log").open("a") as log:
            child = subprocess.run(command, cwd=ROOT.parent, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        if child.returncode:
            raise RuntimeError(f"{variant} seed {seed} failed; see {destination / 'run.log'}")
        result = completed_receipt(variant, seed, protocol_hash)
        print(json.dumps({"completed": variant, "seed": seed, "cpu": cpu,
                          "training_cpu_seconds": result["train_cpu_seconds"],
                          "updates": result["updates"], "best_validation_nll": result["best_validation_nll"]}), flush=True)
        return result

    def worker(job):
        cpu = free.get()
        variant, seed = job
        done = []
        try:
            done.append(execute(variant, seed, cpu))
            if variant == "rr_full":
                for control in protocol.get("cpu_matched_variants", {}):
                    done.append(execute(control, seed, cpu))
            return [{"variant": r["variant"], "seed": r["seed"],
                     "checkpoint_sha256": r["checkpoint_sha256"]} for r in done]
        finally:
            free.put(cpu)

    print(json.dumps({"fixed_runs": len(jobs), "additional_cpu_controls": len(protocol.get("cpu_matched_variants", {}))*len(protocol["seeds"]),
                      "workers": workers, "cpus": cpus, "protocol_sha256": protocol_hash}), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, job): job for job in jobs}
        for future in as_completed(futures):
            try:
                completed.extend(future.result())
            except Exception as error:
                errors.append({"job": futures[future], "error": str(error)})
                print(json.dumps(errors[-1]), flush=True)
            atomic_json(ROOT / "results" / "matrix_progress.json", {"completed": completed,
                        "errors": errors, "elapsed_seconds": time.perf_counter()-begin})
    verify_protocol()
    status = {"schema": "rr-v4-matrix-status-1", "all_completed": not errors,
              "fixed_jobs": len(jobs), "expected_receipts": len(jobs)+len(protocol.get("cpu_matched_variants", {}))*len(protocol["seeds"]),
              "completed": completed, "errors": errors, "workers": workers, "cpus": cpus,
              "elapsed_seconds": time.perf_counter()-begin, "protocol_sha256": protocol_hash,
              "resources_before": initial_resources, "resources_after": memory_snapshot(),
              "holdout_opened": False}
    if status["all_completed"] and len(completed) != status["expected_receipts"]:
        raise RuntimeError("matrix completed count does not match the frozen protocol")
    atomic_json(ROOT / "results" / "matrix_status.json", status)
    if errors:
        raise RuntimeError(f"{len(errors)} training jobs failed; incomplete matrix retained")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cpus", help="comma-separated explicit worker CPUs")
    args = parser.parse_args()
    selected = [int(x) for x in args.cpus.split(",")] if args.cpus else None
    run_matrix(args.workers, selected)
