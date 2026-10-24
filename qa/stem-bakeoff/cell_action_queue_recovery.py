"""Recover one real source-bound training job after a worker leaves its lease.

The first worker exits after claiming, before any optimizer update. A 1 ns real
lease expires naturally before the replacement process starts. This proves
restart from persisted inputs, not recovery of unsaved Adam state or a crash SLO.
"""

import resource
import time

from cell_action_training_queue import owned_path, train_persisted_job
from cell_training_queue import TrainingQueue, TrainingQueueError


def abandon_training_job(root):
    before = time.time_ns()
    with TrainingQueue(owned_path(root, "training.sqlite"), max_jobs=3) as queue:
        job = queue.claim(lease_ns=1)
        returned = time.time_ns()
        if job is None or job["cell_id"] != "runtime-training-linear" or job["attempt"] != 1:
            raise ValueError("one initial claim of the real linear training job required")
        stored = queue.db.execute("SELECT deadline_ns,created_ns FROM jobs WHERE job_id=?",
                                  (job["job_id"],)).fetchone()
    return {"claimed_job": job, "optimizer_updates": 0,
        "claim_call_started_unix_ns": before, "claim_returned_unix_ns": returned,
        "created_unix_ns": stored["created_ns"], "deadline_unix_ns": stored["deadline_ns"],
        "requested_lease_ns": 1, "lease_clock": "actual time.time_ns, no injected clock or sleep",
        "worker_exit_point": "after committed claim; before loading training inputs or optimization",
        "actual_process_killed": False, "power_loss_tested": False}


def recover_training_job(root):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    claim_at = time.time_ns()
    with TrainingQueue(owned_path(root, "training.sqlite"), max_jobs=3) as queue:
        job = queue.claim(lease_ns=120_000_000_000)
        returned = time.time_ns()
        if job is None or job["cell_id"] != "runtime-training-linear" or job["attempt"] != 2:
            raise ValueError("replacement worker must reclaim the same real linear job")
        stored = queue.db.execute("SELECT deadline_ns,created_ns FROM jobs WHERE job_id=?",
                                  (job["job_id"],)).fetchone()
        fit_at, fit_cpu = time.perf_counter_ns(), time.process_time_ns()
        result = train_persisted_job(root, job)
        receipt = {"job_id": job["job_id"], "generation": job["generation"],
            "attempt": job["attempt"], "wall_ns": time.perf_counter_ns()-fit_at,
            "cpu_ns": time.process_time_ns()-fit_cpu,
            "timing_scope": "child snapshot loading, one real fit, save, and private replay; nested in child/outer totals"}
        complete_at = time.time_ns()
        digest = queue.complete(job["job_id"], job["lease_token"], result)
        completed = time.time_ns()
        publication = queue.read_current(job["cell_id"])
        if publication is None or publication["result"] != result or result["training"]["optimizer_steps"] != 20:
            raise ValueError("recovered real training result was not durably published")
        receipt["result_sha256"] = digest
    return {"job_id": job["job_id"], "cell_id": job["cell_id"], "attempt": job["attempt"],
        "feature_identity": job["feature_identity"], "source_digest": job["source_digest"],
        "claim_call_started_unix_ns": claim_at, "claim_returned_unix_ns": returned,
        "created_unix_ns": stored["created_ns"], "deadline_unix_ns": stored["deadline_ns"],
        "lease_until_unix_ns": job["lease_until_ns"], "complete_call_started_unix_ns": complete_at,
        "completed_unix_ns": completed, "optimizer_updates": 20,
        "initial_tensor_sha256": result["initial_tensor_sha256"], "trained_tensor_sha256": result["tensor_sha256"],
        "training_receipt": receipt, "calibration_status": result["calibration_status"],
        "worker_wall_ns": time.perf_counter_ns()-began, "worker_cpu_ns": time.process_time_ns()-cpu,
        "intermediate_optimizer_resume_tested": False, "actual_process_killed": False}


