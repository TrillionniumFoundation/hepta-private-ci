#!/usr/bin/env python3
"""Execute real Rust decoders against independent Python/Node cases.

Fixtures are qualification inputs, never authenticated producer evidence. This
runner does not rewrite source and does not claim a source-mutation score.
Performance observations use a maximum-collection MemoryEvent profile and are
reported without an uncalibrated pass/fail latency threshold.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import re

from probe_execution import invoke_probe

ALGORITHM = b"canonical-json-utf8-sorted-keys-integer-only-preserve-unicode-v1"
MAX_EVENT_SPANS = 32
MAX_EVENT_BINDINGS = 32
MAX_EVENT_SEMANTIC_KEYS = 64
MAX_EVENT_PROVENANCE = 64
MAX_EVENT_REFERENCES = 64
PERFORMANCE_REPEATS = 256
PERFORMANCE_SAMPLES = 3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def framed(part):
    return len(part).to_bytes(8, "big") + part


def digests(envelope):
    payload = canonical(envelope["payload"])
    contract = envelope["contract"].encode()
    frozen = hashlib.sha256(b"hepta.cognitive.contract.canonical-json.v1\0" + contract + b"\0" + payload).hexdigest()
    bound = hashlib.sha256(b"hepta.cognitive.contract.bound-digest.v1\0" + framed(envelope["schema"].encode())
                           + (1).to_bytes(4, "big") + framed(contract) + framed(ALGORITHM) + framed(payload)).hexdigest()
    return {"outcome": "accepted", "contract": envelope["contract"], "encoded_bytes": len(canonical(envelope)),
            "wire_sha256": hashlib.sha256(canonical(envelope)).hexdigest(),
            "frozen_sha256": frozen, "bound_sha256": bound}


def load_vectors(root):
    vectors = []
    for version in (1, 2):
        path = root / f"qualification/cognitive-types-v{version}/verify_vectors.py"
        spec = importlib.util.spec_from_file_location(f"cognitive_v{version}_oracle", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        vectors.extend(module.VECTORS)
    if len(vectors) != 16 or len({item[0] for item in vectors}) != 16:
        raise ValueError("expected exactly 12 V1 and four V2 contract vectors")
    return vectors


def cases(vectors):
    positive, negative, envelopes = [], [], {}
    for contract, schema, payload, golden in vectors:
        envelope = {"contract": contract, "schema": schema, "schemaVersion": 1, "payload": copy.deepcopy(payload)}
        if digests(envelope)["frozen_sha256"] != golden:
            raise ValueError(f"golden vector drift: {contract}")
        envelopes[contract] = envelope
        positive.append((contract + ":golden", envelope))
        negative.append((contract + ":whitespace", b" " + canonical(envelope)))
        negative.append((contract + ":duplicate-key", b'{"contract":"other",' + canonical(envelope)[1:]))
        for name, replacement in [("schemaVersion", 2), ("schema", "unknown.schema"), ("contract", "UnknownContract")]:
            mutant = copy.deepcopy(envelope)
            mutant[name] = replacement
            negative.append((contract + ":" + name, canonical(mutant)))
        mutant = copy.deepcopy(envelope)
        mutant["payload"]["unknownCriticalField"] = True
        negative.append((contract + ":unknown-field", canonical(mutant)))

    span = envelopes["ModalitySpanRefV1"]
    for end in (2**53 + 1, 2**64 - 1):
        mutant = copy.deepcopy(span)
        mutant["payload"]["range"] = {"kind": "byte_range", "start": end - 1, "end": end}
        positive.append((f"span:u64:{end}", mutant))
    for pointer in ("/é", "/e\u0301", "/~0/~1", ""):
        mutant = copy.deepcopy(span)
        mutant["payload"]["modality"] = "structured_data"
        mutant["payload"]["range"] = {"kind": "json_pointer", "pointer": pointer}
        positive.append(("span:pointer:" + pointer, mutant))
    for pointer in ("/~", "/~2", "missing-leading-slash"):
        mutant = copy.deepcopy(span)
        mutant["payload"]["modality"] = "structured_data"
        mutant["payload"]["range"] = {"kind": "json_pointer", "pointer": pointer}
        negative.append(("span:invalid-pointer:" + pointer, canonical(mutant)))

    event = copy.deepcopy(envelopes["MemoryEventV1"])
    row = copy.deepcopy(event["payload"]["provenance"][0])
    row["observedAtUnixMs"] += 1
    event["payload"]["provenance"].append(row)
    negative.append(("event:logical-provenance-conflict", canonical(event)))
    recall = copy.deepcopy(envelopes["RecallPacketV1"])
    row = copy.deepcopy(recall["payload"]["selectedEvents"][0])
    row["eventDigest"] = "9" * 64
    recall["payload"]["selectedEvents"].append(row)
    recall["payload"]["resourceReceipt"]["candidateEventCount"] = 2
    negative.append(("recall:logical-event-conflict", canonical(recall)))

    recall = copy.deepcopy(envelopes["RecallPacketV1"])
    row = copy.deepcopy(recall["payload"]["activeNodes"][0])
    row["activationPpm"] += 1
    recall["payload"]["activeNodes"].append(row)
    recall["payload"]["resourceReceipt"]["activeNodeCount"] = 2
    recall["payload"]["resourceReceipt"]["nodeCount"] = 2
    negative.append(("recall:logical-active-node-conflict", canonical(recall)))

    recall = copy.deepcopy(envelopes["RecallPacketV1"])
    path = {
        "sourceNodeId": "node:1",
        "targetNodeId": "node:2",
        "relation": "associative",
        "contributionPpm": 1,
    }
    duplicate_path = copy.deepcopy(path)
    duplicate_path["contributionPpm"] = 2
    recall["payload"]["activationPaths"] = [path, duplicate_path]
    recall["payload"]["resourceReceipt"]["nodeCount"] = 2
    recall["payload"]["resourceReceipt"]["synapseCount"] = 2
    negative.append(("recall:logical-activation-path-conflict", canonical(recall)))

    recall = copy.deepcopy(envelopes["RecallPacketV1"])
    recall["payload"]["activationPaths"] = [path]
    recall["payload"]["resourceReceipt"].update(nodeCount=2, synapseCount=1)
    positive.append(("recall:resource-exact", copy.deepcopy(recall)))
    for name, field, count in [
        ("recall:underreported-synapses", "synapseCount", 0),
        ("recall:underreported-path-nodes", "nodeCount", 1),
    ]:
        underreported = copy.deepcopy(recall)
        underreported["payload"]["resourceReceipt"][field] = count
        negative.append((name, canonical(underreported)))
    recall["payload"]["contradictions"] = [
        {"leftNodeId": "node:1", "rightNodeId": "node:3"}
    ]
    negative.append(("recall:underreported-contradiction-nodes", canonical(recall)))

    plasticity = copy.deepcopy(envelopes["PlasticityBatchV1"])
    row = copy.deepcopy(plasticity["payload"]["weightProposals"][0])
    row["newWeightQ16"], row["deltaPpm"] = 1024, 15625
    plasticity["payload"]["weightProposals"].insert(0, row)
    negative.append(("plasticity:logical-target-conflict", canonical(plasticity)))

    plasticity = copy.deepcopy(envelopes["PlasticityBatchV1"])
    row = copy.deepcopy(plasticity["payload"]["thresholdProposals"][0])
    row["newThresholdQ16"], row["deltaPpm"] = -1024, -15625
    plasticity["payload"]["thresholdProposals"].append(row)
    negative.append(("plasticity:logical-threshold-conflict", canonical(plasticity)))

    topology = copy.deepcopy(envelopes["TopologyProposalV1"])
    row = copy.deepcopy(topology["payload"]["typedNodesEdges"]["nodes"][0])
    row["label"] = "other-label"
    topology["payload"]["typedNodesEdges"]["nodes"].append(row)
    topology["payload"]["resourceDelta"].update(nodeDelta=2, residentBytesUpperBoundDelta=8192)
    negative.append(("topology:logical-node-conflict", canonical(topology)))
    return positive, negative


def digest_hex(value):
    """Return a non-zero, exact lowercase SHA-256-shaped value."""
    return f"{value:064x}"


def maximal_memory_event(golden):
    """Build one valid event with every declared collection at its count ceiling."""
    maximal = copy.deepcopy(golden)
    payload = maximal["payload"]
    spans = []
    for index in range(MAX_EVENT_SPANS):
        text = index % 2 == 0
        spans.append({
            "spanId": f"span:capacity:{index:02}",
            "modality": "text" if text else "image",
            "assetSha256": digest_hex(1_000 + index),
            "range": (
                {"kind": "byte_range", "start": index, "end": index + 1}
                if text else
                {"kind": "pixel_rect", "x": 0, "y": 0, "width": 1, "height": 1}
            ),
            "preprocessorManifestSha256": digest_hex(2_000 + index),
            "featureBlobSha256": None,
            "symbolicProjectionSha256": None,
            "uncertaintyPpm": index,
            "privacyClass": "agent_private",
            "redactionMaskSha256": None,
        })
    payload["modalitySpans"] = spans
    payload["crossModalBindings"] = [
        {
            "bindingId": f"binding:capacity:{index:02}",
            "eventId": payload["eventId"],
            "spanRefs": ["span:capacity:00", "span:capacity:01"],
            "alignmentKind": "same_observation",
            "confidencePpm": 1_000_000 - index,
            "producerManifestSha256": digest_hex(3_000 + index),
        }
        for index in range(MAX_EVENT_BINDINGS)
    ]
    payload["semanticKeys"] = [
        f"key-{index:02}-" + "x" * 120 for index in range(MAX_EVENT_SEMANTIC_KEYS)
    ]
    payload["provenance"] = [
        {
            "sourceId": f"source:capacity:{index:02}",
            "sourceRevision": 1,
            "sourceSha256": digest_hex(4_000 + index),
            "observedAtUnixMs": index + 1,
        }
        for index in range(MAX_EVENT_PROVENANCE)
    ]
    payload["causalParents"] = [
        f"event:causal:{index:02}" for index in range(MAX_EVENT_REFERENCES)
    ]
    payload["temporalNeighbors"] = [
        f"event:temporal:{index:02}" for index in range(MAX_EVENT_REFERENCES)
    ]
    return maximal


def invoke(argv, wire, expected=None):
    return invoke_probe(argv, wire, expected)


def performance_summary(samples):
    invalid = {"measurementValid": False, "error": "incomplete or invalid performance observations"}
    if type(samples) is not list or len(samples) != PERFORMANCE_SAMPLES:
        return invalid
    elapsed = []
    encoded_bytes = None
    observed_identity = None
    for index, sample in enumerate(samples, 1):
        if (type(sample) is not dict or sample.get("passed") is not True
                or sample.get("status") != "passed" or type(sample.get("exit_code")) is not int
                or sample["exit_code"] != 0 or type(sample.get("sample")) is not int
                or sample["sample"] != index or sample.get("implementation") != "rust"
                or sample.get("case") != "event:maximum-declared-collection-counts"):
            return invalid
        report = sample.get("report")
        if type(report) is not dict or report.get("outcome") != "accepted" or report.get("contract") != "MemoryEventV1":
            return invalid
        duration, repeat, size = (report.get(key) for key in ("elapsed_ns", "repeat", "encoded_bytes"))
        # The existing Rust probe encodes its u128 nanoseconds as a decimal
        # string. Preserve that explicit profile; do not coerce arbitrary JSON.
        if (type(duration) is not str or re.fullmatch(r"[1-9][0-9]{0,38}", duration) is None
                or type(repeat) is not int or type(size) is not int
                or repeat != PERFORMANCE_REPEATS or size <= 0):
            return invalid
        duration = int(duration)
        if duration >= 2**128:
            return invalid
        identity = tuple(report.get(key) for key in ("wire_sha256", "frozen_sha256", "bound_sha256"))
        if (any(type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in identity)
                or sample.get("wire_sha256") != identity[0]
                or (observed_identity is not None and observed_identity != identity)
                or (encoded_bytes is not None and size != encoded_bytes)):
            return invalid
        observed_identity, encoded_bytes = identity, size
        elapsed.append(duration)
    per_round_trip = [duration / PERFORMANCE_REPEATS for duration in elapsed]
    return {
        "measurementValid": True,
        "profile": "memory-event-v1-all-declared-collections-at-count-ceilings",
        "samples": len(samples),
        "roundTripsPerSample": PERFORMANCE_REPEATS,
        "encodedBytes": encoded_bytes,
        "elapsedNs": elapsed,
        "nsPerDecodeValidateEncode": {
            "minimum": min(per_round_trip),
            "median": statistics.median(per_round_trip),
            "maximum": max(per_round_trip),
        },
        "allocationMeasurement": None,
        "allocationMeasurementReason": "qualification probe does not install a global allocator instrumentor",
        "latencyThresholdEnforced": False,
        "thresholdReason": "observation-only until runner and toolchain baselines are independently calibrated",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    positive, negative = cases(load_vectors(root))
    results = []
    for name, envelope in positive:
        wire, expected = canonical(envelope), digests(envelope)
        for implementation, command in [("rust", [str(args.probe.resolve())]),
                                        ("node", ["node", str(Path(__file__).with_name("verify_lossless_wire.mjs"))])]:
            results.append({"case": name, "implementation": implementation,
                            "wire_sha256": hashlib.sha256(wire).hexdigest(),
                            **invoke(command, wire, expected)})
    for name, wire in negative:
        results.append({"case": name, "implementation": "rust", "wire_sha256": hashlib.sha256(wire).hexdigest(),
                        **invoke([str(args.probe.resolve())], wire)})

    golden_event = next(envelope for name, envelope in positive if name == "MemoryEventV1:golden")
    maximal = maximal_memory_event(golden_event)
    maximal_wire = canonical(maximal)
    maximal_expected = digests(maximal)
    performance_samples = []
    for sample_index in range(PERFORMANCE_SAMPLES):
        sample = invoke(
            [str(args.probe.resolve()), "--repeat", str(PERFORMANCE_REPEATS)],
            maximal_wire,
            maximal_expected,
        )
        sample.update({
            "case": "event:maximum-declared-collection-counts",
            "implementation": "rust",
            "sample": sample_index + 1,
            "wire_sha256": hashlib.sha256(maximal_wire).hexdigest(),
        })
        performance_samples.append(sample)
        results.append(sample)
    performance = performance_summary(performance_samples)

    passed = (
        bool(results)
        and all(item["passed"] for item in results)
        and performance.get("measurementValid") is True
    )
    receipt = {
        "schema": "hepta.cognitive-types.differential-quality.v1",
        "passed": passed,
        "golden_contracts": 16,
        "positive_cases": len(positive),
        "negative_cases": len(negative),
        "source_mutation_score": None,
        "capacity_profile": "memory-event-v1-all-declared-collections-at-count-ceilings",
        "capacity_counts": {
            "modalitySpans": MAX_EVENT_SPANS,
            "crossModalBindings": MAX_EVENT_BINDINGS,
            "semanticKeys": MAX_EVENT_SEMANTIC_KEYS,
            "provenance": MAX_EVENT_PROVENANCE,
            "causalParents": MAX_EVENT_REFERENCES,
            "temporalNeighbors": MAX_EVENT_REFERENCES,
        },
        "performance": performance,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key != "results"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
