"""One fresh process in the fixed 17-Cell optimizer continuation protocol."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from cell_microbatch_training import FrozenTrainingBank
from cell_optimizer_checkpoint import (file_sha, load_optimizer_checkpoint, ordinary_file,
    ordinary_root, save_optimizer_checkpoint)
from cell_resumable_training import ResumableMicrobatchAdam, array_sha
from cell_runtime_bundle import load_training_inputs


BUNDLE_SHA256 = "266af205b6053df3c3968d2de52ff6ede8d8ebc6add3909fa7bc081cd52a6fdc"
FEATURE_SHA256 = "00b09d213137fd60d33b39761d462f69b6e692155f51b7efd77896911cbd62c0"
MODES, CURSORS = ("linear", "gated", "residual"), (3, 20, 27, 40, 59, 60)
CONTRACT = {"cells": 17, "steps": 20, "microbatch": 8, "rows": 32, "width": 770,
    "classes": 2, "rank": 4, "seed_start": 1000000, "learning_rate": .02, "l2": .001,
    "modes": list(MODES), "checkpoint_cursors": list(CURSORS), "max_tensor_bytes": 512*1024**2,
    "optimizer_updates": 3060, "example_updates": 97920, "legacy_atol": 1e-10, "legacy_rtol": 1e-10}
CODE_FILES = ("cell_optimizer_resume_worker.py", "probe_cell_optimizer_resume.py",
    "cell_resumable_training.py", "cell_optimizer_checkpoint.py", "cell_microbatch_training.py",
    "cell_learning_models.py", "cell_learning_metrics.py", "cell_runtime_bundle.py",
    "cell_calibration_bounded.py", "CELL_NATIVE_RESUME_PROTOCOL.md")


def code_pins():
    pins = {}
    for name in CODE_FILES:
        try: pins[name] = file_sha(Path(__file__).with_name(name))
        except OSError: pins[name] = None
    return pins


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value)+b"\n")


def read_plan(path, expected_sha256):
    path = ordinary_root(path)
    ordinary_file(path, 16*1024**2)
    if file_sha(path) != expected_sha256:
        raise ValueError("external execution plan identity differs")
    plan = json.loads(path.read_bytes())
    if (plan.get("schema") != "hepta.optimizer-continuation-run.v1" or plan.get("contract") != CONTRACT
            or plan.get("bundle_manifest_sha256") != BUNDLE_SHA256
            or plan.get("feature_identity") != FEATURE_SHA256 or plan.get("source_code_sha256") != code_pins()
            or any(pin is None for pin in plan["source_code_sha256"].values())
            or set(plan.get("owners", {})) != set(MODES)):
        raise ValueError("execution protocol or implementation differs")
    return plan


def make_owner(bundle, mode):
    if mode not in MODES:
        raise ValueError("predeclared Head structure required")
    meta, x, y, rows = load_training_inputs(bundle, expected_manifest_sha256=BUNDLE_SHA256)
    if meta["feature_identity"] != FEATURE_SHA256 or meta["task_id"] != "action_usefulness":
        raise ValueError("original sealed TRAIN feature/task identity required")
    bank = FrozenTrainingBank.build({meta["task_id"]: x},
        {meta["task_id"]: [r["source_id"] for r in rows]}, meta["feature_identity"])
    heads = [NumpyCellHead(770, 2, mode, rank=4, seed=1000000+i) for i in range(17)]
    for head in heads: head.feature_identity = bank.feature_identity
    return ResumableMicrobatchAdam(heads, [f"resume-cell-{i}" for i in range(17)],
        [meta["task_id"]]*17, bank, np.broadcast_to(y, (17, 32)),
        source_record_digests=[r["source_record_digest"] for r in rows], steps=20, microbatch=8,
        generation=1, learning_rate=.02, l2=.001, max_tensor_bytes=CONTRACT["max_tensor_bytes"])


def updates_at(cursor):
    return sum(min(max(cursor-group*20, 0), 20)*count for group, count in enumerate((8, 8, 1)))


def job_boundary(kind, target, checkpoint, checkpoint_sha256):
    if kind not in ("segment", "uninterrupted", "legacy", "verify"):
        raise ValueError("unknown fixed worker role")
    if kind in ("uninterrupted", "legacy"):
        if target != 60 or checkpoint is not None or checkpoint_sha256 is not None:
            raise ValueError("whole-run comparison starts at the frozen initial state")
        return 0
    if kind == "verify":
        if target != 60 or checkpoint is None or checkpoint_sha256 is None:
            raise ValueError("verification requires a pinned complete checkpoint")
        return 60
    if target not in CURSORS:
        raise ValueError("pause cursor was not predeclared")
    previous = 0 if target == CURSORS[0] else CURSORS[CURSORS.index(target)-1]
    if (checkpoint is not None) != bool(previous) or (checkpoint_sha256 is not None) != bool(previous):
        raise ValueError("each continuation segment must consume its pinned predecessor")
    return previous


def run_worker(plan_path, plan_sha256, output, mode, kind, target, checkpoint=None, checkpoint_sha256=None):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    root, pins = ordinary_root(output), code_pins()
    if root.exists(): raise ValueError("fresh worker output required; retain previous attempts")
    root.mkdir(parents=True)
    owner, updates = None, 0
    try:
        if sys.platform != "linux" or any(os.environ.get(k) != "1" for k in
                ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("Linux and explicit one-thread BLAS required")
        plan = read_plan(plan_path, plan_sha256)
        if mode not in MODES: raise ValueError("predeclared mode required")
        previous = job_boundary(kind, target, checkpoint, checkpoint_sha256)
        binding = plan["owners"][mode]
        load_at, load_cpu = time.perf_counter_ns(), time.process_time_ns()
        owner = (make_owner(plan["bundle"], mode) if checkpoint is None else load_optimizer_checkpoint(checkpoint,
            expected_manifest_sha256=checkpoint_sha256, expected_plan_sha256=binding["plan_sha256"],
            expected_input_sha256=binding["input_sha256"]))
        if owner.plan != binding["plan"] or owner.plan_sha256 != binding["plan_sha256"] or owner.progress()["cursor"] != previous:
            raise ValueError("loaded private initialization or continuation cursor differs")
        setup = {"wall_ns": time.perf_counter_ns()-load_at, "cpu_ns": time.process_time_ns()-load_cpu}
        report = {"schema": "hepta.optimizer-continuation-worker.v1", "kind": kind, "mode": mode,
            "run_plan_sha256": plan_sha256, "owner_plan_sha256": owner.plan_sha256,
            "input_sha256": owner.input_sha256, "previous_cursor": previous, "target_cursor": target,
            "predecessor_manifest_sha256": checkpoint_sha256, "setup": setup}
        if kind == "legacy":
            updates = None
            fitted = owner._core.train(owner._labels, feature_identity=FEATURE_SHA256, generation=1,
                steps=20, learning_rate=.02, l2=.001)
            updates = fitted["private_optimizer_updates"]
            parameters = owner._core.parameters()
            with (root/"parameters.npz").open("xb") as stream: np.savez_compressed(stream, **parameters)
            report.update(legacy=fitted, parameters_sha256=file_sha(root/"parameters.npz"),
                parameter_array_sha256={k: array_sha(v) for k, v in parameters.items()})
        else:
            if kind != "verify":
                updates = None
                advance = owner.advance(target-previous, expected_plan_sha256=binding["plan_sha256"])
                updates = advance["private_optimizer_updates"]
                save_at, save_cpu = time.perf_counter_ns(), time.process_time_ns()
                receipt = save_optimizer_checkpoint(owner, root/"checkpoint", expected_plan_sha256=owner.plan_sha256)
                report.update(advance=advance, checkpoint=receipt, checkpoint_write={
                    "wall_ns": time.perf_counter_ns()-save_at, "cpu_ns": time.process_time_ns()-save_cpu})
            report["progress"] = owner.progress()
            if report["progress"]["cursor"] != target: raise ValueError("worker did not reach its exact pause boundary")
        expected_updates = 0 if kind == "verify" else updates_at(target)-updates_at(previous)
        if updates != expected_updates: raise ValueError("worker update accounting differs from fixed schedule")
        observed = code_pins()
        if pins != observed or read_plan(plan_path, plan_sha256) != plan:
            raise ValueError("execution inputs or code changed")
        report.update(actual_optimizer_updates=updates, actual_example_updates=updates*32,
            source_code_sha256=pins, end_source_code_sha256=observed,
            wall_ns=time.perf_counter_ns()-began, cpu_ns=time.process_time_ns()-cpu,
            process_lifetime_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            timing_scope="worker body through checks; imports/final report/printing included in controller outer child receipt; nested fields not additional",
            task_count=1, encoder_calls=0, calibration_fits=0, quality_scoring=False,
            mode_authority="SHADOW_ONLY", authority="DENY_ALL", quality_qualified=False)
        write_json(root/"report.json", report)
        return {"report_sha256": file_sha(root/"report.json"), "actual_optimizer_updates": updates}
    except BaseException as error:
        write_json(root/"failed.json", {"error": repr(error), "kind": kind, "mode": mode,
            "actual_optimizer_updates": updates, "partial_optimizer_work_unknown": updates is None,
            "progress": owner.progress() if owner is not None and kind != "legacy" else None,
            "source_code_sha256": pins, "end_source_code_sha256": code_pins(),
            "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
            "partial_artifacts_retained": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "plan-sha256", "output", "mode", "kind"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--target-cursor", type=int, required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--checkpoint-sha256")
    args = parser.parse_args()
    print(json.dumps(run_worker(args.plan, args.plan_sha256, args.output, args.mode, args.kind,
        args.target_cursor, args.checkpoint, args.checkpoint_sha256)))
