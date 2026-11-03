#!/usr/bin/env python3
"""Measure one Runtime-owned native worker; never retry or create an authority.

Linux only. The wrapper proves waiting/signalling its own direct child. It does
not create a session/group, walk PIDs, or claim to reap arbitrary descendants.
Runtime's externally verified process-group/cgroup owner retains that scope.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def identity(pid, pidfd=None):
    # A direct child is not reaped until our wait4 call. start_ticks + boot_id
    # records the observed identity; no later PID lookup grants signal authority.
    own_fd = pidfd is None
    if own_fd:
        pidfd = os.pidfd_open(pid, 0)
    try:
        # A mounted procfs can describe an ancestor PID namespace. Resolve its
        # PID from our bound descriptor; /proc/<getpid()> can name somebody else.
        info = dict(line.split(":", 1) for line in Path(f"/proc/self/fdinfo/{pidfd}").read_text().splitlines())
        proc_pid = int(info["Pid"].strip())
        namespaces = [int(value) for value in info["NSpid"].split()]
        if proc_pid <= 0 or not namespaces or namespaces[-1] != pid:
            raise ValueError("pidfd namespace identity is unavailable or mismatched")
        proc = Path(f"/proc/{proc_pid}")
        text = (proc / "stat").read_text()
        if int(text.split(" ", 1)[0]) != proc_pid:
            raise ValueError("pidfd and procfs identity differ")
        fields = text.rsplit(") ", 1)[1].split()
        return {"pid": pid, "procfs_pid": proc_pid, "namespace_pids": namespaces,
                "start_ticks": int(fields[19]),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "parent_procfs_pid": int(fields[1]), "process_group": int(fields[2]),
                "session": int(fields[3]), "cgroup_observed": (proc / "cgroup").read_text()}
    finally:
        if own_fd:
            os.close(pidfd)


def usage(value):
    return {"user_cpu_seconds": value.ru_utime, "system_cpu_seconds": value.ru_stime,
            "peak_rss_kib": value.ru_maxrss, "minor_faults": value.ru_minflt,
            "major_faults": value.ru_majflt, "input_blocks": value.ru_inblock,
            "output_blocks": value.ru_oublock, "voluntary_switches": value.ru_nvcsw,
            "involuntary_switches": value.ru_nivcsw}


class Receipt:
    """Exclusive intent, then atomic/fsynced updates in one pinned directory."""
    def __init__(self, path, value):
        self.name = path.name
        self.directory = os.open(path.parent.resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY)
        try:
            fd = os.open(self.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self.directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
            os.fsync(self.directory)
        except BaseException:
            os.close(self.directory)
            raise

    def save(self, value):
        name = self.name + ".tmp-" + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.name, src_dir_fd=self.directory, dst_dir_fd=self.directory)
            os.fsync(self.directory)
        finally:
            try:
                os.unlink(name, dir_fd=self.directory)
            except FileNotFoundError:
                pass

    def close(self):
        os.close(self.directory)


def run(args):
    started = time.monotonic_ns()
    started_unix = time.time_ns()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command or not Path(command[0]).is_absolute():
        raise ValueError("one absolute worker executable and its exact argv are required")
    binary = Path(command[0]).resolve(strict=True)
    if not stat.S_ISREG(binary.stat().st_mode) or sha256_file(binary) != args.worker_sha256:
        raise ValueError("worker executable does not match the supplied SHA256; no child submitted")
    if (sys.platform != "linux" or not hasattr(os, "wait4") or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")):
        raise ValueError("Linux wait4 and pidfd support are required")
    if not (0 < args.ready_timeout_seconds <= 300
            and 0 < args.terminate_grace_seconds <= 3 and 0 < args.kill_wait_seconds <= 3):
        raise ValueError("ready timeout must be 0..300s; TERM/KILL bounds must each be 0..3s")
    if args.receipt.exists():
        raise FileExistsError("existing receipt is a no-replay boundary; observe the original Runtime job")

    signals = []
    def request_stop(number, _frame):
        # No signalling, reaping or filesystem work in an asynchronous handler.
        if not signals:
            signals.append({"number": number, "name": signal.Signals(number).name,
                            "observed_monotonic_ns": time.monotonic_ns(),
                            "observed_unix_ns": time.time_ns()})
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, request_stop)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    before = usage(resource.getrusage(resource.RUSAGE_CHILDREN))
    record = {"schema": "hepta.cell-worker-lifecycle.v1", "state": "intent",
              "complete": False, "classification": "unknown", "launch_attempts": 0,
              "started_unix_ns": started_unix, "started_monotonic_ns": started,
              "wrapper_identity": identity(os.getpid()), "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
              "worker_executable": str(binary), "worker_sha256": args.worker_sha256,
              "argv": command, "argv_sha256": hashlib.sha256(encoded(command)).hexdigest(),
              "argv_encoding": "UTF-8 compact sort_keys JSON array plus newline",
              "qualification_job_label": os.environ.get("HEPTA_QUALIFICATION_JOB_LABEL"),
              "runtime_job_id_environment_observation": os.environ.get("HEPTA_RUNTIME_JOB_ID"),
              "runtime_job_id_provenance": "observed inherited environment only; bind to the original Runtime receipt externally",
              "rusage_children_before": before, "signals_received": signals, "signals_sent": [],
              "scope": {"new_session": False, "new_process_group": False,
                        "signal_target": "own direct child, only before its wait4 reap",
                        "descendants_reaped_or_cleaned_by_wrapper": False,
                        "external_cleanup_verified": False,
                        "external_verification_required": "retain original Runtime job and systemd KillMode/ControlGroup evidence; recorded cgroup text alone does not prove containment or descendant cleanup"},
              "ready": None, "stdout_bytes_forwarded": 0, "stdout_eof": False,
              "child_reaped": False, "wait4_usage": None}
    receipt = Receipt(args.receipt, record)
    child = None
    child_pidfd = None
    selector = selectors.DefaultSelector()
    error = None
    ready_buffer = bytearray()
    pending_stdout = bytearray()
    original_stdout_blocking = os.get_blocking(sys.stdout.fileno())
    reap_at = None
    returncode = None

    def save():
        record["signals_received"] = list(signals)
        receipt.save(record)

    def reap():
        nonlocal reap_at, returncode
        if child is None or record["child_reaped"]:
            return
        try:
            pid, status, measured = os.wait4(child.pid, os.WNOHANG)
        except ChildProcessError:
            # ECHILD invalidates even our previously owned numeric identity.
            # No later exception cleanup may signal that PID.
            record["child_wait_identity_lost"] = True
            raise
        if pid == child.pid:
            returncode = os.waitstatus_to_exitcode(status)
            child.returncode = returncode  # Popen must not perform a second wait.
            record.update({"child_reaped": True, "child_wait_status": status,
                           "child_returncode": returncode, "wait4_usage": usage(measured),
                           "child_reaped_unix_ns": time.time_ns()})
            reap_at = time.monotonic()

    def send(number):
        if child is None or record["child_reaped"] or record.get("child_wait_identity_lost"):
            return
        # SIGCHLD is not ignored, there is one child and no other wait path.
        # Until wait4 returns this child, its PID cannot be reused. Never signal
        # a historical numeric PID after reap, even on a later exception.
        row = {"number": number, "name": signal.Signals(number).name,
               "unix_ns": time.time_ns(), "child_unreaped": True,
               "mechanism": "pidfd" if child_pidfd is not None else "unreaped-direct-child-pid"}
        try:
            if child_pidfd is not None:
                signal.pidfd_send_signal(child_pidfd, number, None, 0)
            else:
                # Only a failed pidfd acquisition after our Popen can reach
                # this path, still before any reap. ECHILD forbids it above.
                os.kill(child.pid, number)
            row["result"] = "submitted"
        except ProcessLookupError:
            row["result"] = "already_absent"
        record["signals_sent"].append(row)

    def forward(raw):
        if len(pending_stdout) + len(raw) > 2 * 1024 * 1024:
            raise BufferError("bounded stdout queue is full; stop original child instead of blocking cancellation")
        pending_stdout.extend(raw)

    def flush_stdout():
        while pending_stdout:
            try:
                count = os.write(sys.stdout.fileno(), pending_stdout[:65536])
            except BlockingIOError:
                return
            record["stdout_bytes_forwarded"] += count
            del pending_stdout[:count]
            if signals:
                return

    def drain():
        if record["stdout_eof"] or child is None:
            return
        for key, _ in selector.select(0):
            try:
                raw = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            if not raw:
                selector.unregister(key.fd)
                record["stdout_eof"] = True
                if ready_buffer:
                    forward(ready_buffer); ready_buffer.clear()
                return
            if record["ready"] is not None:
                forward(raw)
                continue
            ready_buffer.extend(raw)
            if len(ready_buffer) > 1024 * 1024:
                raise ValueError("worker ready line exceeded the 1 MiB qualification bound")
            newline = ready_buffer.find(b"\n")
            if newline < 0:
                continue
            line = bytes(ready_buffer[:newline + 1])
            value = json.loads(line)
            if not isinstance(value, dict) or value.get("ready") is not True:
                raise ValueError("worker first line was not a ready JSON object")
            record["ready"] = {"json": value, "raw_base64": base64.b64encode(line).decode(),
                               "sha256": hashlib.sha256(line).hexdigest(), "bytes": len(line),
                               "observed_unix_ns": time.time_ns(),
                               "wrapper_start_to_ready_seconds": (time.monotonic_ns() - started) / 1e9}
            record["state"] = "ready"
            save()  # Persist the raw ready receipt before exposing that same line.
            forward(ready_buffer); ready_buffer.clear()

    try:
        if signals:
            record["classification"] = "cancelled"
        else:
            record["launch_attempts"] = 1
            record["state"] = "launch_intent"
            save()
            if signals:
                raise InterruptedError("cancel observed before child creation; no retry")
            child = subprocess.Popen(command, executable=str(binary), stdout=subprocess.PIPE,
                                     stdin=None, stderr=None, close_fds=True, start_new_session=False)
            record["child_pid"] = child.pid
            child_pidfd = os.pidfd_open(child.pid, 0)
            record["child_identity"] = identity(child.pid, child_pidfd)
            record["child_spawned_unix_ns"] = time.time_ns()
            record["state"] = "running"
            wrapper = record["wrapper_identity"]
            original = record["child_identity"]
            if original["parent_procfs_pid"] != wrapper["procfs_pid"]:
                raise ValueError("pidfd child is not the recorded wrapper's direct child")
            record["inherited_scope_observed"] = {
                name: original[name] == wrapper[name] for name in ("session", "process_group", "cgroup_observed")}
            save()
            # A full Runtime/log-reader pipe must not strand the wrapper in a
            # restarted blocking write while SIGTERM only sets its flag.
            os.set_blocking(sys.stdout.fileno(), False)
            os.set_blocking(child.stdout.fileno(), False)
            selector.register(child.stdout, selectors.EVENT_READ)
            ready_deadline = time.monotonic() + args.ready_timeout_seconds
            while True:
                drain()
                flush_stdout()
                reap()
                if signals:
                    break
                if record["child_reaped"]:
                    if (record["stdout_eof"] and not pending_stdout) or time.monotonic() - reap_at >= 1:
                        break
                elif record["ready"] is None and time.monotonic() >= ready_deadline:
                    raise TimeoutError("worker ready deadline expired; original child is stopped, never retried")
                time.sleep(0.02)
    except BaseException as exc:
        error = repr(exc)
        record["error"] = error
    finally:
        if child is not None and not record["child_reaped"]:
            record["state"] = "stopping"
            try:
                term_until = time.monotonic() + args.terminate_grace_seconds
                kill_until = term_until + args.kill_wait_seconds
                send(signal.SIGTERM)
                try:
                    save()
                except OSError as exc:
                    record.setdefault("receipt_publication_errors", []).append(repr(exc))
                escalated = False
                while not record["child_reaped"]:
                    reap()
                    if record["child_reaped"]:
                        break
                    now = time.monotonic()
                    if now >= term_until and not escalated:
                        send(signal.SIGKILL); escalated = True
                        try:
                            save()
                        except OSError as exc:
                            record.setdefault("receipt_publication_errors", []).append(repr(exc))
                    if now >= kill_until:
                        record["cleanup_unknown"] = "original direct child not reaped by bounded deadline; external Runtime owner must reconcile"
                        break
                    time.sleep(0.02)
            except BaseException as exc:
                record["cleanup_unknown"] = repr(exc)
        if child is not None:
            try:
                drain()
                flush_stdout()
            except BaseException as exc:
                record["output_drain_error"] = repr(exc)
            child.stdout.close()
        if child_pidfd is not None:
            os.close(child_pidfd)
        os.set_blocking(sys.stdout.fileno(), original_stdout_blocking)
        selector.close()
        record["stdout_pending_bytes_at_exit"] = len(pending_stdout)
        record["stdout_transport_complete"] = record["stdout_eof"] and not pending_stdout and not ready_buffer
        after = usage(resource.getrusage(resource.RUSAGE_CHILDREN))
        record["rusage_children_after"] = after
        record["rusage_children_cpu_delta_seconds"] = {
            key: after[key] - before[key] for key in ("user_cpu_seconds", "system_cpu_seconds")}
        record["resource_scope"] = "wait4 accounts the one reaped direct child and any descendants it itself waited for; RUSAGE_CHILDREN is cumulative waited-child usage. Linux peak RSS is KiB, a maximum, never a before/after subtraction or sum. Arbitrary descendants and Runtime supervisor/SSH CPU are not proved here."
        record["wrapper_self_usage"] = usage(resource.getrusage(resource.RUSAGE_SELF))
        record["wrapper_usage_sample_scope"] = "cumulative process usage through this sample, before final receipt serialization/fsync; Runtime startup/SSH/supervisor usage is external"
        record["cancellation_classification_scope"] = "an external stop signal observed by the wrapper; child exit code and signals sent are retained separately, without inferring signal causality"
        record["finished_unix_ns"] = time.time_ns()
        record["observed_lifecycle_wall_seconds"] = (time.monotonic_ns() - started) / 1e9
        record["complete"] = bool(record["child_reaped"])
        record["state"] = "terminal" if record["child_reaped"] else "unknown"
        if record["child_reaped"]:
            record["classification"] = ("cancelled" if signals else "normal" if returncode == 0 and
                                        record["ready"] is not None and error is None else "failed")
        elif child is None and signals:
            record.update({"state": "cancelled_before_spawn", "classification": "cancelled"})
        elif child is None:
            record.update({"state": "launch_failed", "classification": "failed"})
        try:
            save()
        finally:
            receipt.close()
    if record["classification"] == "normal":
        return 0
    if signals:
        return 128 + signals[0]["number"]
    return 124 if record["classification"] == "unknown" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--worker-sha256", required=True)
    parser.add_argument("--ready-timeout-seconds", type=float, default=30)
    parser.add_argument("--terminate-grace-seconds", type=float, default=1)
    parser.add_argument("--kill-wait-seconds", type=float, default=2)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        return run(args)
    except BaseException as exc:
        print("worker lifecycle failed: " + repr(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
