"""POSIX research workers with common CPU allowances and retained checkpoints.

Only training data is accepted here; this module never evaluates development or
test outcomes. The integer-second RLIMIT_CPU is a hard worker-process fuse.
Cooperative training uses 90% of that allowance, reserving the rest for atomic
receipts; actual wait4 user+system CPU includes teacher, fitting and serialization.
Parent supervision and shared roster construction are separately accounted.
"""

from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import time

from .learning import (
    MAX_EXAMPLES,
    MAX_UPDATES,
    Learner,
    _sha,
    train_actor_critic,
    train_distilled,
)
from .model import Profile, legal_actions, transitions

CPU_CAPS = (1, 2, 4)
MAX_EPOCHS = 512


def classify_termination(wait_status, worker):
    """Classify observed wait status without attributing SIGKILL to CPU limits."""
    exit_code = os.waitstatus_to_exitcode(wait_status)
    worker_status = worker.get("status") if isinstance(worker, dict) else None
    name = None
    allowed = False
    if exit_code < 0:
        number = -exit_code
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = f"signal_{number}"
        if number == signal.SIGXCPU:
            kind = "CpuBudgetSignal"
            allowed = worker_status != "Failed"
        elif number == signal.SIGKILL:
            kind = "AmbiguousSigkill"
        elif number == signal.SIGALRM:
            kind = "WallAlarmSignal"
        else:
            kind = "UnexpectedSignal"
    elif exit_code == 0 and worker_status in ("Completed", "CpuBudgetStop"):
        kind = (
            "Completed" if worker_status == "Completed" else "CooperativeCpuBudgetStop"
        )
        allowed = True
    else:
        kind = "ProcessFailure" if exit_code else "MissingOrInvalidCompletionReceipt"
    if worker_status == "Failed":
        kind, allowed = "WorkerReportedFailure", False
    return {
        "kind": kind,
        "exit_code": exit_code,
        "signal": name,
        "allows_retained_checkpoint": allowed,
    }


def checkpoint_is_complete(record, plan):
    """Authenticate the retained epoch against this attempt, including labels."""
    model = Learner.from_record(record)
    training = model.training
    expected_method = (
        "fitted_actor_critic" if plan["method"] == "actor_critic" else "distilled"
    )
    if (
        model.method != expected_method
        or _sha(model.profile) != plan["profile_sha256"]
        or training["seed"] != plan["seed"]
        or training["epochs"] != plan["max_epochs"]
        or training["examples"] != plan["examples"]
        or training["examples_sha256"] != plan["examples_sha256"]
        or training["profile_sha256"] != plan["profile_sha256"]
        or training["cpu_budget_seconds"] != plan["soft_training_cpu_seconds"]
    ):
        raise ValueError("Retained checkpoint does not belong to its CPU attempt")
    epochs, retained = training["completed_epochs"], training["retained_actor_updates"]
    if (
        type(epochs) is not int
        or not 0 <= epochs <= plan["max_epochs"]
        or type(retained) is not int
        or retained != epochs * plan["examples"]
        or type(training["counts"]["actor_updates"]) is not int
        or training["counts"]["actor_updates"] < retained
    ):
        raise ValueError("Retained epoch/update evidence is inconsistent")
    if retained and training["teacher_complete"] is not True:
        raise ValueError("A retained epoch has incomplete teacher labels")
    return retained > 0


