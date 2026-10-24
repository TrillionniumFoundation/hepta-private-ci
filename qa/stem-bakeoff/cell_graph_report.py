"""Complete-census performance/parity report; never an accuracy or AGI score."""

import argparse
import json
from pathlib import Path

import numpy as np

from cell_graph_worker import canonical, sha, strict_json
from cell_graph_reduce import compare_tensors, validate_recovery


def read(path, maximum=1_048_576):
    data = Path(path).read_bytes()
    if len(data) > maximum:
        raise ValueError("bounded evidence file required")
    return data, strict_json(data)


def owner_check(owner, graph, dispatch_sha256):
    errors = []
    if (owner.get("schema") != "hepta.fixed-cell-graph.owner.v1" or owner.get("graph_id") != graph["graph_id"]
            or owner.get("dispatch_sha256") != dispatch_sha256 or owner.get("no_cross_host_clock_subtraction") is not True
            or owner.get("no_serial_fallback") is not True):
        errors.append("owner identity or clock/fallback contract differs")
    for key in ("started_ms", "completed_ms", "critical_path_ms", "collect_path_ms", "reducer_service_path_ms"):
        if type(owner.get(key)) is not int or owner[key] < 0:
            errors.append("owner actual millisecond measurement absent: " + key)
    if not errors and (owner["completed_ms"] < owner["started_ms"]
            or owner["completed_ms"] - owner["started_ms"] != owner["critical_path_ms"]
            or owner["collect_path_ms"] + owner["reducer_service_path_ms"] > owner["critical_path_ms"]):
        errors.append("owner intervals inconsistent")
    if type(owner.get("collect_path_ms")) is int and owner["collect_path_ms"] > 60000:
        errors.append("observed primary collection exceeded60s")
    events = owner.get("events", [])
    for request in graph["requests"]:
        calls = [event for event in events if event.get("request_id") == request["request_id"]]
        starts = [event for event in calls if event.get("operation") == "process_start"]
        if len(starts) != 1 or not any(e.get("operation") == "process_read" for e in calls) or len(calls) > 24:
            errors.append("exact one original start and bounded full-read calls required: " + request["request_id"])
        for event in calls:
            if (event.get("host") != request["host"] or event.get("operation") not in ("process_start", "process_status", "process_read")
                    or type(event.get("started_ms")) is not int or type(event.get("finished_ms")) is not int
                    or event["finished_ms"] < event["started_ms"] or event.get("status") != "completed"
                    or not isinstance(event.get("native_receipt_sha256"), str) or len(event["native_receipt_sha256"]) != 64):
                errors.append("native API event incomplete or failed: " + request["request_id"])
        if (len(starts) == 1 and type(starts[0].get("started_ms")) is int
                and any(type(event.get("finished_ms")) is int
                        and event["finished_ms"] - starts[0]["started_ms"] > 60000 for event in calls)):
            errors.append("late completed native call exceeded primary collection bound")
    if graph["arm"] in ("B", "C"):
        if owner.get("requested_submission") != "Promise.all" or owner.get("concurrent_start_calls_observed") is not True:
            errors.append("predeclared concurrent submission not observed")
    return errors


def recovery_events_valid(replay, request, primary_completed_ms):
    started, completed = replay.get("started_ms"), replay.get("completed_ms")
    events = replay.get("api_events")
    if (type(started) is not int or type(completed) is not int or primary_completed_ms is None
            or started < primary_completed_ms or not 0 <= completed - started <= 60000
            or replay.get("status") != "completed" or not isinstance(events, list) or not 2 <= len(events) <= 24):
        return False
    if any(not isinstance(event, dict) for event in events):
        return False
    if (sum(e.get("operation") == "process_start" for e in events) != 1
            or not any(e.get("operation") == "process_read" for e in events)
            or events[0].get("operation") != "process_start"):
        return False
    previous = started
    for event in events:
        if (event.get("operation") not in ("process_start", "process_status", "process_read")
                or event.get("request_id") != request["request_id"] or event.get("host") != request["host"]
                or event.get("status") != "completed" or type(event.get("started_ms")) is not int
                or type(event.get("finished_ms")) is not int or not previous <= event["started_ms"] <= event["finished_ms"] <= completed
                or not isinstance(event.get("native_receipt_sha256"), str) or len(event["native_receipt_sha256"]) != 64):
            return False
        previous = event["finished_ms"]
    return True


