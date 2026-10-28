"""Verify complete population tensors, causal route locks and native gate bytes."""

from evidence import canonical, decode, digest, integer, owner_facts, read_json, require
from model_evidence import artifact
from structure_selection import select


def worker(directory, code):
    request, response = (read_json(directory / name) for name in ("FIT_REQUEST.json", "FIT_RESPONSE.json"))
    frame, result = decode(request["request_json"]), decode(response["response_json"])
    require(request["code_identity"] == response["code_identity"] == code, "structure worker source differs")
    require(digest(request["request_json"].encode()) == request["request_sha256"] == result["request_digest"], "structure request digest")
    require(response["request_bytes"] == len(request["request_json"].encode()) <= 16777216
            and response["response_bytes"] == len(response["response_json"].encode()) <= 16777216
            and response["stderr_bytes"] == len(response["stderr"].encode()) <= 8192
            and response["exit_code"] == 0, "structure worker bounds/exit")
    integer(response["whole_worker_wall_ns"], "structure whole worker wall", 1)
    return frame, result, {"whole_worker_wall_ns": response["whole_worker_wall_ns"],
                           "request_bytes": response["request_bytes"], "response_bytes": response["response_bytes"]}


def selection(directory, code, export, prefix, claimed):
    frame, result, cost = worker(directory, code)
    facts = owner_facts(export)
    observations = []
    for index, record in enumerate(prefix["records"]):
        observations.append({"sequence": index + 1, "request_digest": record["request_digest"],
                             "readout_digest": record["readout_digest"],
                             "addresses": sorted({digest(query["entity"].encode()) for query in record["requests"]})})
    require(frame == {"schema": "hepta.memory.v9.structure-selection.v1", "source_cut_digest": export["owner_cut_digest"],
                      "addresses": sorted(digest(entity.encode()) for entity in facts),
                      "observations": observations, "resident_budget_bytes": 16384}, "selector saw facts, future labels or invented coaccess")
    expected = select(frame)
    for key in expected.keys() - {"wall_ns"}:
        require(result[key] == expected[key], "prefix-only selection cannot be reproduced")
    require(result == claimed, "selected routes differ from exact worker response")
    return result, cost


def population(directory, code, export, count, selected=None):
    frame, result, cost = worker(directory, code)
    config = {"shard_count": count, "seed": 91317, "steps": 600, "dimension": 48, "total_hidden": 64, "threshold": 0.5}
    trace = None if selected is None else selected["trace"]
    require(frame == {"schema": "hepta.memory.prospective-population-fit.v1", "export": export,
                      "configuration": config, "routing_mode": "fixed" if trace is None else "learned", "routing_trace": trace},
            "population worker scope or fitting budget differs")
    require(result["schema"] == ("hepta.memory.population-training-result.v2" if trace is None else "hepta.memory.population-training-result.v3")
            and result["configuration"] == config and result["owner_cut_digest"] == export["owner_cut_digest"]
            and result["scope"] == export["scope"] and result["receipt"]["fit_calls"] == 2 * count, "population result binding")
    facts = owner_facts(export)
    addresses = sorted(digest(entity.encode()) for entity in facts)
    routes = {address: rank * count // len(addresses) for rank, address in enumerate(addresses)} if trace is None else next(
        item["routes"] for item in selected["candidates"] if item["mode"] == "learned" and item["count"] == count)
    report = {}
    for kind in ("semantic", "procedure"):
        payload = result["artifacts"][kind]
        require(set(payload) == {"native", "originals"}, "population payload fields")
        raw = payload["native"].encode()
        model = decode(raw)
        fields = {"schema", "kind", "partition_profile", "shards", "routes", "lineage_sources"}
        require(set(model) == fields | ({"routing_trace"} if trace is not None else set()), "population fields")
        require(model["schema"] == ("hepta.memory.population.native.v2" if trace is None else "hepta.memory.population.native.v3")
                and model["kind"] == kind and model["routes"] == routes
                and model["partition_profile"] == ("hepta.memory.sha256-address-rank.v1" if trace is None else "hepta.memory.causal-coaccess-greedy.v1")
                and len(model["shards"]) == len(payload["originals"]) == count, "population route/count contract")
        if trace is not None:
            require(model["routing_trace"] == trace, "native learned trace differs from completed prefix")
        lineage = sorted(row[kind][0] for row in facts.values())
        require(model["lineage_sources"] == lineage, "complete population ancestry")
        receipt = result["receipt"]["types"][kind]
        require(receipt["native_digest"] == digest(raw) and receipt["serialized_bytes"] == len(raw)
                and len(receipt["shards"]) == count, "population receipt identity")
        sizes = []
        for index, (shard, original, evidence) in enumerate(zip(model["shards"], payload["originals"], receipt["shards"])):
            require(set(shard) == {"digest", "payload"} and shard["digest"] == digest(shard["payload"].encode()), "shard raw digest")
            subset = {entity: row for entity, row in facts.items() if routes[digest(entity.encode())] == index}
            width = 64 // count + int(index < 64 % count)
            enriched = dict(evidence, original_digest=digest(original.encode()))
            _, _, measured = artifact({"native": shard["payload"], "original": original}, "catalog", kind, subset, enriched, (48, width))
            require(evidence["training"]["steps"] == 600 and evidence["source_ids"] == sorted(row[kind][0] for row in subset.values())
                    and evidence["original_bytes"] == len(original.encode()), "shard training/provenance receipt")
            sizes.append(measured)
        report[kind] = {"native_digest": digest(raw), "native_bytes": len(raw), "parameter_bytes": sum(item["parameter_bytes"] for item in sizes),
                        "catalog_bytes": sum(item["catalog_bytes"] for item in sizes), "shards": sizes, "routes": routes}
    return report, cost