def _publish(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run_budget_worker(examples, profile, seed, method, cpu_cap, output_dir):
    """Return an attempt receipt; killed/failed work never disappears.

    A valid checkpoint is the latest complete epoch, never the best held-out
    outcome. After an unobserved hard-stop tail, actual update counts are unknown
    while retained counts and inclusive process CPU remain recorded.
    """
    if not hasattr(os, "fork") or not hasattr(os, "wait4"):
        raise RuntimeError(
            "This research mode requires POSIX fork/wait4; Windows is unsupported"
        )
    import resource
    from .run import Teacher, source_manifest

    if (
        not isinstance(examples, (list, tuple))
        or not 1 <= len(examples) <= MAX_EXAMPLES
        or not isinstance(profile, Profile)
        or type(seed) is not int
        or not 0 <= seed < 2**64
        or method not in ("actor_critic", "distillation")
        or type(cpu_cap) is not int
        or not 1 <= cpu_cap <= 60
    ):
        raise ValueError(
            "Invalid CPU sensitivity roster, method or integer-second allowance"
        )
    wall, parent_cpu = time.perf_counter(), time.process_time()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = source_manifest()
    epochs = min(MAX_EPOCHS, MAX_UPDATES // len(examples))
    plan = {
        "schema": "hepta.ctrl1.cpu-allowance.v1",
        "method": method,
        "seed": seed,
        "hard_worker_cpu_seconds": cpu_cap,
        "soft_training_cpu_seconds": 0.9 * cpu_cap,
        "wall_fuse_seconds": max(5, 4 * cpu_cap),
        "max_epochs": epochs,
        "profile": asdict(profile),
        "profile_sha256": _sha(profile),
        "examples": len(examples),
        "examples_sha256": _sha(examples),
        "sources": sources,
        "sources_sha256": _sha(sources),
        "selection": "last complete epoch; no development/test access",
        "cache": "transition and legal-action LRUs cleared inside each worker",
    }
    _publish(output / "PLAN.json", plan)
    pid = os.fork()
    if pid == 0:
        exit_code = 1
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_cap, cpu_cap))
            signal.alarm(plan["wall_fuse_seconds"])
            _publish(
                output / "LIMITS.json",
                {
                    "cpu": resource.getrlimit(resource.RLIMIT_CPU),
                    "wall_alarm_seconds": plan["wall_fuse_seconds"],
                },
            )
            transitions.cache_clear()
            legal_actions.cache_clear()

            def checkpoint(model):
                _publish(output / "CHECKPOINT.json", model.record())

            options = {
                "seed": seed,
                "epochs": epochs,
                "cpu_budget_seconds": plan["soft_training_cpu_seconds"],
                "_checkpoint_callback": checkpoint,
            }
            model = (
                train_actor_critic(examples, profile, **options)
                if method == "actor_critic"
                else train_distilled(examples, Teacher(profile), profile, **options)
            )
            checkpoint(model)
            stage = model.training["budget_stop_stage"]
            _publish(
                output / "WORKER.json",
                {
                    "status": "CpuBudgetStop" if stage else "Completed",
                    "budget_stop_stage": stage,
                    "actual_actor_updates": model.training["actual_actor_updates"],
                    "actual_counts": model.training["counts"],
                    "teacher_complete": model.training["teacher_complete"],
                    "teacher_model_calls": model.training["teacher_model_calls"],
                    "teacher_expanded_nodes": model.training["teacher_expanded_nodes"],
                },
            )
            exit_code = 0
        except BaseException as error:
            _publish(
                output / "WORKER.json",
                {
                    "status": "Failed",
                    "error_type": type(error).__name__,
                    "error": str(error)[:2000],
                },
            )
        finally:
            os._exit(exit_code)
    wait_error = None
    try:
        _, status, usage = os.wait4(pid, 0)
    except BaseException as error:
        wait_error = {"error_type": type(error).__name__, "message": str(error)[:2000]}
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        _, status, usage = os.wait4(pid, 0)
    worker_path, checkpoint_path = output / "WORKER.json", output / "CHECKPOINT.json"
    worker, record, complete, limits_validated = (
        {"status": "MissingReceipt"},
        None,
        False,
        False,
    )
    parent_error, validation = wait_error, "missing"
    try:
        if worker_path.exists():
            worker = json.loads(worker_path.read_text())
            if not isinstance(worker, dict):
                raise ValueError("Worker receipt must be an object")
        limits_path = output / "LIMITS.json"
        if limits_path.exists():
            limits = json.loads(limits_path.read_text())
            limits_validated = (
                limits["cpu"] == [cpu_cap, cpu_cap]
                and limits["wall_alarm_seconds"] == plan["wall_fuse_seconds"]
            )
        if checkpoint_path.exists():
            record = json.loads(checkpoint_path.read_text())
            complete = checkpoint_is_complete(record, plan)
            validation = "valid"
    except Exception as error:
        parent_error = {
            "error_type": type(error).__name__,
            "message": str(error)[:2000],
        }
        validation = "invalid"
        record = None
    try:
        source_drift = source_manifest() != sources
    except Exception as error:
        source_drift = None
        parent_error = {
            "error_type": type(error).__name__,
            "message": str(error)[:2000],
        }
    training = record["training"] if record else {}
    termination = classify_termination(status, worker)
    retained = training.get("retained_actor_updates", 0)
    actual_updates = (
        worker.get("actual_actor_updates") if isinstance(worker, dict) else None
    )
    available = bool(
        complete
        and not source_drift
        and parent_error is None
        and limits_validated
        and termination["allows_retained_checkpoint"]
    )
    receipt = {
        "schema": "hepta.ctrl1.cpu-attempt.v1",
        "plan_sha256": _sha(plan),
        "method": method,
        "seed": seed,
        "profile_sha256": plan["profile_sha256"],
        "examples_sha256": plan["examples_sha256"],
        "sources_sha256": plan["sources_sha256"],
        "hard_worker_cpu_seconds": cpu_cap,
        "worker": worker,
        "worker_exit_code": termination["exit_code"],
        "termination": termination,
        "worker_user_cpu_seconds": usage.ru_utime,
        "worker_system_cpu_seconds": usage.ru_stime,
        "worker_inclusive_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "parent_cpu_seconds": time.process_time() - parent_cpu,
        "wall_seconds": time.perf_counter() - wall,
        "source_drift": source_drift,
        "parent_error": parent_error,
        "checkpoint_validation": validation,
        "limits_validated": limits_validated,
        "candidate_status": "Available" if available else "NoCandidate",
        "checkpoint_path": str(checkpoint_path) if available else None,
        "retained_record_path": str(checkpoint_path)
        if checkpoint_path.exists()
        else None,
        "initial_parameters_sha256": training.get("initial_parameters_sha256"),
        "parameters_sha256": record.get("parameters_sha256") if record else None,
        "actual_actor_updates": actual_updates,
        "retained_actor_updates": retained,
        "completed_epochs": training.get("completed_epochs", 0),
        "unobserved_tail": actual_updates is None,
    }
    _publish(output / "RECEIPT.json", receipt)
    return receipt
