"""POSIX local probe of three real 770D training jobs and durable publications.

The first real job is reclaimed and trained by a replacement process after an
unacknowledged 1 ns lease. A separate metadata control uses a logical clock.
Neither condition resumes unsaved Adam state or emulates power interruption.
"""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from cell_action_queue_recovery import (abandon_training_job, recover_training_job,
                                        run_recoverable_queue)
from cell_action_training_queue import (MODES, owned_path, prepare_training_jobs,
    sha_file, verify_queue_publications)
from cell_runtime_bundle import load_training_inputs
from cell_training_queue import TrainingQueue, TrainingQueueError


CODE_FILES = ("probe_action_training_queue.py", "cell_action_queue_recovery.py",
    "cell_action_training_queue.py", "cell_training_queue.py", "cell_runtime_bundle.py",
    "cell_learning_models.py", "cell_learning_metrics.py", "cell_calibration_bounded.py")


def _rss_bytes(usage):
    return usage.ru_maxrss*1024 if sys.platform == "linux" else None


def _child(mode, root):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    launch_unix_ns = time.time_ns()
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), mode, str(root)],
        check=True, capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1",
             "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"result": json.loads(child.stdout), "stderr": child.stderr,
        "child_launch_started_unix_ns": launch_unix_ns, "child_reaped_unix_ns": time.time_ns(),
        "wall_ns": time.perf_counter_ns()-began, "parent_cpu_ns": time.process_time_ns()-cpu,
        "reaped_child_cpu_ns": round(((after.ru_utime-before.ru_utime)+(after.ru_stime-before.ru_stime))*1e9),
        "reaped_children_lifetime_peak_rss_bytes": _rss_bytes(after),
        "rss_scope": "Linux lifetime maximum among reaped children so far, not this child's exclusive peak or an additive value",
        "fresh_process": True, "exit_code": child.returncode}


def abandon_lease(root):
    with TrainingQueue(owned_path(root, "lease-control.sqlite"), max_jobs=2) as queue:
        job = queue.claim(now_ns=11, lease_ns=10)
        if job is None or job["attempt"] != 1:
            raise ValueError("first logical-clock claim expected")
    return {"claimed_job": job, "optimizer_updates": 0,
            "worker_exit_point": "after durable claim; before optimization or completion"}


def reclaim_lease(root):
    with TrainingQueue(owned_path(root, "lease-control.sqlite"), max_jobs=2) as queue:
        old = queue.db.execute("SELECT * FROM jobs WHERE cell_id=? AND generation=1",
                               ("logical-lease-control",)).fetchone()
        if old is None or old["status"] != "running" or old["attempts"] != 1:
            raise ValueError("one abandoned durable claim required")
        job_id = old["job_id"]
        replacement = queue.claim(now_ns=22, lease_ns=100)
        if (replacement is None or replacement["job_id"] != job_id or replacement["attempt"] != 2
                or replacement["lease_token"] == old["lease_token"]):
            raise ValueError("expired lease did not transfer to a distinct attempt")
        try:
            queue.complete(job_id, old["lease_token"], {"control": "late old worker"}, now_ns=23)
        except TrainingQueueError:
            late_worker_rejected = True
        else:
            raise ValueError("old worker published after lease transfer")
        result = {"control": "replacement metadata", "optimizer_updates": 0}
        digest = queue.complete(job_id, replacement["lease_token"], result, now_ns=24)
        generation2 = queue.submit("logical-lease-control", 2, old["source_digest"], old["feature_identity"],
            {"purpose": "generation fence metadata only"}, deadline_ns=1000, now_ns=25)
        if queue.read_current("logical-lease-control") is not None:
            raise ValueError("stale trained generation remained current")
        try:
            queue.complete(job_id, replacement["lease_token"], result, now_ns=26)
        except TrainingQueueError:
            old_generation_rejected = True
        else:
            raise ValueError("superseded generation completed")
        current = queue.claim(now_ns=27, lease_ns=100)
        queue.complete(generation2, current["lease_token"], {"control": "generation2 metadata"}, now_ns=28)
        accounting = queue.accounting()
    return {"original_job_id": job_id, "reclaimed_attempt": replacement["attempt"],
        "late_worker_rejected": late_worker_rejected, "stale_generation_hidden": True,
        "old_generation_rejected": old_generation_rejected,
        "replacement_result_sha256": digest, "queue_costs_open": accounting,
        "simulated_clock_values_ns": [10, 11, 22, 23, 24, 25, 26, 27, 28],
        "actual_process_killed": False, "power_loss_tested": False,
        "optimizer_updates": 0, "intermediate_optimizer_resume_tested": False}


def probe_lease_control(root, feature_identity, source_digest):
    path = owned_path(root, "lease-control.sqlite")
    if path.exists():
        raise ValueError("lease control needs a new database")
    with TrainingQueue(path, max_jobs=2) as queue:
        job_id = queue.submit("logical-lease-control", 1, source_digest, feature_identity,
            {"purpose": "lease fence metadata only; no private training"}, deadline_ns=1000, now_ns=10)
    abandoned = _child("--abandon-lease", root)
    recovered = _child("--reclaim-lease", root)
    if (abandoned["result"]["claimed_job"]["job_id"] != job_id
            or recovered["result"]["original_job_id"] != job_id):
        raise ValueError("replacement process recovered a different job")
    return {**recovered["result"],
        "scope": "independent logical-clock metadata control; zero optimizer work",
        "abandoned_worker": abandoned, "replacement_worker": recovered,
        "lease_reclaimed_in_fresh_process": True}


