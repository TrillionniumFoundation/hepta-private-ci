"""Audit actual tool proposals, original feedback and live model identities."""

import hashlib
import json
from pathlib import Path


def response_objects(path):
    objects = []
    for line in path.read_text().splitlines():
        if line.startswith("data: ") and line[6:] != "[DONE]":
            event = json.loads(line[6:])
            if event.get("type") == "response.completed":
                objects.append(event["response"])
    if len(objects) != 1:
        raise ValueError("missing or duplicate completed provider response")
    return objects[0]


def feedback_value(item, *, allow_excerpt=False):
    value = item["output"]
    if isinstance(value, list):
        if len(value) != 1 or value[0].get("type") != "input_text":
            raise ValueError("feedback is not one complete tool result")
        value = value[0]["text"]
    result = json.loads(value)
    fields = {"exit_code", "stdout", "stderr"}
    if allow_excerpt:
        fields.add("presentation")
    if (not isinstance(result, dict) or set(result) != fields
            or type(result["exit_code"]) is not int
            or any(not isinstance(result[key], str) for key in ("stdout", "stderr"))):
        raise ValueError("tool result lacks exact terminal status and streams")
    return result


def audit_actual(root, case_id, mode, expected_model=None):
    evidence = root / "model"
    request_paths = sorted(evidence.glob("*.request.json"))
    response_paths = sorted(evidence.glob("*.response.sse"))
    if len(request_paths) != len(response_paths) or not request_paths:
        raise ValueError("incomplete model capture")
    requests = [json.loads(path.read_bytes()) for path in request_paths]
    responses = [response_objects(path) for path in response_paths]
    calls, feedback, first_seen = [], {}, {}
    models, usage, item_sizes = set(), [], []
    for index, (request, response) in enumerate(zip(requests, responses)):
        models.add(response.get("model"))
        usage.append(response.get("usage"))
        for item in request.get("input", []):
            if item.get("type") == "function_call_output":
                call_id = item["call_id"]
                value = feedback_value(item, allow_excerpt=case_id == "long_output")
                if case_id == "long_output":
                    item_sizes.append({"request_index": index, "call_id": call_id,
                                       "bytes": validate_excerpt(item, value, 4096)})
                if call_id in feedback and feedback[call_id] != value:
                    raise ValueError("a previous tool result was rewritten")
                feedback[call_id] = value
                first_seen.setdefault(call_id, index)
        for item in response.get("output", []):
            if item.get("type") == "function_call":
                calls.append({"call_id": item["call_id"], "name": item["name"],
                              "arguments": json.loads(item["arguments"]), "response_index": index})
    ids = [call["call_id"] for call in calls]
    if len(ids) != len(set(ids)) or set(feedback) != set(ids):
        raise ValueError("duplicate proposal or missing/unexpected feedback")
    admissions = [json.loads(path.read_bytes()) for path in (root / "sessions").rglob("tool-*.json")]
    admitted = {item["call"]["call_id"]: item["call"] for item in admissions}
    if len(admissions) != len(admitted) or set(admitted) != set(ids):
        raise ValueError("proposals do not match original owner admissions")
    for call in calls:
        record = admitted[call["call_id"]]
        args = record["arguments"]
        # SessionOwner's snapshot::call_json freezes these as the original
        # UTF-8 JSON string. Reject alternative encodings instead of repairing
        # a malformed or substituted owner record for the audit.
        if not isinstance(args, str):
            raise ValueError("owner admission has no original JSON argument string")
        args = json.loads(args)
        if record["name"] != call["name"] or args != call["arguments"]:
            raise ValueError("admitted payload differs from model proposal")
        if first_seen[call["call_id"]] <= call["response_index"]:
            raise ValueError("feedback predates its proposal")
        call["exit_code"] = feedback[call["call_id"]]["exit_code"]
    names = [call["name"] for call in calls]
    required = {"edit": {"hepta_read", "hepta_patch", "hepta_tests"},
                "repair": {"hepta_read", "hepta_patch", "hepta_tests"},
                "multi_tool": {"hepta_read", "hepta_write", "hepta_tests"},
                "mcp_readonly": {"hepta_mcp_lookup"}, "long_output": {"hepta_fixture"}}[case_id]
    if not required.issubset(names):
        raise ValueError("representative capability coverage incomplete")
    if case_id in ("edit", "repair", "multi_tool"):
        writes = [i for i, call in enumerate(calls) if call["name"] in ("hepta_patch", "hepta_write")]
        tests = [i for i, call in enumerate(calls) if call["name"] == "hepta_tests"]
        if not writes or not tests or max(tests) < max(writes) or calls[max(tests)]["exit_code"] != 0:
            raise ValueError("successful independent test must follow final mutation")
        read_path = "input.json" if case_id == "multi_tool" else "src/calc.py"
        reads = [call for call in calls if call["name"] == "hepta_read"
                 and call["arguments"] == {"path": read_path} and call["exit_code"] == 0]
        if not any(first_seen[call["call_id"]] <= calls[min(writes)]["response_index"] for call in reads):
            raise ValueError("mutation was proposed before observing the original input")
        if first_seen[calls[max(writes)]["call_id"]] > calls[max(tests)]["response_index"]:
            raise ValueError("validation was proposed before observing the final mutation")
        if case_id == "repair":
            first = calls[0]
            if first["name"] != "hepta_tests" or first["exit_code"] == 0:
                raise ValueError("repair did not first observe an actual failed test")
            if first_seen[first["call_id"]] > calls[min(writes)]["response_index"]:
                raise ValueError("repair mutation was proposed before failed-test feedback")
    elif case_id == "mcp_readonly":
        for call in calls:
            if call["name"] == "hepta_mcp_lookup":
                data = json.loads(feedback[call["call_id"]]["stdout"])
                if data["result"].get("isError") or json.loads(data["result"]["content"][0]["text"]) != {
                        "version": "1.0.0", "source": "fixture"}:
                    raise ValueError("MCP returned an incorrect result")
    else:
        if len(calls) != 1 or calls[0]["exit_code"] != 0:
            raise ValueError("long output requires one original successful process")
        from representative_runtime_evidence import audit_long_output
        long_evidence = audit_long_output(root, admissions[0], feedback[ids[0]])
    if mode == "live":
        if models != {expected_model}:
            raise ValueError("actual provider identity differs from frozen evidence")
        for item in usage:
            if (not isinstance(item, dict) or any(type(item.get(key)) is not int or item[key] < 0
                    for key in ("input_tokens", "output_tokens", "total_tokens"))
                    or item["total_tokens"] != item["input_tokens"] + item["output_tokens"]):
                raise ValueError("actual provider token usage is absent or inconsistent")
    return {"calls": calls, "provider_models": sorted(models), "actual_usage": usage,
            **({"retained_output": long_evidence, "model_items": item_sizes} if case_id == "long_output" else {}),
            "usage_is_synthetic": mode == "replay", "request_bytes": [path.stat().st_size for path in request_paths],
            "model_request_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in request_paths],
            "response_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in response_paths]}


def validate_excerpt(item, value, limit):
    presentation = value["presentation"]
    if (presentation.get("schema") != "hepta.runtime-output-excerpt.v1"
            or presentation.get("limit_bytes") != limit or presentation.get("truncated") is not True
            or not isinstance(presentation.get("retained"), dict)):
        raise ValueError("long output has no explicit bounded retained-output reference")
    actual_bytes = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode())
    if actual_bytes > limit:
        raise ValueError("actual model-facing tool item exceeds its admitted byte cap")
    for field in ("host", "job_id", "operation_id", "idempotency_key", "runtime_intent_digest"):
        if not isinstance(presentation["retained"].get(field), str) or not presentation["retained"][field]:
            raise ValueError("retained-output reference lost its original " + field)
    return actual_bytes
