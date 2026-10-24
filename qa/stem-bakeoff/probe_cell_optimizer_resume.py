"""Run the precommitted 17-Cell optimizer continuation engineering comparison.

All numerical workers are new processes. Existing output roots are never reused;
failed attempts and every outer worker receipt remain available for accounting.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time

import numpy as np

from cell_learning_models import canonical
from cell_optimizer_checkpoint import (file_sha, layout, load_optimizer_checkpoint,
                                       ordinary_file, ordinary_root)
from cell_optimizer_resume_worker import (BUNDLE_SHA256, CODE_FILES, CONTRACT, CURSORS,
    FEATURE_SHA256, MODES, code_pins, make_owner, updates_at, write_json)
from cell_resumable_training import array_sha
from cell_runtime_bundle import check_npz, inventory, verify_bundle


def committed_code(commit, pins):
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("complete frozen source Git commit required")
    repo = Path(__file__).resolve().parents[2]
    for name in CODE_FILES:
        data = subprocess.check_output(["git", "-C", str(repo), "show", commit+":qa/stem-bakeoff/"+name])
        if hashlib.sha256(data).hexdigest() != pins[name]:
            raise ValueError("running source or protocol differs from frozen commit: "+name)


def execute(root, name, argv):
    began, cpu, started_unix_ns = time.perf_counter_ns(), time.process_time_ns(), time.time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    error, result, stdout, stderr, report = None, None, "", "", None
    try:
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, check=False)
        stdout, stderr = result.stdout, result.stderr
        if result.returncode: raise RuntimeError("worker failed: "+name)
        pointer = json.loads(stdout)
        path = root/"workers"/name/"report.json"
        if file_sha(path) != pointer["report_sha256"]: raise ValueError("worker report identity differs")
        report = json.loads(path.read_bytes())
        if report["actual_optimizer_updates"] != pointer["actual_optimizer_updates"]:
            raise ValueError("worker reported inconsistent update accounting")
    except BaseException as caught:
        error = caught
        if isinstance(caught, subprocess.TimeoutExpired):
            stdout = (caught.stdout or b"").decode(errors="replace") if isinstance(caught.stdout, bytes) else caught.stdout or ""
            stderr = (caught.stderr or b"").decode(errors="replace") if isinstance(caught.stderr, bytes) else caught.stderr or ""
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"argv": argv, "started_unix_ns": started_unix_ns,
        "exit_code": None if result is None else result.returncode, "stdout": stdout, "stderr": stderr,
        "error": None if error is None else repr(error), "fresh_process": True,
        "wall_ns": time.perf_counter_ns()-began, "parent_cpu_ns": time.process_time_ns()-cpu,
        "child_cpu_ns": round((after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)*1e9),
        "scope": "complete worker subprocess and report verification; worker nested timings included",
        "reaped_children_lifetime_peak_rss_bytes": after.ru_maxrss*1024,
        "rss_scope": "nonadditive Linux maximum across reaped children so far; not this job's exclusive peak"}
    write_json(root/"worker-receipts"/(name+".json"), receipt)
    if error is not None: raise error
    return report


def compare_mode(root, mode, plan, reports):
    binding = plan["owners"][mode]
    full_name, resumed_name = mode+"-uninterrupted", mode+"-segment-60"
    loaded = []
    for name in (full_name, resumed_name):
        loaded.append(load_optimizer_checkpoint(root/"workers"/name/"checkpoint",
            expected_manifest_sha256=reports[name]["checkpoint"]["manifest_sha256"],
            expected_plan_sha256=binding["plan_sha256"], expected_input_sha256=binding["input_sha256"]))
    (full_meta, full), (resumed_meta, resumed) = (owner.snapshot() for owner in loaded)
    full_sha = {name: array_sha(value) for name, value in full.items()}
    resumed_sha = {name: array_sha(value) for name, value in resumed.items()}
    if full_meta != resumed_meta or full_sha != resumed_sha:
        raise ValueError("resumed parameters, both moments, steps, losses or trajectory differ bitwise")
    legacy = reports[mode+"-legacy"]
    archive = root/"workers"/(mode+"-legacy")/"parameters.npz"
    expected = {k[2:]: value for k, value in layout(binding["plan"])[0].items() if k.startswith("p_")}
    ordinary_file(archive, sum(int(np.prod(shape))*dtype.itemsize for shape, dtype in expected.values())+4096*len(expected))
    if file_sha(archive) != legacy["parameters_sha256"]: raise ValueError("legacy reference bytes changed")
    check_npz(archive, expected)
    maximum = 0.0
    with np.load(archive, allow_pickle=False) as arrays:
        for name in expected:
            value = arrays[name]
            if array_sha(value) != legacy["parameter_array_sha256"][name]: raise ValueError("legacy tensor digest differs")
            if not np.allclose(value, full["p_"+name], atol=1e-10, rtol=1e-10):
                raise ValueError("legacy parameter tolerance exceeded")
            maximum = max(maximum, float(np.max(np.abs(value-full["p_"+name]))))
    loss_errors = {}
    for name in ("initial_loss", "final_loss"):
        values = np.asarray(legacy["legacy"][name])
        if not np.allclose(values, full[name], atol=1e-10, rtol=1e-10):
            raise ValueError("legacy loss tolerance exceeded")
        loss_errors[name] = float(np.max(np.abs(values-full[name])))
    if legacy["legacy"]["initial_parameter_digests"] != binding["plan"]["model"]["initial_parameter_digests"]:
        raise ValueError("legacy initialization was not matched")
    return {"mode": mode, "cells": 17, "task_count": 1, "complete_steps_per_cell": full["steps"].tolist(),
        "new_paths_bitwise_equal": True, "all_state_array_sha256": full_sha,
        "trajectory_sha256": full_meta["trajectory_sha256"], "legacy_max_parameter_error": maximum,
        "legacy_max_loss_errors": loss_errors, "legacy_atol": 1e-10, "legacy_rtol": 1e-10}


def reverify_inputs(bundle, plan_path, plan_sha256):
    if file_sha(plan_path) != plan_sha256:
        raise ValueError("sealed execution plan changed during the run")
    verify_bundle(bundle, expected_manifest_sha256=BUNDLE_SHA256)


def run_probe(bundle, source_commit, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    root, bundle, pins = ordinary_root(output), ordinary_root(bundle), code_pins()
    if root.exists(): raise ValueError("new complete attempt directory required")
    root.mkdir(parents=True)
    (root/"worker-receipts").mkdir()
    completed, comparisons, active_worker = {}, [], None
    try:
        if sys.platform != "linux" or any(os.environ.get(k) != "1" for k in
                ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("Linux and explicit one-thread BLAS required")
        if any(v is None for v in pins.values()): raise ValueError("source pin missing before input load")
        committed_code(source_commit, pins)
        owners = {}
        for mode in MODES:
            owner = make_owner(bundle, mode)
            if len(set(owner.plan["model"]["initial_parameter_digests"])) != 17:
                raise ValueError("17 distinct initial private states required")
            owners[mode] = {"plan": owner.plan, "plan_sha256": owner.plan_sha256,
                            "input_sha256": owner.input_sha256}
            del owner
        plan = {"schema": "hepta.optimizer-continuation-run.v1", "contract": CONTRACT,
            "bundle": str(bundle), "bundle_manifest_sha256": BUNDLE_SHA256,
            "feature_identity": FEATURE_SHA256, "source_git_commit": source_commit,
            "source_code_sha256": pins, "owners": owners, "task_count": 1,
            "fit_order": "per mode: new uninterrupted, six continuation workers, legacy",
            "runtime": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
            "authority": "DENY_ALL", "quality_qualified": False}
        write_json(root/"plan.json", plan)
        plan_sha = file_sha(root/"plan.json")
        for mode in MODES:
            checkpoint, checkpoint_sha = None, None
            jobs = [("uninterrupted", 60), *(("segment", cursor) for cursor in CURSORS), ("legacy", 60)]
            for kind, target in jobs:
                name = f"{mode}-{kind}"+(f"-{target}" if kind == "segment" else "")
                argv = [sys.executable, str(Path(__file__).with_name("cell_optimizer_resume_worker.py")),
                    "--plan", str(root/"plan.json"), "--plan-sha256", plan_sha, "--output", str(root/"workers"/name),
                    "--mode", mode, "--kind", kind, "--target-cursor", str(target)]
                if kind == "segment" and checkpoint is not None:
                    argv.extend(("--checkpoint", str(checkpoint), "--checkpoint-sha256", checkpoint_sha))
                active_worker = name
                report = execute(root, name, argv)
                completed[name] = report
                active_worker = None
                if kind == "segment":
                    checkpoint = root/"workers"/name/"checkpoint"
                    checkpoint_sha = report["checkpoint"]["manifest_sha256"]
            comparisons.append(compare_mode(root, mode, plan, completed))
        updates = sum(r["actual_optimizer_updates"] for r in completed.values())
        examples = sum(r["actual_example_updates"] for r in completed.values())
        reverify_inputs(bundle, root/"plan.json", plan_sha)
        if len(completed) != 24 or updates != 3060 or examples != 97920 or code_pins() != pins:
            raise ValueError("complete fixed work matrix or final source identity differs")
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        report = {"schema": "hepta.optimizer-continuation-comparison.v1", "plan_sha256": plan_sha,
            "source_code_sha256": pins, "source_git_commit": source_commit, "comparisons": comparisons,
            "actual_optimizer_updates": updates, "actual_example_updates": examples,
            "original_bundle_reverified_after_training": True, "execution_plan_reverified_after_training": True,
            "fresh_worker_commands": 24, "worker_reports": {name: file_sha(root/"workers"/name/"report.json") for name in completed},
            "wall_ns": time.perf_counter_ns()-began, "parent_cpu_ns": time.process_time_ns()-cpu,
            "reaped_child_cpu_ns": round((after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime)*1e9),
            "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            "reaped_children_lifetime_peak_rss_bytes": after.ru_maxrss*1024,
            "cost_scope": "inclusive controller body, Git reads, worker trees and comparisons; worker receipts nested; final serialization/imports covered by caller outer receipt",
            "rss_scope": "separate nonadditive parent/reaped-child lifetime peaks; whole-system peak unknown",
            "task_count": 1, "encoder_calls": 0, "calibration_fits": 0, "quality_scoring": False,
            "power_loss_tested": False, "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "quality_qualified": False}
        write_json(root/"report.json", report)
        write_json(root/"manifest.json", inventory(root))
        return report
    except BaseException as error:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write_json(root/"failed.json", {"error": repr(error), "completed_workers": list(completed),
            "completed_worker_updates": sum(r["actual_optimizer_updates"] for r in completed.values()),
            "failed_worker": active_worker, "failed_worker_additional_updates_unknown": active_worker is not None,
            "partial_artifacts_retained": True,
            "source_code_sha256": pins, "end_source_code_sha256": code_pins(),
            "wall_ns": time.perf_counter_ns()-began, "parent_cpu_ns": time.process_time_ns()-cpu,
            "reaped_child_cpu_ns": round((after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime)*1e9)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "source-commit", "output"): parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    result = run_probe(args.bundle, args.source_commit, args.output)
    print(json.dumps({key: result[key] for key in ("actual_optimizer_updates", "actual_example_updates", "fresh_worker_commands")}))
