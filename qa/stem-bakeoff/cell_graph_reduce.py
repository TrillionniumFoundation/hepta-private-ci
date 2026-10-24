"""Validate authoritative bounded worker outputs and reduce the same six-head graph.

No task labels or training are used. External dispatch timing remains a separate
owner receipt; local worker timestamps are never subtracted across hosts.
"""

import time

_ENTRY_WALL = time.perf_counter_ns()
_ENTRY_CPU = time.process_time_ns()
_FRESH_EXECUTABLE = __name__ == "__main__"

import argparse
import base64
import io
import json
from pathlib import Path
import resource
import sys

import numpy as np

from cell_graph_worker import HEAD_IDS, MAX_OUTPUT, array, canonical, sha, strict_json, tensor


def read_worker(data, request):
    if len(data) > MAX_OUTPUT:
        raise ValueError("stdout exceeds predeclared bound")
    lines = data.splitlines(keepends=True)
    if len(lines) != 2 or any(not line.endswith(b"\n") for line in lines):
        raise ValueError("complete two-line authoritative stdout required")
    result, final = map(strict_json, lines)
    if (result.get("schema") != "hepta.fixed-cell-graph.worker.v1" or result.get("status") != "completed"
            or final.get("schema") != "hepta.fixed-cell-graph.worker-final.v1" or final.get("status") != "completed"
            or result.get("request_id") != request["request_id"]
            or result.get("request_sha256") != request["request_sha256"]
            or final.get("request_sha256") != request["request_sha256"]
            or final.get("result_line_sha256") != sha(lines[0]) or final.get("result_line_bytes") != len(lines[0])
            or result.get("environment_sha256") != request["environment_sha256"]
            or result.get("head_indices") != request["head_indices"]
            or result.get("head_ids") != [HEAD_IDS[i] for i in request["head_indices"]]
            or result.get("child_process_cpu_ns") != 0 or result.get("authority") != "DENY_ALL"
            or result.get("model_checkpoint_or_task_labels_opened") is not False
            or result.get("request_bytes") != request["request_bytes"]
            or len(result.get("probabilities", [])) != len(request["head_indices"])):
        raise ValueError("worker output is incomplete, stale or not the requested graph shard")
    values = [array(item, (480, 4)) for item in result["probabilities"]]
    limits = result.get("own_cgroup_limits", {})
    if (result.get("local_resource_ceiling_match") is not True
            or result.get("own_cgroup_receipt_sha256") != sha(canonical(limits))
            or type(limits.get("cpu_quota_us")) is not int or type(limits.get("cpu_period_us")) is not int
            or limits["cpu_period_us"] <= 0
            or limits["cpu_quota_us"] * 100 != request["cpu_quota_percent"] * limits["cpu_period_us"]
            or limits.get("memory_max_bytes") != request["memory_max_bytes"]
            or limits.get("cpu_max") != f'{limits["cpu_quota_us"]} {limits["cpu_period_us"]}'
            or limits.get("memory_max") != str(request["memory_max_bytes"])):
        raise ValueError("own cgroup ceiling proof differs from declared native request")
    if any(np.any(value < 0) or np.any(value > 1) or not np.allclose(value.sum(axis=1), 1, atol=1e-12, rtol=0)
           for value in values):
        raise ValueError("invalid frozen probability tensor")
    for key in ("worker_wall_ns_before_final_trailer", "worker_cpu_ns_before_final_trailer", "process_peak_rss_bytes",
                "stdin_read_wall_ns", "result_json_encode_wall_ns", "result_stdout_write_wall_ns"):
        if type(final.get(key)) is not int or final[key] < 0:
            raise ValueError("actual nonnegative worker cost receipt required")
    return values, result, final


