"""Bounded Linux supervision for one immutable HCSN training dispatch.

This host tool is called by the final-use-authorized native adapter. It does not
mint authority, evaluate a candidate, publish it, or restart an uncertain job.
The private store must be initialized by its host owner before serving requests.
"""

import argparse
import importlib.machinery
import os
from pathlib import Path
import resource
import select
import secrets
import signal
import subprocess
import sys
import time

# The native transport uses -I and a pinned absolute script, never PYTHONPATH.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
class _RepositorySourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        return self.source_to_code(self.get_data(self.path), self.path)


class _RepositorySourceFinder:
    @staticmethod
    def find_spec(fullname, path=None, target=None):
        if fullname != "qualification" and not fullname.startswith("qualification."):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            if not Path(spec.origin).resolve().is_relative_to(REPO/"qualification"):
                raise ImportError("pinned repository module redirected")
            spec.loader = _RepositorySourceLoader(fullname, spec.origin)
        return spec


if __name__ == "__main__":
    # -B still reads cached bytecode. Compile pinned repository modules from
    # their source, while retaining caches for the installed Python runtime.
    sys.meta_path.insert(0, _RepositorySourceFinder())
from qualification.hcsn_training.supervisor_store import (MAX_REQUEST, decode, dispatch_lock, encoded, identity,
    initialize, job_path, observe, open_store, process_identity, read_bytes, retained_cancellation, sha, sources,
    sync_directory, validate_command, validate_outputs, write_new)

MAX_SECONDS = 300