def verify_gate(gate, roles, code, cut):
    rows = gate["measurements"]
    require([row["shards"] for row in rows if row["role"] == "Fixed"] == list(range(1, 9))
            and sum(row["role"] == "KeepFixed" for row in rows) == 1, "native gate lost strong fixed inventory")
    raw = bytearray(b"hepta.memory.structure-cost.v1")
    for number in (16777216, 32768, 100000, 0, 1000000000, 1, 1, 1):
        raw.extend(number.to_bytes(8, "little"))
    raw.extend(bytes([8, *range(1, 9)]))
    required = ("source_ledger_bytes", "search_wall_ns", "training_wall_ns", "replay_wall_ns", "read_compute_wall_ns",
                "wake_wall_ns", "communication_wall_ns", "communication_bytes")
    for row in rows:
        require(row["source_cut_digest"] == cut and row["training_profile_digest"] == code["digest"]
                and row["independent_evaluation"] is True, "gate measured source/profile")
        actual = next(item for item in roles if item["publication"].get("bundle_digest") == row["artifact_digest"])
        require(row["shards"] == actual["shards"] and row["queries"] == actual["phases"][0]["queries"]
                and row["errors"] == actual["phases"][0]["queries"] - actual["phases"][0]["correct"]
                and row["retention_queries"] == actual["phases"][1]["queries"]
                and row["retention_errors"] == actual["phases"][1]["queries"] - actual["phases"][1]["correct"], "gate outcomes differ from actual role")
        for name in ("artifact_digest", "source_cut_digest", "task_set_digest", "training_profile_digest"):
            raw.extend(bytes.fromhex(row[name]))
        raw.extend(bytes([{"KeepFixed": 0, "Fixed": 1, "Split": 2, "Merge": 3}[row["role"]], row["shards"], 1]))
        values = [row[name] for name in ("queries", "errors", "retention_queries", "retention_errors")]
        values.extend(row["cost"][name] for name in ("artifact_bytes", "raw_cache_bytes", "resident_payload_bytes", "resident_metadata_bytes", "catalog_bytes", "route_bytes"))
        for number in values:
            raw.extend(integer(number, "gate cost").to_bytes(8, "little"))
        for name in required:
            value = row["cost"][name]
            raw.append(int(value is not None))
            raw.extend((0 if value is None else integer(value, name)).to_bytes(8, "little"))
        require(row["cost"]["communication_wall_ns"] is None and row["cost"]["search_wall_ns"] is None
                and row["cost"]["replay_wall_ns"] is None, "unknown exclusive measurements became invented zero")
    require(gate["evidence_digest"] == digest(raw) and gate["reason"] == "MissingMeasurements"
            and gate["proposed_digest"] is None and gate["owner_publication_performed"] is False
            and gate["proposal_candidates"] == 1 and gate["full_cost_gain_established"] is False, "native measured NoChange gate mismatch")
