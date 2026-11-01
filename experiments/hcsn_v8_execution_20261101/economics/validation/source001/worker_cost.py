"""Linux isolated task supervisor with waited-tree CPU and measured boundaries.

The outer wait4 counts the complete inner supervisor once, including its task,
waited descendants, startup, sampling and evidence serialization. Inner wait4
records are diagnostic disjoint subtrees, never added to the outer receipt.
No scientific or economic acceptance follows from a successful probe.
"""

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import selectors
import signal
import subprocess
import sys
import time

from experiments.hcsn_v7_support_20261101.memory_observer.process_memory import Observer, Unavailable


MODULE = "experiments.hcsn_v8_execution_20261101.economics.worker_cost"
ENTRY = "experiments.hcsn_v8_execution_20261101.economics.worker_entry"
MAX_EVENT_BYTES = 65536


def usage(value):
    return {"cpu_seconds": value.ru_utime + value.ru_stime,
            "user_cpu_seconds": value.ru_utime, "system_cpu_seconds": value.ru_stime,
            "largest_single_process_highwater_bytes": value.ru_maxrss * 1024}


def subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # Linux PR_SET_CHILD_SUBREAPER.
        return {"enabled": False, "reason": os.strerror(ctypes.get_errno())}
    value = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(value), 0, 0, 0) != 0 or value.value != 1:
        return {"enabled": False, "reason": "PR_GET_CHILD_SUBREAPER did not confirm"}
    return {"enabled": True, "scope": "Dedicated supervisor and its ordinary spawned descendants"}


def energy_capability():
    # A shared host counter, even if present, is not attributable device energy.
    directories = ("/sys/class/powercap", "/sys/class/hwmon", "/sys/class/drm")
    return {"joules": None, "attributable_to_task": False,
            "visible_counter_directories": {p: Path(p).exists() for p in directories},
            "reason": "No configured directly observed, attributable device-energy counter"}


def amortized_cpu(setup, execution_cpu_seconds, execution_episodes, horizons=(20, 10000)):
    """Preserve unknown required setup costs instead of silently replacing them."""
    if isinstance(execution_episodes, bool) or not isinstance(execution_episodes, int) or execution_episodes < 1:
        raise ValueError("A positive measured execution episode count is required")
    if not setup:
        raise ValueError("Explicit setup scope is required, including unavailable components")
    values = dict(setup, execution=execution_cpu_seconds)
    for name, value in values.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid cost for " + name)
    result = []
    for horizon in horizons:
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ValueError("Invalid amortization horizon")
        missing = [name for name, value in values.items() if value is None]
        known_setup = sum(x for x in setup.values() if x is not None)
        known_execution = None if execution_cpu_seconds is None else execution_cpu_seconds / execution_episodes
        total = None if missing else known_setup / horizon + known_execution
        result.append({"horizon_episodes": horizon, "cpu_seconds_per_episode": total,
                       "known_setup_cpu_seconds": known_setup,
                       "measured_execution_cpu_seconds_per_episode": known_execution,
                       "unavailable_components": missing,
                       "complete_scope": not missing})
    return result


