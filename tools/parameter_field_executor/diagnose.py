"""Engineering-only executor measurements; never loads a study or admits science."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import struct
import tempfile
import time

RAM_GATE = 1879048192
DISK_GATE = 2415919104
CONTRACT = Path(__file__).with_name("runtime_contract.json")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def runtime_digest(value):
    """The frozen codec's scalar subset; reject unsupported state rather than coerce."""
    def tagged(item):
        if item is None:
            return ["none"]
        if type(item) is bool:
            return ["bool", item]
        if type(item) is int:
            return ["int", str(item)]
        if type(item) is str:
            return ["str", item]
        if type(item) is dict and all(type(k) is str for k in item):
            return ["dict", [[tagged(k), tagged(item[k])] for k in sorted(item, key=lambda k: canonical(tagged(k)))]]
        raise ValueError("Non-scalar runtime descriptor")

    header = canonical({"tree": tagged(value), "arrays": []})
    return hashlib.sha256(b"HEPTA_BRANCH_PREPARATION_1\n" + struct.pack(">Q", len(header)) + header).hexdigest()


def memory_node(path, allow_unconstrained_root=False):
    try:
        if allow_unconstrained_root and not (path / "memory.max").exists() and not (path / "memory.current").exists():
            controllers = (path / "cgroup.controllers").read_text().split()
            if "memory" in controllers and (path / "cgroup.procs").is_file():
                return {"path": str(path), "kind": "unconstrained_kernel_root", "finite_limit": None,
                        "current": None, "effective_available": None,
                        "evidence": "Mapped cgroup2 mount root=/; root has memory controller and cgroup.procs but neither limit nor usage interface.",
                        "oom_counters_unavailable": True}
        values = {}
        for name in ("memory.stat", "memory.events"):
            values.update({k: int(v) for k, v in (line.split() for line in (path / name).read_text().splitlines())})
        maximum = (path / "memory.max").read_text().strip()
        current = int((path / "memory.current").read_text())
        clean = max(0, values.get("inactive_file", 0) - values.get("file_dirty", 0) - values.get("file_writeback", 0))
        limit = None if maximum == "max" else int(maximum)
        return {"path": str(path), "finite_limit": limit, "current": current, "clean_inactive_file": clean,
                "effective_available": None if limit is None else limit - max(0, current - clean),
                "oom": values.get("oom", 0), "oom_kill": values.get("oom_kill", 0)}
    except (OSError, ValueError) as error:
        return {"path": str(path), "error_type": type(error).__name__, "effective_available": None}


def ancestor_nodes(leaf, mount, allow_unconstrained_root=False):
    if not leaf.is_relative_to(mount):
        raise ValueError("Cgroup leaf escaped its mount")
    return [memory_node(p, allow_unconstrained_root=allow_unconstrained_root and p == mount)
            for p in (leaf, *leaf.parents) if p.is_relative_to(mount)]


