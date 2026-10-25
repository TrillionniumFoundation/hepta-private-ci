"""Per-attempt observed costs and explicitly unverified external token inputs."""

import json
from pathlib import Path
import re
import time


def accounting(path):
    value = {
        "schema": "hepta.memory-cell.external-accounting.v1",
        "model_calls": None,
        "input_tokens": None,
        "output_tokens": None,
        "training_tokens": None,
        "tokenizer_id": None,
        "tokenizer_sha256": None,
        "receipt_sha256": None,
    }
    if path is not None:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
            raise ValueError("accounting input must be a bounded regular file")
        provided = json.loads(path.read_bytes())
        if set(provided) != set(value) or provided["schema"] != value["schema"]:
            raise ValueError("external accounting schema")
        value = provided
    for key in ("model_calls", "input_tokens", "output_tokens", "training_tokens"):
        if value[key] is not None and (type(value[key]) is not int or value[key] < 0):
            raise ValueError("invalid external token/model count")
    for key in ("tokenizer_id", "tokenizer_sha256", "receipt_sha256"):
        if value[key] is not None and (
            not isinstance(value[key], str) or len(value[key]) > 512
        ):
            raise ValueError("invalid external accounting identity")
    for key in ("tokenizer_sha256", "receipt_sha256"):
        if value[key] is not None and re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
            raise ValueError("invalid external accounting SHA256")
    return {
        "input": value,
        "verification": "not_provided"
        if path is None
        else "caller_declared_unverified",
        "executor_model_calls": 0,
        "host_cpu_seconds": None,
        "money_cost": None,
        "model_base_bytes": None,
        "dynamic_library_bytes": None,
        "peak_transient_storage_bytes": None,
    }


def ledger(
    processes,
    output,
    source_bytes,
    candidate_bytes,
    runtime,
    external,
    started_wall,
    started_cpu,
):
    costs = []
    for process in processes:
        usage = process.get("usage")
        cpu = (
            usage["user_cpu_seconds"] + usage["system_cpu_seconds"]
            if usage
            else process.get("child_cpu_seconds")
        )
        costs.append(
            {
                "pid": process.get("pid"),
                "returncode": process.get("returncode"),
                "timeout": process.get("timeout"),
                "cpu_seconds": cpu,
                "wall_seconds": process["wall_seconds"],
                "stdout_bytes": process.get("stdout", {}).get("bytes"),
                "stderr_bytes": process.get("stderr", {}).get("bytes"),
            }
        )
    retained = sum(
        p.stat().st_size
        for p in Path(output).rglob("*")
        if p.is_file() and not p.is_symlink()
    )
    return {
        "schema": "hepta.memory-cell.attempt-ledger.v1",
        "processes": costs,
        "parent_process_cpu_seconds_before_final_receipt": time.process_time()
        - started_cpu,
        "attempt_wall_seconds_before_final_receipt": time.monotonic() - started_wall,
        "known_process_cpu_seconds_sum": sum(p["cpu_seconds"] or 0 for p in costs),
        "unknown_process_cpu_count": sum(p["cpu_seconds"] is None for p in costs),
        "process_wall_seconds_sum": sum(p["wall_seconds"] for p in costs),
        "source_payload_bytes_loaded": source_bytes,
        "candidate_bytes_retained": candidate_bytes,
        "source_byte_basis": "Logical payload copied once; excludes repeated hash reads and is not filesystem block I/O.",
        "retained_regular_output_bytes_before_final_receipts": retained,
        "available_tool_binary_bytes": sum(
            p["bytes"] for p in runtime.get("tools", {}).values()
        ),
        "nested_cpu": "Already included where waited by parent; nested receipt deltas are attribution only, never added again.",
        "external": external,
        "whole_system_cost_complete": False,
    }
