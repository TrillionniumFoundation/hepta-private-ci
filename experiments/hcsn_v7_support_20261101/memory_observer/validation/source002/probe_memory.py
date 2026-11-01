"""Controlled parent/child/grandchild allocation probe; no candidate execution."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from process_memory import Observer


def usage(value):
    return {"user_cpu_seconds": value.ru_utime, "system_cpu_seconds": value.ru_stime,
            "largest_single_process_highwater_bytes": value.ru_maxrss * 1024}


def emit(value):
    print(json.dumps(value), flush=True)


def read_line(pipe):
    line = pipe.readline()
    if not line:
        raise RuntimeError("Owned probe process closed its handshake unexpectedly")
    return json.loads(line)


def launch(role):
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--role", role],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def wait_owned(process):
    pid, status, measured = os.wait4(process.pid, 0)
    process.returncode = os.waitstatus_to_exitcode(status)
    return {"pid_seen_by_parent": pid, "exit_code": process.returncode,
            "wait4": usage(measured)}


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
    observer = Observer()
    identity = observer.own_identity()
    retained, measured = allocation(observer, identity, 16 if role == "child" else 24)
    child = launch("grandchild") if role == "child" else None
    handshake = read_line(child.stdout) if child else None
    emit({"role": role, "identity": identity.record(), "allocation": measured,
          "child_pid_seen_by_parent": child.pid if child else None,
          "child_handshake": handshake})
    command = sys.stdin.readline().strip()
    if command != "finish":
        raise RuntimeError("Unexpected owned probe command")
    final_child, wait = None, None
    if child:
        child.stdin.write("finish\n")
        child.stdin.flush()
        final_child = read_line(child.stdout)
        wait = wait_owned(child)
    emit({"role": role, "self_usage": usage(resource.getrusage(resource.RUSAGE_SELF)),
          "retained_bytes": len(retained), "child_final": final_child, "child_wait": wait})


def parent(output):
    began, cpu_begin = time.monotonic(), time.process_time()
    observer = Observer()
    root = observer.own_identity()
    retained, parent_allocation = allocation(observer, root, 8)
    child = launch("child")
    try:
        hello = read_line(child.stdout)
        child_id = observer.register_owned_child(root, child.pid, hello["identity"])
        grandchild_hello = hello["child_handshake"]
        grandchild_id = observer.register_owned_child(child_id, hello["child_pid_seen_by_parent"],
                                                      grandchild_hello["identity"])
        members = [root, child_id, grandchild_id]
        registered = []
        families = []
        for _ in range(3):
            registered.append(observer.sample_registered_set(root, members))
            families.append(observer.sample_family(root))
            time.sleep(0.02)
        child.stdin.write("finish\n")
        child.stdin.flush()
        final_child = read_line(child.stdout)
        child_wait = wait_owned(child)
    finally:
        if child.returncode is None:
            # This is our own deliberately spawned child, never an unrelated PID.
            try:
                child.stdin.write("finish\n")
                child.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            child.wait(timeout=10)
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
              "full_family_measurement_available": all(x["available"] for x in families),
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