def collect(command, out, timeout, sample_interval):
    began = time.monotonic_ns()
    sr = subreaper()
    observer = Observer()
    try:
        own = observer.own_identity()
        identity_error = None
    except Unavailable as error:
        own, identity_error = None, str(error)
    selector = selectors.DefaultSelector()
    worker = subprocess.Popen([sys.executable, "-m", ENTRY, "--", *command],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for stream, name in ((worker.stdout, "stdout"), (worker.stderr, "stderr")):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    registered, first_line, buffer = None, True, bytearray()
    waits, outputs, protocol_errors = [], [], []
    invalid_line, timed_out, completed_collection = False, False, False
    first_stdout_ns, root_exit = None, None
    strict_memory, registered_memory, memory_errors = [], [], []
    next_sample = time.monotonic()
    cleanup_deadline = None
    logs = {name: (out / (name + ".log")).open("wb") for name in ("stdout", "stderr")}
    try:
        while True:
            now = time.monotonic()
            if not timed_out and now - began / 1e9 > timeout:
                timed_out, cleanup_deadline = True, now + 2.0
                if root_exit is None:
                    # The unreaped direct child cannot have its PID reused.
                    try:
                        os.kill(worker.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if cleanup_deadline is not None and now > cleanup_deadline:
                protocol_errors.append("Outstanding descendants or inherited output pipes after timeout; collection incomplete")
                break
            for key, _ in selector.select(timeout=0.005):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                logs[key.data].write(chunk)
                if key.data != "stdout":
                    continue
                received_ns = time.monotonic_ns()
                first_stdout_ns = first_stdout_ns or received_ns
                for byte in chunk:
                    if byte != 10:
                        if not invalid_line:
                            buffer.append(byte)
                            if len(buffer) > MAX_EVENT_BYTES:
                                buffer.clear()
                                invalid_line = True
                        continue
                    if invalid_line:
                        protocol_errors.append("Oversized stdout line was not parsed as measurement metadata")
                        invalid_line = False
                        continue
                    raw, buffer = bytes(buffer), bytearray()
                    try:
                        message = json.loads(raw)
                    except (UnicodeError, json.JSONDecodeError):
                        first_line = False
                        continue
                    if not isinstance(message, dict):
                        first_line = False
                        continue
                    if first_line and message.get("kind") == "owned_exec_identity":
                        try:
                            if own is None or message.get("identity") is None:
                                raise Unavailable(message.get("reason") or identity_error)
                            registered = observer.register_owned_child(own, worker.pid, message["identity"])
                        except (Unavailable, TypeError) as error:
                            identity_error = str(error)
                    first_line = False
                    if message.get("kind") == "episode_output":
                        start = message.get("source_monotonic_ns")
                        flush = message.get("output_flush_monotonic_ns")
                        valid = (type(start) is int and type(flush) is int
                                 and began <= start <= flush <= received_ns)
                        outputs.append({"episode_id": message.get("episode_id"),
                                        "worker_reported_source_monotonic_ns": start,
                                        "worker_reported_flush_monotonic_ns": flush,
                                        "observer_received_monotonic_ns": received_ns,
                                        "bounds_valid": valid,
                                        "source_to_flush_seconds": (flush - start) / 1e9 if valid else None,
                                        "source_to_receive_upper_seconds": (received_ns - start) / 1e9 if valid else None,
                                        "scope": "Trusted worker post-flush marker; parent observes receipt upper bound"})
            if now >= next_sample and own is not None:
                required = [own] + ([registered] if registered is not None and root_exit is None else [])
                family = observer.sample_family(own, required)
                if family["available"]:
                    strict_memory.append({"at_ns": time.monotonic_ns(), "rss_bytes": family["rss_sum_bytes"]})
                elif len(memory_errors) < 3:
                    memory_errors.append(family["reason"])
                known = observer.sample_registered_set(own, required)
                if known["available"]:
                    registered_memory.append({"at_ns": time.monotonic_ns(), "rss_bytes": known["rss_sum_bytes"],
                                              "known_processes": len(required)})
                next_sample = now + sample_interval
            no_children = False
            while True:
                try:
                    pid, status, measured = os.wait4(-1, os.WNOHANG)
                except ChildProcessError:
                    no_children = True
                    break
                if pid == 0:
                    break
                exit_code = os.waitstatus_to_exitcode(status)
                waits.append({"pid_in_supervisor_namespace": pid, "is_direct_worker": pid == worker.pid,
                              "exit_code": exit_code, "wait4": usage(measured)})
                if pid == worker.pid:
                    root_exit = worker.returncode = exit_code
            if no_children and not selector.get_map():
                completed_collection = True
                break
    finally:
        selector.close()
        for stream in (worker.stdout, worker.stderr):
            if not stream.closed:
                stream.close()
        for log in logs.values():
            log.flush()
            log.close()
    end = time.monotonic_ns()
    all_samples_available = bool(strict_memory) and not memory_errors
    receipt = {"schema": "hcsn-v8-task-supervision.v1", "command": command,
               "boundary_begin_monotonic_ns": began, "boundary_end_monotonic_ns": end,
               "command_to_collection_seconds": (end - began) / 1e9,
               "first_stdout_receive_monotonic_ns": first_stdout_ns,
               "root_exit_code": root_exit, "timed_out": timed_out,
               "all_waitable_children_collected": completed_collection,
               "subreaper": sr, "disjoint_wait4_subtrees": waits,
               "observed_task_subtree_cpu_seconds": sum(x["wait4"]["cpu_seconds"] for x in waits),
               "complete_task_cpu_coverage": sr["enabled"] and completed_collection,
               "task_success": root_exit == 0 and completed_collection and not timed_out
                               and all(x["exit_code"] == 0 for x in waits),
               "episode_outputs": outputs, "protocol_errors": protocol_errors,
               "owned_identity_error": identity_error,
               "memory": {"family_sampled_peak_rss_sum_bytes": max((x["rss_bytes"] for x in strict_memory), default=None)
                          if all_samples_available else None,
                          "all_family_samples_available": all_samples_available,
                          "successful_family_samples": len(strict_memory), "family_errors": memory_errors,
                          "registered_subset_peak_rss_sum_bytes": max((x["rss_bytes"] for x in registered_memory), default=None),
                          "registered_subset_samples": registered_memory,
                          "family_samples": strict_memory,
                          "continuous_peak_proved": False, "physical_unique_memory": False,
                          "scope": "Includes supervisor. Registered subset can omit descendants; RSS sums double-count shared pages."},
               "energy": energy_capability(),
               "accounting": "Inner waited subtrees are disjoint diagnostics. Outer supervisor wait4 includes these once; never add inner waits again.",
               "limits": ["Dedicated Linux supervisor, ordinary fork/exec children; arbitrary malicious clone/reparent behavior is not qualified.",
                          "Timeout cleanup kills only an unreaped direct task. Uncollected descendants make coverage fail; no whole-tree fault recovery claim.",
                          "Sampled family RSS is not an atomic or continuous peak even where enumeration is available."]}
    (out / "SUPERVISION.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if receipt["task_success"] else 1


def run(command, out, timeout=30.0, sample_interval=0.05):
    if not command or any(not isinstance(x, str) or not x for x in command):
        raise ValueError("Nonempty argument-vector command required")
    if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(sample_interval) or sample_interval <= 0:
        raise ValueError("Positive finite timing bounds required")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    configuration = {"command": list(command), "out": str(out), "timeout": timeout, "sample_interval": sample_interval}
    (out / "CONFIG.json").write_text(json.dumps(configuration, indent=2) + "\n")
    began = time.monotonic_ns()
    with (out / "supervisor.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", MODULE, "--supervisor", str(out / "CONFIG.json")],
                                   stdout=log, stderr=subprocess.STDOUT)
        _, status, measured = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    ended = time.monotonic_ns()
    details_path = out / "SUPERVISION.json"
    details = json.loads(details_path.read_text()) if details_path.is_file() else None
    receipt = {"schema": "hcsn-v8-enclosing-worker-cost.v1", "command": list(command),
               "enclosing_supervisor_exit_code": process.returncode,
               "complete_supervisor_wait4": usage(measured),
               "cold_supervisor_to_exit_seconds": (ended - began) / 1e9,
               "monotonic_begin_ns": began, "monotonic_end_ns": ended,
               "complete_task_cpu_coverage": bool(details and details["complete_task_cpu_coverage"]),
               "task_success": bool(details and details["task_success"]),
               "supervision_sha256": hashlib.sha256(details_path.read_bytes()).hexdigest() if details else None,
               "measurement_boundary": "Before fresh supervisor creation through wait4 exit. Includes supervisor interpreter/import/startup, task exec, waited descendants, output drains, memory coordination and inner evidence write.",
               "outside_boundary": "Outer launcher bootstrap/argument parsing, CONFIG write and final RECEIPT serialization; none is candidate inference time.",
               "nested_cost_rule": "Use enclosing wait4 CPU once. Inner worker/child/grandchild and component timers are explanatory, not additive.",
               "scientific_confirmation": False, "candidate_economic_advantage": None}
    (out / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sample-interval", type=float, default=0.05)
    parser.add_argument("--supervisor", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.supervisor:
        config = json.loads(args.supervisor.read_text())
        return collect(config["command"], Path(config["out"]), config["timeout"], config["sample_interval"])
    if args.out is None:
        parser.error("--out is required")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    receipt = run(command, args.out, args.timeout, args.sample_interval)
    print(json.dumps({"out": str(args.out), "task_success": receipt["task_success"],
                      "cpu_seconds": receipt["complete_supervisor_wait4"]["cpu_seconds"],
                      "wall_seconds": receipt["cold_supervisor_to_exit_seconds"]}))
    return 0 if receipt["task_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