def cgroups():
    try:
        relative = next(line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
        mount_line = next(line for line in Path("/proc/self/mountinfo").read_text().splitlines() if " - cgroup2 " in line)
        fields = mount_line.split(" - ", 1)[0].split()
        root, mount = Path(fields[3].replace("\\040", " ")), Path(fields[4].replace("\\040", " "))
        visible = Path(relative)
        if ".." in visible.parts or ".." in root.parts:
            return {"error_type": "CgroupNamespaceMappingUnknown", "nodes": []}
        if visible.is_relative_to(root):
            leaf = mount / visible.relative_to(root)
        elif relative == "/":
            leaf = mount
        else:
            return {"error_type": "CgroupNamespaceMappingUnknown", "nodes": []}
        nodes = ancestor_nodes(leaf, mount, allow_unconstrained_root=root == Path("/"))
        finite = [n["effective_available"] for n in nodes if n.get("effective_available") is not None]
        return {"nodes": nodes, "mount_root": str(root), "hidden_ancestors_not_observed": True,
                "minimum_visible_finite_headroom": min(finite) if finite else None,
                "all_visible_nodes_readable": not any("error_type" in n for n in nodes)}
    except (OSError, ValueError, StopIteration) as error:
        return {"error_type": type(error).__name__, "nodes": []}


def capacity(work):
    space = os.statvfs(work)
    original = memory_node(Path("/sys/fs/cgroup"))
    hierarchy = cgroups()
    host_available = None
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            host_available = int(line.split()[1]) * 1024
    bounds = [host_available, hierarchy.get("minimum_visible_finite_headroom")]
    measured = [x for x in bounds if x is not None]
    candidate = min(measured) if measured and hierarchy.get("all_visible_nodes_readable", False) else None
    return {"at_unix": time.time(), "original_root": original, "hierarchy": hierarchy,
            "host_mem_available": host_available, "disk_available": space.f_bavail * space.f_frsize,
            "candidate_effective_available": candidate,
            "candidate_joint_pass": candidate is not None and candidate >= RAM_GATE
            and space.f_bavail * space.f_frsize >= DISK_GATE,
            "candidate_scope": "Host MemAvailable bounded by every visible finite ancestor; observation for a prospective registration, not the original launcher gate.",
            "available_inodes": space.f_favail,
            "original_joint_pass": original.get("effective_available") is not None
            and original["effective_available"] >= RAM_GATE and space.f_bavail * space.f_frsize >= DISK_GATE}


def process_probe():
    """Only this function's direct tiny child is created and reaped."""
    try:
        import resource
        read_fd, write_fd = os.pipe()
        started = time.monotonic()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                os.setsid()
                payload = {"pid": os.getpid(), "session": os.getsid(0), "group": os.getpgrp(),
                           "proc_pid": int(Path("/proc/self/stat").read_text().split(" ", 1)[0])}
                sum(i * i for i in range(50000))
                os.write(write_fd, canonical(payload))
                os._exit(0)
            except BaseException:
                os._exit(7)
        os.close(write_fd)
        raw = os.read(read_fd, 1024)
        os.close(read_fd)
        waited, status, usage = os.wait4(pid, 0)
        child = json.loads(raw) if raw else {}
        return {"supported": waited == pid and os.waitstatus_to_exitcode(status) == 0
                and child.get("pid") == child.get("session") == child.get("group") == child.get("proc_pid"),
                "child": child, "exit_code": os.waitstatus_to_exitcode(status),
                "wall_seconds": time.monotonic() - started, "user_cpu_seconds": usage.ru_utime,
                "system_cpu_seconds": usage.ru_stime, "peak_rss_bytes": usage.ru_maxrss * 1024,
                "parent_usage_measured": resource.getrusage(resource.RUSAGE_SELF).ru_utime >= 0,
                "detached_measuring_parent_lifecycle_qualified": False}
    except (OSError, AttributeError, ValueError) as error:
        return {"supported": False, "error_type": type(error).__name__}


def filesystem_probe(work):
    result = {}
    with tempfile.TemporaryDirectory(prefix="executor-measurement-", dir=work) as temporary:
        directory = Path(temporary)
        path = directory / "payload"
        try:
            import fcntl
            with path.open("xb") as stream:
                stream.write(b"synthetic executor measurement\n" * 128)
                stream.flush()
                os.fsync(stream.fileno())
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.setxattr(path, "user.executor-qualification", b"synthetic")
            result["xattr"] = os.getxattr(path, "user.executor-qualification") == b"synthetic"
            original = hashlib.sha256(path.read_bytes()).hexdigest()
            final = directory / "renamed"
            os.replace(path, final)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            result.update(fsync=True, atomic_rename=True, flock=True,
                          byte_readback=hashlib.sha256(final.read_bytes()).hexdigest() == original)
        except (OSError, ImportError, AttributeError) as error:
            result["error_type"] = type(error).__name__
    return result


def runtime_probe(expected):
    try:
        import sys
        import numpy as np
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        value = {"python": sys.version, "torch": str(torch.__version__), "numpy": np.__version__,
                 "torch_build": torch.__config__.show(), "cpu_capability": torch.backends.cpu.get_cpu_capability(),
                 "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
                 "default_dtype": str(torch.get_default_dtype()), "grad_enabled": torch.is_grad_enabled(),
                 "inference_mode": torch.is_inference_mode_enabled(), "autocast_cpu": torch.is_autocast_enabled("cpu"),
                 "deterministic": torch.are_deterministic_algorithms_enabled(),
                 "matmul_precision": torch.get_float32_matmul_precision(), "mkldnn": torch.backends.mkldnn.enabled,
                 "environment": {k: os.environ.get(k) for k in ("ATEN_CPU_CAPABILITY", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}
        versions = {name: importlib.metadata.version(name) for name in expected["package_versions"]}
        digest = runtime_digest(value)
        return {"descriptor": value, "runtime_sha256": digest, "package_versions": versions,
                "exact_match": digest == expected["runtime_sha256"] and versions == expected["package_versions"],
                "different_fields": [k for k in value if value[k] != expected["descriptor"][k]],
                "model_created": False, "scientific_inputs_opened": False}
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        return {"exact_match": False, "error_type": type(error).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resource-only", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    expected = json.loads(CONTRACT.read_text())
    if runtime_digest(expected["descriptor"]) != expected["runtime_sha256"]:
        raise ValueError("Published historical runtime descriptor is internally inconsistent")
    first = capacity(args.output.parent)
    bounds = [first["host_mem_available"], first["hierarchy"].get("minimum_visible_finite_headroom")]
    readable = first["hierarchy"].get("all_visible_nodes_readable", False)
    can_import = readable and any(x is not None for x in bounds) and min(x for x in bounds if x is not None) >= RAM_GATE
    runtime = runtime_probe(expected) if can_import and not args.resource_only else {
        "exact_match": False, "not_measured": "resource_only" if args.resource_only else "insufficient_or_unknown_visible_headroom"}
    samples = []
    for index in range(3):
        samples.append(capacity(args.output.parent))
        if index < 2:
            time.sleep(10)
    process, filesystem = process_probe(), filesystem_probe(args.output.parent)
    flags = next((line.split(":", 1)[1].split() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("flags")), [])
    report = {"schema": "hepta.executor-qualification.engineering.1", "at_unix": time.time(),
              "scope": "Synthetic capability measurements; no scientific input, worker or admission.",
              "platform": {"machine": platform.machine(), "kernel": platform.release(),
                           "avx512_flags": sorted(f for f in flags if f.startswith("avx512"))},
              "runtime": runtime, "runtime_import_admitted_by_visible_headroom": can_import,
              "capacity_samples": samples, "sample_interval_seconds": 10,
              "original_thresholds": {"ram_bytes": RAM_GATE, "disk_bytes": DISK_GATE, "samples": 3},
              "three_original_joint_passes": all(s["original_joint_pass"] for s in samples),
              "three_candidate_joint_passes": all(s["candidate_joint_pass"] for s in samples),
              "process": process, "filesystem": filesystem, "science_admission": False,
              "unresolved_science_requirements": ["new committed operational registration and source closure",
                  "authenticated full ancestry/data restoration and original import/preflight checks",
                  "17 fresh same-version independent readback/ACK barriers and terminal closure",
                  "original detached-parent lifecycle and 12-hour deadline/cost contract"]}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"report": str(args.output), "exact_runtime": runtime["exact_match"],
                      "original_capacity_gate": report["three_original_joint_passes"], "science_admission": False}))


if __name__ == "__main__":
    main()