def reduce_graph(dispatch, graph_id, owner_input, output, *, expected_dispatch_sha256):
    """Owner input records completed jobs and full stdout; failures remain failures."""
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    data = Path(dispatch).read_bytes()
    if sha(data) != expected_dispatch_sha256:
        raise ValueError("dispatch census changed")
    plan = strict_json(data)
    matching = [g for g in plan["graphs"] if g["graph_id"] == graph_id]
    if len(matching) != 1:
        raise ValueError("one predeclared graph ID required")
    graph = matching[0]
    owner_bytes = Path(owner_input).read_bytes()
    if len(owner_bytes) > 1_048_576:
        raise ValueError("bounded owner input required")
    owner = strict_json(owner_bytes)
    if (owner.get("schema") != "hepta.fixed-cell-graph.collection.v1" or owner.get("graph_id") != graph_id
            or owner.get("dispatch_sha256") != expected_dispatch_sha256
            or len(owner.get("workers", [])) != len(graph["requests"])):
        raise ValueError("exact complete owner node census required")
    nodes, predictions, failures = [], {}, []
    for expected, observed in zip(graph["requests"], owner["workers"], strict=True):
        node = {"request_id": expected["request_id"], "host": expected["host"], "status": "failed",
            "observed_job_id": observed.get("job_id"), "observed_exit_code": observed.get("exit_code"),
            "native_process_cpu_ns": observed.get("native_process_cpu_ns"),
            "native_process_peak_rss_bytes": observed.get("native_process_peak_rss_bytes"),
            "unknown_failed_process_cost_is_not_zero": True,
            "observed_start_disposition": observed.get("start_disposition"),
            "cleanup": observed.get("cleanup"),
            "owner_node_started_ms": observed.get("owner_node_started_ms"),
            "owner_collection_observed_ms": observed.get("owner_collection_observed_ms"),
            "collection_elapsed_ms": observed.get("collection_elapsed_ms")}
        try:
            if (observed.get("request_id") != expected["request_id"] or observed.get("host") != expected["host"]
                    or observed.get("idempotency_key") != expected["idempotency_key"]
                    or observed.get("request_sha256") != expected["request_sha256"]
                    or observed.get("status") != "completed" or observed.get("exit_code") != 0
                    or observed.get("start_disposition") != "created"
                    or not isinstance(observed.get("start_disposition_receipt_sha256"), str)
                    or len(observed["start_disposition_receipt_sha256"]) != 64
                    or not isinstance(observed.get("job_id"), str) or not observed["job_id"]
                    or observed.get("stdout_complete") is not True or observed.get("truncated") is not False
                    or type(observed.get("stderr_bytes")) is not int or not 0 <= observed["stderr_bytes"] <= 8192):
                raise ValueError("failed or non-authoritative native process collection")
            encoded = observed.get("stdout_base64")
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_OUTPUT + 2) // 3):
                raise ValueError("bounded full stdout base64 required")
            stdout = base64.b64decode(encoded, validate=True)
            if sha(stdout) != observed.get("stdout_sha256"):
                raise ValueError("collected stdout identity changed")
            values, result, final = read_worker(stdout, expected)
            if result["graph_sha256"] != plan["graph_sha256"] or result["protocol_sha256"] != plan["protocol_sha256"]:
                raise ValueError("worker graph/protocol identity differs")
            for index, value in zip(expected["head_indices"], values, strict=True):
                if index in predictions:
                    raise ValueError("duplicate head contribution")
                predictions[index] = value
            node.update(status="completed", job_id=observed["job_id"], stdout_sha256=sha(stdout), stdout_bytes=len(stdout),
                request_bytes=expected["request_bytes"], worker_final=final, worker_phase_ns=result["phase_ns"],
                start_disposition=observed["start_disposition"],
                start_disposition_receipt_sha256=observed["start_disposition_receipt_sha256"],
                own_cgroup_cpu_quota_percent=100 * result["own_cgroup_limits"]["cpu_quota_us"] // result["own_cgroup_limits"]["cpu_period_us"],
                own_cgroup_memory_max_bytes=result["own_cgroup_limits"]["memory_max_bytes"],
                requested_cpu_quota_percent=expected["cpu_quota_percent"],
                quota_receipt_sha256=result["own_cgroup_receipt_sha256"],
                authoritative_status_sha256=observed.get("authoritative_status_sha256"),
                head_probability_sha256=[item["sha256"] for item in result["probabilities"]])
        except (ValueError, KeyError, TypeError) as error:
            failures.append({"request_id": expected["request_id"], "type": type(error).__name__, "message": str(error)})
            node["failure"] = failures[-1]
        nodes.append(node)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "hepta.fixed-cell-graph.reduction.v1", "graph_id": graph_id, "block": graph["block"],
        "arm": graph["arm"], "dispatch_sha256": expected_dispatch_sha256,
        "protocol_sha256": plan["protocol_sha256"], "graph_sha256": plan["graph_sha256"],
        "collection_sha256": sha(owner_bytes), "nodes": nodes, "failures": failures,
        "status": "failed" if failures or set(predictions) != set(range(6)) else "completed",
        "no_missing_node_substitution": True,
        "known_completed_worker_cpu_ns": sum(node["worker_final"]["worker_cpu_ns_before_final_trailer"]
            for node in nodes if node["status"] == "completed"),
        "failed_process_costs_may_be_unknown": bool(failures)}
    if receipt["status"] == "completed":
        compute, compute_cpu = time.perf_counter_ns(), time.process_time_ns()
        ordered = np.stack([predictions[i] for i in range(6)])
        reduced = ordered.mean(axis=0, dtype=np.float64)
        receipt["aggregate_wall_ns"] = time.perf_counter_ns() - compute
        receipt["aggregate_cpu_ns"] = time.process_time_ns() - compute_cpu
        with (output / "predictions.npz").open("xb") as stream:
            np.savez_compressed(stream, per_head=ordered, mean=reduced)
        receipt.update(predictions_sha256=sha((output / "predictions.npz").read_bytes()),
            per_head_tensor_sha256=sha(ordered.astype("<f8").tobytes()),
            mean_tensor_sha256=sha(reduced.astype("<f8").tobytes()),
            worker_cpu_ns=sum(v["worker_final"]["worker_cpu_ns_before_final_trailer"] for v in nodes),
            worker_peak_rss_bytes=[v["worker_final"]["process_peak_rss_bytes"] for v in nodes],
            worker_peak_sum_is_not_simultaneous_rss=True)
    receipt.update(reducer_body_wall_ns=time.perf_counter_ns() - began, reducer_body_cpu_ns=time.process_time_ns() - cpu,
        reducer_process_wall_ns_before_receipt=time.perf_counter_ns() - _ENTRY_WALL if _FRESH_EXECUTABLE else None,
        reducer_process_cpu_ns_before_receipt=time.process_time_ns() - _ENTRY_CPU if _FRESH_EXECUTABLE else None,
        reducer_process_peak_rss_bytes_before_receipt=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)),
        fresh_reducer_executable=_FRESH_EXECUTABLE,
        reducer_environment={"python": sys.version, "numpy": np.__version__},
        cost_scope="body is a subset; fresh executable counters include NumPy/import/CLI setup but exclude time import and final receipt/CLI output; enclosing owner path includes all",
        labels_read=False, authority="DENY_ALL")
    with (output / "receipt.json").open("xb") as stream:
        stream.write(canonical(receipt) + b"\n")
    return {"graph_id": graph_id, "status": receipt["status"], "receipt_sha256": sha((output / "receipt.json").read_bytes())}


