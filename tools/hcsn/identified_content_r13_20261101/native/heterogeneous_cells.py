"""Independent-Q scaling audit; no changes to the frozen inference implementation."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
TIMES = [0.15, 0.45, 2.1]
STEPS = 8


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rss(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except FileNotFoundError:
        pass
    return 0


def memory_snapshot():
    base = Path("/sys/fs/cgroup")
    return {name: (base/name).read_text().strip() for name in
            ["memory.max", "memory.current", "memory.peak", "memory.events"] if (base/name).exists()}


def physical(index, baseline):
    theta = list(baseline)
    theta[2] = 0.15 + 0.25 * (((index + 1) * 0.6180339887498949) % 1.0)
    theta[5] = 0.005 + 0.035 * (((index + 1) * 0.4142135623730951) % 1.0)
    return theta


def load_implementations():
    sys.path.insert(0, str(ROOT.parent))
    import numpy as np
    import torch
    import contract
    from adapter import PreparedModel
    from benchmark import NumpyPrepared
    torch.set_num_threads(1)
    return np, torch, contract, PreparedModel, NumpyPrepared


def make_terms(index, np, torch, contract):
    theta = np.asarray(physical(index, contract.PROTOCOL["baseline_financial_parameters"]), dtype=np.float64)
    with torch.no_grad():
        terms = contract.as_numpy(contract.model_terms(theta=torch.as_tensor(theta), prices=False))
    assert terms["Q"].shape == (116, 116)
    return theta, terms


def worker(method, start, count):
    np, torch, contract, PreparedModel, NumpyPrepared = load_implementations()
    imported = time.process_time()
    imported_rss = rss(os.getpid())
    cells, parameter_table = [], []
    physics_cpu, constructor_cpu = 0.0, 0.0
    common_identity = hashlib.sha256()
    begin = time.process_time()
    for index in range(start, start + count):
        phase = time.process_time()
        theta, terms = make_terms(index, np, torch, contract)
        physics_cpu += time.process_time() - phase
        q, prior = terms["Q"], terms["prior"]
        version = 13_000_000 + index
        phase = time.process_time()
        backend = PreparedModel(q, version=version) if method == "native" else NumpyPrepared(q)
        constructor_cpu += time.process_time() - phase
        likes = np.random.default_rng(20261101 + index).uniform(.05, 1.0, (STEPS, 116))
        for value in [theta, q, prior, likes]:
            common_identity.update(np.ascontiguousarray(value, dtype="<f8").tobytes())
        parameter_table.append({"index": index, "sigma": float(theta[2]), "liquidity": float(theta[5]),
            "boundary": float(terms["boundary"]),
            "reset_x": math.log(contract.PROTOCOL["reset_asset"] / float(terms["boundary"])),
            "q_sha256": hashlib.sha256(q.tobytes()).hexdigest(), "version": version})
        cells.append({"backend": backend, "q": q, "prior": prior, "state": prior.copy(),
                      "buffer": np.empty_like(prior), "likes": likes, "planner": []})
    initialized = time.process_time()
    for cell in cells:
        cell["planner"] = [cell["backend"].transition(dt) for dt in TIMES]
    prepared = time.process_time()
    for step in range(STEPS):
        for cell in cells:
            cell["backend"].propagate(cell["state"], TIMES[step % len(TIMES)], out=cell["buffer"])
            cell["backend"].observe(cell["buffer"], cell["likes"][step], out=cell["state"])
    finished = time.process_time()
    execution_rss, execution_peak = rss(os.getpid()), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    cache_bytes = sum(c["backend"].cache_info()["cached_bytes"] for c in cells) if method == "native" else sum(
        sum(matrix.nbytes for matrix in c["backend"].cache.values()) for c in cells)
    planner_bytes = sum(sum(matrix.nbytes for matrix in c["planner"]) for c in cells)
    unique_transition_bytes = cache_bytes + planner_bytes if method == "native" else cache_bytes
    cache_preparations = sum(c["backend"].cache_info()["preparations"] for c in cells) if method == "native" else sum(
        len(c["backend"].cache) for c in cells)
    # These checks are outside the deployment timing and its RSS snapshot.
    max_error, max_mass_error = 0.0, 0.0
    for cell in cells:
        reference = NumpyPrepared(cell["q"])
        state, buffer = cell["prior"].copy(), np.empty_like(cell["prior"])
        for step in range(STEPS):
            reference.propagate(state, TIMES[step % len(TIMES)], out=buffer)
            reference.observe(buffer, cell["likes"][step], out=state)
        max_error = max(max_error, float(np.max(abs(cell["state"] - state))))
        max_mass_error = max(max_mass_error, abs(float(cell["state"].sum()) - 1.0))
    result = {"method": method, "pid": os.getpid(), "start_index": start, "count": count,
        "n_states": 116, "steps": STEPS, "times": TIMES,
        "imports_and_startup_cpu_seconds": imported,
        "initialization_cpu_seconds": initialized - begin,
        "full_HX_boundary_and_Q_cpu_seconds": physics_cpu,
        "immutable_backend_constructor_cpu_seconds": constructor_cpu,
        "prepare_all_transitions_cpu_seconds": prepared - initialized,
        "online_cpu_seconds": finished - prepared,
        "model_and_online_cpu_seconds": finished - begin,
        "execution_cpu_since_process_start_seconds": finished,
        "audit_after_execution_cpu_seconds": time.process_time() - finished,
        "baseline_rss_after_imports_bytes": imported_rss, "execution_current_rss_bytes": execution_rss,
        "execution_peak_rss_bytes": execution_peak,
        "cache_payload_bytes": cache_bytes, "planner_array_logical_bytes": planner_bytes,
        "unique_transition_payload_bytes": unique_transition_bytes, "cache_preparations": cache_preparations,
        "input_sha256": common_identity.hexdigest(), "parameters": parameter_table,
        "maximum_posterior_error": max_error, "maximum_mass_error": max_mass_error,
        "quality_pass": max_error < 3e-11 and max_mass_error < 5e-10,
        "all_Q_distinct": len({x["q_sha256"] for x in parameter_table}) == count,
        "library_sha256": sha(ROOT/"evidence/build/libhcsn_prepared.so"),
        "source_sha256": sha(__file__), "numpy_version": np.__version__, "torch_version": torch.__version__}
    if method == "native":
        for cell in cells:
            cell["backend"].close()
    return result


def limit_probe():
    np, torch, contract, PreparedModel, unused = load_implementations()
    models, prior, refusal = [], None, None
    for index in range(256):
        theta, terms = make_terms(index, np, torch, contract)
        if prior is None:
            prior = terms["prior"]
        try:
            models.append(PreparedModel(terms["Q"], version=13_000_000 + index))
        except ValueError as error:
            refusal = {"cell_number_one_based": index + 1, "reason": str(error)}
            break
    survivor = models[0].propagate(prior, 0.0)
    result = {"attempted_target": 256, "created_models": len(models), "refusal": refusal,
        "surviving_model_valid": bool(np.array_equal(prior, survivor)), "pid": os.getpid(),
        "pass": len(models) == 128 and refusal is not None and refusal["cell_number_one_based"] == 129
                and "work_limit" in refusal["reason"] and np.array_equal(prior, survivor),
        "library_sha256": sha(ROOT/"evidence/build/libhcsn_prepared.so")}
    for model in models:
        model.close()
    return result


def launch_workers(commands, destination, label, environment):
    pending, launched, observations = {}, [], []
    begin = time.perf_counter()
    for index, command in enumerate(commands):
        stem = destination/f"{label}_worker{index}"
        stdout, stderr = stem.with_suffix(".json").open("x"), stem.with_suffix(".stderr").open("x")
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=environment)
        pending[process.pid] = (process, stdout, stderr, stem)
        launched.append({"pid": process.pid, "command": command})
    receipts, peak_sum_rss = [], 0
    while pending:
        sample = sum(rss(pid) for pid in pending)
        peak_sum_rss = max(peak_sum_rss, sample)
        observations.append([time.perf_counter() - begin, sample])
        for pid in list(pending):
            done, status, usage = os.wait4(pid, os.WNOHANG)
            if done:
                process, stdout, stderr, stem = pending.pop(pid)
                process.returncode = os.waitstatus_to_exitcode(status)
                stdout.close(); stderr.close()
                receipt = {"pid": pid, "returncode": process.returncode,
                    "whole_child_user_cpu_seconds": usage.ru_utime,
                    "whole_child_system_cpu_seconds": usage.ru_stime,
                    "whole_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
                    "whole_child_peak_rss_bytes": usage.ru_maxrss * 1024,
                    "stdout": stem.with_suffix(".json").name, "stderr": stem.with_suffix(".stderr").name}
                if process.returncode != 0:
                    receipt["error"] = stem.with_suffix(".stderr").read_text()
                receipts.append(receipt)
        if pending:
            time.sleep(.005)
    receipt = {"launched": launched, "workers": receipts, "outer_wall_seconds": time.perf_counter() - begin,
        "sampled_peak_sum_worker_rss_bytes": peak_sum_rss,
        "sum_individual_whole_child_peak_rss_upper_bound_bytes": sum(x["whole_child_peak_rss_bytes"] for x in receipts),
        "rss_samples": observations,
        "rss_scope": "Sampled sum of worker RSS, not unique physical memory; includes imports and post-timing quality checks. Individual worker execution RSS snapshots precede those checks. 5ms sampling is not an exact continuous peak."}
    (destination/f"{label}_PROCESS_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if any(x["returncode"] != 0 for x in receipts):
        raise RuntimeError(f"Worker failed; preserve {label}_PROCESS_RECEIPT.json")
    return [json.loads((destination/x["stdout"]).read_text()) for x in receipts], receipt


def freeze_matches():
    root = ROOT.parent
    frozen = json.loads((root/"evidence/FREEZE.json").read_text())
    mismatches = []
    for field, base in [("source_sha256", root.parent), ("fit_sha256", root/"evidence")]:
        mismatches.extend(f"{field}:{name}" for name, expected in frozen[field].items() if sha(base/name) != expected)
    if sha(ROOT/"evidence/build/libhcsn_prepared.so") != frozen["native_library_sha256"]:
        mismatches.append("native_library")
    return mismatches


def run(destination, repetitions):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    before = freeze_matches()
    if before:
        raise AssertionError(before)
    memory = memory_snapshot()
    plan = {"schema": "hcsn-r13-heterogeneous-cells-plan-v1", "counts": [1, 16, 64, 256],
        "methods": ["native", "numpy_cached"], "repetitions": repetitions, "steps": STEPS, "times": TIMES,
        "parameter_rule": "index-based distinct sigma/liquidity inside the preregistered box; same fixed 116-state grid",
        "physics": "Frozen contract.model_terms(prices=False): full HX five-output/Jacobian boundary call, then Q; no per-grid payoff calls or text encoding",
        "deployment": "1/16/64 in one process; 256 in two concurrent independent 128-cell processes, for both backends",
        "memory_before": memory, "maximum_cells_decision": "Stop at requested 256. 8GiB cgroup and observed remaining memory do not justify optional 1024 with this multi-process dependency stack.",
        "source_sha256": sha(__file__), "frozen_root_sha256": sha(ROOT.parent/"evidence/FREEZE.json"),
        "frozen_native_sha256": sha(ROOT/"RUNTIME_FREEZE.json"),
        "quality_threshold_max_absolute": 3e-11, "frozen_sources_before_mismatches": before}
    (destination/"PLAN.json").write_text(json.dumps(plan, indent=2) + "\n")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
                       OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    base = [sys.executable, str(Path(__file__).resolve())]
    probe, probe_receipt = launch_workers([base + ["--limit-probe"]], destination, "handle_limit", environment)
    if not probe[0]["pass"]:
        raise AssertionError(probe)
    jobs = [(count, method, repeat) for count in plan["counts"] for method in plan["methods"] for repeat in range(repetitions)]
    random.Random(20261101256).shuffle(jobs)
    results = []
    metrics = ["imports_and_startup_cpu_seconds", "initialization_cpu_seconds", "full_HX_boundary_and_Q_cpu_seconds",
        "immutable_backend_constructor_cpu_seconds", "prepare_all_transitions_cpu_seconds", "online_cpu_seconds",
        "model_and_online_cpu_seconds", "execution_cpu_since_process_start_seconds", "audit_after_execution_cpu_seconds",
        "cache_payload_bytes", "planner_array_logical_bytes", "unique_transition_payload_bytes", "cache_preparations",
        "baseline_rss_after_imports_bytes", "execution_current_rss_bytes", "execution_peak_rss_bytes"]
    for number, (count, method, repeat) in enumerate(jobs):
        shards = [(0, count)] if count <= 128 else [(0, 128), (128, 128)]
        commands = [base + ["--worker", method, "--start", str(start), "--count", str(size)] for start, size in shards]
        rows, receipt = launch_workers(commands, destination, f"cells{count}_{method}_rep{repeat}", environment)
        rows.sort(key=lambda row: row["start_index"])
        parameters = [p for row in rows for p in row["parameters"]]
        result = {"count": count, "method": method, "repetition": repeat, "worker_count": len(rows),
            **{metric: sum(row[metric] for row in rows) for metric in metrics},
            "worker_input_sha256": [row["input_sha256"] for row in rows],
            "parameter_sha256": hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest(),
            "all_Q_distinct": len({p["q_sha256"] for p in parameters}) == count,
            "quality_pass": all(row["quality_pass"] for row in rows),
            "maximum_posterior_error": max(row["maximum_posterior_error"] for row in rows),
            "maximum_mass_error": max(row["maximum_mass_error"] for row in rows),
            "sampled_peak_sum_worker_rss_bytes": receipt["sampled_peak_sum_worker_rss_bytes"],
            "whole_children_cpu_seconds": sum(r["whole_child_cpu_seconds"] for r in receipt["workers"]),
            "outer_wall_seconds": receipt["outer_wall_seconds"],
            "worker_execution_peak_rss_sum_is_upper_bound": len(rows) > 1}
        results.append(result)
        print(json.dumps({"completed": number + 1, "total": len(jobs), "cells": count, "method": method,
            "full_model_cpu": result["model_and_online_cpu_seconds"], "quality": result["quality_pass"]}), flush=True)
    groups = []
    for count in plan["counts"]:
        selected = [x for x in results if x["count"] == count]
        identity_equal = len({(tuple(x["worker_input_sha256"]), x["parameter_sha256"]) for x in selected}) == 1
        medians = {method: {metric: statistics.median(x[metric] for x in selected if x["method"] == method)
            for metric in metrics + ["sampled_peak_sum_worker_rss_bytes", "whole_children_cpu_seconds", "outer_wall_seconds"]}
            for method in plan["methods"]}
        groups.append({"count": count, "input_identity_equal": identity_equal, "medians": medians,
            "model_native_over_numpy": medians["native"]["model_and_online_cpu_seconds"] / medians["numpy_cached"]["model_and_online_cpu_seconds"],
            "execution_with_imports_native_over_numpy": medians["native"]["execution_cpu_since_process_start_seconds"] /
                medians["numpy_cached"]["execution_cpu_since_process_start_seconds"]})
    after = freeze_matches()
    report = {"schema": "hcsn-r13-heterogeneous-cells-v1", "plan": plan, "handle_limit": probe[0],
        "results": results, "groups": groups, "memory_after": memory_snapshot(),
        "frozen_sources_after_mismatches": after,
        "all_passed": all(x["quality_pass"] and x["all_Q_distinct"] for x in results) and
            all(g["input_identity_equal"] for g in groups) and not after,
        "scope": "Independent heterogeneous models; no recurrent coupling, GPU, training, task quality or production claim. Full model timing includes physical initialization and every prepare. Startup-inclusive CPU and full child CPU are separately reported; full child also includes numerical audit/serialization. 256 cells require two processes under the frozen 128-handle cap. Planner exports retained: NumPy aliases cache, native exports own copies."}
    (destination/"RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["all_passed"]:
        raise AssertionError("See preserved heterogeneous results")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT/"evidence/heterogeneous_cells")
    parser.add_argument("--worker", choices=["native", "numpy_cached"])
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--limit-probe", action="store_true")
    args = parser.parse_args()
    if args.limit_probe:
        print(json.dumps(limit_probe()))
    elif args.worker:
        print(json.dumps(worker(args.worker, args.start, args.count)))
    else:
        run(args.output, args.repetitions)
