"""One owned runner/worker lifecycle with an immutable absolute deadline."""

import os
import resource
import signal
import subprocess
import time

from qualification.hcsn_training.joint_lifecycle import (
    cancel_pending, child_environment, finish, internal_argv, job_key,
)
from qualification.hcsn_training.joint_outputs import read_claim, read_inputs, read_reservation, read_worker, validate_outputs
from qualification.hcsn_training.joint_process import (
    boot_id, clock_ns, host_id, liveness, process_identity, remaining_ns, stop_pidfd, verified_pidfd,
)
from qualification.hcsn_training.joint_protocol import (
    MAX_WALL_MS, PROFILE, decode, digest, process, require,
)


def admitted_job(root, key, nonce, sources):
    digest(key)
    digest(nonce)
    job = root.child("jobs").child(key)
    reservation = decode(job.read("reservation.json"))
    require(job_key(reservation["identity"]) == key, "retained job key")
    reservation = read_reservation(root, job, reservation["identity"], sources)
    require(reservation["nonce"] == nonce, "retained runner nonce")
    _, request, _, _ = read_inputs(root, reservation["input"], sources)
    return job, reservation, request


def confirm_child_record(job, child_identity):
    if child_identity is None:
        return
    process(child_identity)
    try:
        job.write("worker.json", child_identity)
    except FileExistsError:
        require(read_worker(job) == child_identity, "owned child differs from announced process")


def _owned_stop(child, pidfd):
    """The held pidfd is opened while this unreaped child is owned by us."""
    if child.poll() is not None:
        return
    require(pidfd is not None, "owned child has no retained pidfd")
    try:
        stopped = stop_pidfd(pidfd)
    except ProcessLookupError:
        stopped = True
    require(stopped, "owned child termination not confirmed")
    child.wait(timeout=5)


def run_job(root, key, nonce, sources):
    require(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "Linux pidfd lifecycle required")
    job, reservation, request = admitted_job(root, key, nonce, sources)
    started = clock_ns()
    budget = min(request["maximum_training_milliseconds"], MAX_WALL_MS)
    claim = dict(schema_version=1, profile=PROFILE, identity=reservation["identity"], root=root.expected,
                 runner=process_identity(os.getpid(), host_id()), boot_id=boot_id(), clock="CLOCK_BOOTTIME",
                 started_nanoseconds=started, deadline_nanoseconds=started + budget * 1000000,
                 budget_milliseconds=budget)
    # Atomic exclusive name reservation before launch. A partial claim is final
    # uncertainty for this identity; no second process can replace it.
    job.write("claim.json", claim)
    child = None
    child_identity = None
    pidfd = None
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        if cancel_pending(root, job, reservation):
            finish(root, job, reservation, "cancelled", None, None, "cancelled_before_worker", claim)
            return
        require(remaining_ns(claim) > 0, "claim deadline elapsed before launch")
        sources.check()
        argv = internal_argv(root, sources, "--worker", key, nonce, claim)
        with job.open_log("worker.stdout") as stdout, job.open_log("worker.stderr") as stderr:
            root.check()
            child = subprocess.Popen(argv, cwd=sources.repo, env=child_environment(job),
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, close_fds=True)
        try:
            pidfd = os.pidfd_open(child.pid)
            child_identity = process_identity(child.pid, host_id())
        except (FileNotFoundError, ProcessLookupError):
            require(child.poll() is not None, "child identity became uncertain")
        state, reason = "failed", "worker_nonzero_exit"
        while child.poll() is None:
            root.check()
            cancelled = cancel_pending(root, job, reservation)
            expired = remaining_ns(claim) == 0
            oversized = any(os.stat(name, dir_fd=job.fd, follow_symlinks=False).st_size > 1048576
                            for name in ("worker.stdout", "worker.stderr"))
            if cancelled or expired or oversized:
                _owned_stop(child, pidfd)
                state = "cancelled" if cancelled and child.returncode != 0 else "failed"
                reason = "retained_cancel_worker_stopped" if cancelled else "absolute_deadline_or_log_bound_worker_stopped"
                break
            time.sleep(0.02)
        # A nonzero/signal outcome cannot be rescued by completed.json. Even a
        # zero exit after we selected a stop condition is conservatively failed.
        if reason == "worker_nonzero_exit" and child.returncode == 0:
            state, reason = "succeeded", "worker_exit_zero_and_outputs_closed"
        if child_identity is None and job.exists("worker.json"):
            child_identity = read_worker(job)
            require(child_identity["process_id"] == child.pid, "announced child PID differs")
        confirm_child_record(job, child_identity)
        output_evidence = validate_outputs(root, job, reservation, sources) if state == "succeeded" else None
        sources.check()
        read_inputs(root, reservation["input"], sources)
        root.check()
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_ns = max(0, int((usage_after.ru_utime + usage_after.ru_stime
                            - usage_before.ru_utime - usage_before.ru_stime) * 1000000000))
        finish(root, job, reservation, state, child_identity, child.returncode, reason,
               claim, output_evidence, cpu_ns)
    except BaseException as error:
        confirmed = child is None
        if child is not None:
            _owned_stop(child, pidfd)
            confirmed = child.poll() is not None
        if confirmed:
            confirm_child_record(job, child_identity)
            if not job.exists("terminal.json"):
                finish(root, job, reservation, "failed", child_identity,
                       child.returncode if child is not None else None,
                       "runner_refusal:" + type(error).__name__, claim)
        # A failed root/name check can also prevent terminal publication. The
        # retained original partial journal then stays Unknown, never green.
        raise
    finally:
        if pidfd is not None:
            os.close(pidfd)


def cancel_orphan(root, command, sources):
    """Only an already retained Cancel may stop the identical orphan worker."""
    pidfd = None
    try:
        job = root.child("jobs").child(job_key(command["target"]))
        if job.exists("terminal.json"):
            return
        reservation = read_reservation(root, job, command["target"], sources)
        if not cancel_pending(root, job, reservation):
            return
        claim, _ = read_claim(root, job, reservation, sources)
        if liveness(claim["runner"]) not in ("stopped", "different"):
            return
        child = read_worker(job)
        expected_command = internal_argv(root, sources, "--worker", job.name, reservation["nonce"], claim)
        pidfd = verified_pidfd(child, expected_command, sources.python_resolved)
        root.check()
        stop_name = "orphan-stop-" + job_key(command["dispatch"])
        # A second contact does not send the signal twice. Missing confirmation
        # after a retained attempt is uncertainty, not permission to repeat.
        if job.exists(stop_name + ".json"):
            return
        job.write(stop_name + ".json", dict(schema_version=1, dispatch=command["dispatch"],
                  target=command["target"], process=child, signal="SIGKILL", original_claim=claim))
        stopped = stop_pidfd(pidfd)
        job.write(stop_name + ".result.json", dict(termination_confirmed=stopped,
                  actual_waitpid_returncode=None, scope="pidfd poll only; no child waitpid or CPU observation"))
        if stopped and not job.exists("terminal.json"):
            finish(root, job, reservation, "cancelled", child, None, "retained_orphan_cancel_pidfd_confirmed", claim)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        # Status retains Unknown if no complete original terminal was committed.
        return
    finally:
        if pidfd is not None:
            os.close(pidfd)
