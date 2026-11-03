"""Recompute tasks from owner facts and retained typed batch encodings.

This checks evidence consistency under the pinned native test/CI execution.
Neither a digest chain nor a serialized owner export authenticates authority.
"""

from hashlib import sha256
import json
import math
from pathlib import Path
import re


MAX_FILE_BYTES = 32 * 1024 * 1024
KINDS = ("event", "semantic", "procedure")
OPERATIONS = ("apply", "semantic", "procedure")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def integer(value, name, minimum=0):
    require(type(value) is int and value >= minimum, f"invalid {name}")
    return value


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    def number(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON number")
        return result

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)


def read_bytes(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"missing regular artifact: {path.name}")
    require(path.stat().st_size <= MAX_FILE_BYTES, f"oversized artifact: {path.name}")
    raw = path.read_bytes()
    require(len(raw) <= MAX_FILE_BYTES, "artifact changed beyond bound")
    return raw


def read_json(path):
    return decode(read_bytes(path))


def digest_text(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) and int(value, 16),
            "nonzero canonical digest required")
    return value


def validate_value(kind, value):
    def bounded(number, low=-1_000_000, high=1_000_000):
        return type(number) is int and low <= number <= high

    if kind == "event":
        valid = bounded(value)
    elif kind == "semantic":
        valid = (isinstance(value, dict) and set(value) == {"factor", "label"}
                 and bounded(value["factor"]) and isinstance(value["label"], str)
                 and 0 < len(value["label"].encode()) <= 256 and "\0" not in value["label"])
    elif kind == "procedure":
        valid = (isinstance(value, dict) and set(value) == {"opcode", "bias", "limit"}
                 and value["opcode"] in {"identity", "add_bias", "multiply", "affine", "clamp"}
                 and bounded(value["bias"]) and bounded(value["limit"], 0))
    else:
        valid = False
    require(valid, "invalid typed owner value")


def owner_facts(export, cut):
    require(export["schema"] == "hepta.memory.owner-snapshot.v1", "owner export schema")
    require(export["owner_cut_digest"] == digest_text(cut), "owner export cut mismatch")
    require(export["withdrawn_addresses"] == [], "prospective fixture unexpectedly withdraws a source")
    require(isinstance(export["scope"], str) and export["scope"], "owner scope missing")
    now = integer(export["observed_at_unix_seconds"], "owner observation time")
    rows, heads = {}, {}
    require(1 <= len(export["records"]) <= 512, "owner record bound")
    for row in export["records"]:
        source = digest_text(row["source_id"])
        require(source not in rows, "duplicate source")
        rows[source] = row
        record = row["record"]
        require(record["schema"] == "hepta.memory.cell-record.v1", "owner record schema")
        validate_value(record["kind"], record["value"])
        key = record["entity"], record["kind"]
        effective = integer(record["effective_at"], "effective time")
        integer(row["revision"], "source revision", 1)
        if effective <= now and (key not in heads or effective > heads[key][0]):
            heads[key] = effective, source
    current = export["current_source_ids"]
    require(len(current) == len(set(current)) and set(current) == {item[1] for item in heads.values()},
            "owner current-head inventory mismatch")
    facts = {}
    for source in current:
        record = rows[source]["record"]
        facts.setdefault(record["entity"], {})[record["kind"]] = (source, record["value"])
    require(len(facts) == 25 and all(set(value) == set(KINDS) for value in facts.values()),
            "expected base entity and 24 newly written complete typed entities")
    return facts


def execute_program(event, semantic, procedure):
    opcode, bias, limit = procedure["opcode"], procedure["bias"], procedure["limit"]
    if opcode == "identity":
        return event
    if opcode == "add_bias":
        return event + bias
    if opcode == "multiply":
        return event * semantic["factor"]
    result = event * semantic["factor"] + bias
    if opcode == "affine":
        return result
    require(opcode == "clamp", "unknown registered opcode")
    return min(limit, max(-limit, result))


def expected_read(facts, entity, operation):
    row = facts[entity]
    kinds = KINDS if operation == "apply" else ("event" if operation == "current" else operation,)
    sources = sorted(row[kind][0] for kind in kinds)
    if operation == "apply":
        value = execute_program(*(row[kind][1] for kind in KINDS))
    else:
        value = row[kinds[0]][1]
    return value, sources


def batch_indices(phase, group):
    family, domain = group // 4, group % 4
    result = []
    for offset in range(6):
        if phase == "future" and family == 1:
            index = ((domain + int(offset >= 3)) % 4) * 6 + offset
        elif phase == "future" and family == 2:
            index = ((domain + offset) % 4) * 6 + offset
        else:
            index = domain * 6 + (5 - offset if phase == "future" else offset)
        result.append(index)
    return result


