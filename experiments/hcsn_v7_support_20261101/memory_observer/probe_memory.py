"""Controlled parent/child/grandchild allocation probe; no candidate execution."""

import argparse
import json
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import time

from process_memory import Observer


def usage(value):
    return {"user_cpu_seconds": value.ru_utime, "system_cpu_seconds": value.ru_stime,
            "largest_single_process_highwater_bytes": value.ru_maxrss * 1024}


def emit(value):
    print(json.dumps(value), flush=True)


class BoundedLineReader:
    """Bound even a partial line; readiness followed by readline is insufficient."""

    def __init__(self, pipe, timeout_seconds=10.0, max_line_bytes=131072):
        self.fd = pipe.fileno()
        self.timeout_seconds = float(timeout_seconds)
        self.max_line_bytes = int(max_line_bytes)
        self.pending = bytearray()
        if self.timeout_seconds <= 0 or self.max_line_bytes < 1:
            raise ValueError("Invalid handshake bounds")
        os.set_blocking(self.fd, False)

    def read_line(self):
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            newline = self.pending.find(b"\n")
            if newline >= 0:
                if newline > self.max_line_bytes:
                    raise RuntimeError("Owned handshake line exceeded byte bound")
                line = bytes(self.pending[:newline])
                del self.pending[:newline + 1]
                return line.decode("utf-8")
            if len(self.pending) > self.max_line_bytes:
                raise RuntimeError("Owned handshake line exceeded byte bound")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Owned handshake did not complete before its deadline")
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                raise TimeoutError("Owned handshake did not complete before its deadline")
            try:
                chunk = os.read(self.fd, min(4096, self.max_line_bytes + 1 - len(self.pending)))
            except BlockingIOError:
                continue
            if not chunk:
                raise RuntimeError("Owned probe process closed its handshake unexpectedly")
            self.pending.extend(chunk)

    def read_json(self):
        return json.loads(self.read_line())


