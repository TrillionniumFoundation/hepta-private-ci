"""Controlled wait4 high-water bound with shared pages, a short task and adoption.

Every created process has exactly one final wait4 receipt. A receipt's maxrss
is used as an upper bound for that process; inherited child maxima can only
make this sum looser. Nested CPU receipts are deliberately never summed.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


SHARED = None


def own_identity():
    raw = Path("/proc/self/stat").read_text()
    prefix, rest = raw.rsplit(") ", 1)
    return {"proc_pid": int(prefix.split(" ", 1)[0]), "start_ticks": int(rest.split()[19]),
            "namespace_pid": os.getpid()}


def allocate(mib):
    block = bytearray(mib * 1024 * 1024)
    for index in range(0, len(block), 4096):
        block[index] = (index // 4096) % 251
    return block


def wait_record(pid):
    waited, status, usage = os.wait4(pid, 0)
    return {"namespace_pid": waited, "exit_code": os.waitstatus_to_exitcode(status),
            "maxrss_upper_bytes": usage.ru_maxrss * 1024,
            "cpu_seconds_nested_diagnostic_not_additive": usage.ru_utime + usage.ru_stime}


def role(name, out, orphan=False):
    own = own_identity()
    private = allocate({"root": 0, "child": 8, "grandchild": 16, "short": 48}[name])
    children = []
    child_roles = {"root": ("child", "short"), "child": ("grandchild",), "grandchild": (), "short": ()}[name]
    for child_role in child_roles:
        pid = os.fork()
        if pid == 0:
            role(child_role, out)
            os._exit(0)
        children.append(pid)
    # A 48 MiB short task lives only briefly; wait4 still supplies its final HWM.
    time.sleep({"root": .04 if orphan else .3, "child": .20, "grandchild": .25, "short": .002}[name])
    waits = [] if orphan and name == "root" else [wait_record(pid) for pid in children]
    row = {"role": name, "identity": own, "shared_inherited_bytes": len(SHARED),
           "private_bytes": len(private), "children_namespace_pids": children,
           "waited_children": waits, "orphaning_root": orphan and name == "root",
           "self_ru_maxrss_diagnostic_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    (out / (name + ".json")).write_text(json.dumps(row, indent=2) + "\n")


def main():
    global SHARED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--orphan", action="store_true")
    parser.add_argument("--root-worker", action="store_true")
    args = parser.parse_args()
    if args.root_worker:
        SHARED = allocate(32)
        role("root", args.out, args.orphan)
        return
    args.out.mkdir(parents=True, exist_ok=False)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "subreaper failed")
    worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--root-worker",
                               "--out", str(args.out)] + (["--orphan"] if args.orphan else []))
    external = []
    while True:
        try:
            row = wait_record(-1)
            external.append(row)
            if row["namespace_pid"] == worker.pid:
                worker.returncode = row["exit_code"]
        except ChildProcessError:
            break
    records = [json.loads((args.out / (name + ".json")).read_text())
               for name in ("root", "child", "grandchild", "short")]
    waits = external + [wait for row in records for wait in row["waited_children"]]
    expected = {row["identity"]["namespace_pid"] for row in records}
    actual = [row["namespace_pid"] for row in waits]
    complete = len(actual) == len(set(actual)) and set(actual) == expected
    if not complete or any(row["exit_code"] != 0 for row in waits):
        raise RuntimeError("Complete unique per-process wait inventory failed")
    bound = sum(row["maxrss_upper_bytes"] for row in waits)
    report = {"schema": "hcsn-v10-conservative-memory-bound-fixture.v1",
              "fixture_not_model": True, "expected_roles": [row["role"] for row in records],
              "per_process_records": records, "external_waits": external,
              "per_process_waits": waits, "complete_unique_wait_inventory": complete,
              "conservative_upper_bound_rss_sum_bytes": bound,
              "exact_simultaneous_family_peak_bytes": None,
              "memory_metric": "Sum of per-process final wait4 maxrss upper bounds; shared pages and inherited maxima may be counted repeatedly",
              "mathematical_inequality": "For a complete fixed process family, sup_t sum_i RSS_i(t) <= sum_i sup_t RSS_i(t) <= sum_i H_i",
              "applicability": "Only this closed controlled fork tree with every creation and final wait receipt reconciled; not arbitrary unobserved processes or production research commands",
              "cpu_rule": "Per-process wait CPU is nested and not additive. Use enclosing stage meter CPU once."}
    (args.out / "BOUND.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"conservative_memory_upper_bound_bytes": bound,
                      "complete_unique_wait_inventory": complete}))


if __name__ == "__main__":
    main()