def run_recoverable_queue(root, submissions, child_runner):
    """Fit exactly three modes; the first actual fit runs in a replacement worker."""
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    before_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    path = owned_path(root, "training.sqlite")
    by_mode = {s["payload"]["mode"]: s for s in submissions}
    if path.exists() or len(submissions) != 3 or set(by_mode) != {"linear", "gated", "residual"}:
        raise ValueError("fresh database and one immutable job for each mode required")
    with TrainingQueue(path, max_jobs=3) as queue:
        linear_job_id = queue.submit(**by_mode["linear"])
    abandoned = child_runner("--abandon-training", root)
    old = abandoned["result"]["claimed_job"]
    replacement = child_runner("--recover-training", root)
    recovered = replacement["result"]
    if (old["job_id"] != linear_job_id or recovered["job_id"] != linear_job_id
            or recovered["attempt"] != 2 or recovered["optimizer_updates"] != 20
            or recovered["claim_call_started_unix_ns"] < old["lease_until_ns"]):
        raise ValueError("replacement did not recover the exact naturally expired real job")
    receipts = [recovered["training_receipt"]]
    with TrainingQueue(path, max_jobs=3) as queue:
        publication = queue.read_current("runtime-training-linear")
        old_token_check_at = time.time_ns()
        try:
            queue.complete(linear_job_id, old["lease_token"], publication["result"])
        except TrainingQueueError:
            old_token_rejected = True
        else:
            raise ValueError("abandoned worker token could publish the replacement result")
        for mode in ("gated", "residual"):
            queue.submit(**by_mode[mode])
        while True:
            receipt = queue.run_one(lambda job: train_persisted_job(root, job), lease_ns=120_000_000_000)
            if receipt is None:
                break
            receipts.append(receipt)
        publications = [queue.read_current("runtime-training-"+mode) for mode in ("linear", "gated", "residual")]
        attempts = {row["cell_id"]: row["attempts"] for row in queue.db.execute("SELECT cell_id,attempts FROM jobs")}
        if (len(receipts) != 3 or any(p is None for p in publications)
                or attempts != {"runtime-training-linear": 2, "runtime-training-gated": 1, "runtime-training-residual": 1}
                or sum(p["result"]["training"]["optimizer_steps"] for p in publications) != 60):
            raise ValueError("exactly three fits and 60 real optimizer updates required")
        costs = queue.accounting()
    reopen_at, reopen_cpu = time.perf_counter_ns(), time.process_time_ns()
    with TrainingQueue(path, max_jobs=3) as queue:
        for publication in publications:
            if queue.read_current(publication["cell_id"]) != publication:
                raise ValueError("trained publication changed after reopening")
        reopened_costs = queue.accounting()
    recovery = {"wall_ns": time.perf_counter_ns()-reopen_at, "cpu_ns": time.process_time_ns()-reopen_cpu,
        "fresh_connection": True, "verified_publications": 3, "power_loss_tested": False}
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"training_receipts": receipts, "publication_digests": [p["result_sha256"] for p in publications],
        "queue_costs_open": costs, "queue_costs_reopened": reopened_costs, "recovery": recovery,
        "attempts_by_cell": attempts, "actual_optimizer_updates": 60,
        "real_job_recovery": {"abandoned_worker": abandoned, "replacement_worker": replacement,
            "same_job_reclaimed": True, "old_token_rejected": old_token_rejected,
            "old_token_check_started_unix_ns": old_token_check_at,
            "abandoned_attempt_optimizer_updates": 0, "replacement_optimizer_updates": 20,
            "short_lease_scope": "1 ns lease expires before replacement startup; no sleep, kill, load-crash simulation, or production failure-latency claim",
            "resume_semantics": "restart from immutable initial parameters and source-bound training inputs",
            "intermediate_optimizer_resume_tested": False},
        "total": {"wall_ns": time.perf_counter_ns()-began, "parent_cpu_ns": time.process_time_ns()-cpu,
            "reaped_child_cpu_ns": round(((after_children.ru_utime-before_children.ru_utime)
                +(after_children.ru_stime-before_children.ru_stime))*1e9),
            "scope": "includes abandoned and replacement processes, three fits, all publications/fences and reopen; nested times are not additional"}}
