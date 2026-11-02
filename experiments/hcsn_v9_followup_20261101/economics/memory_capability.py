"""Fail-closed preflight for an isolated Linux hierarchical memory meter.

A shared root memory.peak is deliberately never read as a task measurement.
This preflight does not run the requested workload unless measurement is possible;
successful cgroup allocation alone is not a validated continuous RSS meter.
"""

import argparse
import errno
import json
import os
from pathlib import Path
import time


def inspect(base=Path("/sys/fs/cgroup")):
    began = time.monotonic_ns()
    record = {
        "schema": "hcsn-v9-memory-capability.v1",
        "kernel_cgroup_membership": Path("/proc/self/cgroup").read_text(),
        "base": str(base),
        "isolated_group_created": False,
        "complete_process_family_peak_bytes": None,
        "shared_cgroup_peak_used": False,
        "energy_joules": None,
        "measurement_ready": False,
    }
    for name in ("cgroup.controllers", "cgroup.subtree_control"):
        try:
            record[name] = (base / name).read_text().strip()
        except OSError as error:
            record[name] = {"errno": error.errno, "error": str(error)}
    mount_lines = Path("/proc/self/mountinfo").read_text().splitlines()
    record["cgroup_mountinfo"] = [line for line in mount_lines if " - cgroup2 " in line]
    group = base / f"hcsn-owned-probe-{os.getpid()}-{began}"
    try:
        group.mkdir()
        record["isolated_group_created"] = True
        record["required_counter_files"] = {
            name: (group / name).is_file()
            for name in ("memory.current", "memory.peak", "cpu.stat", "cgroup.procs", "cgroup.events")
        }
        record["reason"] = (
            "A fresh isolated group was available; task admission, inheritance, exit-drain, "
            "counter charging and timeout controls still require an executed qualification."
        )
    except OSError as error:
        record["mkdir_error"] = {
            "errno": error.errno, "errno_name": errno.errorcode.get(error.errno), "message": str(error)
        }
        record["reason"] = "Cannot create a fresh isolated task cgroup; shared root counters are not attributable."
    finally:
        if record["isolated_group_created"]:
            group.rmdir()
    record["probe_wall_seconds"] = (time.monotonic_ns() - began) / 1e9
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = inspect()
    with args.out.open("x") as handle:
        handle.write(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
