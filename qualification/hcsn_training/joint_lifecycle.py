"""Stable dispatch journal. Lost contact permits observation, never relaunch."""

import os
import secrets
import subprocess

from qualification.hcsn_training.joint_outputs import read_claim, read_inputs, read_reservation, read_terminal, read_worker
from qualification.hcsn_training.joint_process import clock_ns, liveness, remaining_ns
from qualification.hcsn_training.joint_protocol import (
    COST_SCOPE, JSON_CAP, MAX_CANCELS, PROFILE, decode, descriptor, digest, encoded, fields,
    observation, require, sha, validate_command,
)
from qualification.hcsn_training.joint_store import dispatch_lock


def job_key(target):
    return sha(target["key"].encode("ascii"))


def cancel_name(dispatch):
    return job_key(dispatch) + ".json"


def internal_argv(root, sources, mode, key, nonce, claim=None):
    argv = [sources.python["path"], "-I", "-B", str(sources.repo / "qualification/hcsn_training/joint_supervisor.py"),
            "--root", str(root.path), "--root-device", str(root.expected["device"]),
            "--root-inode", str(root.expected["inode"]), "--root-uid", str(root.expected["uid"]),
            mode, key, "--nonce", nonce]
    if mode == "--worker":
        require(claim is not None, "worker must retain original claim")
        argv += ["--deadline-ns", str(claim["deadline_nanoseconds"]), "--boot-id", claim["boot_id"]]
    return argv


def child_environment(job):
    return dict(PATH=os.defpath, TMPDIR=str(job.path / "tmp"), OMP_NUM_THREADS="1",
                MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")


def finish(root, job, reservation, state, child, returncode, reason, claim=None, outputs=None, cpu_ns=None):
    """Only callers with actual confirmed termination may commit this record."""
    require(state in ("succeeded", "failed", "cancelled"), "known terminal state")
    require(type(reason) is str and 0 < len(reason.encode()) <= 256, "bounded terminal reason")
    claim_sha = None
    elapsed = 0
    if claim is not None:
        claim_raw = job.read("claim.json", JSON_CAP)
        require(decode(claim_raw) == claim, "terminal claim changed")
        claim_sha = sha(claim_raw)
        remaining_ns(claim)  # Checks boot/clock identity even after the deadline.
        elapsed = max(0, clock_ns() - claim["started_nanoseconds"])
    if state == "succeeded":
        require(type(returncode) is int and returncode == 0 and child is not None
                and claim is not None and outputs is not None
                and reason == "worker_exit_zero_and_outputs_closed", "success terminal requires actual closure")
        require(elapsed <= claim["budget_milliseconds"] * 1000000, "success exceeded original absolute deadline")
    else:
        require(outputs is None, "stopped outcome does not carry successful outputs")
    value = dict(schema_version=1, profile=PROFILE, identity=reservation["identity"],
                 input=reservation["input"], root=root.expected, process=child, state=state,
                 returncode=returncode, termination_confirmed=True, reason=reason,
                 claim_sha256=claim_sha, outputs=outputs, wall_nanoseconds=elapsed,
                 child_cpu_nanoseconds=cpu_ns, cost_scope=COST_SCOPE,
                 physical_energy_joules=None, full_history_cost=None)
    job.write("terminal.json", value)


def validate_cancellation(record):
    fields(record, ("dispatch", "target"))
    validate_command(encoded(dict(schema_version=1, profile=PROFILE, action="cancel",
                                  dispatch=record["dispatch"], target=record["target"], payload=None)))
    return record


def retained_cancel(cancellations, target):
    found = None
    for name in cancellations.names(MAX_CANCELS):
        require(name.endswith(".json"), "cancellation filename")
        digest(name[:-5])
        record = validate_cancellation(decode(cancellations.read(name, JSON_CAP)))
        require(name == cancel_name(record["dispatch"]), "retained cancellation key")
        if record["target"]["key"] == target["key"]:
            require(record["target"] == target, "target key has a different payload")
            found = record
    return found


def cancel_pending(root, job, reservation):
    if not job.exists("cancel.json"):
        return False
    with dispatch_lock(root):
        record = validate_cancellation(decode(job.read("cancel.json", JSON_CAP)))
        retained = root.child("cancellations").read(cancel_name(record["dispatch"]), JSON_CAP)
        require(decode(retained) == record and record["target"] == reservation["identity"], "cancel record changed")
    return True


def observe(root, command, sources):
    unknown = observation(command)
    try:
        job = root.child("jobs").child(job_key(command["target"]))
        reservation = read_reservation(root, job, command["target"], sources)
        read_inputs(root, reservation["input"], sources)
        if command["dispatch"] != command["target"]:
            record = decode(root.child("cancellations").read(cancel_name(command["dispatch"]), JSON_CAP))
            require(record == dict(dispatch=command["dispatch"], target=command["target"]), "query of unretained cancel")
        child = read_worker(job) if job.exists("worker.json") else None
        if job.exists("terminal.json"):
            state, evidence = read_terminal(root, job, reservation, child, sources)
            root.check()
            return observation(command, state, child, evidence)
        claim, _ = read_claim(root, job, reservation, sources)
        if remaining_ns(claim) == 0 or liveness(claim["runner"]) != "live":
            return unknown
        if child is None:
            return observation(command, "reserved")
        if liveness(child) == "live":
            return observation(command, "running", child)
    except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError):
        pass
    return unknown


