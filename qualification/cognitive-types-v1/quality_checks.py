#!/usr/bin/env python3
"""Execute real Rust decoders against independent Python/Node cases.

Fixtures are qualification inputs, never authenticated producer evidence. This
runner does not rewrite source and does not claim a source-mutation score.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ALGORITHM = b"canonical-json-utf8-sorted-keys-integer-only-preserve-unicode-v1"


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
    plasticity = copy.deepcopy(envelopes["PlasticityBatchV1"])
    row = copy.deepcopy(plasticity["payload"]["weightProposals"][0])
    row["newWeightQ16"], row["deltaPpm"] = 1024, 15625
    plasticity["payload"]["weightProposals"].insert(0, row)
    negative.append(("plasticity:logical-target-conflict", canonical(plasticity)))
    topology = copy.deepcopy(envelopes["TopologyProposalV1"])
    row = copy.deepcopy(topology["payload"]["typedNodesEdges"]["nodes"][0])
    row["label"] = "other-label"
    topology["payload"]["typedNodesEdges"]["nodes"].append(row)
    topology["payload"]["resourceDelta"].update(nodeDelta=2, residentBytesUpperBoundDelta=8192)
    negative.append(("topology:logical-node-conflict", canonical(topology)))
    return positive, negative


def invoke(argv, wire, expected=None):
    try:
        process = subprocess.run(argv, input=wire, capture_output=True, timeout=60, check=False)
        report = json.loads(process.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return {"passed": False, "status": "infrastructure_invalid", "error": str(error), "argv": argv}
    passed = process.returncode == 2 and report.get("outcome") == "rejected" if expected is None else (
        process.returncode == 0 and all(report.get(key) == value for key, value in expected.items()))
    return {"passed": passed, "status": "passed" if passed else "failed", "argv": argv,
            "exit_code": process.returncode, "report": report,
            "stdout_sha256": hashlib.sha256(process.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(process.stderr).hexdigest(),
            "stderr": process.stderr.decode(errors="replace")[-4000:]}


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
    # Bound every modality span and semantic-key count at their declared maxima.
    maximal = copy.deepcopy(next(envelope for name, envelope in positive if name == "MemoryEventV1:golden"))
    template = maximal["payload"]["modalitySpans"][0]
    maximal["payload"]["modalitySpans"] = [dict(copy.deepcopy(template), spanId=f"span:capacity:{index:02}") for index in range(32)]
    maximal["payload"]["semanticKeys"] = [f"key-{index:02}-" + "x" * 120 for index in range(64)]
    capacity = invoke([str(args.probe.resolve()), "--repeat", "128"], canonical(maximal), digests(maximal))
    results.append({"case": "event:maximum-span-and-key-counts", "implementation": "rust", **capacity})
    passed = bool(results) and all(item["passed"] for item in results)
    receipt = {"schema": "hepta.cognitive-types.differential-quality.v1", "passed": passed,
               "golden_contracts": 16, "positive_cases": len(positive), "negative_cases": len(negative),
               "source_mutation_score": None, "allocation_measurement": None,
               "capacity_profile": "maximum-span-and-semantic-key-counts-not-all-maximum-bytes",
               "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: value for key, value in receipt.items() if key != "results"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
