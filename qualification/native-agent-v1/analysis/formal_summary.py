#!/usr/bin/env python3
"""Read REPORT.json and adjacent model captures; never launch or modify a lane.

Usage: python formal_summary.py RUN1/REPORT.json ... RUN6/REPORT.json
       python formal_summary.py --format markdown RUN*/REPORT.json
An optional --model-dir REPORT=DIR overrides one report's adjacent model/ folder.
Missing evidence is the literal "unknown", never zero or a substitute RSS peak.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys


UNKNOWN = "unknown"
MODEL = "qwen38-flash-next-uc"
LANES = ("app-server", "facade", "native")
MODES = ("replay", "live")
MAX_REQUEST_BYTES = 65536
MAX_OUTPUT_TOKENS = 256
MAX_MODEL_CALLS = 4
MAX_TOOL_CALLS = 3
CAPTURE_NAME = re.compile(r"^(?P<case>[^/\\]+)-model-(?P<call>\d+)\.(?P<kind>request\.json|response\.sse)$")
USAGE_PATHS = {
    "input_tokens": ("input_tokens",),
    "output_tokens": ("output_tokens",),
    "total_tokens": ("total_tokens",),
    "cached_input_tokens": ("input_tokens_details", "cached_tokens"),
    "reasoning_output_tokens": ("output_tokens_details", "reasoning_tokens"),
}
FIELD_MAP = {
    "correct_denominator": "planned_cases[warmup=false]; attempted/unrun remain separate",
    "correctness": "rows.correct plus completed status, exact stdout, one tool, final feedback audit and model_capture_complete",
    "completed_latency": "rows[warmup=false, no error, result.status=completed].wall_ms; incorrect completed rows are counted separately",
    "benchmark_summary_latency": "summary.wall_ms uses measured rows without error; it is NOT a correct-only latency",
    "startup_shutdown": "startup_ms / shutdown_ms, separate from case latency; shutdown is not proof of graceful exit",
    "resource_window": "metrics.elapsed_seconds; whole lane includes startup, warmup, observer and shutdown",
    "primary_memory": "metrics.memory.pss_peak_complete_sample_bytes with complete/incomplete samples, sampling gaps and coverage",
    "secondary_memory": "RSS and partial PSS are diagnostics only; no cgroup lifetime peak is used",
    "cpu": "metrics.cpu.cgroup_nonoverlap_observed_seconds and process_lifecycle_observed_seconds separately; never add or divide by measured case count",
    "model_usage": "adjacent model/*.response.sse response.completed.usage; result.usage is not a fallback",
    "request_budget": "actual *.request.json bytes/model/max_output_tokens plus gateway record effective hash/cap",
    "response_budget": "captured response.completed.usage.output_tokens <= 256, unknown when absent",
    "model_identity": "advertised request model only; provider weights/deployment pin remains unknown",
}
LIMITATIONS = [
    "Whole-lane CPU/memory includes startup, warmup, observer and shutdown; it is not steady-state per-case cost.",
    "PSS completeness describes observed selected scopes, not global coverage; sampled peaks are lower bounds.",
    "Cgroup memory.peak is cumulative lifetime high-water and is deliberately excluded.",
    "Process CPU, cgroup CPU, waited-child CPU and observer CPU overlap; they must not be added.",
    "Live upstream model compute/memory and some loopback SSH/control-plane work are outside measured scopes.",
    "Replay usage is synthetic and must not be presented as actual token consumption.",
    "Small sequential samples, caches and changing host/provider load do not establish stable superiority.",
    "No normal benchmark result proves original-operation recovery; that needs separate fault evidence.",
    "Captured model-call counts cover admitted requests; attempts rejected before gateway recording are not an exhaustive HTTP attempt log.",
]


def value(obj, *path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return UNKNOWN
        obj = obj[key]
    return UNKNOWN if obj is None else obj


def number(obj):
    return type(obj) in (int, float) and math.isfinite(obj) and obj >= 0


def integer(obj):
    return type(obj) is int and obj >= 0


def known_number(obj):
    return obj if number(obj) else UNKNOWN


def boolean(obj):
    return obj if type(obj) is bool else UNKNOWN


def all_known(checks):
    checks = list(checks)
    if any(check is False for check in checks):
        return False
    return True if checks and all(check is True for check in checks) else UNKNOWN


def at_most(obj, maximum, minimum=0):
    return minimum <= obj <= maximum if type(obj) in (int, float) and math.isfinite(obj) else UNKNOWN


def json_object(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = val
    return result


def decode(raw):
    def invalid_constant(token):
        raise ValueError(f"non-finite JSON constant: {token}")
    return json.loads(raw, object_pairs_hook=json_object, parse_constant=invalid_constant)


def read_bytes(path, limit):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"evidence exceeds read limit ({limit} bytes)")
    return raw


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def quantiles(values):
    known = sorted(item for item in values if number(item))
    if not known:
        return {"n_known": 0, "n_unknown": len(values), "median": UNKNOWN, "p95_nearest_rank": UNKNOWN}
    return {"n_known": len(known), "n_unknown": len(values) - len(known),
            "median": statistics.median(known), "p95_nearest_rank": known[math.ceil(.95 * len(known)) - 1],
            "min": known[0], "max": known[-1]}


def sse_capture(path):
    result = {"file": str(path), "available": False, "usage": UNKNOWN, "response_id": UNKNOWN,
              "completed": UNKNOWN, "model_tool_call_ids": UNKNOWN, "errors": []}
    try:
        raw = read_bytes(path, 4 * 1024 * 1024)
        result.update(available=True, bytes=len(raw), sha256=digest(raw))
        completed, created, calls, data = {}, set(), set(), []
        for line in raw.decode("utf-8").splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line and data:
                payload, data = "\n".join(data), []
                if payload == "[DONE]":
                    continue
                event = decode(payload)
                if not isinstance(event, dict):
                    raise ValueError("SSE data is not an object")
                kind = event.get("type")
                items = []
                if kind == "response.created":
                    response_id = value(event, "response", "id")
                    if isinstance(response_id, str) and response_id != UNKNOWN:
                        created.add(response_id)
                elif kind == "response.completed":
                    response = event.get("response")
                    response_id = value(event, "response", "id")
                    if not isinstance(response, dict) or not isinstance(response_id, str) or response_id == UNKNOWN:
                        raise ValueError("completed response identity is missing")
                    if response_id in completed and completed[response_id] != response:
                        raise ValueError("conflicting duplicate completion")
                    completed[response_id] = response
                    items = response.get("output", [])
                elif kind == "response.output_item.done":
                    items = [event.get("item")]
                elif kind in ("error", "response.failed", "response.incomplete"):
                    result["errors"].append(f"terminal failure event: {kind}")
                if isinstance(items, list):
                    calls.update(item["call_id"] for item in items if isinstance(item, dict)
                                 and item.get("type") == "function_call" and isinstance(item.get("call_id"), str))
        if len(completed) != 1:
            raise ValueError(f"expected one original completed response, observed {len(completed)}")
        response_id, response = next(iter(completed.items()))
        if created and created != {response_id}:
            raise ValueError("created/completed response identities differ")
        if response.get("status", "completed") != "completed" or result["errors"]:
            raise ValueError("capture does not prove successful original completion")
        result.update(completed=True, response_id=response_id, model_tool_call_ids=sorted(calls))
        usage = response.get("usage")
        if isinstance(usage, dict):
            result["usage"] = {field: (val if integer(val := value(usage, *keys)) else UNKNOWN)
                               for field, keys in USAGE_PATHS.items()}
            main = [result["usage"][key] for key in ("input_tokens", "output_tokens", "total_tokens")]
            if all(integer(item) for item in main) and main[0] + main[1] != main[2]:
                result["errors"].append("reported input/output/total token counts disagree")
                result["usage"]["total_tokens"] = UNKNOWN
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as error:
        result["errors"].append(str(error))
        result["usage"] = UNKNOWN
    return result


def audit_call(entry, model_dir):
    case, call, record = entry["case"], entry["call"], entry.get("record", {})
    prefix = f"{case}-model-{call:02}"
    request_path = model_dir / entry.get("request_file", prefix + ".request.json")
    response_path = model_dir / entry.get("response_file", prefix + ".response.sse")
    result = {"case": case, "call": call, "gateway_record_present": bool(record), "errors": [],
              "request_file": str(request_path), "request_bytes": UNKNOWN, "actual_model": UNKNOWN,
              "actual_max_output_tokens": UNKNOWN, "requested_cap_within_256": UNKNOWN,
              "effective_cap_from_gateway": value(record, "output_token_cap"),
              "effective_request_hash_verified": UNKNOWN, "request_hash_matches_record": UNKNOWN,
              "request_bytes_within_65536": UNKNOWN, "advertised_model_matches": UNKNOWN,
              "effective_request_bytes_verified_within_65536": UNKNOWN,
              "actual_only_shared_tool_inventory": UNKNOWN,
              "effective_cap_verified_within_256": UNKNOWN}
    try:
        raw = read_bytes(request_path, 2 * 1024 * 1024)
        body = decode(raw)
        if not isinstance(body, dict):
            raise ValueError("request capture is not a JSON object")
        actual_cap = value(body, "max_output_tokens")
        actual_model = value(body, "model")
        tools = body.get("tools", [])
        inventory = [{"type": tool.get("type"), "name": tool.get("name"), "namespace": tool.get("namespace")}
                     for tool in tools] if isinstance(tools, list) and all(isinstance(tool, dict) for tool in tools) else UNKNOWN
        result.update(request_bytes=len(raw), request_sha256=digest(raw), actual_model=actual_model,
                      actual_max_output_tokens=actual_cap, requested_cap_within_256=at_most(actual_cap, 256, 1),
                      request_bytes_within_65536=len(raw) <= MAX_REQUEST_BYTES,
                      advertised_model_matches=(actual_model == MODEL if actual_model != UNKNOWN else UNKNOWN),
                      actual_only_shared_tool_inventory=inventory == [{"type": "function", "name": "hepta_probe", "namespace": None}],
                      actual_model_visible_options={"store": value(body, "store"), "reasoning": value(body, "reasoning"),
                          "parallel_tool_calls": value(body, "parallel_tool_calls"),
                          "tool_strict": [value(tool, "strict") for tool in tools] if isinstance(tools, list) else UNKNOWN})
        if value(record, "request_sha256") != UNKNOWN:
            result["request_hash_matches_record"] = digest(raw) == record["request_sha256"]
        # This reconstructs the documented gateway transform and verifies its recorded hash.
        # It never replaces the raw request's missing max_output_tokens field with an assumed value.
        effective = dict(body)
        effective["max_output_tokens"] = min(int(body.get("max_output_tokens", 256)), 256)
        effective_raw = json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if value(record, "effective_sha256") != UNKNOWN:
            verified = digest(effective_raw) == record["effective_sha256"] and len(effective_raw) == value(record, "effective_bytes")
            result["effective_request_hash_verified"] = verified
            result["effective_request_bytes_verified_within_65536"] = verified and len(effective_raw) <= MAX_REQUEST_BYTES
            result["effective_cap_verified_within_256"] = all_known([
                verified, effective["max_output_tokens"] == value(record, "output_token_cap"),
                at_most(value(record, "output_token_cap"), MAX_OUTPUT_TOKENS, 1)])
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as error:
        result["errors"].append(str(error))
    response = sse_capture(response_path)
    result["response"] = response
    result["response_bytes_match_record"] = (response.get("bytes") == record["response_bytes"]
        if "bytes" in response and number(value(record, "response_bytes")) else UNKNOWN)
    result["completed_output_tokens_within_256"] = at_most(value(response, "usage", "output_tokens"), MAX_OUTPUT_TOKENS)
    return result


def collect_calls(report, model_dir, issues):
    entries = {}
    def entry(case, call):
        if not isinstance(case, str) or not case or case == UNKNOWN or "/" in case or "\\" in case or not integer(call) or call < 1:
            issues.append("invalid model-request case/call identity")
            return None
        return entries.setdefault((case, call), {"case": case, "call": call})
    rows = report.get("rows", [])
    for row in rows if isinstance(rows, list) else []:
        records = value(row, "model_requests")
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    issues.append("invalid model_requests row")
                    continue
                item = entry(value(record, "case"), value(record, "call"))
                if item is not None:
                    if "record" in item:
                        issues.append(f"duplicate gateway model record: {item['case']}/{item['call']}")
                    item["record"] = record
                    if value(row, "name") != item["case"]:
                        issues.append("gateway record attached to a different case")
    filenames = []
    inventory = report.get("model_inventory", [])
    if isinstance(inventory, list):
        filenames.extend(value(item, "file") for item in inventory)
    if model_dir.is_dir():
        filenames.extend(path.name for pattern in ("*.request.json", "*.response.sse") for path in model_dir.glob(pattern))
    for name in filenames:
        match = CAPTURE_NAME.fullmatch(name) if isinstance(name, str) else None
        if not match:
            issues.append(f"unrecognized model capture name: {name}")
            continue
        item = entry(match["case"], int(match["call"]))
        if item is not None:
            item["request_file" if match["kind"] == "request.json" else "response_file"] = name
    return [audit_call(item, model_dir) for _, item in sorted(entries.items())]


def usage_summary(calls, mode, catalog_complete):
    fields = {}
    for field in USAGE_PATHS:
        values = [value(call, "response", "usage", field) for call in calls]
        known = [item for item in values if integer(item)]
        fields[field] = {"sum": sum(known) if calls and len(known) == len(calls) and catalog_complete is True else UNKNOWN,
                         "known_partial_sum": sum(known) if known else UNKNOWN,
                         "known_requests": len(known), "unknown_requests": len(calls) - len(known)}
    return {"kind": "synthetic_replay_fixture" if mode == "replay" else "provider_reported_captured_usage",
            "catalogued_requests": len(calls), "tokens": fields,
            "catalog_complete": catalog_complete,
            "captured_provider_primary_usage_complete": mode == "live" and bool(calls) and catalog_complete is True
                and all(fields[field]["unknown_requests"] == 0 for field in ("input_tokens", "output_tokens", "total_tokens"))
                and all(not call["response"]["errors"] for call in calls),
            "scope": "provider-reported usage in catalogued captures only; not unobserved provider work or billing",
            "uncaptured_provider_work": UNKNOWN,
            "result_usage_fallback_used": False}


def row_success(row, report):
    return all_known([boolean(value(row, "correct")), "error" not in row,
        value(row, "result", "status") == "completed" if value(row, "result", "status") != UNKNOWN else UNKNOWN,
        boolean(value(row, "answer_matches_exact_stdout_json")),
        value(row, "result", "tool_calls") == 1 if integer(value(row, "result", "tool_calls")) else UNKNOWN,
        boolean(value(row, "tool_feedback_audit", "valid")), boolean(value(report, "model_capture_complete")),
        not row["correctness_pending_tool_audit"] if type(value(row, "correctness_pending_tool_audit")) is bool else UNKNOWN])


def rates(correct, unknown, planned, attempted):
    return {"correct": correct, "correctness_unknown": unknown, "planned": planned, "attempted": attempted,
            "correct_over_planned": correct / planned if integer(planned) and planned > 0 and unknown == 0 else UNKNOWN,
            "correct_over_attempted": correct / attempted if attempted > 0 and unknown == 0 else UNKNOWN}


def memory_cpu(report, issues):
    metrics = value(report, "metrics")
    peak = known_number(value(metrics, "memory", "pss_peak_complete_sample_bytes"))
    complete = value(metrics, "memory", "pss_complete_samples")
    incomplete = value(metrics, "memory", "pss_incomplete_samples")
    samples = value(metrics, "sampling", "samples")
    if integer(complete) and complete == 0 and peak != UNKNOWN:
        issues.append("complete-sample PSS peak exists but complete sample count is zero")
        peak = UNKNOWN
    if integer(complete) and integer(incomplete) and integer(samples) and complete + incomplete != samples:
        issues.append("PSS complete/incomplete sample counts do not match sampler count")
    fraction = complete / (complete + incomplete) if integer(complete) and integer(incomplete) and complete + incomplete else UNKNOWN
    paths = value(metrics, "cpu", "cgroup_nonoverlap_paths")
    nonoverlap = UNKNOWN
    if isinstance(paths, list) and all(isinstance(path, str) and path.startswith("/") for path in paths):
        nonoverlap = len(set(paths)) == len(paths) and not any(
            a != b and a.startswith(b.rstrip("/") + "/") for a in paths for b in paths)
        if not nonoverlap:
            issues.append("reported cgroup aggregate paths overlap; aggregate excluded")
    group_cpu = known_number(value(metrics, "cpu", "cgroup_nonoverlap_observed_seconds"))
    return {"window_seconds": known_number(value(metrics, "elapsed_seconds")),
        "memory": {"primary_metric": "pss_peak_complete_sample_bytes", "primary_peak_bytes": peak,
            "primary_peak_mib": peak / 1048576 if number(peak) else UNKNOWN,
            "pss_complete_samples": complete, "pss_incomplete_samples": incomplete,
            "pss_complete_fraction": fraction, "sampling_samples": samples,
            "rss_peak_sum_bytes_diagnostic_only": known_number(value(metrics, "memory", "rss_peak_sum_bytes")),
            "partial_pss_peak_bytes_diagnostic_only": known_number(value(metrics, "memory", "pss_peak_observed_partial_bytes")),
            "cgroup_lifetime_memory_peak_used": False, "sampled_lower_bound": True},
        "cpu": {"cgroup_nonoverlap_observed_seconds": group_cpu if nonoverlap is not False else UNKNOWN,
            "process_lifecycle_observed_seconds": known_number(value(metrics, "cpu", "process_lifecycle_observed_seconds")),
            "cgroup_nonoverlap_paths": paths, "paths_verified_nonoverlapping": nonoverlap,
            "totals_overlap_do_not_add": True, "per_measured_case_cpu": UNKNOWN},
        "sampling": value(metrics, "sampling"), "coverage": value(metrics, "coverage"),
        "cgroup_coverage": [{key: value(group, key) for key in ("path", "baseline", "first_seen_seconds",
            "cpu_counter_reset", "cpu_available_last_sample", "cpu_before_first_observation_missing",
            "exit_cpu_endpoint_missing", "errors")} for group in metrics.get("cgroups", [])]
            if isinstance(metrics, dict) and isinstance(metrics.get("cgroups"), list) else UNKNOWN,
        "runtime_discovery_errors": value(report, "runtime_discovery_errors"),
        "detached_runtime_jobs": value(report, "detached_runtime_jobs")}


def summarize(path, model_dir):
    raw = read_bytes(path, 64 * 1024 * 1024)
    report = decode(raw)
    if not isinstance(report, dict):
        raise ValueError("REPORT is not an object")
    issues = []
    mode, lane = value(report, "mode"), value(report, "lane")
    if not isinstance(mode, str) or not isinstance(lane, str):
        raise ValueError("lane/mode must be strings")
    if mode not in MODES or lane not in LANES or value(report, "schema") != "hepta.native.qualification.benchmark.v1":
        issues.append("unknown report schema, mode or lane")
    rows = report.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("rows must be a list of case objects")
    plan = report.get("planned_cases")
    plan_valid = isinstance(plan, list) and all(isinstance(item, dict) and type(item.get("warmup")) is bool
        and isinstance(item.get("name"), str) and isinstance(item.get("task"), str) for item in plan)
    plan_names = [item["name"] for item in plan] if plan_valid else []
    row_names = [value(row, "name") for row in rows]
    if len(set(row_names)) != len(row_names) or (plan_valid and len(set(plan_names)) != len(plan_names)):
        issues.append("duplicate case name in plan or rows")
        plan_valid = False
    details = [{"name": value(row, "name"), "task": value(row, "task"), "warmup": value(row, "warmup"),
        "correct": row_success(row, report), "reported_correct": value(row, "correct"),
        "completed": False if "error" in row else (value(row, "result", "status") == "completed"
            if value(row, "result", "status") != UNKNOWN else UNKNOWN),
        "wall_ms": known_number(value(row, "wall_ms")), "error": value(row, "error"),
        "feedback_valid": boolean(value(row, "tool_feedback_audit", "valid")),
        "tool_calls": value(row, "result", "tool_calls"), "requires_process_reset": value(row, "requires_process_reset")}
        for row in rows]
    measured = [item for item in details if item["warmup"] is False]
    warmup = [item for item in details if item["warmup"] is True]
    if len(measured) + len(warmup) != len(rows):
        issues.append("case warmup classification missing/invalid")
    for row in details:
        if row["reported_correct"] is True and row["correct"] is not True:
            issues.append(f"reported correct is not supported by final evidence: {row['name']}")
    measured_plan = [item for item in plan if item["warmup"] is False] if plan_valid else None
    warmup_plan = [item for item in plan if item["warmup"] is True] if plan_valid else None
    expected_repeats = 3 if mode == "replay" else 2 if mode == "live" else None
    formal_plan = (len(measured_plan) == 3 * expected_repeats and len(warmup_plan) == 1
        and warmup_plan[0]["task"] == "sum"
        and plan[0]["warmup"] is True
        and [item["task"] for item in plan] == ["sum"] + ["sum", "lines", "digest"] * expected_repeats
        and Counter(item["task"] for item in measured_plan) == {task: expected_repeats for task in ("sum", "lines", "digest")}) if plan_valid and expected_repeats else UNKNOWN
    unrun = [item for item in plan if item["name"] not in row_names] if plan_valid else UNKNOWN
    extras = [name for name in row_names if name not in plan_names] if plan_valid else UNKNOWN
    if plan_valid:
        expected_rows = {item["name"]: item for item in plan}
        for row in details:
            planned = expected_rows.get(row["name"])
            if not planned or (row["task"], row["warmup"]) != (planned["task"], planned["warmup"]):
                issues.append(f"row disagrees with plan: {row['name']}")
    calls = collect_calls(report, model_dir, issues)
    records_complete = all(isinstance(value(row, "model_requests"), list) for row in rows)
    record_count = sum(len(row["model_requests"]) for row in rows) if records_complete else UNKNOWN
    catalog_complete = all_known([boolean(value(report, "model_capture_complete")),
        True if model_dir.is_dir() else UNKNOWN,
        len(calls) == record_count if integer(record_count) else UNKNOWN,
        all_known(call["gateway_record_present"] and call["request_hash_matches_record"] is True
            and call["response_bytes_match_record"] is True for call in calls) if model_dir.is_dir() else UNKNOWN])
    measured_names, warmup_names = {item["name"] for item in measured}, {item["name"] for item in warmup}
    known_names = measured_names | warmup_names
    case_calls = {name: [call for call in calls if call["case"] == name] for name in known_names}
    budget_by_case = []
    for row, detail in zip(rows, details):
        records = value(row, "model_requests")
        captured = case_calls.get(detail["name"], [])
        raw_complete = bool(captured) and all(number(call["request_bytes"]) for call in captured)
        generated_ids = [value(call, "response", "model_tool_call_ids") for call in captured]
        # Deduplicate done/completed projections within each response, not actions across responses.
        generated_count = sum(len(ids) for ids in generated_ids) if captured and all(isinstance(ids, list) for ids in generated_ids) else UNKNOWN
        budget_by_case.append({"name": detail["name"], "warmup": detail["warmup"],
            "recorded_model_calls": len(records) if isinstance(records, list) else UNKNOWN,
            "catalogued_model_calls": len(captured),
            "actual_captured_model_calls": len(captured) if raw_complete else UNKNOWN,
            "recorded_model_call_budget": at_most(len(records), MAX_MODEL_CALLS) if isinstance(records, list) else UNKNOWN,
            "captured_model_call_budget": at_most(len(captured), MAX_MODEL_CALLS) if raw_complete else UNKNOWN,
            "captured_generated_tool_calls": generated_count,
            "generated_tool_call_budget": at_most(generated_count, MAX_TOOL_CALLS),
            "executor_tool_calls": detail["tool_calls"], "executor_tool_call_budget": at_most(detail["tool_calls"], MAX_TOOL_CALLS)})
    completed = [item for item in measured if item["completed"] is True]
    count = lambda items, state: sum(item["correct"] is state for item in items)
    result = {"report": str(path), "report_sha256": digest(raw), "mode": mode, "lane": lane,
        "schema": value(report, "schema"), "issues": issues,
        "timing": {"startup_ms": known_number(value(report, "startup_ms")), "shutdown_ms": known_number(value(report, "shutdown_ms")),
            "measured_completed_rows_wall_ms": quantiles([item["wall_ms"] for item in completed]),
            "measured_correct_rows_wall_ms_diagnostic": quantiles([item["wall_ms"] for item in measured if item["correct"] is True]),
            "measured_attempted_rows_wall_ms": quantiles([item["wall_ms"] for item in measured]),
            "reported_summary_wall_ms": value(report, "summary", "wall_ms"),
            "measurement_windows": value(report, "measurement_windows"), "shutdown_errors": value(report, "shutdown_errors")},
        "cases": {"plan": plan if plan_valid else UNKNOWN,
            "measured": rates(count(measured, True), sum(item["correct"] == UNKNOWN for item in measured),
                len(measured_plan) if measured_plan is not None else UNKNOWN, len(measured)),
            "warmup": rates(count(warmup, True), sum(item["correct"] == UNKNOWN for item in warmup),
                len(warmup_plan) if warmup_plan is not None else UNKNOWN, len(warmup)),
            "completed_measured": len(completed), "completed_measured_incorrect": count(completed, False),
            "completed_measured_correctness_unknown": sum(item["correct"] == UNKNOWN for item in completed),
            "completion_status_unknown": sum(item["completed"] == UNKNOWN for item in measured),
            "unrun": unrun, "unplanned_rows": extras, "details": details},
        "gates": {"formal_plan_matches": formal_plan, "reported_qualification_passed": boolean(value(report, "summary", "qualification_passed")),
            "reported_completed_lane": boolean(value(report, "summary", "completed_lane")),
            "reported_equal_tool_comparison": boolean(value(report, "summary", "valid_equal_tool_comparison")),
            "only_shared_tool_inventory": boolean(value(report, "only_shared_tool_inventory")),
            "model_capture_complete": boolean(value(report, "model_capture_complete"))},
        "resources": memory_cpu(report, issues),
        "model": {"advertised_model": value(report, "model"), "provider_weight_or_deployment_pin": UNKNOWN,
            "capture_directory": str(model_dir), "capture_directory_available": model_dir.is_dir(),
            "measured_usage": usage_summary([call for call in calls if call["case"] in measured_names], mode, catalog_complete),
            "warmup_usage": usage_summary([call for call in calls if call["case"] in warmup_names], mode, catalog_complete),
            "all_catalogued_usage": usage_summary(calls, mode, catalog_complete),
            "unattributed_calls": [call for call in calls if call["case"] not in known_names],
            "calls": calls, "case_budgets": budget_by_case, "inventory": value(report, "model_inventory")},
        "provenance": {key: value(report, key) for key in ("started_ns", "finished_ns", "platform", "cpu_count",
            "executor_sha256", "runtime_helper_sha256", "fixture", "budgets", "case_timeout_seconds", "resource_limits")}}
    result["provenance"].update(source_revision_in_REPORT=UNKNOWN, compiler_identity_in_REPORT=UNKNOWN)
    for key in ("request_bytes_within_65536", "requested_cap_within_256", "advertised_model_matches",
                "effective_cap_verified_within_256", "completed_output_tokens_within_256",
                "effective_request_bytes_verified_within_65536", "actual_only_shared_tool_inventory"):
        result["gates"][key] = all_known(call[key] for call in calls)
    for key in ("recorded_model_call_budget", "captured_model_call_budget", "executor_tool_call_budget", "generated_tool_call_budget"):
        result["gates"][key] = all_known(item[key] for item in budget_by_case)
    for name, computed in (("planned", len(measured_plan) if measured_plan is not None else UNKNOWN),
                           ("attempted", len(measured)), ("correct", count(measured, True))):
        reported = value(report, "summary", name)
        if integer(reported) and integer(computed) and reported != computed:
            issues.append(f"summary.{name} differs from audited rows/plan ({reported} vs {computed})")
    result["gates"]["reported_success_and_full_plan_verified"] = all_known([
        result["gates"]["reported_qualification_passed"], formal_plan, not unrun if isinstance(unrun, list) else UNKNOWN,
        not extras if isinstance(extras, list) else UNKNOWN, all_known(item["correct"] for item in details), not issues])
    result["gates"]["full_capture_budget_evidence_verified"] = all_known([catalog_complete,
        result["gates"]["request_bytes_within_65536"], result["gates"]["advertised_model_matches"],
        result["gates"]["effective_request_bytes_verified_within_65536"], result["gates"]["actual_only_shared_tool_inventory"],
        result["gates"]["effective_cap_verified_within_256"], result["gates"]["completed_output_tokens_within_256"],
        result["gates"]["captured_model_call_budget"], result["gates"]["executor_tool_call_budget"],
        result["gates"]["generated_tool_call_budget"]])
    return result


def equal_field(reports, *path):
    values = [value(report, *path) for report in reports]
    if len(values) < 2 or any(item == UNKNOWN or (isinstance(item, dict) and "unavailable" in item) for item in values):
        return UNKNOWN
    return all(item == values[0] for item in values)


def display(item, digits=2):
    if number(item):
        return f"{item:.{digits}f}"
    return str(item)


def markdown(bundle):
    lines = ["# Formal resident-lane summary", "", "Memory is sampled complete-scope PSS; CPU columns overlap and must not be added.", "",
        "| Mode / lane | Correct / planned (attempted; correctness unknown) | Warmup correct / planned (unknown) | Measured completed rows median / p95 ms (known / completed n) | Completed incorrect | Startup / shutdown ms | PSS MiB (complete / incomplete samples) | Cgroup CPU s | Process CPU s | Live measured input / output / total tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for report in bundle["reports"]:
        cases, timing, resources = report["cases"], report["timing"], report["resources"]
        measured, warmup = cases["measured"], cases["warmup"]
        latency, memory, cpu = timing["measured_completed_rows_wall_ms"], resources["memory"], resources["cpu"]
        usage = report["model"]["measured_usage"]["tokens"]
        token_text = "synthetic replay; not actual consumption" if report["mode"] == "replay" else " / ".join(str(usage[key]["sum"]) for key in ("input_tokens", "output_tokens", "total_tokens"))
        fields = [f"{report['mode']} / {report['lane']}", f"{measured['correct']} / {measured['planned']} ({measured['attempted']}; {measured['correctness_unknown']})",
            f"{warmup['correct']} / {warmup['planned']} ({warmup['correctness_unknown']})", f"{display(latency['median'])} / {display(latency['p95_nearest_rank'])} ({latency['n_known']} / {latency['n_known'] + latency['n_unknown']})",
            str(cases["completed_measured_incorrect"]), f"{display(timing['startup_ms'])} / {display(timing['shutdown_ms'])}",
            f"{display(memory['primary_peak_mib'])} ({memory['pss_complete_samples']} / {memory['pss_incomplete_samples']})",
            display(cpu["cgroup_nonoverlap_observed_seconds"]), display(cpu["process_lifecycle_observed_seconds"]), token_text]
        lines.append("| " + " | ".join(fields) + " |")
    lines.extend(["", "## Gates and coverage", ""])
    for report in bundle["reports"]:
        lines.append(f"### {report['mode']} / {report['lane']}")
        lines.append("")
        for name, data in (("Gates", report["gates"]), ("Sampling", report["resources"]["sampling"]),
                           ("Coverage", report["resources"]["coverage"]), ("Issues", report["issues"])):
            lines.append(f"- {name}: `{json.dumps(data, ensure_ascii=False, sort_keys=True)}`")
        lines.append("")
    lines.extend(["## Comparison checks", "", "```json", json.dumps(bundle["comparison_checks"], ensure_ascii=False, indent=2), "```", "", "## Limits", ""])
    lines.extend("- " + item for item in LIMITATIONS)
    if bundle["input_errors"]:
        lines.extend(["", "## Input errors", "", "```json", json.dumps(bundle["input_errors"], indent=2), "```"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--model-dir", action="append", default=[], metavar="REPORT=DIR")
    args = parser.parse_args(argv)
    overrides = {}
    for mapping in args.model_dir:
        source, sep, target = mapping.partition("=")
        if not sep or not source or not target:
            parser.error("--model-dir requires REPORT=DIR")
        overrides[str(Path(source).resolve())] = Path(target).resolve()
    reports, errors = [], []
    for path in args.reports:
        path = path.resolve()
        try:
            reports.append(summarize(path, overrides.get(str(path), path.parent / "model")))
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append({"report": str(path), "error": str(error)})
    reports.sort(key=lambda row: (row["mode"], row["lane"], row["report"]))
    matrix = Counter((report["mode"], report["lane"]) for report in reports)
    comparisons = {"six_unique_formal_lanes_present": matrix == Counter((mode, lane) for mode in MODES for lane in LANES),
        "missing_lanes": [[mode, lane] for mode in MODES for lane in LANES if (mode, lane) not in matrix],
        "duplicate_lanes": [[mode, lane, count] for (mode, lane), count in matrix.items() if count > 1],
        "same_helper_binary": equal_field(reports, "provenance", "runtime_helper_sha256"),
        "same_fixture_script": equal_field(reports, "provenance", "fixture", "script_sha256"),
        "same_fixture_data": equal_field(reports, "provenance", "fixture", "data_sha256"),
        "same_budget_ceilings": equal_field(reports, "provenance", "budgets"),
        "same_case_timeout": equal_field(reports, "provenance", "case_timeout_seconds"),
        "same_advertised_model": equal_field(reports, "model", "advertised_model"),
        "same_provider_weights": UNKNOWN, "same_source_and_compiler_requires_external_manifest": UNKNOWN,
        "same_executor_across_modes": {lane: equal_field([report for report in reports if report["lane"] == lane],
            "provenance", "executor_sha256") for lane in LANES},
        "same_case_order_per_mode": {mode: equal_field([report for report in reports if report["mode"] == mode],
            "cases", "plan") for mode in MODES},
        "model_visible_options_require_inventory_review": True,
        "resource_cap_checks": {key: equal_field(reports, "provenance", "resource_limits", key)
            for key in ("cpu.max", "cpu.weight", "memory.max", "cpuset.cpus.effective", "affinity_cpus")},
        "run_order": [{key: value(report, "provenance", key) for key in ("started_ns", "finished_ns")}
            | {"mode": report["mode"], "lane": report["lane"]} for report in sorted(reports,
                key=lambda row: value(row, "provenance", "started_ns") if integer(value(row, "provenance", "started_ns")) else 0)]}
    bundle = {"schema": "hepta.native.qualification.formal-summary.v1", "field_map": FIELD_MAP,
              "reports": reports, "comparison_checks": comparisons, "input_errors": errors, "limitations": LIMITATIONS}
    print(markdown(bundle) if args.format == "markdown" else json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2), end="" if args.format == "markdown" else "\n")
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
