"""Recount native language evidence without importing a model or its evaluator.

The owner snapshot is retained evidence, not imported authority. This audit
checks its consistency with frozen writes and each reported source dependency;
native owner and signature validation remain the Rust runtime's responsibility.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HELD_SHA = "6fd373b11089db17b8b6ac0a015725d8a0397cf7ba69169132cb136456622f0a"
NATIVE_SHA = "cb1dabcd85fe5dd7ec1b3e4246d6b4cb51c25d408bc2d295ce155088b4cac357"
ARMS = {"baseline-v7-native-held.json": "frozen-v7",
        "baseline-v8-native-held.json": "frozen-v8-shadow",
        "candidate-v9-native-held.json": "candidate-v9-shadow"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    def number(value):
        result = float(value)
        require(math.isfinite(result), "nonfinite JSON number")
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_float=number,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def load(path, maximum=32_000_000):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, "bounded regular file required")
    raw = path.read_bytes()
    require(len(raw) <= maximum, "file grew beyond bound")
    return raw, decode(raw)


def gold(records, case):
    operation = case["expected_operation"]
    if operation is None:
        return None, []
    def latest(kind, cutoff=2**53 - 1):
        candidates = [item for item in records if item["record"]["entity"] == case["entity"]
                      and item["record"]["kind"] == kind and item["record"]["effective_at"] <= cutoff]
        require(candidates, "known request lacks a source")
        return max(candidates, key=lambda item: item["record"]["effective_at"])
    if operation in ("current", "history", "semantic", "procedure"):
        selected = latest("event" if operation in ("current", "history") else operation,
                          case["at"] if operation == "history" else 2**53 - 1)
        return selected["record"]["value"], [selected["source_id"]]
    current = latest("event")
    if operation == "change":
        previous = latest("event", case["since"])
        return current["record"]["value"] - previous["record"]["value"], sorted({current["source_id"], previous["source_id"]})
    require(operation == "apply", "unknown gold operation")
    semantic, procedure = latest("semantic"), latest("procedure")
    x, factor, program = current["record"]["value"], semantic["record"]["value"]["factor"], procedure["record"]["value"]
    values = {"identity": x, "add_bias": x + program["bias"], "multiply": x * factor,
              "affine": x * factor + program["bias"],
              "clamp": min(program["limit"], max(-program["limit"], x * factor + program["bias"]))}
    return values[program["opcode"]], sorted(item["source_id"] for item in (current, semantic, procedure))


def fixture():
    held_raw, held = load(ROOT / "evaluation/held.json")
    native_raw, native = load(ROOT / "fixtures/address-model/native-fixture.json")
    require(sha(held_raw) == HELD_SHA and sha(native_raw) == NATIVE_SHA, "frozen input bytes changed")
    records = [{"schema": "hepta.memory.cell-record.v1", "entity": entity["entity"], **record}
               for entity in held["entities"] for record in entity["records"]]
    pseudo = [{"record": record, "source_id": str(index)} for index, record in enumerate(records)]
    expected = [{**row, "max_hops": 8, "max_cells": 8, "expected_value": gold(pseudo, row)[0]} for row in held["rows"]]
    require(native["records"] == records and native["requests"] == expected
            and native["aliases"] == {item["entity"]: item["aliases"] for item in held["entities"]}
            and native["suite_digest"] == sha(canonical(held))
            and native["native_execution_claim"] is False and native["split"] == "held", "native fixture differs from independent inputs")
    return native


def audit(path, arm, native):
    raw, report = load(path)
    require(report["schema"] == "hepta.memory.v9.native-language-report.v1" and report["arm"] == arm
            and report["fixture_sha256"] == NATIVE_SHA and report["suite_digest"] == native["suite_digest"]
            and report["final_use_authority"] is False and report["qualification_only"] is True, "report identity")
    owner = report["owner_snapshot"]
    require(owner["owner_cut_digest"] == report["source_cut"] and not owner["withdrawn_addresses"], "owner cut differs")
    records = owner["records"]
    ids = [item["source_id"] for item in records]
    require(len(set(ids)) == len(ids) and set(owner["current_source_ids"]) <= set(ids), "duplicate or unknown source")
    entities = set(native["aliases"])
    actual = Counter(canonical(item["record"]) for item in records if item["record"]["entity"] in entities)
    require(actual == Counter(canonical(item) for item in native["records"]), "written facts differ from frozen inputs")
    for entity in entities:
        for kind in ("event", "semantic", "procedure"):
            eligible = [item for item in records if item["record"]["entity"] == entity and item["record"]["kind"] == kind]
            current = max(eligible, key=lambda item: item["record"]["effective_at"])
            require(current["source_id"] in owner["current_source_ids"], "latest written fact is absent from current owner")
    require(len(report["readouts"]) == len(native["requests"]) == 272, "native request inventory")
    counts, retained, null_frames = {}, 0, 0
    for row, case in zip(report["readouts"], native["requests"]):
        require(row["case"] == case, "native request order or gold changed")
        request = {key: case[key] for key in ("entity", "text", "at", "since", "max_hops", "max_cells")}
        request.update(schema="hepta.memory.request.v1", query_id=case["id"], scope=owner["scope"])
        require(row["request"] == request, "actual request differs from held input")
        for field in ("direct_worker_response", "control_worker_response"):
            frame = row[field]
            if frame is None:
                null_frames += 1
                continue
            data = frame["utf8"].encode()
            require(len(data) == frame["bytes"] <= 32_769 and data.endswith(b"\n") and sha(data) == frame["sha256"], "worker frame bytes changed")
            decision = decode(data)
            require(decision["query_id"] == case["id"] and decision["model_digest"] == report["model_digest"]
                    and decision["source_cut"] == report["source_cut"] and decision["authority"] is False, "worker frame binding")
            if decision["status"] == "accepted":
                require(decision["plan"]["operation"] == decision["decision"]["operation"], "worker operation differs from plan")
            retained += 1
        require(row["direct_error"] is None and row["transport_error"] is None
                and row["direct_identity_valid"] is True and row["read_identity_valid"] is True, "native execution or binding error")
        readout, route = row["readout"], row["direct_operation"]
        require(readout["schema"] == "hepta.memory.readout.v1" and readout["query_id"] == case["id"]
                and readout["snapshot_digest"] == report["bundle_digest"] and readout["generation"] == 1, "readout version binding")
        value, sources = gold(records, case)
        require(value == case["expected_value"], "owner-derived value differs from frozen gold")
        if readout["status"] == "ok":
            require(readout["operation"] == route and len(set(readout["source_ids"])) == len(readout["source_ids"]), "readout route/source inventory")
            correct = case["expected_operation"] is not None and route == case["expected_operation"] and readout["value"] == value and sorted(readout["source_ids"]) == sources
        else:
            require(readout["value"] is None and readout["source_ids"] == [] and readout["cell_digests"] == [], "failed readout exposes partial content")
            correct = case["expected_operation"] is None and route is None and readout["status"] == "abstain"
        require(row["native_correct"] == correct, "native correctness flag differs from raw value/source evidence")
        count = counts.setdefault(case["category"], dict.fromkeys(("rows", "routing_correct", "native_correct", "wrong_native_accepts", "negative_routes", "errors"), 0))
        count["rows"] += 1
        count["routing_correct"] += route == case["expected_operation"]
        count["native_correct"] += correct
        count["wrong_native_accepts"] += readout["status"] == "ok" and not correct
        count["negative_routes"] += case["expected_operation"] is None and route is not None
        count["errors"] += readout["status"] in ("unavailable", "stale")
    require(counts == report["counts"] and report["binding_failures"] == 0 and report["errors"] == sum(item["errors"] for item in counts.values()), "reported counts differ from raw rows")
    known, unsupported = counts["known"], counts["unsupported"]
    coverage, rate = known["native_correct"] / known["rows"], unsupported["negative_routes"] / unsupported["rows"]
    boundary = all(item["native_correct"] == item["rows"] and item["negative_routes"] == 0 for name, item in counts.items() if name not in ("known", "unsupported"))
    gate = coverage >= .8 and known["wrong_native_accepts"] == 0 and rate <= .05 and boundary and report["errors"] == 0
    require(report["quality_gate_passed"] == gate and report["known_correct_coverage"] == coverage
            and report["unsupported_route_acceptance_rate"] == rate, "quality gate or rate differs")
    require(retained == report["retained_worker_responses"] == report["worker"]["responses"]
            and null_frames == report["worker"]["host_time_abstentions"]
            and retained + null_frames == report["worker"]["attempts"] == 544, "worker inventory differs")
    return {"arm": arm, "input_sha256": sha(raw), "counts": counts, "known_correct_coverage": coverage,
            "unsupported_route_acceptance_rate": rate, "quality_gate_passed": gate,
            "retained_worker_frames": retained, "host_time_abstentions": null_frames,
            "owner_source_value_consistency_verified": True, "model_digest": report["model_digest"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.output.is_absolute() and (args.reports is None or args.reports.is_absolute()), "absolute evidence paths required")
    native = fixture()
    result = {"schema": "hepta.memory.v9.native-evidence-audit.v1", "fixture_sha256": NATIVE_SHA,
              "fixture_matches_independent_inputs": True, "models_executed": 0,
              "reports": [] if args.reports is None else [audit(args.reports / name, arm, native) for name, arm in ARMS.items()],
              "evidence_grants_authority": False, "population_risk_established": False}
    with args.output.open("x") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
