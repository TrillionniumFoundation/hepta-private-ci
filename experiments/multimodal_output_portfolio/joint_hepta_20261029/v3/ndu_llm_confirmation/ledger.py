"""Durable pre-dispatch intent, terminal pairing and one charge per completed attempt."""
import datetime as dt
import os
from pathlib import Path
from .contracts import canonical, digest, number, sha, usage

BINDINGS = ("request_id", "kind", "task_id", "arm", "repeat", "protocol_sha256", "request_sha256",
            "transport_sha256", "expected_identity_sha256", "identity_kind", "timeout_seconds", "deadline_monotonic")


def append_event(path, event):
    line = (canonical(event)+"\n").encode()
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if os.write(fd, line) != len(line):
                raise OSError("Incomplete ledger append; retain file and HOLD")
            os.fsync(fd)
            os.fsync(directory)
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def complete_events(records):
    """Raw ordered ledger -> terminal attempts plus host meters; dangling intent is fatal."""
    pending, completed, result = {}, set(), []
    for record in records:
        rid, phase = record["request_id"], record["phase"]
        if rid in completed:
            raise ValueError("duplicate_terminal_or_reused_request:"+rid)
        if phase == "intent":
            if rid in pending:
                raise ValueError("duplicate_intent:"+rid)
            pending[rid] = record
            continue
        if phase == "terminal":
            intent = pending.pop(rid, None)
            if intent is None:
                raise ValueError("terminal_without_intent:"+rid)
            if (record["intent_sha256"] != digest(intent) or
                    any(record[k] != intent[k] or type(record[k]) is not type(intent[k]) for k in BINDINGS)):
                raise ValueError("intent_terminal_binding_mismatch:"+rid)
            if (record["deadline_monotonic"] > intent["prepared_monotonic"]+record["timeout_seconds"] or
                    record["started_monotonic"] != intent["prepared_monotonic"] or
                    not intent["prepared_monotonic"] <= record["intent_finished_monotonic"] <= record["finished_monotonic"] or
                    dt.datetime.fromisoformat(record["started_at"]) < dt.datetime.fromisoformat(intent["prepared_at"])):
                raise ValueError("dispatch_before_intent:"+rid)
            if (not record["dispatched"] and (record["dispatch_monotonic"] is not None or
                    record["response_received"] or record["status"] not in ("failure", "timeout")) or
                    record["status"] == "ok" and (not record["response_received"] or
                    record["finished_monotonic"] > record["deadline_monotonic"])):
                raise ValueError("inconsistent_dispatch_or_response:"+rid)
            if "verified_quality" in record and not (record["kind"] == "verifier" and record["response_received"] and
                    number(record["verified_quality"]) and record["verified_quality"] <= 1):
                raise ValueError("invalid_verified_quality:"+rid)
            if record["kind"] == "verifier" and record["status"] == "ok" and "verified_quality" not in record:
                raise ValueError("missing_verified_quality:"+rid)
            if record["dispatched"] and not (sha(record["request_sha256"]) and number(record["dispatch_monotonic"]) and
                    record["intent_finished_monotonic"] <= record["dispatch_monotonic"] <= record["finished_monotonic"] and
                    record["dispatch_monotonic"] < record["deadline_monotonic"]):
                raise ValueError("dispatch_outside_admission_window:"+rid)
        elif phase != "meter" or record["kind"] != "host_envelope" or rid in pending:
            raise ValueError("invalid_ledger_phase:"+rid)
        completed.add(rid)
        result.append(record)
    if pending:
        raise ValueError("unfinished_intent:"+next(iter(pending)))
    return result


def reconcile(events, invoices, currency):
    """Completed attempts only. The gate separately requires their original intent pairs."""
    index, seen, problems = {}, set(), []
    for item in invoices:
        key = item.get("invoice_sha256"), item.get("line_id")
        rid = item.get("request_id")
        if rid in index or key in seen:
            problems.append("duplicate_invoice_line")
        index[rid] = item
        seen.add(key)
    result = {}
    for event in events:
        rid = event["request_id"]
        item = index.get(rid)
        if rid in result:
            problems.append("duplicate_request")
        if (not item or item.get("status") != "final" or item.get("currency") != currency or not number(item.get("amount"))
                or not sha(item.get("invoice_sha256")) or not item.get("line_id")):
            result[rid] = None
            problems.append("unreconciled_charge:"+rid)
            continue
        if (event.get("provider_request_sha256") is not None and
                item.get("provider_request_sha256") != event["provider_request_sha256"]):
            problems.append("invoice_request_mismatch:"+rid)
        if event["kind"] == "model":
            billed, known = usage(item.get("usage")), usage(event.get("usage"))
            if any(raw is not None and usage(raw) is None for raw in (event.get("usage"), item.get("usage"))):
                problems.append("invalid_usage_record:"+rid)
            if billed is None and known is None:
                problems.append("usage_unknown:"+rid)
            if billed is not None and known is not None and billed != known:
                problems.append("usage_discrepancy:"+rid)
            identity = event.get("identity_status")
            if identity == "mismatch" or event["status"] == "identity_mismatch":
                problems.append("model_version_mismatch:"+rid)
            elif identity == "match":
                if event.get("response_received") is not True or not sha(event.get("observed_identity_sha256")):
                    problems.append("missing_observed_identity:"+rid)
            elif not (event["status"] in ("failure", "timeout") and event.get("response_received") is False and
                      identity == "unobserved" and event.get("observed_identity_sha256") is None and
                      item.get("identity_sha256") == event["expected_identity_sha256"] and
                      sha(item.get("identity_evidence_sha256"))):
                problems.append("unresolved_model_identity:"+rid)
        result[rid] = item["amount"]
    if set(index)-set(result):
        problems.append("invoice_without_attempt")
    return result, problems
