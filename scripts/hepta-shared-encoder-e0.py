#!/usr/bin/env python3
"""Read-only Linux /proc process sampler for the Hepta E0 Encoder baseline.

A process sample and a manifest hash do NOT establish the installed model,
artifact signature, inference latency or production readiness. This tool never
claims a passed E0 or grants deployment authority.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time


class CaptureError(Exception):
    """A requested process or evidence input could not be safely captured."""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def parse_stat(raw):
    """Parse Linux /proc/PID/stat, preserving spaces and parentheses in comm."""
    try:
        prefix, rest = raw.rstrip().rsplit(") ", 1)
        pid, _command = prefix.split(" (", 1)
        fields = rest.split()  # begins at proc(5) field 3, state
        return {
            "pid": int(pid),
            "start_time_ticks": int(fields[19]),  # field 22
            "user_cpu_ticks": int(fields[11]),   # field 14
            "system_cpu_ticks": int(fields[12]),  # field 15
            "rss_pages": int(fields[21]),       # field 24
        }
    except (ValueError, IndexError) as exc:
        raise CaptureError("malformed /proc stat") from exc


def parse_memory_kib(raw, fields):
    result = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(":")
        if sep and key in fields:
            pieces = value.strip().split()
            if len(pieces) != 2 or pieces[1] != "kB":
                raise CaptureError("invalid proc memory unit")
            try:
                number = int(pieces[0])
            except ValueError as exc:
                raise CaptureError("invalid proc memory value") from exc
            if number < 0:
                raise CaptureError("negative proc memory value")
            result[key] = number
    return result


def read_process_stat(pid):
    try:
        return parse_stat(Path(f"/proc/{pid}/stat").read_text(encoding="utf-8"))
    except OSError as exc:
        raise CaptureError(f"cannot read process {pid} stat: {exc.strerror}") from exc


def read_memory(pid):
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError as exc:
        raise CaptureError(f"cannot read process {pid} status: {exc.strerror}") from exc
    values = parse_memory_kib(status, {"VmRSS", "VmHWM"})
    try:
        rollup = Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="utf-8")
    except OSError:
        values["smaps_rollup_available"] = False
    else:
        values.update(parse_memory_kib(rollup, {"Rss", "Pss", "Private_Clean", "Private_Dirty", "Shared_Clean", "Shared_Dirty", "Swap"}))
        values["smaps_rollup_available"] = True
    return values


def capture_process(pid, samples=8, interval_ms=50, sleep=time.sleep):
    if type(pid) is not int or pid <= 0 or type(samples) is not int or not 2 <= samples <= 256 or type(interval_ms) is not int or not 1 <= interval_ms <= 1000:
        raise CaptureError("invalid PID, sample count, or interval")
    initial = read_process_stat(pid)
    if initial["pid"] != pid:
        raise CaptureError("process PID mismatch")
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise CaptureError("cannot bind process to Linux boot identity") from exc
    if not boot_id:
        raise CaptureError("missing Linux boot identity")
    observations = []
    for index in range(samples):
        if index:
            sleep(interval_ms / 1000)
        before = read_process_stat(pid)
        memory = read_memory(pid)
        after = read_process_stat(pid)
        if before["start_time_ticks"] != initial["start_time_ticks"] or after["start_time_ticks"] != initial["start_time_ticks"] or before["pid"] != pid or after["pid"] != pid:
            raise CaptureError("PID was reused or process identity changed during sample")
        observations.append({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "user_cpu_ticks": after["user_cpu_ticks"],
            "system_cpu_ticks": after["system_cpu_ticks"],
            "rss_pages": after["rss_pages"],
            "memory_kib": memory,
        })
    return {
        "pid": pid,
        "boot_identity_sha256": hashlib.sha256(boot_id.encode("ascii")).hexdigest(),
        "process_start_time_ticks": initial["start_time_ticks"],
        "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
        "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
        "os_kernel": platform.release(),
        "sample_count": samples,
        "interval_ms": interval_ms,
        "observations": observations,
        "rss_pages_max": max(s["rss_pages"] for s in observations),
        "pss_kib_max": max((s["memory_kib"].get("Pss", 0) for s in observations), default=0) if all(s["memory_kib"]["smaps_rollup_available"] for s in observations) else None,
    }


def capture_baseline(pid, manifest, samples=8, interval_ms=50, receipts=None):
    manifest = Path(manifest)
    if not manifest.is_file():
        raise CaptureError("model manifest file not found")
    if receipts is not None and not Path(receipts).is_file():
        raise CaptureError("model invocation receipts file not found")
    manifest_hash = sha256_file(manifest)
    receipt_hash = sha256_file(receipts) if receipts is not None else None
    process = capture_process(pid, samples, interval_ms)
    return {
        "schema": "hepta.shared-encoder-e0.process-capture.v1",
        "status": "PROCESS_OBSERVED_E0_INCOMPLETE",
        "authority": "DENY_ALL",
        "production_promotion_permitted": False,
        "manifest_file_sha256_unverified": manifest_hash,
        "receipt_file_sha256_unverified": receipt_hash,
        "model_weights_verified": False,
        "signed_runtime_execution_verified": False,
        "model_loaded_into_pid_verified": False,
        "model_invocation_latency_percentiles_verified": False,
        "gpu_resource_measurement_verified": False,
        "independent_ndu_future_window_verified": False,
        "process": process,
        "caveat": "Sampling /proc is real process telemetry but does not prove what weights executed, who signed receipts, or any inference-task metric.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runtime-receipts", type=Path)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--interval-ms", type=int, default=50)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = capture_baseline(args.pid, args.manifest, args.samples, args.interval_ms, args.runtime_receipts)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except (CaptureError, OSError) as exc:
        print(f"E0 capture failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"wrote process-only E0 evidence to {args.out}; status is INCOMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