def run_probe(bundle_root, output_root, *, expected_manifest_sha256):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    code_pins = {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}
    before_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    before_prepare, cpu_prepare = time.perf_counter_ns(), time.process_time_ns()
    prepared = prepare_training_jobs(bundle_root, output_root,
        expected_manifest_sha256=expected_manifest_sha256,
        deadline_ns=time.time_ns()+600_000_000_000)
    preparation = {"wall_ns": time.perf_counter_ns()-before_prepare,
        "cpu_ns": time.process_time_ns()-cpu_prepare}
    root = Path(output_root).absolute()
    plan = prepared["plan"]
    with (root / "execution-code-pins.json").open("x") as stream:
        json.dump({"source_code_sha256": code_pins, "bundle_manifest_sha256": expected_manifest_sha256,
            "recorded_before_actual_optimizer_updates": True}, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
    queue = run_recoverable_queue(root, prepared["submissions"], _child)
    fresh = _child("--verify", root)
    verified = fresh["result"]["verified_publications"]
    if (sorted(row["mode"] for row in verified) != sorted(MODES)
            or any(row["optimizer_steps"] != 20 or not row["logits_bitwise_equal"] for row in verified)):
        raise ValueError("fresh-process publication recovery differs")
    first = prepared["submissions"][0]
    fence = probe_lease_control(root, first["feature_identity"], first["source_digest"])
    metadata, _, _, _ = load_training_inputs(bundle_root, expected_manifest_sha256=expected_manifest_sha256)
    if (metadata["feature_identity"] != first["feature_identity"]
            or metadata["generation"] != first["generation"]
            or metadata["task_id"] != first["payload"]["task_id"]
            or code_pins != {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}):
        raise ValueError("original bundle or queue implementation changed during the probe")
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    files = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size,
              "sha256": sha_file(p)} for p in sorted(root.rglob("*")) if p.is_file()]
    return {"schema": "hepta.action-runtime-training-probe.v1",
        "bundle_manifest_sha256": expected_manifest_sha256,
        "source_code_sha256": code_pins, "original_bundle_reverified_after_training": True,
        "source_code_unchanged": True,
        "training_plan_sha256": sha_file(root / "plan.json"),
        "feature_identity": first["feature_identity"], "task_id": first["payload"]["task_id"],
        "logical_tasks": 1, "training_jobs": 3, "distinct_modes": list(MODES),
        "unique_training_source_groups": 32, "training_rows_per_job": 32,
        "optimizer_steps_per_job": 20, "actual_optimizer_updates": 60,
        "example_updates": 1920, "concurrency": 1,
        "preparation": preparation, "queue": queue, "fresh_process_recovery": fresh,
        "lease_generation_control": fence, "persisted_files": files,
        "persisted_file_bytes_before_report": sum(row["bytes"] for row in files),
        "storage_scope": "owned queue root only; shared original bundle reported separately",
        "initial_parameter_snapshots": len(MODES),
        "resume_semantics": plan["resume_semantics"],
        "calibration_after_training": plan["calibration_after_training"],
        "old_calibrator_rebound": False, "learning_quality_measured": False,
        "encoder_forward_calls": 0, "heldout_or_calibration_labels_used": False,
        "total_wall_ns": time.perf_counter_ns()-began,
        "total_parent_cpu_ns": time.process_time_ns()-cpu,
        "total_reaped_child_cpu_ns": round(((after_children.ru_utime-before_children.ru_utime)
            +(after_children.ru_stime-before_children.ru_stime))*1e9),
        "timing_scope": "outer totals contain preparation, main queue, checks, and child controls; nested times are not additive",
        "memory": {"parent_process_lifetime_peak_rss_bytes": _rss_bytes(resource.getrusage(resource.RUSAGE_SELF)),
            "reaped_children_lifetime_peak_rss_bytes": _rss_bytes(after_children),
            "rss_scope": "Linux ru_maxrss; parent lifetime and maximum reaped-child lifetime peaks are separate and cannot be added; not isolated category allocations; null on non-Linux",
            "exclusive_python_metadata_bytes": None, "whole_system_peak_bytes": None},
        "power_loss_tested": False, "authority": "DENY_ALL", "quality_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--verify", type=Path)
    actions.add_argument("--abandon-lease", type=Path)
    actions.add_argument("--reclaim-lease", type=Path)
    actions.add_argument("--abandon-training", type=Path)
    actions.add_argument("--recover-training", type=Path)
    actions.add_argument("--bundle", type=Path)
    parser.add_argument("--bundle-sha256")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify_queue_publications(args.verify)
    elif args.abandon_lease:
        result = abandon_lease(args.abandon_lease)
    elif args.reclaim_lease:
        result = reclaim_lease(args.reclaim_lease)
    elif args.abandon_training:
        result = abandon_training_job(args.abandon_training)
    elif args.recover_training:
        result = recover_training_job(args.recover_training)
    else:
        if args.output is None or args.bundle_sha256 is None:
            parser.error("--bundle requires --output and --bundle-sha256")
        result = run_probe(args.bundle, args.output, expected_manifest_sha256=args.bundle_sha256)
        with (args.output / "report.json").open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    result["process_lifetime_peak_rss_bytes_at_receipt"] = _rss_bytes(resource.getrusage(resource.RUSAGE_SELF))
    result["process_rss_scope"] = "Linux child/entrypoint lifetime ru_maxrss before JSON serialization; not additive; null on non-Linux"
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
