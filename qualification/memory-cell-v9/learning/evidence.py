"""Independent value and exact native-read evidence checks; no training imports."""

from hashlib import sha256
import json
import math
from pathlib import Path
import re


KINDS = ("event", "semantic", "procedure")
VARIANTS = ("zero", "frozen", "trained", "clean")
MAX_BYTES = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"invalid JSON number: {value}")

    def number(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON number")
        return result

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid, parse_float=number)


def read_bytes(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f"regular evidence file required: {path.name}")
    require(path.stat().st_size <= MAX_BYTES, "evidence file exceeds bound")
    raw = path.read_bytes()
    require(len(raw) <= MAX_BYTES, "evidence file changed beyond bound")
    return raw


def read_json(path):
    return decode(read_bytes(path))


def identity(path, claimed):
    raw = read_bytes(path)
    require(claimed["bytes"] == len(raw) and claimed["sha256"] == digest(raw), "raw artifact identity mismatch")
    return decode(raw)


def child_path(root, name):
    require(isinstance(name, str) and name not in {"", ".", ".."} and Path(name).name == name,
            "artifact name escapes the evidence directory")
    path = root / name
    require(not path.is_symlink(), "symlink evidence is not allowed")
    return path


def integer(value, name, low=0, high=2**64 - 1):
    require(type(value) is int and low <= value <= high, f"invalid integer: {name}")
    return value


def digest_text(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) and int(value, 16), "invalid digest")
    return value


def validate_value(kind, value):
    def bounded(number, low=-1_000_000):
        return type(number) is int and low <= number <= 1_000_000

    if kind == "event":
        valid = bounded(value)
    elif kind == "semantic":
        valid = (isinstance(value, dict) and set(value) == {"factor", "label"} and bounded(value["factor"])
                 and isinstance(value["label"], str) and 0 < len(value["label"].encode()) <= 256 and "\0" not in value["label"])
    elif kind == "procedure":
        valid = (isinstance(value, dict) and set(value) == {"opcode", "bias", "limit"}
                 and value["opcode"] in {"identity", "add_bias", "multiply", "affine", "clamp"}
                 and bounded(value["bias"]) and bounded(value["limit"], 0))
    else:
        valid = False
    require(valid, "invalid typed owner value")


def owner_facts(export):
    require(set(export) == {"schema", "owner_agent_id", "scope", "owner_cut_digest", "observed_at_unix_seconds",
                           "records", "withdrawn_addresses", "current_source_ids"}, "owner export fields")
    require(export["schema"] == "hepta.memory.owner-snapshot.v1" and export["withdrawn_addresses"] == [], "owner export schema/withdrawal")
    digest_text(export["owner_cut_digest"])
    now = integer(export["observed_at_unix_seconds"], "owner time", high=2**53 - 1)
    rows, heads, addresses = {}, {}, set()
    require(1 <= len(export["records"]) <= 512, "bounded owner record inventory required")
    for row in export["records"]:
        require(set(row) == {"source_id", "owner_memory_id", "revision", "record"}, "owner row fields")
        source = digest_text(row["source_id"])
        require(source not in rows, "duplicate source")
        rows[source] = row
        integer(row["revision"], "source revision", 1)
        record = row["record"]
        require(set(record) == {"schema", "entity", "kind", "effective_at", "value"}
                and record["schema"] == "hepta.memory.cell-record.v1", "record schema")
        validate_value(record["kind"], record["value"])
        require(isinstance(record["entity"], str) and 0 < len(record["entity"].encode()) <= 128, "owner entity")
        effective = integer(record["effective_at"], "source effective time", high=2**53 - 1)
        key = record["entity"], record["kind"]
        require((*key, effective) not in addresses, "ambiguous source address")
        addresses.add((*key, effective))
        if effective <= now and (key not in heads or effective > heads[key][0]):
            heads[key] = effective, source
    current = export["current_source_ids"]
    require(len(current) == len(set(current)) and set(current) == {item[1] for item in heads.values()}, "current owner inventory")
    facts = {}
    for source in current:
        record = rows[source]["record"]
        facts.setdefault(record["entity"], {})[record["kind"]] = source, record["value"]
    require(all(set(value) == set(KINDS) for value in facts.values()), "incomplete typed entity")
    return facts


def expected_read(facts, entity, operation):
    row = facts[entity]
    kinds = KINDS if operation == "apply" else ("event" if operation == "current" else operation,)
    if operation != "apply":
        return row[kinds[0]][1], sorted(row[kind][0] for kind in kinds)
    event, semantic, procedure = (row[kind][1] for kind in KINDS)
    opcode, bias, limit = (procedure[key] for key in ("opcode", "bias", "limit"))
    values = {"identity": event, "add_bias": event + bias, "multiply": event * semantic["factor"],
              "affine": event * semantic["factor"] + bias,
              "clamp": min(limit, max(-limit, event * semantic["factor"] + bias))}
    return values[opcode], sorted(row[kind][0] for kind in kinds)


def scalar(value, operation):
    number = value["factor"] if operation == "semantic" else value["bias"] if operation == "procedure" else value
    return integer(number, "task scalar", -(2**63), 2**63 - 1)