def launch(role):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--role", role],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def wait_owned(process, timeout_seconds=10.0):
    deadline = time.monotonic() + timeout_seconds
    while True:
        pid, status, measured = os.wait4(process.pid, os.WNOHANG)
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return {"pid_seen_by_parent": pid, "exit_code": process.returncode,
                    "wait4": usage(measured)}
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned process did not exit before its deadline")
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def cleanup_owned(process, grace_seconds=1.0):
    """Only the unreaped direct child represented by this Popen is signalled."""
    if process.returncode is not None:
        return {"exit_code": process.returncode, "already_reaped": True}
    try:
        process.stdin.write("finish\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    actions = []
    for action in (None, signal.SIGTERM, signal.SIGKILL):
        if action is not None:
            # An unreaped child PID cannot be reused; no process-group signalling.
            try:
                os.kill(process.pid, action)
                actions.append(int(action))
            except ProcessLookupError:
                pass
        try:
            result = wait_owned(process, timeout_seconds=grace_seconds)
            result["cleanup_signals"] = actions
            return result
        except TimeoutError:
            continue
    raise RuntimeError("Owned process remained uncollected after bounded cleanup")


def exact_controlled_family_sample(observer, root, members):
    result = observer.sample_family(root, required_members=members)
    result["controlled_inventory_exact_match"] = None
    if result["available"]:
        expected = sorted([x.record() for x in members], key=lambda x: x["proc_pid"])
        observed = sorted([x["identity"] for x in result["members"]], key=lambda x: x["proc_pid"])
        exact = expected == observed
        result["controlled_inventory_exact_match"] = exact
        if not exact:
            result["available"] = False
            result["full_descendant_coverage"] = False
            result["reason"] = "Controlled family inventory differs from the exact registered identity set"
            result["observed_members_before_rejection"] = result["members"]
            result["members"] = None
            result["rss_sum_bytes"] = None
    return result


def allocation(observer, identity, mib):
    before = observer.read_rss(identity)
    value = bytearray(mib * 1024 * 1024)
    for i in range(0, len(value), observer.page_bytes):
        value[i] = (i // observer.page_bytes) % 251 + 1
    after = observer.read_rss(identity)
    return value, {"requested_bytes": len(value), "resident_before_bytes": before,
                   "resident_after_bytes": after, "resident_delta_bytes": after - before,
                   "touched_pages": (len(value) + observer.page_bytes - 1) // observer.page_bytes,
                   "touch_checksum": sum(value[::observer.page_bytes])}


def descendant(role):
    def terminate(_number, _frame):
        raise SystemExit(128 + signal.SIGTERM)

    signal.signal(signal.SIGTERM, terminate)
    child = None
    try:
        observer = Observer()
        identity = observer.own_identity()
        retained, measured = allocation(observer, identity, 16 if role == "child" else 24)
        child = launch("grandchild") if role == "child" else None
        child_reader = BoundedLineReader(child.stdout) if child else None
        handshake = child_reader.read_json() if child else None
        emit({"role": role, "identity": identity.record(), "allocation": measured,
              "child_pid_seen_by_parent": child.pid if child else None,
              "child_handshake": handshake})
        command = BoundedLineReader(sys.stdin).read_line().strip()
        if command != "finish":
            raise RuntimeError("Unexpected owned probe command")
        final_child, wait = None, None
        if child:
            child.stdin.write("finish\n")
            child.stdin.flush()
            final_child = child_reader.read_json()
            wait = wait_owned(child)
        emit({"role": role, "self_usage": usage(resource.getrusage(resource.RUSAGE_SELF)),
              "retained_bytes": len(retained), "child_final": final_child, "child_wait": wait})
    finally:
        if child is not None and child.returncode is None:
            cleanup_owned(child)


def parent(output):
    began, cpu_begin = time.monotonic(), time.process_time()
    observer = Observer()
    root = observer.own_identity()
    retained, parent_allocation = allocation(observer, root, 8)
    child = launch("child")
    try:
        child_reader = BoundedLineReader(child.stdout)
        hello = child_reader.read_json()
        child_id = observer.register_owned_child(root, child.pid, hello["identity"])
        grandchild_hello = hello["child_handshake"]
        grandchild_id = observer.register_owned_child(child_id, hello["child_pid_seen_by_parent"],
                                                      grandchild_hello["identity"])
        members = [root, child_id, grandchild_id]
        registered = []
        families = []
        for _ in range(3):
            registered.append(observer.sample_registered_set(root, members))
            families.append(exact_controlled_family_sample(observer, root, members))
            time.sleep(0.02)
        child.stdin.write("finish\n")
        child.stdin.flush()
        final_child = child_reader.read_json()
        child_wait = wait_owned(child)
    finally:
        if child.returncode is None:
            cleanup_owned(child)
    allocations = {"parent": parent_allocation, "child": hello["allocation"],
                   "grandchild": grandchild_hello["allocation"]}
    known_touches_observed = all(row["resident_delta_bytes"] >= 0.85 * row["requested_bytes"]
                                for row in allocations.values())
    result = {"schema": "hcsn-v7-owned-memory-observer-probe.v1",
              "allocations": allocations, "owned_root": root.record(),
              "child_pid_seen_by_parent": child.pid, "child_handshake": hello,
              "registered_process_set_samples": registered,
              "strict_process_family_samples": families,
              "registered_set_measurement_passed": all(x["available"] and len(x["members"]) == 3 for x in registered),
              "known_allocations_observed": known_touches_observed,
              "expected_controlled_identities": [x.record() for x in members],
              "full_family_measurement_available": all(x["available"] and x["controlled_inventory_exact_match"] is True for x in families),
              "child_final": final_child, "child_wait4": child_wait,
              "parent_self_usage": usage(resource.getrusage(resource.RUSAGE_SELF)),
              "retained_parent_bytes": len(retained),
              "parent_own_probe_cpu_seconds": time.process_time() - cpu_begin,
              "probe_body_wall_seconds": time.monotonic() - began,
              "accounting": "Nested component CPU is diagnostic, not additive to the enclosing complete worker wait4 receipt.",
              "limitations": ["RSS sum double-counts shared pages; it is not PSS or physical unique memory.",
                              "Per-process reads are sequential; sample spans are retained and short peaks may be missed.",
                              "Registered-set success proves only the controlled declared inventory; it does not prove general descendant coverage.",
                              "wait4 high-water for a waited subtree is a largest-single-process high-water, not simultaneous family RSS."]}
    Path(output).write_text(json.dumps(result, indent=2) + "\n")
    emit({"registered_set_measurement_passed": result["registered_set_measurement_passed"],
          "known_allocations_observed": known_touches_observed,
          "full_family_measurement_available": result["full_family_measurement_available"]})
    return 0 if result["registered_set_measurement_passed"] and known_touches_observed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["parent", "child", "grandchild"], default="parent")
    parser.add_argument("--output", default="PROBE_REPORT.json")
    args = parser.parse_args()
    if args.role == "parent":
        raise SystemExit(parent(args.output))
    descendant(args.role)
