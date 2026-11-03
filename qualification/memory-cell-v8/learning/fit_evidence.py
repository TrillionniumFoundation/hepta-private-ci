"""Verify actual candidate payloads without importing NumPy or retraining."""

import base64
import json
import math
import struct

from allocation import PARTITION, learn_routes
from evidence import decode, digest, integer, owner_facts, read_json, require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def equivalent(left, right):
    """Rust summaries may round an f64 when parsing; raw worker bytes win."""
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(equivalent(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    if type(left) is float and type(right) is float:
        return math.isclose(left, right, rel_tol=1e-14, abs_tol=1e-15)
    return type(left) is type(right) and left == right


def verify_fit(path, facts, cut, count, trace, code_digest):
    envelope = read_json(path)
    require(set(envelope) == {"schema", "response_json", "host_measurement"}
            and envelope["schema"] == "hepta.memory.prospective-fit-evidence.v1", "fit evidence envelope")
    measurement = envelope["host_measurement"]
    require(isinstance(envelope["response_json"], str) and isinstance(measurement["request_json"], str),
            "exact worker input/output encodings must be strings")
    response_raw, request_raw = envelope["response_json"].encode(), measurement["request_json"].encode()
    result, request = decode(response_raw), decode(request_raw)
    require(len(response_raw) == measurement["response_bytes"] and len(request_raw) == measurement["request_bytes"],
            "training pipe byte count mismatch")
    require(digest(request_raw) == result["request_digest"], "fit request/response binding mismatch")
    require(measurement["training_code_digest"] == code_digest, "training code pin changed")
    require(request["schema"] == "hepta.memory.prospective-population-fit.v1"
            and request["routing_mode"] == ("learned" if trace is not None else "fixed")
            and request["routing_trace"] == trace, "fit received a different observation prefix")
    require(owner_facts(request["export"], cut) == facts, "fit source values differ from the current owner")
    configuration = {"shard_count": count, "seed": 91317, "steps": 600,
                     "dimension": 48, "total_hidden": 64, "threshold": 0.5}
    require(request["configuration"] == result["configuration"] == configuration, "fit budget changed")
    require(result["owner_cut_digest"] == cut and result["scope"] == request["export"]["scope"], "fit owner binding")
    receipt = result["receipt"]
    require(result["schema"] == f"hepta.memory.population-training-result.v{3 if trace else 2}"
            and receipt["fit_calls"] == 2 * count and receipt["clean_parameters"] is True
            and receipt["authority"] is False and receipt["language_model_finetuning"] is False,
            "fit provenance changed")
    integer(receipt["wall_ns"], "worker fit wall")
    integer(receipt["cpu_ns"], "worker CPU")
    integer(measurement["whole_training_process_wall_ns"], "training process wall")
    integer(measurement["stderr_bytes"], "training stderr byte count")
    parameters, catalogs, diagnostics = 0, 0, []
    for kind in ("semantic", "procedure"):
        support = {digest(entity.encode()): [values[kind][0]] for entity, values in facts.items()}
        addresses = sorted(support)
        routes = (learn_routes(addresses, count, trace)[0] if trace is not None
                  else {key: rank * count // len(addresses) for rank, key in enumerate(addresses)})
        artifact, report = result["artifacts"][kind], receipt["types"][kind]
        raw = artifact["native"].encode()
        require(digest(raw) == report["native_digest"] and len(raw) == report["serialized_bytes"], "native population digest")
        wire = decode(raw)
        require(wire["schema"] == f"hepta.memory.population.native.v{3 if trace else 2}"
                and wire["kind"] == kind and wire["routes"] == routes
                and wire["partition_profile"] == (PARTITION if trace else "hepta.memory.sha256-address-rank.v1"),
                "native routes differ from the declared allocation algorithm")
        require(wire.get("routing_trace") == trace and wire["lineage_sources"] == sorted(ids[0] for ids in support.values()),
                "native source lineage/trace mismatch")
        require(len(wire["shards"]) == len(report["shards"]) == len(artifact["originals"]) == count, "incomplete shard evidence")
        for index, (shard, shard_report, original) in enumerate(zip(wire["shards"], report["shards"], artifact["originals"])):
            payload = shard["payload"].encode()
            require(digest(payload) == shard["digest"] == shard_report["native_digest"], "shard byte digest mismatch")
            native, original_envelope = decode(payload), decode(original)
            original_value = original_envelope["payload"]
            require(digest(canonical(original_value)) == original_envelope["sha256"], "original training artifact digest")
            hidden = 64 // count + int(index < 64 % count)
            require(native["schema"] == "hepta.memory.associative-native.v1"
                    and original_value["schema"] == "hepta.memory.v6.associative-cell.v1", "actual parameter schema mismatch")
            for actual in (native, original_value):
                require(actual["kind"] == kind and actual["dimension"] == 48 and actual["hidden"] == hidden
                        and actual["threshold"] == 0.5 and actual["acceptance_enabled"] is True,
                        "actual trained model exceeds or changes the frozen parameter budget")
            training = original_value["training_receipt"]
            require(training == shard_report["training"], "raw shard training receipt mismatch")
            require(native["original_artifact_sha256"] == digest(original.encode())
                    and native["training_receipt_sha256"] == digest(canonical(training)), "native training linkage mismatch")
            selected = {key: ids for key, ids in support.items() if routes[key] == index}
            require(native["supports"] == original_value["supports"] == selected, "shard support differs from owner")
            require(native["lineage_sources"] == original_value["lineage_sources"] == sorted(ids[0] for ids in selected.values()),
                    "shard lineage differs from owner")
            tensors, originals = bytearray(), bytearray()
            shapes = {"A": [48, hidden], "a": [hidden], "B": [hidden, len(native["catalog"])], "b": [len(native["catalog"])]}
            for label, original_label in (("input_weights", "A"), ("hidden_bias", "a"), ("output_weights", "B"), ("output_bias", "b")):
                tensor = native["arrays"][label]
                require(isinstance(tensor, list) and len(tensor) == math.prod(shapes[original_label])
                        and all(type(value) in (int, float) for value in tensor)
                        and original_value["arrays"][original_label]["shape"] == shapes[original_label],
                        "actual tensor shape differs from the declared frozen budget")
                tensors.extend(struct.pack(f"<{len(tensor)}f", *tensor))
                originals.extend(base64.b64decode(original_value["arrays"][original_label]["data"], validate=True))
            require(tensors == originals and digest(tensors) == native["parameter_sha256"] == shard_report["parameter_digest"],
                    "native parameters differ from original trained weights")
            require(native["catalog"] == original_value["catalog"]
                    and training["kind"] == "actual-numpy-tanh-mlp-adam" and training["steps"] == 600
                    and training["parent_parameters"] is None and training["source_bound"] is True
                    and training["rows"] == len(selected) and training["examples_seen"] == 600 * len(selected),
                    "not a fresh actual source-bound fit")
            changed = training["initial_parameters"] != native["parameter_sha256"]
            diagnostics.append({"kind": kind, "shard": index, "parameter_update": changed,
                "initial_cross_entropy": training["initial_cross_entropy"], "final_cross_entropy": training["final_cross_entropy"],
                "training_accuracy": training["training_accuracy"], "training_diagnostic_is_future_evidence": False})
            require(len(tensors) == shard_report["parameter_bytes"]
                    and len(canonical(native["catalog"])) == shard_report["catalog_bytes"], "payload byte count mismatch")
            parameters += len(tensors)
            catalogs += shard_report["catalog_bytes"]
    return {"receipt": receipt, "measurement": measurement, "parameters_bytes": parameters,
            "catalog_bytes": catalogs, "diagnostics": diagnostics,
            "native_digests": {kind: receipt["types"][kind]["native_digest"] for kind in ("semantic", "procedure")}}


def verify_direct(acquisition, facts, export, budget):
    require(acquisition["schema"] == "hepta.memory.direct-owner-acquisition.v1"
            and acquisition["trained_models"] == 0 and acquisition["logical_cache_budget_bytes"] == budget * 2,
            "direct baseline acquisition profile mismatch")
    rows = {}
    pages = acquisition["pages"]
    require(1 <= len(pages) <= 512, "missing direct owner pages")
    for index, page in enumerate(pages):
        require(page["schema"] == "hepta.memory.owner-snapshot-page.v1" and page["scope"] == export["scope"]
                and page["owner_cut_digest"] == export["owner_cut_digest"], "direct owner page cut/scope mismatch")
        for row in page["records"]:
            require(row["source_id"] not in rows, "repeated direct owner source")
            rows[row["source_id"]] = row
        require(page["next_after"] == (page["records"][-1]["source_id"] if index + 1 < len(pages) else None),
                "incomplete direct pagination")
    expected = {row["source_id"]: row for row in export["records"] if row["source_id"] in export["current_source_ids"]}
    require(rows == expected, "direct baseline did not acquire the same actual owner facts")
    cache_bytes = len(json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())
    require(acquisition["logical_cache_bytes"] == cache_bytes, "direct cache byte count differs from actual acquired facts")
    integer(acquisition["logical_cache_bytes"], "direct cache bytes", 1)
    require(acquisition["logical_cache_bytes"] <= budget * 2 and len(facts) == 25, "direct cache exceeds common budget")