def verify_batch(batch, export, tasks, publication):
    facts = owner_facts(export)
    direct = publication.get("mode") == "direct_owner"
    require(batch["source_cut"] == export["owner_cut_digest"], "batch owner cut mismatch")
    require(batch["tasks"] == len(tasks) == len(batch["records"]), "missing or extra task")
    integer(batch["wall_ns"], "batch wall")
    for field in ("rpc_attempts", "transmitted_bytes", "received_bytes"):
        integer(batch["traffic"][field], field)
    outcomes, decisions, statuses, request_hashes, families = {}, {}, {}, [], {}
    for task, record in zip(tasks, batch["records"]):
        require(record["task"] == task, "task differs from independently frozen fixture")
        for name, field in (("request", "requests"), ("readout", "readouts")):
            raw = record[f"{name}_json"].encode()
            require(digest(raw) == record[f"{name}_digest"] and decode(raw) == record[field], "exact typed wire bytes differ")
        require(len(record["requests"]) == len(record["readouts"]) == len(task["queries"]), "read inventory")
        expected_values, target, actual = [], 0, 0
        family = families.setdefault(task["family"], {"reads": 0, "correct_reads": 0, "tasks": 0, "correct_decisions": 0})
        for offset, (query, request, readout) in enumerate(zip(task["queries"], record["requests"], record["readouts"])):
            require(request == {"schema": "hepta.memory.request.v1", "query_id": f"query:v9:{task['id']}:{offset}",
                    "scope": export["scope"], "entity": query["entity"], "text": "Explicit trusted resolver integration test",
                    "at": 15, "since": 10, "max_hops": 3, "max_cells": 3}, "request changed frozen operation/address profile")
            expected, sources = expected_read(facts, query["entity"], query["operation"])
            expected_values.append(expected)
            require(readout["query_id"] == request["query_id"], "readout query identity")
            if direct:
                require(readout["schema"] == "hepta.memory.direct-owner-read.v1" and readout["owner_cut"] == export["owner_cut_digest"]
                        and readout["scope"] == export["scope"] and readout["before_and_after_cut_verified"] is True
                        and readout["model_storage_bytes"] == 0, "direct owner cut revalidation")
            else:
                require(readout["schema"] == "hepta.memory.readout.v1" and readout["generation"] == publication["generation"]
                        and readout["snapshot_digest"] == publication["bundle_digest"], "readout release identity")
            status = readout["status"]
            require(status in {"ok", "abstain", "stale", "unavailable", "budget_exceeded"}, "read status")
            statuses[status] = statuses.get(status, 0) + 1
            ok = status == "ok"
            if ok:
                operation = query["operation"]
                kinds = ("semantic", "procedure") if operation == "apply" else () if operation == "current" else (operation,)
                predicted = "mixed" if operation == "apply" else "source_evidence" if operation == "current" else "model_prediction"
                require(readout["operation"] == operation and sorted(readout["source_ids"]) == sources, "readout source binding")
                if not direct:
                    require(readout["cell_digests"] == sorted(publication[f"{kind}_digest"] for kind in kinds)
                            and readout["prediction_kind"] == predicted and readout["reason"] is None
                            and readout["hops"] == (3 if operation == "apply" else 1), "readout model binding")
                if operation in KINDS:
                    validate_value(operation, readout["value"])
            else:
                require(readout["value"] is None and readout["source_ids"] == [] and readout["cell_digests"] == []
                        and readout["prediction_kind"] == "none", "failed read exposed a partial value")
            key = f"{task['id']}:{offset}"
            require(key not in outcomes, "duplicate task/query identity")
            outcomes[key] = ok and readout["value"] == expected
            family["reads"] += 1
            family["correct_reads"] += outcomes[key]
            target += task["coefficients"][offset] * scalar(expected, query["operation"])
            actual = None if not ok or actual is None else actual + task["coefficients"][offset] * scalar(readout["value"], query["operation"])
        target_action = target > task["threshold"]
        action = None if actual is None else actual > task["threshold"]
        require(record["expected_values"] == expected_values and record["expected_action"] == target_action
                and record["action"] == action, "downstream value/decision recomputation")
        decisions[task["id"]] = action == target_action
        family["tasks"] += 1
        family["correct_decisions"] += decisions[task["id"]]
        request_hashes.append(record["request_digest"])
    require(len(request_hashes) == len(set(request_hashes)), "duplicate requests")
    require((batch["queries"], batch["correct"], batch["decisions_correct"]) ==
            (len(outcomes), sum(outcomes.values()), sum(decisions.values())), "reported score differs")
    return {"reads": len(outcomes), "correct_reads": sum(outcomes.values()), "tasks": len(decisions),
            "correct_decisions": sum(decisions.values()), "statuses": statuses, "families": families,
            "items": outcomes, "decisions": decisions, "request_digests": request_hashes}


def transitions(before, after):
    require(set(before) == set(after), "paired item inventory differs")
    counts = {name: 0 for name in ("retained", "lost", "gained", "still_wrong")}
    for key in before:
        name = "retained" if before[key] and after[key] else "lost" if before[key] else "gained" if after[key] else "still_wrong"
        counts[name] += 1
    return counts
