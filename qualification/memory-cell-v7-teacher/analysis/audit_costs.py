#!/usr/bin/env python3
"""Post hoc, offline cost audit. Never imports or executes a frozen candidate.

Reads original RUN/admission/body/result/SSE bytes. Writes only a fresh output
directory. A recorded token subtotal is not a bill or an estimate of missing
usage. No labels, prompt text, user text, or model text are copied to output.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys


RUN_NAMES = ("teacher-held-v1", "public-training-smoke-v1")
SERVING_FIELDS = {"utterance", "series_name", "date"}
TERMINALS = {"response.completed", "response.failed", "response.incomplete", "error"}
TOKEN_KEYS = ("input_tokens", "output_tokens", "total_tokens")
DETAIL_PATHS = {"cached_input_tokens": ("input_tokens_details", "cached_tokens", "input_tokens"),
                "reasoning_output_tokens": ("output_tokens_details", "reasoning_tokens", "output_tokens")}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def exact_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("nonfinite JSON number")


def decode(raw):
    return json.loads(raw, object_pairs_hook=exact_object,
                      parse_constant=reject_constant)


def token_view(value):
    """Keep all observations; only coherent nonnegative integer totals add up."""
    if value is None:
        return None, "missing"
    if not isinstance(value, dict):
        return None, "usage_not_object"
    for key in TOKEN_KEYS[:2]:
        if type(value.get(key)) is not int or value[key] < 0:
            return None, "invalid_" + key
    total = value["input_tokens"] + value["output_tokens"]
    if "total_tokens" in value:
        if type(value["total_tokens"]) is not int or value["total_tokens"] < 0:
            return None, "invalid_total_tokens"
        if value["total_tokens"] != total:
            return None, "total_differs_from_input_plus_output"
    return {"input_tokens": value["input_tokens"],
            "output_tokens": value["output_tokens"], "total_tokens": total}, None


def token_sum(values):
    result = dict.fromkeys(TOKEN_KEYS, 0)
    for value in values:
        if value is not None:
            for key in TOKEN_KEYS:
                result[key] += value[key]
    return result


def usage_metadata(value):
    """Optional counters remain components of their parent, never extra tokens."""
    partial = {key: value.get(key) if isinstance(value, dict)
               and type(value.get(key)) is int and value[key] >= 0 else None for key in TOKEN_KEYS}
    details, errors = {}, []
    for name, (section, field, parent) in DETAIL_PATHS.items():
        nested = value.get(section) if isinstance(value, dict) else None
        count = nested.get(field) if isinstance(nested, dict) else None
        if count is None:
            details[name] = None
        elif type(count) is not int or count < 0 or (partial[parent] is not None and count > partial[parent]):
            details[name] = None
            errors.append("invalid_" + name)
        else:
            details[name] = count
    return {"partial_token_counters": partial, "detail_counters": details,
            "detail_counter_errors": errors}


def nonempty_id(value):
    return value if isinstance(value, str) and value else None


def sse_observations(raw):
    """Inspect retained frames, including failed/incomplete terminal usage.

    This does not call the serving decoder or assign a semantic prediction.
    An unterminated frame is retained for audit but excluded from exact sums.
    Identical terminal frames are reported; usage is deduplicated separately.
    """
    normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    frames = normalized.split(b"\n\n")
    events, problems, created_ids = [], [], set()
    for number, frame in enumerate(frames):
        if not frame.strip():
            continue
        complete = number < len(frames) - 1
        parts = []
        for line in frame.split(b"\n"):
            if line.startswith(b"data:"):
                parts.append(line[5:].removeprefix(b" "))
        if not parts:
            continue
        payload = b"\n".join(parts)
        if payload == b"[DONE]":
            continue
        try:
            event = decode(payload)
            if not isinstance(event, dict):
                raise ValueError("event_not_object")
        except (ValueError, UnicodeDecodeError) as error:
            problems.append({"frame": number, "kind": "unparsed_frame",
                             "error_type": type(error).__name__,
                             "frame_sha256": sha(frame), "complete": complete})
            continue
        kind = event.get("type")
        response = event.get("response")
        response = response if isinstance(response, dict) else {}
        if kind == "response.created":
            identity = nonempty_id(response.get("id"))
            if identity and complete:
                created_ids.add(identity)
        events.append((number, complete, event, response, sha(canonical(event))))
        if not complete:
            problems.append({"frame": number, "kind": "unterminated_frame",
                             "frame_sha256": sha(frame)})

    observations, terminal_counts, terminal_hashes = [], Counter(), []
    dispatched_terminal_events = 0
    terminal_ids, terminal_statuses = set(), set()
    for number, complete, event, response, digest in events:
        kind = event.get("type")
        if kind not in TERMINALS:
            continue
        terminal_counts[kind] += 1
        dispatched_terminal_events += int(complete)
        terminal_hashes.append(digest)
        identity = nonempty_id(response.get("id")) or nonempty_id(event.get("response_id"))
        id_source = "terminal" if identity else None
        if not identity and len(created_ids) == 1:
            identity, id_source = next(iter(created_ids)), "sole_complete_created_event"
        if identity:
            terminal_ids.add(identity)
        if isinstance(response.get("status"), str):
            terminal_statuses.add(response["status"])
        provider_error = response.get("error") or event.get("error")
        provider_error_code = provider_error.get("code") if isinstance(provider_error, dict) else None
        provider_error_code = provider_error_code if isinstance(provider_error_code, str) else None
        entries = [("response.usage", response.get("usage"))]
        if "usage" in event:
            entries.append(("event.usage", event["usage"]))
        for location, usage in entries:
            counters, error = token_view(usage)
            observations.append({"source_kind": "sse_terminal", "frame": number,
                "event_type": kind, "terminal_event_sha256": digest,
                "provider_error_code": provider_error_code,
                "usage_location": location, "provider_response_id": identity,
                "response_id_source": id_source, "frame_complete": complete,
                "eligible_for_recorded_sum": complete, "usage": usage,
                "tokens": counters, "usage_error": error})
    return {"observations": observations, "created_ids": sorted(created_ids),
            "terminal_ids": sorted(terminal_ids), "terminal_statuses": sorted(terminal_statuses),
            "terminal_events": sum(terminal_counts.values()),
            "dispatched_terminal_events": dispatched_terminal_events,
            "terminal_counts": dict(terminal_counts),
            "duplicate_terminal_events": len(terminal_hashes) - len(set(terminal_hashes)),
            "problems": problems}


class Sources:
    def __init__(self, root):
        self.root = root
        self.records = {}

    def key(self, path):
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path.resolve())

    def read(self, path):
        key = self.key(path)
        if not path.is_file():
            self.records[key] = {"present": False}
            return None
        raw = path.read_bytes()
        record = {"present": True, "bytes": len(raw), "sha256": sha(raw)}
        if key in self.records and self.records[key] != record:
            raise ValueError("source changed during audit: " + key)
        self.records[key] = record
        return raw

    def json(self, path, problems):
        raw = self.read(path)
        if raw is None:
            return None
        try:
            value = decode(raw)
            if not isinstance(value, dict):
                raise ValueError("not_object")
            return value
        except (ValueError, UnicodeDecodeError) as error:
            problems.append({"file": self.key(path), "kind": "invalid_json_object",
                             "error_type": type(error).__name__})
            return None

    def verify_unchanged(self):
        changed = []
        for key, original in self.records.items():
            path = Path(key) if Path(key).is_absolute() else self.root / key
            now = ({"present": True, "bytes": path.stat().st_size,
                    "sha256": sha(path.read_bytes())} if path.is_file()
                   else {"present": False})
            if now != original:
                changed.append(key)
        return changed


def read_jsonl(sources, path, errors):
    raw = sources.read(path)
    if raw is None:
        return None, None
    rows = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        try:
            if not line:
                raise ValueError("empty_line")
            row = decode(line)
            if not isinstance(row, dict):
                raise ValueError("not_object")
            rows.append(row)
        except (ValueError, UnicodeDecodeError) as error:
            errors.append({"file": sources.key(path), "line": line_number,
                           "kind": "invalid_jsonl_row", "error_type": type(error).__name__,
                           "line_sha256": sha(line)})
            rows.append(None)
    return raw, rows


def audit_case(run_name, run, index, case_dir, input_rows, aggregate, sources):
    errors, unavailable, checks = [], [], {}

    def check(name, condition, available=True):
        checks[name] = "pass" if condition and available else "fail" if available else "unavailable"
        if not available:
            unavailable.append(name)
        elif not condition:
            errors.append({"kind": name})

    admission = sources.json(case_dir / "admission.json", errors)
    result = sources.json(case_dir / "result.json", errors)
    raw_body = sources.read(case_dir / "request.body.json")
    raw_response = sources.read(case_dir / "response.sse")
    body, request = None, None
    check("admission_present", admission is not None)
    check("request_body_present", raw_body is not None)
    check("result_present", result is not None, result is not None)
    if raw_body is not None:
        try:
            body = decode(raw_body)
            if not isinstance(body, dict):
                raise ValueError("body_not_object")
            check("body_canonical_bytes", raw_body == canonical(body))
            items = body["input"]
            if (not isinstance(items, list) or len(items) != 1 or items[0].get("role") != "user"
                    or len(items[0]["content"]) != 1
                    or items[0]["content"][0].get("type") != "input_text"):
                raise ValueError("unexpected_serving_input_shape")
            request_text = items[0]["content"][0]["text"]
            request = decode(request_text)
            check("serving_request_exact_fields", isinstance(request, dict)
                  and set(request) == SERVING_FIELDS
                  and all(isinstance(value, str) for value in request.values()))
            check("serving_request_canonical_text", request_text.encode("utf-8") == canonical(request))
            prompt = body.get("instructions")
            check("prompt_sha256_matches_run", isinstance(prompt, str)
                  and sha(prompt.encode("utf-8")) == run.get("prompt_sha256"),
                  "prompt_sha256" in run)
            check("body_model_matches_run", body.get("model") == run.get("model"))
        except (ValueError, UnicodeDecodeError, KeyError, TypeError, AttributeError) as error:
            errors.append({"kind": "body_decode_or_shape", "error_type": type(error).__name__})
    expected_operation, body_sha, request_sha = None, None, None
    if raw_body is not None:
        body_sha = sha(raw_body)
        try:
            expected_operation = "hepta-route-" + sha(canonical({"run_id": run["run_id"],
                "input_sha256": run["input_sha256"], "freeze_sha256": run["freeze_sha256"],
                "index": index, "body_sha256": body_sha}))
        except KeyError:
            errors.append({"kind": "run_missing_operation_identity_field"})
    if request is not None:
        request_sha = sha(canonical(request))
    if input_rows is not None:
        check("request_matches_original_input_index", 0 <= index < len(input_rows)
              and request == input_rows[index])
    else:
        check("request_matches_original_input_index", False, False)
    for name, record in (("admission", admission), ("result", result)):
        if record is None:
            continue
        check(name + "_index", type(record.get("index")) is int and record["index"] == index)
        check(name + "_operation_id", record.get("operation_id") == expected_operation,
              expected_operation is not None)
        check(name + "_body_sha256", record.get("body_sha256") == body_sha, body_sha is not None)
        check(name + "_request_sha256", record.get("request_sha256") == request_sha,
              request_sha is not None)
    if admission is not None:
        check("admission_submission_attempted", admission.get("submission_attempted") is True)
        check("admission_no_automatic_retry", admission.get("automatic_retry_allowed") is False)
        check("admission_model", admission.get("model") == run.get("model"))
        check("admission_endpoint", admission.get("endpoint") == run.get("endpoint"))
    if result is not None:
        check("result_no_automatic_retry", result.get("automatic_retries") == 0,
              "automatic_retries" in result)
        check("case_result_equals_aggregate_row", aggregate == result, aggregate is not None)
        if raw_response is not None:
            check("response_sha256", result.get("response_sha256") == sha(raw_response))
            check("response_bytes", result.get("response_bytes") == len(raw_response))
        else:
            check("response_sha256", False, False)
            if result.get("response_sha256"):
                errors.append({"kind": "recorded_response_hash_but_missing_response_file"})
            if result.get("response_bytes", 0) != 0:
                errors.append({"kind": "recorded_response_bytes_but_missing_response_file"})
    parsed = sse_observations(raw_response) if raw_response is not None else {
        "observations": [], "created_ids": [], "terminal_ids": [], "terminal_statuses": [],
        "terminal_events": 0, "dispatched_terminal_events": 0, "terminal_counts": {},
        "duplicate_terminal_events": 0, "problems": []}
    result = result or {}
    provider_id = nonempty_id(result.get("provider_response_id"))
    if provider_id and parsed["created_ids"]:
        check("result_provider_id_matches_created", parsed["created_ids"] == [provider_id])
    if provider_id and parsed["terminal_ids"]:
        check("result_provider_id_matches_terminal", parsed["terminal_ids"] == [provider_id])
    if len(parsed["created_ids"]) > 1 or len(parsed["terminal_ids"]) > 1:
        errors.append({"kind": "multiple_provider_response_ids_within_operation"})
    counters, usage_error = token_view(result.get("usage"))
    observations = [{"source_kind": "case_result", "provider_response_id": provider_id,
        "response_id_source": "case_result" if provider_id else None,
        "eligible_for_recorded_sum": True, "usage": result.get("usage"),
        "tokens": counters, "usage_error": usage_error}] + parsed.pop("observations")
    operation_id = nonempty_id(result.get("operation_id")) or (
        nonempty_id(admission.get("operation_id")) if admission else None) or expected_operation
    for observation in observations:
        observation.update({"run": run_name, "index": index, "operation_id": operation_id})
        observation.update(usage_metadata(observation["usage"]))
    case = {"run": run_name, "index": index, "operation_id": operation_id,
        "request_sha256": request_sha, "body_sha256": body_sha,
        "response_sha256": sha(raw_response) if raw_response is not None else None,
        "reported_status": result.get("status", "missing_result"),
        "reported_error_type": result.get("error_type"),
        "provider_response_id": provider_id, "result_usage": counters,
        "result_usage_error": usage_error, "sse": parsed,
        "binding_checks": checks, "verification_errors": errors,
        "unavailable_checks": unavailable, "request_recovered": request is not None}
    return case, observations, request


def resolve_usage(cases, observations):
    """One recorded total per response identity, never per duplicated event."""
    case_ids = defaultdict(set)
    for item in observations:
        if item.get("provider_response_id"):
            case_ids[(item["run"], item["index"])].add(item["provider_response_id"])
    groups = defaultdict(list)
    for item in observations:
        if item["tokens"] is None or not item["eligible_for_recorded_sum"]:
            continue
        identity = item.get("provider_response_id")
        ids = case_ids[(item["run"], item["index"])]
        if not identity and len(ids) == 1:
            identity = next(iter(ids))
            item["deduplication_identity_inferred_within_single_operation"] = True
        group_key = "response:" + identity if identity else (
            "operation:" + str(item["operation_id"]) + ":" + item["run"] + ":" + str(item["index"]))
        item["cost_group"] = group_key
        groups[group_key].append(item)
    resolved = {}
    for key, items in groups.items():
        values = sorted({tuple(item["tokens"][field] for field in TOKEN_KEYS) for item in items})
        owners = sorted({(item["run"], item["index"]) for item in items})
        detail_values = {name: sorted({item["detail_counters"][name] for item in items
                        if item["detail_counters"][name] is not None}) for name in DETAIL_PATHS}
        resolved[key] = {"cost_group": key,
            "resolution": "consistent_recorded_usage" if len(values) == 1 else "conflicting_recorded_usage",
            "tokens": dict(zip(TOKEN_KEYS, values[0])) if len(values) == 1 else None,
            "observed_alternatives": [dict(zip(TOKEN_KEYS, value)) for value in values],
            "observations": len(items), "case_refs": [{"run": run, "index": index} for run, index in owners],
            "cross_operation_identity_collision": len(owners) > 1,
            "has_result_usage": any(item["source_kind"] == "case_result" for item in items),
            "has_terminal_usage": any(item["source_kind"] == "sse_terminal" for item in items),
            "detail_counters": {name: counts[0] if len(counts) == 1 and len(values) == 1 else None
                                for name, counts in detail_values.items()},
            "detail_observed_alternatives": detail_values,
            "detail_conflicts": [name for name, counts in detail_values.items() if len(counts) > 1],
            "provider_response_identity_present": key.startswith("response:")}
    for case in cases:
        matching = [item for item in observations if (item["run"], item["index"]) == (case["run"], case["index"])]
        keys = sorted({item["cost_group"] for item in matching if "cost_group" in item})
        case["cost_groups"] = keys
        case["usage_observations"] = len(matching)
        case["usage_observations_with_counters"] = sum(item["tokens"] is not None for item in matching)
        case["classification"] = ("unknown_usage" if not keys else "conflicting_usage"
            if any(resolved[key]["tokens"] is None for key in keys) else "recorded_usage")
        if not keys and any(item["tokens"] is not None for item in matching):
            case["classification"] = "usage_only_in_undispatched_frame"
        case["recorded_tokens"] = (token_sum(resolved[key]["tokens"] for key in keys)
                                   if keys and all(resolved[key]["tokens"] is not None for key in keys) else None)
        case["semantic_status_reinterpreted"] = False
    return resolved


def summarize_cases(cases, observations, groups):
    result_items = [item for item in observations if item["source_kind"] == "case_result"]
    completed = {(case["run"], case["index"]) for case in cases if case["reported_status"] == "completed"}
    completed_items = [item for item in result_items if (item["run"], item["index"]) in completed]
    matching_keys = {key for case in cases for key in case["cost_groups"]}
    matching_groups = [groups[key] for key in sorted(matching_keys)]

    def summarize_result(items):
        known = [item["tokens"] for item in items if item["tokens"] is not None]
        return {"rows": len(items), "rows_with_usable_usage": len(known),
                "rows_without_usable_usage": len(items) - len(known),
                "recorded_token_sum": token_sum(known),
                "partial_recorded_counters": {key: {
                    "known_sum": sum(item["partial_token_counters"][key] for item in items
                                     if item["partial_token_counters"][key] is not None),
                    "known_rows": sum(item["partial_token_counters"][key] is not None for item in items)}
                    for key in TOKEN_KEYS},
                "recorded_component_counters": {key: {
                    "known_sum": sum(item["detail_counters"][key] for item in items if item["detail_counters"][key] is not None),
                    "known_rows": sum(item["detail_counters"][key] is not None for item in items)} for key in DETAIL_PATHS},
                "sum_scope": "result rows; kept separately from SSE and never added to it"}

    additional = [group for group in matching_groups if not group["has_result_usage"]
                  and group["has_terminal_usage"] and group["tokens"] is not None]
    return {"cases": len(cases), "reported_status_counts": dict(Counter(case["reported_status"] for case in cases)),
        "reported_error_type_counts": dict(Counter(case["reported_error_type"] for case in cases if case["reported_error_type"])),
        "classification_counts": dict(Counter(case["classification"] for case in cases)),
        "completed_result_usage": summarize_result(completed_items),
        "all_result_usage_including_invalid": summarize_result(result_items),
        "noncompleted_result_usage": summarize_result([item for item in result_items
            if (item["run"], item["index"]) not in completed]),
        "all_recorded_usage_deduplicated": {
            "consistent_cost_groups": sum(group["tokens"] is not None for group in matching_groups),
            "conflicting_cost_groups": sum(group["tokens"] is None for group in matching_groups),
            "response_identity_unavailable_groups": sum(not group["provider_response_identity_present"] for group in matching_groups),
            "recorded_token_sum": token_sum(group["tokens"] for group in matching_groups),
            "recorded_component_counters": {key: {
                "known_sum": sum(group["detail_counters"][key] for group in matching_groups if group["detail_counters"][key] is not None),
                "known_groups": sum(group["detail_counters"][key] is not None for group in matching_groups),
                "conflicting_groups": sum(key in group["detail_conflicts"] for group in matching_groups)} for key in DETAIL_PATHS},
            "sum_scope": "one consistent reported token vector per provider response identity; operation-scoped when absent",
            "conflicts_excluded_from_sum_and_preserved_in_observations": True},
        "additional_terminal_usage_absent_from_results": {"groups": len(additional),
            "recorded_token_sum": token_sum(group["tokens"] for group in additional)},
        "cases_without_resolved_usage": sum(case["classification"] != "recorded_usage" for case in cases),
        "total_provider_cost": None, "missing_usage_assumed_zero": False,
        "dollar_cost": None, "pricing_source_used": None,
        "sse_terminal_events": sum(case["sse"]["terminal_events"] for case in cases),
        "sse_dispatched_terminal_events": sum(case["sse"]["dispatched_terminal_events"] for case in cases),
        "sse_duplicate_terminal_events": sum(case["sse"]["duplicate_terminal_events"] for case in cases),
        "sse_terminal_usage_observations": sum(item["source_kind"] == "sse_terminal" and item["tokens"] is not None for item in observations),
        "sse_parse_or_framing_problems": sum(len(case["sse"]["problems"]) for case in cases),
        "invalid_usage_observations": sum(item["usage_error"] not in (None, "missing") for item in observations),
        "sse_provider_error_codes": dict(Counter(item["provider_error_code"] for item in observations
            if item.get("provider_error_code"))),
        "cases_with_verification_errors": sum(bool(case["verification_errors"]) for case in cases)}


def audit(root, output, smoke_input=None):
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise ValueError("output must be a new, nonexistent directory")
    protected = [root / "evidence" / name for name in RUN_NAMES]
    protected.extend(root / name for name in ("holdout", "teacher", "baselines"))
    for original_dir in protected:
        try:
            output.relative_to(original_dir)
        except ValueError:
            pass
        else:
            raise ValueError("output cannot be inside an original run or frozen source directory")
    sources = Sources(root)
    run_reports, cases, observations, global_errors = {}, [], [], []
    original_inputs = {"teacher-held-v1": root / "holdout" / "requests.jsonl",
                       "public-training-smoke-v1": smoke_input}
    run_directory_inventory = {}
    for name in RUN_NAMES:
        run_dir = root / "evidence" / name
        run_errors = []
        run = sources.json(run_dir / "RUN.json", run_errors)
        if run is None:
            raise ValueError("missing or malformed original RUN.json: " + str(run_dir))
        requested = run.get("requests")
        if type(requested) is not int or not 0 < requested <= 100000:
            raise ValueError("RUN.requests must be a positive bounded integer")
        input_path = original_inputs[name]
        if input_path is not None and not input_path.is_absolute():
            input_path = root / input_path
        input_raw, input_rows = read_jsonl(sources, input_path, run_errors) if input_path else (None, None)
        input_check = "unavailable"
        if input_raw is not None:
            input_check = "pass" if sha(input_raw) == run.get("input_sha256") and len(input_rows) == requested else "fail"
            if input_check == "fail":
                run_errors.append({"kind": "original_input_hash_or_count_differs_from_run"})
        freeze_raw = sources.read(root / "teacher" / "FREEZE.json")
        freeze_check = "unavailable" if freeze_raw is None else "pass" if sha(freeze_raw) == run.get("freeze_sha256") else "fail"
        if freeze_check == "fail":
            run_errors.append({"kind": "teacher_freeze_sha256_differs_from_run"})
        _, aggregate_rows = read_jsonl(sources, run_dir / "results.jsonl", run_errors)
        aggregate = {}
        for row in aggregate_rows or []:
            if row is None:
                continue
            index = row.get("index")
            if type(index) is not int or not 0 <= index < requested or index in aggregate:
                run_errors.append({"kind": "aggregate_invalid_or_duplicate_index", "index": index})
                continue
            aggregate[index] = row
        if aggregate_rows is None or len(aggregate_rows) != requested or len(aggregate) != requested:
            run_errors.append({"kind": "aggregate_missing_or_incomplete"})
        prior_summary = sources.json(run_dir / "SUMMARY.json", run_errors)
        discovered = sorted(path.name for path in run_dir.glob("case-*") if path.is_dir())
        run_directory_inventory[name] = discovered
        expected = [f"case-{index:04d}" for index in range(requested)]
        if sorted(expected) != discovered:
            run_errors.append({"kind": "case_directory_inventory_differs_from_requested",
                               "missing": sorted(set(expected) - set(discovered)),
                               "extra": sorted(set(discovered) - set(expected))})
        recovered = []
        for index in range(requested):
            case, items, request = audit_case(name, run, index, run_dir / f"case-{index:04d}",
                input_rows, aggregate.get(index), sources)
            cases.append(case)
            observations.extend(items)
            recovered.append(request)
        reconstruction = (sha(b"".join(canonical(request) + b"\n" for request in recovered))
                          if all(request is not None for request in recovered) else None)
        run_reports[name] = {"run_id": run.get("run_id"), "requested": requested,
            "original_input_sha256": run.get("input_sha256"), "original_input_hash_check": input_check,
            "teacher_freeze_hash_check": freeze_check,
            "canonical_reconstruction_sha256": reconstruction,
            "canonical_reconstruction_matches_original_input_hash": reconstruction == run.get("input_sha256"),
            "reconstruction_note": "Canonical reconstruction is supplementary; differing original whitespace is possible.",
            "original_summary_usage": prior_summary.get("usage") if prior_summary else None,
            "original_summary_completed": prior_summary.get("completed") if prior_summary else None,
            "verification_errors": run_errors}
    operation_owners = defaultdict(list)
    for case in cases:
        if case["operation_id"]:
            operation_owners[case["operation_id"]].append({"run": case["run"], "index": case["index"]})
    for operation, owners in operation_owners.items():
        if len(owners) > 1:
            global_errors.append({"kind": "duplicate_operation_id", "operation_id": operation, "case_refs": owners})
    groups = resolve_usage(cases, observations)
    for group in groups.values():
        if group["cross_operation_identity_collision"]:
            global_errors.append({"kind": "provider_response_identity_shared_across_operations",
                                  "cost_group": group["cost_group"], "case_refs": group["case_refs"]})
    for name, report in run_reports.items():
        run_cases = [case for case in cases if case["run"] == name]
        run_observations = [item for item in observations if item["run"] == name]
        report.update(summarize_cases(run_cases, run_observations, groups))
        if report["original_summary_completed"] != report["reported_status_counts"].get("completed", 0):
            report["verification_errors"].append({"kind": "summary_completed_count_differs_from_results"})
        old_usage = report["original_summary_usage"]
        if isinstance(old_usage, dict):
            comparisons = {}
            for key in TOKEN_KEYS:
                if isinstance(old_usage.get(key), dict):
                    comparisons[key] = old_usage[key].get("known_sum") == report["completed_result_usage"]["recorded_token_sum"][key]
            report["original_summary_matches_completed_only_usage"] = comparisons
    changed_sources = sources.verify_unchanged()
    for name, inventory in run_directory_inventory.items():
        current = sorted(path.name for path in (root / "evidence" / name).glob("case-*") if path.is_dir())
        if current != inventory:
            changed_sources.append("evidence/" + name + "/case-directory-inventory")
    if changed_sources:
        global_errors.append({"kind": "source_changed_while_reading", "sources": changed_sources})
    error_count = len(global_errors) + sum(len(report["verification_errors"]) for report in run_reports.values()) + sum(len(case["verification_errors"]) for case in cases)
    summary = {"schema": "hepta.cell-v7.posthoc-cost-audit.v1", "posthoc_analysis": True,
        "read_only_source_access": True, "network_requests": 0, "automatic_retries": 0,
        "semantic_scoring_modified": False, "qualification_gate_recomputed": False,
        "script_sha256": sha(Path(__file__).read_bytes()), "source_root": str(root),
        "original_sources_unchanged": not changed_sources,
        "verification_errors": global_errors, "verification_error_count": error_count,
        "available_binding_checks_pass": error_count == 0,
        "runs": run_reports, "combined": summarize_cases(cases, observations, groups),
        "cost_groups": list(groups.values()),
        "interpretation": [
            "Original semantic completion counts are copied, never recomputed from SSE.",
            "All result usage is counted, including failed or invalid semantic outputs.",
            "Completed, failed, incomplete and error SSE terminal usage is inspected independently.",
            "Consistent repeated usage for one response identity is counted once, never added to result usage again.",
            "Conflicting usage vectors are retained as alternatives and excluded from the exact recorded subtotal.",
            "An unterminated SSE frame is retained as an observation but not an exact terminal count.",
            "Unknown usage is not zero. Token subtotals cannot establish the full run cost or dollar billing.",
            "Cached input and reasoning output are optional components, not extra tokens to add to input/output totals.",
            "Provider compute, memory, latency beyond recorded evidence, and unreturned usage remain unmeasured.",
            "No request, instructions, answer text, credentials, or live endpoint is copied into this audit."]}
    output.mkdir(parents=True, exist_ok=False)
    payloads = {"COST_AUDIT.json": json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n",
        "CASE_COSTS.jsonl": b"".join(canonical(case) + b"\n" for case in cases),
        "USAGE_OBSERVATIONS.jsonl": b"".join(canonical(item) + b"\n" for item in observations),
        "SOURCE_SHA256.json": json.dumps({"sources": sources.records,
            "unchanged_after_reading": not changed_sources, "changed": changed_sources}, sort_keys=True, indent=2).encode() + b"\n"}
    for name, raw in payloads.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"output": str(output), "verification_error_count": error_count,
        "combined": summary["combined"], "files": {name: {"bytes": len(raw), "sha256": sha(raw)} for name, raw in payloads.items()}}, sort_keys=True))
    return 0 if error_count == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v7-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--smoke-input", type=Path, help="Original smoke input JSONL; relative paths resolve against --v7-root")
    args = parser.parse_args()
    try:
        return audit(args.v7_root, args.output, args.smoke_input)
    except (OSError, ValueError) as error:
        print(json.dumps({"audit_error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
