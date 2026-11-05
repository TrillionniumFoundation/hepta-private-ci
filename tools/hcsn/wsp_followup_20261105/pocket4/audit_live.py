#!/usr/bin/env python3
"""Bounded read-only Laya status/candidate/adapter audit; never loads a model.

Private source paths are supplied explicitly and excluded from the JSON result.
No broker queries, training, forward pass, state change or service mutation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import stat
import struct
import subprocess
import time
from zoneinfo import ZoneInfo


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def at_ms(value):
    t = dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc)
    return {"utc": t.isoformat(), "america_new_york": t.astimezone(ZoneInfo("America/New_York")).isoformat()}


def stamp(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read_bound(path, cap):
    start = utc()
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "SOURCE_NOT_SINGLE_LINK_REGULAR")
        require(0 <= before.st_size <= cap, "SOURCE_BYTE_CAP")
        chunks, count = [], 0
        while chunk := os.read(fd, min(65536, cap + 1 - count)):
            chunks.append(chunk)
            count += len(chunk)
            require(count <= cap, "SOURCE_GREW_OVER_CAP")
        after = os.fstat(fd)
        require(stamp(before) == stamp(after) == stamp(path.lstat()), "SOURCE_CHANGED_DURING_READ")
        b = b"".join(chunks)
        return b, {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                   "observed_start_utc": start, "observed_end_utc": utc(),
                   "same_descriptor_and_path_metadata_during_read": True}
    finally:
        os.close(fd)


def read_json(path, cap):
    b, record = read_bound(path, cap)
    return json.loads(b), record


def relative_under(path, root):
    p, r = path.resolve(), root.resolve()
    require(p.is_relative_to(r), "UNEXPECTED_SOURCE_ROOT")
    return p


def service(unit):
    keys = ["ActiveState", "SubState", "MainPID", "MemoryCurrent", "MemoryPeak",
            "MemoryHigh", "MemoryMax", "CPUQuotaPerSecUSec", "TasksCurrent", "NRestarts"]
    p = subprocess.run(
        ["systemctl", "--user", "show", unit] + ["--property=" + k for k in keys],
        capture_output=True, text=True, timeout=6,
    )
    require(p.returncode == 0, "SERVICE_OBSERVATION_FAILED")
    values = dict(line.split("=", 1) for line in p.stdout.splitlines() if "=" in line)
    values.pop("MainPID", None)
    return {"observed_utc": utc(), "properties": values}


def live_guardian_binding(guardian):
    p = subprocess.run(
        ["systemctl", "--user", "show", "heptatrader-laya-trainer.service",
         "--property=MainPID", "--value"], capture_output=True, text=True, timeout=6,
    )
    require(p.returncode == 0, "LIVE_TRAINER_PID_UNAVAILABLE")
    pid = int(p.stdout.strip())
    require(pid > 0, "NO_LIVE_TRAINER_PROCESS")
    proc = Path("/proc") / str(pid)
    start_ticks = (proc / "stat").read_text().rpartition(")")[2].split()[19]
    args = (proc / "cmdline").read_bytes().split(b"\0")
    positions = [i for i, value in enumerate(args) if value == b"--config"]
    require(len(positions) == 1 and positions[0] + 1 < len(args), "LIVE_CONFIG_ARGUMENT_AMBIGUOUS")
    require(Path(os.fsdecode(args[positions[0] + 1])).resolve() == guardian.resolve(),
            "LIVE_PROCESS_CONFIG_MISMATCH")
    commitment = hashlib.sha256(
        str(pid).encode() + b":" + start_ticks.encode() + b":" + b"\0".join(args)
    ).hexdigest()
    return {"observed_utc": utc(), "config_argument_matches": True,
            "process_start_and_argument_commitment_sha256": commitment}


def checkpoint(payload):
    require(len(payload) >= 8, "TRUNCATED_HEADER")
    n = struct.unpack("<Q", payload[:8])[0]
    require(n <= 65536 and 8 + n <= len(payload), "HEADER_BYTE_CAP")
    header = json.loads(payload[8:8+n])
    data = payload[8+n:]
    rows, intervals = [], []
    total = 0
    for name, entry in header.items():
        if name == "__metadata__":
            continue
        require(entry["dtype"] == "F32", "UNQUALIFIED_ADAPTER_DTYPE")
        shape = entry["shape"]
        require(isinstance(shape, list) and all(type(x) is int and x >= 0 for x in shape),
                "BAD_SHAPE")
        count = math.prod(shape)
        total += count
        require(total <= 262144, "PARAMETER_COUNT_CAP")
        lo, hi = entry["data_offsets"]
        require(type(lo) is int and type(hi) is int and 0 <= lo <= hi <= len(data),
                "DATA_OFFSET_BOUND")
        require(hi - lo == 4 * count, "DATA_SHAPE_MISMATCH")
        values = struct.iter_unpack("<f", data[lo:hi])
        finite = sum(math.isfinite(value[0]) for value in values)
        intervals.append((lo, hi))
        rows.append({"name": name, "shape": shape, "dtype": "F32",
                     "parameters": count, "finite_parameters": finite})
    intervals.sort()
    cursor = 0
    for lo, hi in intervals:
        require(lo == cursor, "NONCONTIGUOUS_OR_OVERLAPPING_TENSOR_LAYOUT")
        cursor = hi
    require(cursor == len(data), "UNDECLARED_TRAILING_PARAMETER_DATA")
    return {"tensor_count": len(rows), "parameter_count": total,
            "all_finite": all(x["finite_parameters"] == x["parameters"] for x in rows),
            "data_layout_nonoverlapping_and_complete": True, "tensors": rows}


def main(args):
    start, cpu = time.perf_counter(), time.process_time()
    result = {
        "schema": "hepta.wsp.live_candidate_readonly_audit.v1",
        "started_utc": utc(), "status": "started",
        "read_only": True, "training_started": False, "model_forward_executed": False,
        "broker_queries_sent": 0, "orders_sent": 0, "services_changed": False,
        "base_weight_content_refreshed": False, "performance_qualified": False,
        "full_trader_to_hepta_neuron_semantic_mapping_verified": False,
        "atomic_cross_file_snapshot": False, "sources": {},
    }
    roots = [args.guardian_config, Path.home()]
    try:
        guardian, identity = read_json(args.guardian_config, 65536)
        result["sources"]["guardian_config"] = identity
        require(identity["sha256"] == args.guardian_config_sha256, "GUARDIAN_CONFIG_IDENTITY")
        effective = subprocess.run(
            ["systemctl", "--user", "show", "heptatrader-laya-trainer.service",
             "--property=ExecStart", "--value"],
            capture_output=True, text=True, timeout=6,
        )
        require(effective.returncode == 0, "EFFECTIVE_START_UNAVAILABLE")
        expected = "--config " + str(args.guardian_config)
        require(expected in effective.stdout, "EFFECTIVE_SERVICE_CONFIG_MISMATCH")
        result["effective_service_config_match"] = True
        live_before = live_guardian_binding(args.guardian_config)
        result["live_trainer_binding_before"] = live_before
        cfg_path = Path(guardian["original_config"])
        cfg, identity = read_json(cfg_path, 262144)
        result["sources"]["original_config"] = identity
        require(identity["sha256"] == guardian["original_config_sha256"], "ORIGINAL_CONFIG_IDENTITY")
        state_root, candidate_root = Path(cfg["state_root"]), Path(cfg["candidate_directory"])
        roots.extend([state_root, candidate_root])
        control = relative_under(Path(cfg["control_directory"]), state_root)
        status, identity = read_json(control / "status.json", 262144)
        result["sources"]["trainer_status_before"] = identity
        require(status["schema"] == "heptatrader.laya-resident-status.v1", "STATUS_SCHEMA")
        registration = status["latest_candidate_registration"]
        candidate_id, job_id = status["last_candidate_id"], registration["job_id"]
        require(re.fullmatch(r"[0-9a-f]{64}", candidate_id) is not None and
                re.fullmatch(r"[0-9a-f]{64}", job_id) is not None, "CANDIDATE_JOB_ID_FORMAT")
        require(registration["candidate_id"] == candidate_id, "STATUS_CANDIDATE_BINDING")
        keep = [
            "schema", "at_ms", "state", "job_counts", "pending_evaluations",
            "viable_pending_evaluations", "completed_candidates_without_forward_trial",
            "deferred_training_candidates", "blocking_deferred_training_candidates",
            "current_blockers", "current_blockers_checked_at_ms",
            "forward_registration_wait_reasons", "no_forward_trial_is_not_performance_rejection",
        ]
        result["trainer"] = {key: status[key] for key in keep if key in status}
        result["trainer"]["source_time"] = at_ms(status["at_ms"])
        result["candidate_binding"] = {
            "candidate_id": candidate_id, "job_id": job_id,
            "training_state": registration.get("training_state"),
            "registration_state": registration.get("state"),
            "plan_file_exists": registration.get("plan_file_exists"),
            "registration_is_performance_result": registration.get("registration_is_performance_result"),
        }
        lineage = status.get("training_lineage", {})
        result["training_lineage"] = {k: lineage[k] for k in [
            "mode", "completed_jobs_are_cumulative_updates", "optimizer_reset_each_job",
            "optimizer_reset_between_epochs", "episode_profile", "auxiliary_action_phase",
            "price_steps_exclude_auxiliary_action_steps",
        ] if k in lineage}
        preflight = status.get("forward_registration_preflight", {})
        result["forward_preflight"] = {k: preflight[k] for k in [
            "at_ms", "admit_new_worker", "reasons", "full_memory_psi",
            "memory_bytes", "minimum_available_bytes", "worker_launched",
            "worker_launch_authority", "trial_allocated", "registration_stability",
            "original_live_source_evidence", "cached_probe_diagnostic",
        ] if k in preflight}
        job, identity = read_json(control / "jobs" / (job_id + ".json"), 524288)
        result["sources"]["bound_job_configuration"] = identity
        artifact = relative_under(Path(job["output_directory"]), candidate_root)
        candidate, identity = read_json(artifact / "candidate.json", 524288)
        result["sources"]["candidate_manifest"] = identity
        require(candidate["candidate_id"] == candidate_id, "MANIFEST_CANDIDATE_BINDING")
        adapter, identity = read_bound(artifact / "adapter.safetensors", 1048576)
        result["sources"]["adapter"] = identity
        require(candidate["adapter_sha256"] == identity["sha256"], "MANIFEST_ADAPTER_HASH")
        result["adapter"] = checkpoint(adapter)
        require(result["adapter"]["all_finite"], "NONFINITE_ADAPTER_PARAMETER")
        result["candidate_binding"]["manifest_adapter_hash_matches"] = True
        result["candidate_binding"]["created"] = at_ms(candidate["created_at_ms"])
        result["candidate_reported_training"] = {
            "scope": "Read from the bound candidate manifest; not independently rerun or out-of-sample efficacy",
            "selected": {key: candidate[key] for key in [
                "status", "trainable_parameters", "changed_parameters", "effective_changed_coordinates",
                "steps", "wall_seconds", "max_gpu_allocated_bytes", "action_update_steps",
                "pretrained_base_unchanged", "pnl_reward_used", "automatic_cutover",
                "canonical_owner_activation_claimed", "broker_orders_sent",
            ] if key in candidate},
            "measurement": candidate.get("measurement"),
            "resource_usage": candidate.get("resource_usage"),
            "calibration": {key: candidate.get("price_calibration", {}).get(key) for key in [
                "model_weight", "model_weight_max", "calibration_is_train_only",
                "future_value_proven", "additional_independent_training_rows",
            ]},
            "calibration_measurement": {key: candidate.get("price_calibration_training_measurement", {}).get(key)
                                        for key in ["exact_prior_fallback", "held_out", "training_only", "future_value_proven"]},
        }
        current, identity = read_json(control / "status.json", 262144)
        result["sources"]["trainer_status_after"] = identity
        result["candidate_binding"]["same_candidate_and_job_at_end"] = (
            current.get("last_candidate_id") == candidate_id
            and current.get("latest_candidate_registration", {}).get("job_id") == job_id
        )
        require(result["candidate_binding"]["same_candidate_and_job_at_end"], "CURRENT_BINDING_CHANGED")
        live_after = live_guardian_binding(args.guardian_config)
        result["live_trainer_binding_after"] = live_after
        result["live_process_identity_stable"] = (
            live_after["process_start_and_argument_commitment_sha256"] ==
            live_before["process_start_and_argument_commitment_sha256"]
        )
        require(result["live_process_identity_stable"], "LIVE_TRAINER_CHANGED_DURING_AUDIT")
        result["resources"] = {
            "observed_utc": utc(), "logical_cpu_count": os.cpu_count(), "loadavg": os.getloadavg(),
            "memory_kib": {k: int(v.split()[0]) for k, v in
                           (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
                           if k in ["MemTotal", "MemAvailable", "SwapTotal", "SwapFree"]},
            "pressure": {kind: Path("/proc/pressure/" + kind).read_text() for kind in ["memory", "cpu", "io"]},
        }
        result["services"] = {unit: service(unit) for unit in [
            "heptatrader-laya-trainer.service", "heptatrader-laya-evaluator.service",
            "heptatrader-execution.service",
        ]}
        result["status"] = "PASS_BOUND_CURRENT_SMALL_ADAPTER_STATIC_AUDIT"
    except Exception as exc:
        message = str(exc)
        for root in roots:
            message = message.replace(str(root), "<private_source>")
        result["status"] = "BLOCKED_OR_FAILED"
        result["error"] = {"type": type(exc).__name__, "message": message[:800]}
    result["finished_utc"] = utc()
    result["finished_america_new_york"] = dt.datetime.now(ZoneInfo("America/New_York")).isoformat()
    result["cost"] = {"wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
                      "max_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    result["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    require("/home/" not in encoded and "/Users/" not in encoded, "PRIVATE_PATH_IN_PUBLIC_PROJECTION")
    print(encoded)
    return 0 if result["status"] == "PASS_BOUND_CURRENT_SMALL_ADAPTER_STATIC_AUDIT" else 2


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--guardian-config", type=Path, required=True)
    p.add_argument("--guardian-config-sha256", required=True)
    arguments = p.parse_args()
    raise SystemExit(main(arguments))