def verify_batch(batch, export, facts, seed, direct, generation):
    phase = batch["phase"]
    require(phase in {"prefix", "selection", "future", "retention"}, "unknown phase")
    groups = 16 if phase == "prefix" else 12 if phase == "future" else 4
    require(len(batch["records"]) == groups and batch["tasks"] == groups and batch["queries"] == groups * 6,
            "incomplete task batch")
    require(batch["source_cut"] == export["owner_cut_digest"], "batch owner cut mismatch")
    integer(batch["socket_and_native_wall_ns"], "batch wall")
    for field in ("rpc_attempts", "transmitted_bytes", "received_bytes"):
        integer(batch["traffic"][field], field)
    correct, decisions, statuses, request_ids = 0, 0, {}, []
    for group, record in enumerate(batch["records"]):
        require(record["sequence"] == group + 1 and record["family"] == group // 4
                and record["task_id"] == f"task:{phase}:{group}", "batch sequence mismatch")
        for name, structured in (("request", "queries"), ("readout", "readouts")):
            require(isinstance(record[f"{name}_bytes"], str), "typed batch encoding must be a UTF-8 string")
            raw = record[f"{name}_bytes"].encode()
            require(digest(raw) == record[f"{name}_digest"], "exact typed batch byte digest mismatch")
            require(decode(raw) == record[structured], "batch encoding differs from retained structured data")
        queries, readouts = record["queries"], record["readouts"]
        require(len(queries) == len(readouts) == 6, "six reads required")
        addresses = sorted({digest(query["entity"].encode()) for query in queries})
        require(record["addresses"] == addresses, "address projection differs from actual requests")
        expected_values, actual_total, expected_total = [], 0, 0
        for offset, (index, query, readout) in enumerate(zip(batch_indices(phase, group), queries, readouts)):
            entity_hash = digest(f"random-owner-values:{seed}:{index}".encode())
            entity = f"entity:trained-{index}-{entity_hash[:12]}"
            require(query == {"schema": "hepta.memory.request.v1", "query_id": f"query:prospective:{phase}:{group}:{offset}",
                    "scope": export["scope"], "entity": entity, "text": "Explicit trusted resolver integration test",
                    "at": 15, "since": 10, "max_hops": 3, "max_cells": 3}, "request violates frozen protocol")
            operation = "current" if phase == "prefix" else OPERATIONS[offset % 3]
            expected, sources = expected_read(facts, entity, operation)
            expected_values.append(expected)
            require(readout["query_id"] == query["query_id"], "readout query identity mismatch")
            status, value = readout["status"], readout["value"]
            require(status in {"ok", "abstain", "stale", "unavailable", "budget_exceeded"}, "readout status")
            statuses[status] = statuses.get(status, 0) + 1
            if status == "ok":
                require(readout["operation"] == operation and sorted(readout["source_ids"]) == sources,
                        "successful readout dependency/operation mismatch")
                if direct:
                    require(readout["schema"] == "hepta.memory.direct-owner-read.v1"
                            and readout["owner_cut"] == export["owner_cut_digest"]
                            and readout["scope"] == export["scope"] and readout["before_and_after_cut_verified"] is True,
                            "direct owner binding mismatch")
                else:
                    require(readout["schema"] == "hepta.memory.readout.v1" and readout["generation"] == generation,
                            "native candidate generation mismatch")
                correct += value == expected
            else:
                require(not direct and value is None and readout["source_ids"] == []
                        and readout["cell_digests"] == [] and readout["prediction_kind"] == "none",
                        "failed readout leaked partial evidence")
            number = lambda item: item["factor"] if operation == "semantic" else item["bias"] if operation == "procedure" else item
            sign = 1 if offset % 2 == 0 else -1
            expected_total += sign * number(expected)
            actual_total = None if status != "ok" or actual_total is None else actual_total + sign * number(value)
        threshold = (group % 5 - 2) * 1200
        expected_action = expected_total > threshold
        action = None if actual_total is None else actual_total > threshold
        require(record["expected_values"] == expected_values and record["threshold"] == threshold
                and record["expected_action"] == expected_action and record["action"] == action
                and record["decision_correct"] == (action == expected_action), "downstream decision recomputation mismatch")
        decisions += action == expected_action
        request_ids.append(record["request_digest"])
    require(len(request_ids) == len(set(request_ids)), "repeated request identity in batch")
    require((batch["correct"], batch["decisions_correct"]) == (correct, decisions), "reported batch score mismatch")
    return {"tasks": groups, "correct_decisions": decisions, "decision_errors": groups - decisions,
            "reads": groups * 6, "correct_reads": correct, "read_errors": groups * 6 - correct,
            "statuses": statuses, "request_digests": request_ids}


def verify_progress(directory, direct):
    phases = [("source_ready", "OWNER_EXPORT.json")]
    phases.append(("owner_acquired", "owner-acquisition.json") if direct else ("bootstrap_fit", "bootstrap-fit.json"))
    phases.extend([("retention_before", "before-retention.json"), ("prefix_complete", "completed-prefix.json")])
    if not direct:
        phases.append(("candidate_fit", "candidate-fit.json"))
    phases.append(("fit_locked", "FIT_LOCK.json"))
    phases.extend((phase, f"{phase}.json") for phase in ("selection", "future", "retention"))
    raw = read_bytes(directory / "PROGRESS.jsonl")
    lines, previous = raw.splitlines(keepends=True), b""
    require(len(lines) == len(phases), "incomplete causal progress chain")
    for line, (phase, artifact) in zip(lines, phases):
        event = decode(line)
        require(event == {"phase": phase, "artifact": artifact,
                          "artifact_sha256": digest(read_bytes(directory / artifact)), "previous_sha256": digest(previous)},
                "causal order or artifact hash mismatch")
        require(line.endswith(b"\n"), "partial progress event")
        previous += line
    return {"events": len(lines), "sha256": digest(raw), "chain_consistent": True,
            "self_authenticating_or_authorizing": False}


def verify_model_use(batch, native_digests):
    """A valid fit must be the exact model actually used, including before-fit retention."""
    for record in batch["records"]:
        for readout in record["readouts"]:
            if readout["status"] != "ok":
                continue
            operation = readout["operation"]
            kinds = ("semantic", "procedure") if operation == "apply" else () if operation == "current" else (operation,)
            expected = sorted(native_digests[kind] for kind in kinds)
            prediction = "mixed" if operation == "apply" else "source_evidence" if operation == "current" else "model_prediction"
            require(readout["cell_digests"] == expected and readout["prediction_kind"] == prediction
                    and readout["hops"] == (3 if operation == "apply" else 1) and readout["reason"] is None,
                    "successful read did not use the exact fitted model/operation profile")
