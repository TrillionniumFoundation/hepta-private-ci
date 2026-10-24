"""Read-only actual-evidence audit using the unchanged frozen graph reporter.

No inference, training, network, host tools, source edits or threshold selection.
The output directory must be new. Negative/missing cases remain in the census.
"""

import argparse
import base64
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time


PINS = {
    "cell_graph_report.py": "7a5b7dfaccda71143e0de6b1087d2744bc5ee16e14d0e146f06b77734621544d",
    "cell_graph_reduce.py": "5ac4bba925d161f8fe3eda5c5c036207d7182ec84733f6c1f310befa0da54efb",
    "cell_graph_worker.py": "bb9a6ddc30cc267d22a530e9486e6590cdef15247d1546905b4a051e8eed8358",
}
DISPATCH_SHA = "595d40d93a9ba394c21c39fd41c5c8b60ab5ceddfcdb8bdd9f5102ce193fa4ae"
WRAPPER_SHA = "fced1311223adde960d9e0c04fc40c8e816d01a4e078f09f802b67b20d3e5b45"
PROTOCOL_SHA = "2c88c2a47f56c05ea86f221ad26806fb5190bd17b8b32a9284a0ae31dfbe85e5"
ORDERS = ("ABC", "ACB", "BAC", "BCA", "CAB", "CBA")
RECOVERIES = ("b0-A-s0", "b0-B-s0", "b0-C-s0")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def strict(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON value: " + value)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def read(path, manifest, maximum=1048576):
    path = Path(path)
    require(not any(item.is_symlink() for item in (path, *path.parents)), "symlink evidence rejected")
    require(path.is_file() and path.stat().st_size <= maximum, "missing/nonregular/oversized file: " + str(path))
    data = path.read_bytes()
    manifest[str(path)] = {"bytes": len(data), "sha256": sha(data)}
    return data


def optional(path, manifest):
    if not Path(path).exists():
        return None
    return strict(read(path, manifest))


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def native(record):
    result = strict(record["result_json"])
    require(result.get("isError") is False and len(result.get("content", [])) == 1
        and result["content"][0].get("type") == "text", "one exact successful native MCP text required")
    value = strict(result["content"][0]["text"])
    require(value.get("audit_recorded") is True, "native audit receipt absent")
    return value


def decode(value):
    require(isinstance(value, str), "base64 string required")
    data = base64.b64decode(value, validate=True)
    require(base64.b64encode(data).decode() == value, "noncanonical base64")
    return data


def event_record(event, lane, records_by_sha, records):
    digest = event.get("native_receipt_sha256")
    candidates = records_by_sha.get(digest, []) if digest else records
    matches = [record for record in candidates if record.get("lane") == lane
        and record.get("request_id") == event.get("request_id")
        and record.get("operation") == event.get("operation")
        and type(event.get("started_ms")) is int and type(event.get("finished_ms")) is int
        and type(record.get("started_ms")) is int and type(record.get("finished_ms")) is int
        and event["started_ms"] <= record["started_ms"] <= record["finished_ms"] <= event["finished_ms"]]
    require(len(matches) == 1, "native event lacks one exact raw lane/identity/time provenance")
    return matches[0]


def check_completed_collection(node, request, events, lane, records_by_sha, records):
    """Independently bind authoritative job/args and reassemble original log bytes."""
    calls = [event for event in events if event.get("request_id") == request["request_id"]]
    starts = [event for event in calls if event.get("operation") == "process_start"]
    require(len(starts) == 1 and len(calls) <= 24, "exact one bounded original start required")
    start = event_record(starts[0], lane, records_by_sha, records)
    args, receipt = strict(start["arguments_json"]), native(start)
    job = receipt["job"]
    worker_path = ("/home/qian-qi/workspace/hepta-cell-graph-evidence-20261024/worker/cell_graph_worker.py"
        if request["host"] == "main" else "/home/alex/hepta-cell-graph-evidence-20261024/worker/cell_graph_worker.py")
    require(all(node.get(key) == request[key] for key in ("request_id", "host", "idempotency_key", "request_sha256")), "normalized original collection identity differs")
    require(args["host"] == request["host"] and args["idempotency_key"] == request["idempotency_key"]
        and args["executable"] == request["python_executable"]
        and args["args"] == ["-u", worker_path, "--expected-request-sha256", request["request_sha256"]]
        and args["cwd"] == str(Path(worker_path).parent)
        and args["env"] == {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": ""}
        and args["cpu_quota_percent"] == request["cpu_quota_percent"]
        and args["memory_max_bytes"] == request["memory_max_bytes"] and args["timeout_seconds"] == 45
        and sha(args["stdin"].encode()) == request["request_sha256"]
        and len(args["stdin"].encode()) == request["request_bytes"], "original native request differs from frozen dispatch")
    require(job["id"] == node["job_id"] and job["host"] == request["host"]
        and job["idempotency_key"] == request["idempotency_key"] and job["args"] == args["args"]
        and job["executable"] == args["executable"] and job["cwd"] == args["cwd"]
        and job["request_digest"] == node["native_request_digest"]
        and str(job["request_fingerprint"]) == node["native_request_fingerprint"], "original native job/digest/fingerprint identity differs")
    expected_reused = lane == "recovery"
    require(receipt["reused"] is expected_reused and node["start_disposition"] == ("reused" if expected_reused else "created"), "native created/reused admission differs")
    args_key = "repeated_start_arguments_sha256" if expected_reused else "original_start_arguments_sha256"
    require(node[args_key] == start["arguments_sha256"], "exact native argument hash differs")
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    pages = [event for event in calls if event.get("operation") == "process_read"]
    require(1 <= len(pages) <= 12, "bounded complete read census required")
    for event in pages:
        raw = event_record(event, lane, records_by_sha, records)
        read_args, result = strict(raw["arguments_json"]), native(raw)
        require(read_args["host"] == request["host"] and read_args["job_id"] == node["job_id"]
            and read_args["limit"] == 16384 and result["job_id"] == node["job_id"], "read host/job/limit differs")
        for name in streams:
            page = result[name]
            require(isinstance(page["bytes_hex"], str) and re.fullmatch(r"(?:[0-9a-f]{2})*", page["bytes_hex"]), "canonical raw bytes_hex required")
            data = bytes.fromhex(page["bytes_hex"])
            require(read_args[name + "_offset"] == len(streams[name]) == page["offset"]
                and len(data) <= 16384 and page["next_offset"] == page["offset"] + len(data)
                and page["eof"] is (page["next_offset"] == page["size"]), "native log cursor/EOF differs")
            streams[name].extend(data)
    terminal_candidates = [record for record in records_by_sha.get(node["authoritative_status_sha256"], [])
        if record.get("lane") == lane and record.get("request_id") == request["request_id"] and record.get("operation") == "process_status"]
    require(bool(terminal_candidates), "original authoritative status raw receipt absent")
    terminal = native(terminal_candidates[-1])
    require(terminal["job_id"] == node["job_id"] and terminal["state"] == "succeeded" and terminal["exit_code"] == 0
        and terminal["output_complete"] is True and terminal["timed_out"] is False and terminal["cancelled"] is False, "successful original terminal status absent")
    for name, cap in (("stdout", 196608), ("stderr", 8192)):
        data = bytes(streams[name])
        require(len(data) <= cap and sha(data) == node[name + "_sha256"] and data == decode(node[name + "_base64"])
            and terminal["log_bytes"][name]["seen"] == terminal["log_bytes"][name]["stored"] == len(data)
            and terminal["log_truncated"][name] is False and terminal["log_errors"][name] is None, "full terminal stream bytes/hash/count differ")
    return {"request_id": request["request_id"], "job_id": node["job_id"], "lane": lane,
        "full_native_provenance": True, "stdout_bytes": len(streams["stdout"]), "stderr_bytes": len(streams["stderr"]), "pages": len(pages)}


def report_summary(value):
    keys = ("graph_id", "arm", "block", "status", "critical_path_ms", "collect_path_ms", "reducer_service_path_ms", "parity")
    return {"rows": [{key: row.get(key) for key in keys} for row in value["rows"]],
        "completed_comparable_graphs": value["completed_comparable_graphs"],
        "failed_or_noncomparable": value["failed_or_noncomparable"],
        "paired_descriptive_wall": value.get("paired_descriptive_wall"),
        "recovery": [{"request_id": row["request_id"], "status": row["status"]} for row in value["separate_idempotency_recovery"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-dir", "dispatch", "evidence-root", "environment-receipt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--ledger", type=Path, action="append", required=True,
        help="Sealed full ledger and optional exact post-sealing tail export; overlapping entries must match")
    parser.add_argument("--setup-costs", type=Path, help="Root's actual external cost receipts/index; absent means unreported, not zero")
    parser.add_argument("--helper-costs", type=Path, help="Exact postrun helper/outer-span store export; absent means full publication wall unreported")
    parser.add_argument("--published-report", type=Path)
    args = parser.parse_args()
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest, issues, notes = {}, [], []
    for name, digest in PINS.items():
        require(sha(read(args.source_dir / name, manifest)) == digest, "frozen reporter dependency changed: " + name)
    dispatch_raw = read(args.dispatch, manifest)
    require(sha(dispatch_raw) == DISPATCH_SHA, "exact frozen dispatch SHA required")
    plan = strict(dispatch_raw)
    graph_ids = [f"b{block}-{arm}" for block, order in enumerate(ORDERS) for arm in order]
    require([item["graph_id"] for item in plan["graphs"]] == graph_ids and plan["requests"] == 30
        and sum(len(item["requests"]) for item in plan["graphs"]) == 30 and plan["protocol_sha256"] == PROTOCOL_SHA, "frozen18/30census differs")
    environment_raw = read(args.environment_receipt, manifest)
    require(sha(environment_raw) == plan["environment_freeze_sha256"], "environment freeze differs")
    environment = strict(environment_raw)
    helpers = strict(read(args.helper_costs, manifest, 33554432)) if args.helper_costs else None
    retained = {item["graph_id"]: item for item in helpers.get("session_retained_unpublished", [])} if helpers else {}
    records_by_index, constructions, snapshots = {}, {}, []
    for path in args.ledger:
        raw = read(path, manifest, 268435456)
        ledger = strict(raw)
        require(ledger["schema"] == "hepta.fixed-cell-graph.native-ledger.v1"
            and ledger["dispatch_sha256"] == DISPATCH_SHA and ledger["wrapper_sha256"] == WRAPPER_SHA, "ledger protocol/dispatch/wrapper differs")
        snapshots.append({"path": str(path), "sha256": sha(raw), "record_count": len(ledger["records"]), "state": ledger.get("state")})
        for index, item in enumerate(ledger.get("constructions", [])):
            require(index not in constructions or constructions[index] == item, "conflicting adapter construction snapshots")
            constructions[index] = item
        for item in ledger["records"]:
            index = item["index"]
            require(type(index) is int and index >= 0, "native call index required")
            require(index not in records_by_index or records_by_index[index] == item, "conflicting immutable raw call snapshots")
            require(sha(item["arguments_json"].encode()) == item["arguments_sha256"]
                and len(item["arguments_json"].encode()) == item["logical_tool_request_bytes"], "raw native arguments identity/bytes differ")
            if "result_json" in item:
                require(sha(item["result_json"].encode()) == item["native_receipt_sha256"]
                    and len(item["result_json"].encode()) == item["logical_tool_response_bytes"], "raw MCP receipt identity/bytes differ")
            records_by_index[index] = item
    indices = sorted(records_by_index)
    require(indices == list(range(len(indices))), "raw native call index holes; include missing original ledger/tail")
    records = [records_by_index[index] for index in indices]
    records_by_sha = defaultdict(list)
    for record in records:
        if record.get("native_receipt_sha256"):
            records_by_sha[record["native_receipt_sha256"]].append(record)
    graph_root, census, provenance = args.evidence_root / "graphs", [], []
    for graph in plan["graphs"]:
        folder = graph_root / graph["graph_id"]
        row = {"graph_id": graph["graph_id"], "arm": graph["arm"], "block": graph["block"],
            "expected_workers": len(graph["requests"]), "missing": [], "file_errors": [], "known_owner_costs": None}
        observed = {}
        for key, relative in (("owner", "owner.json"), ("collection", "collection.json"), ("reduction", "reduction/receipt.json")):
            try:
                observed[key] = optional(folder / relative, manifest)
                if observed[key] is None:
                    row["missing"].append(relative)
            except (OSError, ValueError, KeyError, TypeError) as error:
                observed[key] = None
                row["file_errors"].append(relative + ": " + str(error))
        owner, collection, reduction = (observed[key] for key in ("owner", "collection", "reduction"))
        for error in row["file_errors"]:
            issues.append({"graph_id": graph["graph_id"], "scope": "observed_evidence_parse", "error": error})
        row["owner_status"] = owner.get("status") if owner else None
        row["reduction_status"] = reduction.get("status") if reduction else None
        if owner:
            row["known_owner_costs"] = {key: owner.get(key) for key in ("started_ms", "completed_ms", "critical_path_ms", "collect_path_ms", "reducer_service_path_ms")}
            for lane, field in (("primary", "events"), ("cleanup", "cleanup_events")):
                for event in owner.get(field, []):
                    try:
                        event_record(event, lane, records_by_sha, records)
                    except (ValueError, KeyError, TypeError) as error:
                        target = issues if event.get("status") == "completed" else notes
                        target.append({"graph_id": graph["graph_id"], "scope": lane, "request_id": event.get("request_id"), "error": str(error)})
        elif retained.get(graph["graph_id"], {}).get("owner"):
            unpublished = retained[graph["graph_id"]]["owner"]
            row["known_owner_costs"] = {key: unpublished.get(key) for key in ("started_ms", "completed_ms", "critical_path_ms", "collect_path_ms", "reducer_service_path_ms")}
            row["known_owner_cost_source"] = "original session-retained unpublished owner; missing publication remains missing"
        row["known_reduction_costs"] = {key: reduction.get(key) for key in ("known_completed_worker_cpu_ns", "worker_cpu_ns", "worker_peak_rss_bytes", "reducer_body_cpu_ns", "reducer_process_cpu_ns_before_receipt", "reducer_process_peak_rss_bytes_before_receipt")} if reduction else None
        if collection:
            if (collection.get("graph_id") != graph["graph_id"] or collection.get("dispatch_sha256") != DISPATCH_SHA
                    or len(collection.get("workers", [])) != len(graph["requests"])):
                issues.append({"graph_id": graph["graph_id"], "scope": "collection_identity_census", "error": "original normalized collection identity or complete worker census differs"})
            if reduction and reduction.get("collection_sha256") != manifest[str(folder / "collection.json")]["sha256"]:
                issues.append({"graph_id": graph["graph_id"], "scope": "reducer_collection_binding", "error": "normalized original collection bytes differ from the original reduction receipt"})
            row["observed_workers"] = [{"request_id": node.get("request_id"), "status": node.get("status"), "job_id": node.get("job_id"), "exit_code": node.get("exit_code"), "failure": node.get("failure"), "cleanup": node.get("cleanup")} for node in collection.get("workers", [])]
            for request, node in zip(graph["requests"], collection.get("workers", [])):
                if node.get("status") == "completed":
                    try:
                        provenance.append(check_completed_collection(node, request, owner["events"], "primary", records_by_sha, records))
                    except (OSError, ValueError, KeyError, TypeError) as error:
                        issues.append({"request_id": request["request_id"], "scope": "completed_primary_native_provenance", "error": str(error)})
        census.append(row)
    # Invoke the actual unchanged reporter, never a replacement scoring function.
    report_path = args.output / "recomputed-report.json"
    command = [sys.executable, str(args.source_dir / "cell_graph_report.py"), "--dispatch", str(args.dispatch),
        "--evidence", str(graph_root), "--output", str(report_path), "--expected-dispatch-sha256", DISPATCH_SHA]
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "CUDA_VISIBLE_DEVICES": ""}, check=False)
    except subprocess.TimeoutExpired as error:
        completed = subprocess.CompletedProcess(command, 124, stdout=error.stdout or b"", stderr=error.stderr or b"")
        issues.append({"scope": "original_reporter", "error": "reporter exceeded bounded60s; partial stdout/stderr retained, no substitute scoring"})
    (args.output / "reporter-stdout.bin").write_bytes(completed.stdout)
    (args.output / "reporter-stderr.bin").write_bytes(completed.stderr)
    recomputed = strict(read(report_path, manifest)) if completed.returncode == 0 and report_path.exists() else None
    comparison, paired_check = None, None
    if recomputed:
        try:
            rows = recomputed["rows"]
            require([row["graph_id"] for row in rows] == graph_ids, "reporter deleted/reordered census rows")
            failed = [row["graph_id"] for row in rows if row["status"] != "completed"]
            require(failed == recomputed["failed_or_noncomparable"] and recomputed["completed_comparable_graphs"] == 18 - len(failed), "reported census counts differ")
            if failed:
                require("paired_descriptive_wall" not in recomputed and "arm_wall_ms" not in recomputed, "selected complete-case subset was reported")
            else:
                pairs, lookup = {}, {(row["block"], row["arm"]): row["critical_path_ms"] for row in rows}
                for label, candidate, baseline in (("C_minus_B", "C", "B"), ("C_minus_A", "C", "A"), ("B_minus_A", "B", "A")):
                    values = [lookup[(block, candidate)] - lookup[(block, baseline)] for block in range(6)]
                    reported = recomputed["paired_descriptive_wall"][label]
                    require(values == reported["all_six_ms"] and statistics.median(values) == reported["median_ms"] and statistics.mean(values) == reported["mean_ms"], "independent raw paired differences/statistics differ")
                    pairs[label] = {"all_six_ms": values, "median_ms": statistics.median(values), "mean_ms": statistics.mean(values)}
                paired_check = pairs
            if args.published_report:
                published_raw = read(args.published_report, manifest)
                published = strict(published_raw)
                same_summary = report_summary(published) == report_summary(recomputed)
                comparison = {"published_sha256": sha(published_raw), "recomputed_sha256": sha(report_path.read_bytes()),
                    "byte_identical": published_raw == report_path.read_bytes(), "structured_result_equal": same_summary,
                    "failure_path_messages_not_normalized": True}
                require(same_summary, "published/recomputed structured scientific result differs")
                if not failed:
                    require(comparison["byte_identical"], "complete successful original reporter result differs bytewise")
        except (ValueError, KeyError, TypeError) as error:
            issues.append({"scope": "original_reporter_independent_census_or_pairs", "error": str(error)})
    else:
        issues.append({"scope": "original_reporter", "returncode": completed.returncode, "error": "original reporter did not produce a valid complete-census report"})
    recovery_census = []
    for request_id in RECOVERIES:
        path = graph_root / "recovery" / (request_id + ".json")
        item = {"request_id": request_id, "present": path.is_file(), "status": None}
        try:
            replay = optional(path, manifest)
            if replay:
                item.update(status=replay.get("status"), failure=replay.get("failure"), started_ms=replay.get("started_ms"), completed_ms=replay.get("completed_ms"))
                if replay.get("status") == "completed":
                    request = next(g["requests"][0] for g in plan["graphs"] if g["graph_id"] == request_id[:4])
                    provenance.append(check_completed_collection(replay["collection"], request, replay["api_events"], "recovery", records_by_sha, records))
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append({"scope": "recovery_native_provenance", "request_id": request_id, "error": str(error)})
        recovery_census.append(item)
    lanes = {}
    for lane in sorted({item["lane"] for item in records}):
        selected = [item for item in records if item["lane"] == lane]
        elapsed = [item["elapsed_ms"] for item in selected if type(item.get("elapsed_ms")) is int]
        lanes[lane] = {"calls": len(selected), "returned_or_failed": {status: sum(item["status"] == status for item in selected) for status in sorted({item["status"] for item in selected})},
            "known_sum_of_call_elapsed_ms": sum(elapsed), "calls_without_elapsed": len(selected) - len(elapsed),
            "known_logical_request_bytes": sum(item.get("logical_tool_request_bytes", 0) for item in selected),
            "known_logical_response_bytes": sum(item.get("logical_tool_response_bytes", 0) for item in selected),
            "calls_without_response_bytes": sum("logical_tool_response_bytes" not in item for item in selected),
            "scope": "Sum of observed call spans is not graph latency; concurrent calls and enclosing owner spans overlap. Logical bytes exclude wire/TLS."}
    setup = strict(read(args.setup_costs, manifest, 16777216)) if args.setup_costs else None
    if helpers:
        for item in helpers.get("helpers", []):
            record = item.get("record")
            if not record:
                notes.append({"scope": "helper_cost", "store_key": item.get("store_key"), "error": "helper record unavailable; do not fill zero"})
                continue
            try:
                require(type(record.get("started_ms")) is int and type(record.get("completed_ms")) is int
                    and record["completed_ms"] - record["started_ms"] == record["elapsed_ms"], "helper actual enclosing interval differs")
                for event in record["events"]:
                    bound = {**event, "request_id": record["key_suffix"]}
                    if event.get("status") == "completed":
                        event_record(bound, "helper:" + record["operation"], records_by_sha, records)
            except (ValueError, KeyError, TypeError) as error:
                issues.append({"scope": "helper_cost_raw_binding", "phase": record.get("operation"), "store_key": item.get("store_key"), "error": str(error)})
    if setup:
        for entry in setup.get("entries", []):
            for receipt in entry.get("receipts", []):
                relative = Path(receipt["file"])
                require(not relative.is_absolute() and ".." not in relative.parts, "setup receipt must stay in task-owned evidence root")
                require(sha(read(args.evidence_root / relative, manifest, 16777216)) == receipt["sha256"], "declared setup receipt hash differs")
    result = {"schema": "hepta.fixed-cell-graph.actual-evidence-audit.v1", "dispatch_sha256": DISPATCH_SHA,
        "original_reporter_dependency_sha256": PINS, "reporter_returncode": completed.returncode,
        "expected_graphs": 18, "expected_workers": 30, "expected_recoveries": 3, "complete_census": census,
        "recovery_census": recovery_census, "original_reporter_completed_comparable_graphs": recomputed.get("completed_comparable_graphs") if recomputed else None,
        "primary_native_provenance_checks": [item for item in provenance if item["lane"] == "primary"],
        "recovery_native_provenance_checks": [item for item in provenance if item["lane"] == "recovery"],
        "published_report_comparison": comparison, "independent_paired_descriptive_check": paired_check,
        "integrity_issues": issues, "unmatched_failed_event_notes": notes, "evidence_integrity_pass": not issues,
        "source_environment": environment, "raw_ledger_snapshots": snapshots, "native_api_cost_lanes": lanes,
        "all_observed_adapter_constructions": list(constructions.values()), "external_setup_cost_document": setup,
        "external_setup_missing_is_not_zero": setup is None,
        "exact_helper_and_outer_span_export": helpers, "helper_enclosing_wall_missing_is_not_zero": helpers is None,
        "external_cost_document_scope": "Declared heterogeneous setup metrics retain their original receipt hashes; only native ledger/helper timings are automatically cross-checked here. No invented aggregate total.",
        "cost_limits": ["Owner wall encloses primary/cleanup/reducer helper work; never add these nested spans again.",
            "Worker/reducer CPU phases overlap their process counters; wrapper child CPU overlaps original reducer CPU.",
            "Summed RSS peaks are not simultaneous or unique physical RAM.",
            "Helper publish/recovery-publication/raw-sealing, setup, request transfer, and every adapter reconstruction are separate costs.",
            "A ledger snapshot cannot include its future self-sealing calls; include an exact post-sealing store tail or mark that cost/provenance absent.",
            "Final archive/publication acknowledgement is outside the archive it acknowledges; retain its receipt separately.",
            "Service daemon and JavaScript-owner CPU/RSS, wire/TLS bytes and global contention remain unmeasured."],
        "claim_scope": "Same fixed graph on the declared heterogeneous Python/NumPy/hardware/dispatch stacks; no isolated network/CPU causal effect, task competence, learning/splitting, AGI or whole-system net benefit claim.",
        "no_new_inference_or_training": True, "no_task_labels_opened": True,
        "audit_wall_ns_before_publication": time.perf_counter_ns() - began, "audit_self_cpu_ns_before_publication": time.process_time_ns() - cpu,
        "audit_is_separate_verification_cost": True, "auditor_source_sha256": sha(Path(__file__).read_bytes())}
    primary_issues = [item for item in issues if not item["scope"].startswith("recovery_")
        and not (item["scope"] == "helper_cost_raw_binding" and item.get("phase") != "reduce")]
    result["qualified_primary_cost_comparison"] = bool(recomputed and recomputed.get("completed_comparable_graphs") == 18 and len(result["primary_native_provenance_checks"]) == 30 and not primary_issues)
    save(args.output / "audit.json", result)
    save(args.output / "input-sha256.json", manifest)
    print(json.dumps({"evidence_integrity_pass": not issues, "qualified_primary_cost_comparison": result["qualified_primary_cost_comparison"],
        "original_reporter_completed_comparable_graphs": result["original_reporter_completed_comparable_graphs"],
        "audit_sha256": sha((args.output / "audit.json").read_bytes()), "output": str(args.output)}))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