def _log(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb")


def _command(root, mode, key, nonce):
    return [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--root", str(root),
            mode, key, "--nonce", nonce]


def _finish(job, reservation, state, process, reason, started, usage=None, evidence=None,
            cost_scope="runner observation through owned worker termination; dispatch and owner publication excluded"):
    write_new(job/"terminal.json", dict(schema_version=1, identity=reservation["identity"],
        state=state, process=process, reason=reason, termination_confirmed=True, evidence=evidence,
        wall_seconds=time.monotonic()-started, child_cpu_seconds=usage,
        cost_scope=cost_scope,
        physical_energy_joules=None, no_retry=True))


def dispatch(root, store, command):
    validate_command(command)
    if command["action"] == "status":
        return observe(root, store, command)  # Queries never resume a control effect.
    target, action = command["target"], command["action"]
    job = job_path(root, target)
    with dispatch_lock(root):
        if action == "start":
            if job.exists():
                return observe(root, store, command)
            # First cancellation also binds its target key/payload. The bounded
            # scan avoids losing a pre-start intent between two index writes.
            try:
                cancellation = retained_cancellation(root, target)
            except (OSError, ValueError, KeyError, TypeError):
                return observe(root, store, command)
            job.mkdir(mode=0o700)
            sync_directory(job.parent)
            reservation = dict(schema_version=1, identity=target, nonce=secrets.token_hex(32),
                sources=sources(), python_sha256=sha(read_bytes(Path(sys.executable).resolve(), 128*1024*1024)),
                timeout_seconds=MAX_SECONDS)
            write_new(job/"request.json", command["payload"].encode())
            write_new(job/"reservation.json", reservation)
            started = time.monotonic()
            if cancellation is not None:
                write_new(job/"cancel.json", cancellation)
                _finish(job, reservation, "cancelled", None, "cancelled_before_runner", started)
            else:
                try:
                    with _log(job/"runner.stdout") as stdout, _log(job/"runner.stderr") as stderr:
                        subprocess.Popen(_command(root, "--run", job.name, reservation["nonce"]),
                            cwd=REPO, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                            close_fds=True, start_new_session=True,
                            env={"PATH": os.defpath, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                                 "OPENBLAS_NUM_THREADS": "1"})
                except OSError as error:
                    _finish(job, reservation, "failed", None, f"runner_spawn:{type(error).__name__}", started)
        else:
            entry = root/"cancellations"/sha(command["dispatch"]["key"].encode())
            record = dict(dispatch=command["dispatch"], target=target)
            try:
                write_new(entry, record)
            except FileExistsError:
                if decode(read_bytes(entry, 4096)) != record:
                    return dict(schema_version=1, dispatch=command["dispatch"], target=target,
                                state="unknown", process=None, evidence=None)
            try:
                reservation = decode(read_bytes(job/"reservation.json", 2*1024*1024))
                if reservation["identity"] == target:
                    try:
                        write_new(job/"cancel.json", record)
                    except FileExistsError:
                        pass
            except FileNotFoundError:
                pass
    if action == "cancel":
        _cancel_orphan(root, store, job, command)
    return observe(root, store, command)


def _cancel_pending(root, job, reservation):
    if not (job/"cancel.json").exists():
        return False
    # The writer holds this lock through fsync; do not interpret its transient
    # empty create-only file as corruption or as a different cancellation.
    with dispatch_lock(root):
        record = decode(read_bytes(job/"cancel.json", 4096))
        retained = decode(read_bytes(root/"cancellations"/sha(record["dispatch"]["key"].encode()), 4096))
        if record != retained or record["target"] != reservation["identity"]:
            raise ValueError("retained cancellation differs from job")
    return True


def _cancel_orphan(root, store, job, command):
    """Continue only an explicitly retained cancel; never infer a job's outcome."""
    started = time.monotonic()
    descriptor, attempt = None, None
    try:
        if ((job/"terminal.json").exists() or not hasattr(os, "pidfd_open")
                or not hasattr(signal, "pidfd_send_signal")):
            return
        reservation = decode(read_bytes(job/"reservation.json", 2*1024*1024))
        if reservation["identity"] != command["target"] or not _cancel_pending(root, job, reservation):
            return
        runner = decode(read_bytes(job/"runner.json", 4096))
        process = decode(read_bytes(job/"worker.json", 4096))
        try:
            if process_identity(runner["process_id"], store["host_id"]) == runner:
                return
        except (FileNotFoundError, ProcessLookupError):
            pass
        descriptor = os.pidfd_open(process["process_id"])
        if process_identity(process["process_id"], store["host_id"]) != process:
            return
        expected = b"\0".join(os.fsencode(value) for value in _command(root, "--worker", job.name, reservation["nonce"]))+b"\0"
        with open(f"/proc/{process['process_id']}/cmdline", "rb") as stream:
            if stream.read(len(expected)+1) != expected:
                return
        attempt = job/("orphan-stop-"+secrets.token_hex(16))
        write_new(attempt.with_suffix(".json"), dict(schema_version=1, dispatch=command["dispatch"],
            identity=command["target"], process=process, runner=runner, signal="SIGKILL", no_retry=True))
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        poller = select.poll()
        poller.register(descriptor, select.POLLIN)
        stopped = any(fd == descriptor and events & (select.POLLIN | select.POLLHUP)
                      for fd, events in poller.poll(5000))
        output = job/reservation["identity"]["output_id"]
        possible = [name for name in ("candidate.pt", "receipt.json", "handoff.bin", "failed.json")
                    if os.path.lexists(output/name)]
        state = "cancelled" if stopped and not possible and output.resolve() == output else "unknown"
        write_new(attempt.with_suffix(".result.json"), dict(state=state, termination_confirmed=stopped,
            possible_outputs=possible, wall_seconds=time.monotonic()-started,
            cost_scope="orphan stop observation only; earlier training CPU/wall cost unknown"))
        if stopped:
            try:
                _finish(job, reservation, state, process, "orphan_worker_stopped", started,
                        cost_scope="orphan stop observation only; earlier training CPU/wall cost unknown")
            except FileExistsError:
                pass  # Another retained cancellation already terminalized it.
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        if attempt is not None:
            try:
                write_new(attempt.with_suffix(".result.json"), dict(state="unknown", error=type(error).__name__,
                    termination_confirmed=False, cost_scope="partial orphan stop observation; earlier cost unknown"))
            except OSError:
                pass  # A partial receipt is retained; it is never overwritten.
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _admitted(root, key, nonce):
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("invalid retained job path")
    job = root/"jobs"/key
    reservation = decode(read_bytes(job/"reservation.json", 2*1024*1024))
    target = reservation["identity"]
    if (reservation["nonce"] != nonce or target != identity(target["key"], target["payload_sha256"])
            or job != job_path(root, target) or sha(read_bytes(job/"request.json", MAX_REQUEST)) != target["payload_sha256"]
            or sha(read_bytes(Path(sys.executable).resolve(), 128*1024*1024)) != reservation["python_sha256"]
            or sources() != reservation["sources"] or reservation["timeout_seconds"] != MAX_SECONDS):
        raise ValueError("retained job/source/runtime binding changed")
    return job, reservation


def _confirm_child_record(job, process):
    # Called only after our owned child has terminated. This closes cancellation
    # before its self-announcement, without racing two live identity writers.
    if process is not None:
        try:
            write_new(job/"worker.json", process)
        except FileExistsError:
            if decode(read_bytes(job/"worker.json", 4096)) != process:
                raise ValueError("owned child identity differs from its announcement")


def run_job(root, store, key, nonce):
    started = time.monotonic()
    job, reservation = _admitted(root, key, nonce)
    # Only the first admitted runner can cross the worker launch boundary.
    write_new(job/"runner.json", process_identity(os.getpid(), store["host_id"]))
    if _cancel_pending(root, job, reservation):
        _finish(job, reservation, "cancelled", None, "cancelled_before_worker", started)
        return
    process = None
    child = None
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        with _log(job/"worker.stdout") as stdout, _log(job/"worker.stderr") as stderr:
            child = subprocess.Popen(_command(root, "--worker", key, nonce), cwd=REPO,
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, close_fds=True,
                env={"PATH": os.defpath, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                     "OPENBLAS_NUM_THREADS": "1"})
        process = process_identity(child.pid, store["host_id"])
        state, reason = "failed", "worker_failed"
        while child.poll() is None:
            cancelled = _cancel_pending(root, job, reservation)
            timed_out = time.monotonic()-started >= MAX_SECONDS
            oversized_log = any((job/name).stat().st_size > 1024*1024 for name in ("worker.stdout", "worker.stderr"))
            if cancelled or timed_out or oversized_log:
                child.kill()
                child.wait(timeout=5)
                if child.returncode == 0:
                    state, reason = "succeeded", "worker_completed_before_stop"
                elif cancelled and child.returncode == -signal.SIGKILL:
                    state, reason = "cancelled", "cancelled_worker_stopped"
                else:
                    state = "failed"
                    reason = "deadline_worker_stopped" if timed_out else "worker_terminal_before_or_during_stop"
                break
            time.sleep(.02)
        else:
            reason = f"worker_exit:{child.returncode}"
            if child.returncode == 0:
                state = "succeeded"
        _confirm_child_record(job, process)
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = usage_after.ru_utime+usage_after.ru_stime-usage_before.ru_utime-usage_before.ru_stime
        evidence = validate_outputs(job, reservation) if state == "succeeded" else None
        _finish(job, reservation, state, process, reason, started, cpu, evidence)
    except BaseException as error:
        # Child ownership is retained locally. A missing durable termination
        # record after runner death stays unknown; status never guesses success.
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        _confirm_child_record(job, process)
        if not (job/"terminal.json").exists():
            _finish(job, reservation, "failed", process, f"runner_error:{type(error).__name__}", started)
        raise


def run_worker(root, store, key, nonce):
    # These bounds survive runner death; never relax an existing host limit.
    signal.alarm(MAX_SECONDS)
    for kind, bound in ((resource.RLIMIT_CPU, MAX_SECONDS), (resource.RLIMIT_FSIZE, 32*1024*1024)):
        soft, hard = resource.getrlimit(kind)
        maximum = min(bound, hard) if hard != resource.RLIM_INFINITY else bound
        maximum = min(maximum, soft) if soft != resource.RLIM_INFINITY else maximum
        resource.setrlimit(kind, (maximum, maximum))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    job, reservation = _admitted(root, key, nonce)
    write_new(job/"worker.json", process_identity(os.getpid(), store["host_id"]))
    runner = decode(read_bytes(job/"runner.json", 4096))
    if process_identity(os.getppid(), store["host_id"]) != runner:
        raise ValueError("worker launcher incarnation changed before training")
    from qualification.hcsn_training.worker import main as worker_main
    sys.argv = ["hcsn-worker", "--request", str(job/"request.json"),
                "--output", str(job/reservation["identity"]["output_id"])]
    worker_main()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--initialize", action="store_true")
    modes.add_argument("--run")
    modes.add_argument("--worker")
    parser.add_argument("--nonce")
    args = parser.parse_args()
    if args.initialize:
        initialize(args.root)
        return
    store = open_store(args.root)
    if args.run:
        run_job(args.root, store, args.run, args.nonce)
    elif args.worker:
        run_worker(args.root, store, args.worker, args.nonce)
    else:
        raw = sys.stdin.buffer.read(2*MAX_REQUEST+65537)
        if len(raw) > 2*MAX_REQUEST+65536:
            raise ValueError("supervisor command byte budget exceeded")
        print(encoded(dispatch(args.root, store, decode(raw))).decode())


if __name__ == "__main__":
    main()