def compare_tensors(reference, candidate):
    """Fixed tolerance before inference; exactness and argmax are reported separately."""
    if reference.shape != candidate.shape or reference.shape != (6, 480, 4):
        raise ValueError("six fixed heads and480rows required")
    error = np.abs(reference - candidate)
    return {"bitwise_equal": bool(np.array_equal(reference, candidate)),
        "max_absolute_error": float(error.max()),
        "within_predeclared_tolerance": bool(np.allclose(reference, candidate, atol=1e-12, rtol=1e-12)),
        "all_head_argmax_equal": bool(np.array_equal(reference.argmax(axis=2), candidate.argmax(axis=2))),
        "mean_argmax_equal": bool(np.array_equal(reference.mean(axis=0).argmax(axis=1), candidate.mean(axis=0).argmax(axis=1)))}


def validate_recovery(original_collection, recovery, request):
    """Idempotency lookup/read exercise, not crash or power-loss recovery."""
    keys = ("request_id", "host", "idempotency_key", "request_sha256", "job_id", "stdout_sha256", "stdout_base64")
    valid = all(isinstance(original_collection.get(key), str) and bool(original_collection[key])
                and recovery.get(key) == original_collection[key] for key in keys)
    for record in (original_collection, recovery):
        valid = valid and record.get("status") == "completed" and record.get("exit_code") == 0
        valid = valid and record.get("stdout_complete") is True and record.get("truncated") is False
        valid = valid and all(isinstance(request.get(key), str) and bool(request[key]) and record.get(key) == request[key]
                              for key in ("request_id", "host", "idempotency_key", "request_sha256"))
    valid = valid and original_collection.get("start_disposition") == "created" and recovery.get("start_disposition") == "reused"
    valid = valid and isinstance(original_collection.get("start_disposition_receipt_sha256"), str) and len(original_collection["start_disposition_receipt_sha256"]) == 64
    valid = valid and isinstance(recovery.get("start_disposition_receipt_sha256"), str) and len(recovery["start_disposition_receipt_sha256"]) == 64
    start_sha = original_collection.get("original_start_arguments_sha256")
    valid = valid and isinstance(start_sha, str) and len(start_sha) == 64
    valid = valid and recovery.get("repeated_start_arguments_sha256") == start_sha
    try:
        encoded = original_collection["stdout_base64"]
        if not valid or len(encoded) > 4 * ((MAX_OUTPUT + 2) // 3):
            raise ValueError("incomplete original completed-job reference")
        stdout = base64.b64decode(encoded, validate=True)
        if sha(stdout) != original_collection["stdout_sha256"]:
            raise ValueError("original authoritative output hash differs")
        read_worker(stdout, request)
    except (ValueError, KeyError, TypeError):
        valid = False
    return {"passed": bool(valid), "scope": "same original request/effect identity; cached authoritative job and exact output",
        "no_recomputation_proof_scope": "same authoritative job ID and byte-identical full stdout; not a kernel or service restart test"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dispatch", "graph-id", "owner-input", "output", "expected-dispatch-sha256"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(reduce_graph(**vars(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