def dispatch(root, command, sources):
    if command["action"] == "status":
        return observe(root, command, sources)
    action, target = command["action"], command["target"]
    with dispatch_lock(root):
        jobs = root.child("jobs", create=True, existing_ok=True)
        cancellations = root.child("cancellations", create=True, existing_ok=True)
        if action == "start":
            if jobs.exists(job_key(target)):
                # Never repair, replace a partial reservation, or launch again.
                return observe(root, command, sources)
            retained = retained_cancel(cancellations, target)
            reference = descriptor(command["payload"].encode("utf-8"))
            read_inputs(root, reference, sources)
            sources.check()
            job = jobs.child(job_key(target), create=True)
            reservation = dict(schema_version=1, profile=PROFILE, identity=target,
                               input=reference, root=root.expected, nonce=secrets.token_hex(32),
                               sources=sources.rows, absent_sources=sources.absent, python=sources.python)
            job.write("descriptor.json", command["payload"].encode("utf-8"))
            job.write("reservation.json", reservation)
            job.child("tmp", create=True)
            if retained is not None:
                job.write("cancel.json", retained)
                finish(root, job, reservation, "cancelled", None, None, "cancelled_before_runner")
            else:
                runner_started = False
                try:
                    with job.open_log("runner.stdout") as stdout, job.open_log("runner.stderr") as stderr:
                        root.check()
                        subprocess.Popen(internal_argv(root, sources, "--run", job.name, reservation["nonce"]),
                            cwd=sources.repo, env=child_environment(job), stdin=subprocess.DEVNULL,
                            stdout=stdout, stderr=stderr, close_fds=True, start_new_session=True)
                        runner_started = True
                except OSError:
                    if runner_started:
                        # A post-contact log-close error cannot prove the
                        # durable runner stopped. Preserve the partial job.
                        raise
                    finish(root, job, reservation, "failed", None, None, "runner_spawn_refused")
        else:
            name = cancel_name(command["dispatch"])
            record = dict(dispatch=command["dispatch"], target=target)
            if cancellations.exists(name):
                require(decode(cancellations.read(name, JSON_CAP)) == record, "cancel key is already bound")
            else:
                require(len(cancellations.names(MAX_CANCELS)) < MAX_CANCELS, "cancellation journal bound")
                cancellations.write(name, record)
            if jobs.exists(job_key(target)):
                job = jobs.child(job_key(target))
                reservation = read_reservation(root, job, target, sources)
                if job.exists("cancel.json"):
                    old = validate_cancellation(decode(job.read("cancel.json", JSON_CAP)))
                    require(old["target"] == target, "cancel target changed")
                else:
                    job.write("cancel.json", record)
    if action == "cancel":
        from qualification.hcsn_training.joint_runner import cancel_orphan
        cancel_orphan(root, command, sources)
    return observe(root, command, sources)
