#!/usr/bin/env python3
"""Measure the actual codec probe with GNU time and optional Valgrind DHAT.

Whole-process CPU/RSS and instrumented heap observations are not per-operation
latency, default-product evidence, an allocator sandbox or host qualification.
Missing tools, malformed observations and wrong semantic outcomes never pass.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import time

from probe_execution import invoke_probe
from resource_workloads import boundary_cases, workload_identity

MAX_PROFILE_BYTES = 16 * 1024 * 1024
MAX_PROFILE_POINTS = 65_536
MAX_SAMPLES = 32


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate profiler JSON key")
        result[key] = value
    return result


def _invalid_number(_value):
    raise ValueError("profiler counters must be JSON integers")


def _counter(value):
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError("invalid profiler counter")
    return value


def parse_time(data, expected_exit):
    """GNU time emits hundredths of a CPU second and KiB maximum resident set."""
    if type(expected_exit) is not int or expected_exit not in (0, 2):
        raise ValueError("invalid expected process exit")
    if type(data) is not bytes or not data or len(data) > 1024:
        raise ValueError("invalid GNU time observation size")
    fields = data.decode("ascii").splitlines()
    if (len(fields) != 4 or any(re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{2}", x) is None
                                for x in fields[:2])
            or re.fullmatch(r"[1-9][0-9]*", fields[2]) is None
            or fields[3] != str(expected_exit)):
        raise ValueError("malformed or inconsistent GNU time observation")
    return {"user_cpu_ns": _counter(int(Decimal(fields[0]) * 1_000_000_000)),
            "system_cpu_ns": _counter(int(Decimal(fields[1]) * 1_000_000_000)),
            "cpu_resolution_ns": 10_000_000,
            "max_rss_bytes": _counter(int(fields[2]) * 1024),
            "scope": "whole_probe_process_including_startup"}


def parse_dhat(data):
    """Sum global-peak contributions (gb), never independent point maxima (mb)."""
    if type(data) is not bytes or not data or len(data) > MAX_PROFILE_BYTES:
        raise ValueError("invalid DHAT observation size")
    report = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                        parse_float=_invalid_number, parse_constant=_invalid_number)
    if (type(report) is not dict or type(report.get("dhatFileVersion")) is not int
            or report["dhatFileVersion"] != 2 or report.get("mode") != "heap"
            or report.get("bklt") is not True or report.get("tu") != "instrs"):
        raise ValueError("unsupported DHAT heap profile")
    if _counter(report.get("tg")) > _counter(report.get("te")):
        raise ValueError("DHAT global peak follows process termination")
    points = report.get("pps")
    if type(points) is not list or not 0 < len(points) <= MAX_PROFILE_POINTS:
        raise ValueError("missing or oversized DHAT point inventory")
    totals = {field: 0 for field in ("tb", "tbk", "gb", "gbk", "eb", "ebk")}
    for point in points:
        if type(point) is not dict:
            raise ValueError("invalid DHAT point")
        values = {field: _counter(point.get(field)) for field in totals}
        if (values["gb"] > values["tb"] or values["eb"] > values["tb"]
                or values["gbk"] > values["tbk"] or values["ebk"] > values["tbk"]):
            raise ValueError("inconsistent DHAT allocation counters")
        for field, value in values.items():
            totals[field] = _counter(totals[field] + value)
    return {"total_allocated_bytes": totals["tb"], "total_allocated_blocks": totals["tbk"],
            "global_peak_live_bytes": totals["gb"], "global_peak_live_blocks": totals["gbk"],
            "exit_live_bytes": totals["eb"], "exit_live_blocks": totals["ebk"],
            "scope": "whole_probe_process_under_valgrind_dhat",
            "native_latency_measurement": False}


def executable_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_observation(path, maximum):
    if type(maximum) is not int or not 0 < maximum <= MAX_PROFILE_BYTES:
        raise ValueError("invalid profiler byte budget")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
        raise ValueError("missing, non-regular or oversized profiler observation")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (not stat.S_ISREG(before.st_mode)
                or (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns) != identity):
            raise ValueError("profiler observation changed before reading")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    path_after = path.lstat()
    if (len(data) != info.st_size
            or any((item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
                   != identity for item in (after, path_after))):
        raise ValueError("profiler observation changed while reading")
    return data


def measure(probe, wire, expected, refusal, output, *, heap=False):
    """Use the same bounded production-probe executor; never substitute a codec."""
    output.mkdir(parents=True, exist_ok=False)
    binary = str(probe)
    before = executable_digest(probe)
    repeat = 1 if heap else 256
    argv = [binary, "--repeat", str(repeat)]
    if expected is not None:
        expected = {**expected, "repeat": repeat}
    observation = output / ("dhat.json" if heap else "time.txt")
    if heap:
        tool = shutil.which("valgrind")
        if tool is None:
            raise ValueError("Valgrind is required for the selected heap profile")
        argv = [tool, "--tool=dhat", "--num-callers=8",
                f"--dhat-out-file={observation}", *argv]
    else:
        argv = ["/usr/bin/time", "--quiet", "--format=%U\\n%S\\n%M\\n%x",
                f"--output={observation}", *argv]
    started = time.monotonic_ns()
    result = invoke_probe(argv, wire, expected)
    elapsed = time.monotonic_ns() - started
    # Retain the actual bounded executor result even when a later semantic or
    # profiler check refuses it. The existing evidence inventory binds this file.
    observation_data = (json.dumps({"executable_sha256": before,
                                   "input_sha256": hashlib.sha256(wire).hexdigest(),
                                   "execution": result}, sort_keys=True) + "\n").encode()
    (output / "probe-observation.json").write_bytes(observation_data)
    if result.get("passed") is not True:
        raise ValueError(f"probe observation failed: {result}")
    if refusal is not None:
        violation = result.get("report", {}).get("violation")
        if type(violation) is not dict or violation.get("code") != refusal:
            raise ValueError("negative input produced the wrong structured refusal")
    if expected is not None:
        duration = result["report"].get("elapsed_ns")
        if (type(duration) is not str or re.fullmatch(r"[1-9][0-9]{0,38}", duration) is None
                or int(duration) >= 2**128):
            raise ValueError("invalid codec elapsed-time observation")
    after = executable_digest(probe)
    if before != after:
        raise ValueError("measured executable changed")
    raw = read_observation(observation, MAX_PROFILE_BYTES if heap else 1024)
    metrics = parse_dhat(raw) if heap else parse_time(raw, result["exit_code"])
    return {"probe": result, "executable_sha256": before, "metrics": metrics,
            "wall_elapsed_ns": elapsed, "profiler_file": observation.name,
            "probe_observation_sha256": hashlib.sha256(observation_data).hexdigest(),
            "profiler_sha256": hashlib.sha256(raw).hexdigest(),
            "requested_accepted_round_trips": repeat,
            "rejection_scope": "one decode per process" if expected is None else None}


def run_profile(probe, output, samples, heap):
    from quality_checks import digests, load_vectors, maximal_memory_event
    from command_process import capture_command

    if type(samples) is not int or not 1 <= samples <= MAX_SAMPLES:
        raise ValueError("sample count outside the bounded resource profile")
    root = Path(__file__).resolve().parents[2]
    probe, output = probe.resolve(strict=True), output.resolve()
    if output == root or root in output.parents or output in root.parents:
        raise ValueError("resource evidence must be disjoint from source")
    if probe == output or output in probe.parents:
        raise ValueError("executable must be outside evidence")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "hepta.cognitive-types.resource-observation.v1",
               "host": {"system": platform.system(), "release": platform.release(),
                        "machine": platform.machine(), "processor": platform.processor()},
               "samples_per_case": samples, "heap_requested": heap, "measurements": [],
               "measurement_complete": False, "product_acceptance": False,
               "latency_threshold_enforced": False, "activation": False, "release": False}
    try:
        receipt["source_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        source_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
        clean = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True)
        if clean:
            raise ValueError("resource profile requires the clean candidate source")
        receipt["source_tree"] = source_tree
        receipt["executable_sha256"] = executable_digest(probe)
        receipt["tools"] = []
        tools = [("gnu-time", ["/usr/bin/time", "--version"])]
        if heap:
            tools.append(("valgrind", ["valgrind", "--version"]))
        for name, command in tools:
            log = output / (name + ".log")
            observed = capture_command(command, root, log, 10)
            receipt["tools"].append({"name": name, "argv": command, **observed,
                                     "log_sha256": executable_digest(log)})
            if observed["status"] != "passed":
                raise ValueError("selected profiling tool is unavailable")
        vectors = load_vectors(root)
        vector = next(item for item in vectors if item[0] == "MemoryEventV1")
        envelope = {"contract": vector[0], "schema": vector[1], "schemaVersion": 1, "payload": vector[2]}
        workloads = boundary_cases(maximal_memory_event(envelope))
        for name, wire, value, refusal in workloads:
            expected = digests(value) if value is not None else None
            for index in range(samples):
                directory = output / name / f"native-{index:02}"
                row = {**workload_identity(name, wire), "sample": index,
                       **measure(probe, wire, expected, refusal, directory)}
                receipt["measurements"].append(row)
            if heap:
                directory = output / name / "heap"
                row = {**workload_identity(name, wire), "sample": "heap",
                       **measure(probe, wire, expected, refusal, directory, heap=True)}
                receipt["measurements"].append(row)
        final_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        final_clean = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True)
        if (final_head != receipt["source_commit"] or final_clean
                or executable_digest(probe) != receipt["executable_sha256"]
                or any(row["executable_sha256"] != receipt["executable_sha256"]
                       for row in receipt["measurements"])):
            raise ValueError("source or executable identity changed across measurements")
        receipt["measurement_complete"] = True
    except (OSError, ValueError, TypeError, KeyError, RecursionError, StopIteration, subprocess.SubprocessError) as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        (output / "resource-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt["measurement_complete"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--heap", action="store_true")
    args = parser.parse_args()
    try:
        return 0 if run_profile(args.probe, args.output, args.samples, args.heap) else 1
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"resource observation unavailable: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