def report(dispatch, evidence, output, *, expected_dispatch_sha256):
    raw, plan = read(dispatch)
    if sha(raw) != expected_dispatch_sha256 or len(plan["graphs"]) != 18 or plan["requests"] != 30:
        raise ValueError("exact frozen dispatch census required")
    root, rows, missing = Path(evidence), [], []
    baseline_path = root / "b0-A" / "reduction" / "predictions.npz"
    reference = None
    reference_failure = None
    if baseline_path.is_file():
        try:
            with np.load(baseline_path, allow_pickle=False) as arrays:
                reference = arrays["per_head"].copy()
        except (OSError, ValueError, KeyError) as error:
            reference_failure = str(error)
    previous_end = None
    for graph in plan["graphs"]:
        name = graph["graph_id"]
        row = {"graph_id": name, "arm": graph["arm"], "block": graph["block"], "status": "failed", "issues": []}
        try:
            owner_raw, owner = read(root / name / "owner.json")
            receipt_raw, reduction = read(root / name / "reduction" / "receipt.json")
            row["issues"].extend(owner_check(owner, graph, expected_dispatch_sha256))
            if (owner.get("reduction", {}).get("receipt_sha256") != sha(receipt_raw)
                    or reduction.get("graph_id") != name or reduction.get("dispatch_sha256") != expected_dispatch_sha256
                    or owner.get("status") != "completed" or reduction.get("status") != "completed"):
                row["issues"].append("failed or mismatched authoritative graph/reduction")
            if previous_end is not None and owner["started_ms"] < previous_end:
                row["issues"].append("graphs did not execute in frozen sequential block order")
            previous_end = owner["completed_ms"]
            row.update(owner_sha256=sha(owner_raw), reduction_sha256=sha(receipt_raw),
                critical_path_ms=owner["critical_path_ms"], collect_path_ms=owner["collect_path_ms"],
                reducer_service_path_ms=owner["reducer_service_path_ms"],
                primary_api_call_count=len(owner["events"]), cleanup_api_call_count=len(owner.get("cleanup_events", [])),
                cleanup_events=owner.get("cleanup_events", []),
                reducer_body_cpu_ns=reduction["reducer_body_cpu_ns"],
                reducer_process_cpu_ns_before_receipt=reduction["reducer_process_cpu_ns_before_receipt"],
                reducer_process_peak_rss_bytes_before_receipt=reduction["reducer_process_peak_rss_bytes_before_receipt"],
                worker_cpu_ns=reduction.get("worker_cpu_ns"), worker_peak_rss_bytes=reduction.get("worker_peak_rss_bytes"),
                nodes=reduction["nodes"])
            for request, node in zip(graph["requests"], reduction["nodes"], strict=True):
                if (node.get("own_cgroup_cpu_quota_percent") != request["cpu_quota_percent"]
                        or node.get("own_cgroup_memory_max_bytes") != request["memory_max_bytes"]
                        or not isinstance(node.get("quota_receipt_sha256"), str) or len(node["quota_receipt_sha256"]) != 64
                        or not isinstance(node.get("authoritative_status_sha256"), str)
                        or len(node["authoritative_status_sha256"]) != 64):
                    row["issues"].append("own cgroup ceilings or native status not attested")
            path = root / name / "reduction" / "predictions.npz"
            if sha(path.read_bytes()) != reduction["predictions_sha256"]:
                raise ValueError("reduced prediction archive changed")
            with np.load(path, allow_pickle=False) as arrays:
                candidate, mean = arrays["per_head"], arrays["mean"]
                if not np.array_equal(candidate.mean(axis=0, dtype=np.float64), mean):
                    raise ValueError("canonical fixed reducer changed")
                if reference is None:
                    raise ValueError("original predeclared b0-A reference unavailable; no substitute selected")
                parity = compare_tensors(reference, candidate)
            row["parity"] = parity
            if not all(parity[key] for key in ("within_predeclared_tolerance", "all_head_argmax_equal", "mean_argmax_equal")):
                row["issues"].append("functional graph parity failed")
            if not row["issues"]:
                row["status"] = "completed"
        except (OSError, ValueError, KeyError, TypeError) as error:
            row["issues"].append(type(error).__name__ + ": " + str(error))
        if row["status"] != "completed":
            missing.append(name)
        rows.append(row)
    result = {"schema": "hepta.fixed-cell-graph.report.v1", "dispatch_sha256": expected_dispatch_sha256,
        "protocol_sha256": plan["protocol_sha256"], "graph_sha256": plan["graph_sha256"],
        "rows": rows, "expected_graphs": 18, "completed_comparable_graphs": 18 - len(missing),
        "failed_or_noncomparable": missing, "complete_case_census_required": True,
        "scope": "same fixed graph through cold native dispatch on these heterogeneous host/environment stacks",
        "not_estimated": ["accuracy", "learned edges", "growth", "general intelligence", "isolated network latency",
            "persistent service throughput", "whole-host unique physical RAM", "service daemon CPU/RSS"],
        "peak_rss_scope": "per-process observed high-water marks; their sum is not simultaneous or unique physical memory",
        "cost_rule": "owner critical path is enclosing wall time; worker/reducer phases are subsets, never added again",
        "clock_limit": "single owner millisecond wall clock; backward changes reject, undetected forward changes remain possible",
        "setup_costs_must_be_published_separately": ["code deployment", "environment inventory", "source export",
            "portable request preparation", "adapter setup and frozen bindings"],
        "no_total_system_net_benefit_claim": True, "labels_read": False}
    result["predeclared_reference_failure"] = reference_failure
    recovery_rows = []
    for arm in ("A", "B", "C"):
        name = f"b0-{arm}-s0"
        item = {"request_id": name, "status": "failed"}
        try:
            _, original = read(root / f"b0-{arm}" / "collection.json")
            _, replay = read(root / "recovery" / f"{name}.json")
            sources = [worker for worker in original["workers"] if worker["request_id"] == name]
            if len(sources) != 1:
                raise ValueError("exact original recovery job absent")
            request = next(g["requests"][0] for g in plan["graphs"] if g["graph_id"] == f"b0-{arm}")
            checked = validate_recovery(sources[0], replay["collection"], request)
            if not checked["passed"] or not recovery_events_valid(replay, request, previous_end):
                raise ValueError("identity-preserving after-census lookup/read recovery failed")
            item.update(status="completed", identity_check=checked,
                extra_owner_wall_ms=replay["completed_ms"] - replay["started_ms"],
                api_events=replay["api_events"], old_worker_cost_not_charged_again=True)
        except (OSError, ValueError, KeyError, TypeError) as error:
            item["failure"] = type(error).__name__ + ": " + str(error)
        recovery_rows.append(item)
    result["separate_idempotency_recovery"] = recovery_rows
    result["recovery_scope"] = "three original block0 shard0 lookups after primary census; no crash or power-loss injection"
    if not missing:
        by_arm = {arm: np.array([row["critical_path_ms"] for row in rows if row["arm"] == arm], dtype=float)
                  for arm in ("A", "B", "C")}
        result["arm_wall_ms"] = {arm: {"all_six": values.tolist(), "median": float(np.median(values)),
            "minimum": float(values.min()), "maximum": float(values.max())} for arm, values in by_arm.items()}
        paired = {}
        by_key = {(row["block"], row["arm"]): row["critical_path_ms"] for row in rows}
        for comparison, baseline in (("C_minus_B", "B"), ("C_minus_A", "A"), ("B_minus_A", "A")):
            candidate = "B" if comparison == "B_minus_A" else "C"
            delta = np.array([by_key[(i, candidate)] - by_key[(i, baseline)] for i in range(6)], dtype=float)
            paired[comparison] = {"all_six_ms": delta.tolist(), "median_ms": float(np.median(delta)),
                "mean_ms": float(delta.mean()), "negative_means_candidate_faster": True}
        result["paired_descriptive_wall"] = paired
        result["statistical_scope"] = "six scheduled paired blocks; no reliable tail, confidence interval, or population generality claim"
    else:
        result["comparison_status"] = "blocked; preserve all raw costs, do not select only successful paired blocks"
    with Path(output).open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    return {"completed_comparable_graphs": result["completed_comparable_graphs"], "output_sha256": sha(Path(output).read_bytes())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dispatch", "evidence", "output", "expected-dispatch-sha256"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(report(**vars(parser.parse_args())), indent=2))
