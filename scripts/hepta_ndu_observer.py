#!/usr/bin/env python3
"""Read-only Linux Agentd NDU observer; atomically export node-exporter textfiles.

No HTTP listener, mutation request, journal access or inferred backup success.
Run as the Agentd owner. All transport, identity and schema failures replace the
previous sample with up=0; collection timestamps make a stopped timer observable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import struct
import sys
import time

MAX_FRAME = 65_536
MAX_U64 = (1 << 64) - 1
LATENCY = ("0.0001", "0.0005", "0.001", "0.002", "0.005", "+Inf")
V1 = set("evaluation_count evaluation_latency_micros_total evaluation_latency_micros_max convergence_runs convergence_iterations convergence_exhaustions candidate_rejections candidate_quarantines store_busy store_indeterminate reopen_failures restore_failures journal_bytes backup_age_seconds".split())
V2 = set("host_generation storage_ready filesystem_profile evaluation_count evaluation_failures evaluation_latency_buckets uncertainty_buckets rejection_reason_counts persistence_count persistence_failures persistence_latency_micros_total persistence_latency_micros_max persistence_latency_buckets store_opens recovered_nonempty_stores corrupt_images journal_bytes backup_age_seconds memory_fallback_count".split())
OPTIONAL = {"journal_bytes", "backup_age_seconds"}
ARRAYS = {"evaluation_latency_buckets": 6, "uncertainty_buckets": 6,
          "rejection_reason_counts": 3, "persistence_latency_buckets": 6}


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def integer(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_U64


def validate(frame: bytes, agent: str, generation: int, request_id: int, version: str) -> dict:
    if not frame.endswith(b"\n") or len(frame) > MAX_FRAME:
        raise ValueError("invalid bounded response frame")
    data = json.loads(frame, object_pairs_hook=unique_object)
    envelope = {"schema_version", "request_id", "agent_id", "spawn_generation", "current_generation", "payload"}
    if not isinstance(data, dict) or set(data) != envelope:
        raise ValueError("response envelope schema mismatch")
    expected = {"schema_version": 2, "request_id": request_id, "agent_id": agent,
                "spawn_generation": generation}
    if any(type(data[k]) is not type(v) or data[k] != v for k, v in expected.items()):
        raise ValueError("response identity mismatch")
    if not integer(data["current_generation"]) or data["current_generation"] == 0:
        raise ValueError("invalid current lifecycle generation")
    result = data["payload"]
    fields = V1 if version == "metrics_v1" else V2
    if not isinstance(result, dict) or set(result) != fields | {"type", "result"}:
        raise ValueError("metrics schema mismatch")
    if result["type"] != "ndu_control" or result["result"] != version:
        raise ValueError("unexpected response payload")
    for key in fields:
        value = result[key]
        if key in OPTIONAL and value is None:
            continue
        if key == "storage_ready":
            if value is not None and type(value) is not bool:
                raise ValueError("invalid storage readiness")
        elif key == "filesystem_profile":
            if value is not None and (not isinstance(value, str) or re.fullmatch(r"[a-z0-9-]{1,80}", value) is None):
                raise ValueError("invalid filesystem profile")
        elif key in ARRAYS:
            if not isinstance(value, list) or len(value) != ARRAYS[key] or not all(integer(v) for v in value):
                raise ValueError("invalid metrics buckets")
        elif not integer(value):
            raise ValueError("invalid unsigned metric")
    if version == "metrics_v2" and result["host_generation"] != generation:
        raise ValueError("NDU generation mismatch")
    return result


def request(path: Path, agent: str, generation: int, request_id: int, version: str, deadline: float) -> tuple[dict, tuple]:
    if not sys.platform.startswith("linux") or not hasattr(socket, "SO_PEERCRED"):
        raise ValueError("Linux peer credentials are required")
    if not path.is_absolute() or path.resolve() != path or len(os.fsencode(path)) > 107:
        raise ValueError("canonical bounded absolute control path required")
    parent, endpoint = path.parent.stat(), path.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o022
        or not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != os.geteuid() or endpoint.st_mode & 0o077):
        raise ValueError("unsafe control socket or directory")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(max(0.001, deadline - time.monotonic()))
        stream.connect(str(path))
        pid, uid, _ = struct.unpack("3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.geteuid() or pid <= 0:
            raise ValueError("unexpected control peer")
        # starttime is field 22; comm (field 2) may contain spaces/parentheses.
        start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        identity = (pid, uid, start, boot)
        wire = {"schema_version": 2, "request_id": request_id, "spawn_generation": generation,
                "method": {"type": "ndu_control", "request": {"operation": version}}}
        stream.sendall(json.dumps(wire, separators=(",", ":")).encode() + b"\n")
        frame = bytearray()
        while not frame.endswith(b"\n"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("collection deadline exceeded")
            stream.settimeout(remaining)
            chunk = stream.recv(min(4096, MAX_FRAME + 1 - len(frame)))
            if not chunk:
                raise ValueError("truncated response")
            frame.extend(chunk)
            if len(frame) > MAX_FRAME or b"\n" in frame[:-1]:
                raise ValueError("oversized or multiple response frames")
        validated = validate(bytes(frame), agent, generation, request_id, version)
        envelope = json.loads(bytes(frame), object_pairs_hook=unique_object)
        identity = (*identity, envelope["current_generation"])
        return validated, identity


def collect(path: Path, agent: str, generation: int, timeout: float) -> tuple[dict, dict, str]:
    deadline = time.monotonic() + timeout
    v2, peer = request(path, agent, generation, 1, "metrics_v2", deadline)
    v1, other = request(path, agent, generation, 2, "metrics_v1", deadline)
    if peer != other:
        raise ValueError("Agentd changed during collection")
    instance = hashlib.sha256(repr(peer).encode()).hexdigest()[:24]
    return v1, v2, instance


def render(agent: str, generation: int, captured: int, sample: tuple | None) -> str:
    labels = {"agent": agent, "generation": str(generation)}
    if sample is not None:
        labels["owner_instance"] = sample[2]
    lines = []

    def emit(name: str, value: int | float, extra: dict | None = None) -> None:
        tags = {**labels, **(extra or {})}
        encoded = ",".join(f"{key}={json.dumps(val)}" for key, val in sorted(tags.items()))
        lines.append(f"hepta_ndu_{name}{{{encoded}}} {value}")

    emit("observer_up", int(sample is not None))
    emit("observer_collection_timestamp_seconds", captured)
    if sample is None:
        return "\n".join(lines) + "\n"
    v1, v2, _ = sample
    emit("storage_readiness_known", int(v2["storage_ready"] is not None))
    if v2["storage_ready"] is not None:
        emit("storage_ready", int(v2["storage_ready"]))
    if v2["filesystem_profile"] is not None:
        emit("filesystem_info", 1, {"profile": v2["filesystem_profile"]})
    for key in ("evaluation_count", "evaluation_failures", "persistence_count", "persistence_failures", "store_opens", "recovered_nonempty_stores", "corrupt_images", "memory_fallback_count"):
        emit(key.removesuffix("_count") + "_total", v2[key])
    for key in ("convergence_runs", "convergence_iterations", "convergence_exhaustions", "candidate_rejections", "candidate_quarantines", "store_busy", "store_indeterminate", "reopen_failures", "restore_failures"):
        emit(key + "_total", v1[key])
    for key in sorted(OPTIONAL):
        emit(key + "_known", int(v2[key] is not None))
        if v2[key] is not None:
            emit(key, v2[key])
    for kind in ("evaluation", "persistence"):
        total = 0
        for bound, count in zip(LATENCY, v2[kind + "_latency_buckets"]):
            total += count
            emit(kind + "_duration_seconds_bucket", total, {"le": bound})
        emit(kind + "_duration_seconds_count", total)
        metrics = v1 if kind == "evaluation" else v2
        emit(kind + "_duration_seconds_sum", metrics[kind + "_latency_micros_total"] / 1_000_000)
        emit(kind + "_duration_seconds_max", metrics[kind + "_latency_micros_max"] / 1_000_000)
    for reason, count in zip(("hard_constraint", "risk_ceiling", "resource_ceiling"), v2["rejection_reason_counts"]):
        emit("rejection_reason_total", count, {"reason": reason})
    # Preserve the source's non-cumulative fixed-Q32 uncertainty bins exactly.
    for bound, count in zip(("0", "16777216", "268435456", "1073741824", "4294967296", "9223372036854775807"), v2["uncertainty_buckets"]):
        emit("uncertainty_bin_total", count, {"upper_q32": bound})
    return "\n".join(lines) + "\n"


def publish(path: Path, text: str) -> None:
    if not path.is_absolute() or path.suffix != ".prom" or path.parent.resolve() != path.parent:
        raise ValueError("canonical absolute .prom output required")
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".{path.name}.{secrets.token_hex(12)}.tmp"
    try:
        meta = os.fstat(fd)
        if meta.st_uid != os.geteuid() or meta.st_mode & 0o022:
            raise ValueError("unsafe observer output directory")
        try:
            old = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            old = None
        if old is not None and (not stat.S_ISREG(old.st_mode) or old.st_nlink != 1 or old.st_uid != os.geteuid()):
            raise ValueError("unsafe existing observer output")
        target = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(target, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    if (re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", args.agent_id) is None
        or not 0 < args.generation <= MAX_U64 or not 0 < args.timeout <= 30):
        parser.error("valid agent identity, nonzero generation and bounded timeout required")
    sample = None
    try:
        sample = collect(args.socket, args.agent_id, args.generation, args.timeout)
    except (OSError, ValueError, KeyError, IndexError, TypeError, RecursionError) as error:
        detail = re.sub(r"\s+", " ", str(error)).strip()[:240]
        print(
            f"NDU-OBS-001: collection failed; no current owner observation; "
            f"{type(error).__name__}: {detail}",
            file=sys.stderr,
        )
    try:
        publish(args.output, render(args.agent_id, args.generation, int(time.time()), sample))
    except (OSError, ValueError):
        print("NDU-OBS-002: textfile publication failed; check sample freshness", file=sys.stderr)
        return 2
    return 0 if sample is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
