#!/usr/bin/env python3
"""Independent Python oracle for all cognitive.types canonical JSON V1 vectors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = b"hepta.cognitive.contract.canonical-json.v1\0"


def repeated(character: str) -> str:
    return character * 64


SPAN = {
    "spanId": "span:1",
    "modality": "text",
    "assetSha256": repeated("a"),
    "range": {"kind": "byte_range", "start": 0, "end": 4},
    "preprocessorManifestSha256": repeated("b"),
    "featureBlobSha256": None,
    "symbolicProjectionSha256": None,
    "uncertaintyPpm": 10_000,
    "privacyClass": "agent_private",
    "redactionMaskSha256": None,
}

VECTORS: list[tuple[str, str, dict[str, object], str]] = [
    (
        "ModalitySpanRefV1",
        "hepta.hnmf.modality-span-ref.v1",
        SPAN,
        "1e1c8f2232a1f6ddfea98400f3c2ae9d29ecd39ae2a2ff0e0bac70f91f0ad273",
    ),
    (
        "MemoryEventV1",
        "hepta.hnmf.memory-event.v1",
        {
            "eventId": "event:1",
            "episodeId": "episode:1",
            "scope": {"kind": "agent_private", "agentId": "agent:a"},
            "observedInterval": {"startUnixMs": 1, "endUnixMs": None},
            "modalitySpans": [SPAN],
            "crossModalBindings": [],
            "semanticKeys": ["door"],
            "provenance": [
                {
                    "sourceId": "source:1",
                    "sourceRevision": 1,
                    "sourceSha256": repeated("c"),
                    "observedAtUnixMs": 1,
                }
            ],
            "verification": "verified",
            "retentionPolicy": {"kind": "persistent", "retainUntilUnixMs": None},
            "objectiveDigest": repeated("d"),
            "nduStateDigest": repeated("e"),
            "causalParents": [],
            "temporalNeighbors": [],
            "behaviorPropensityPpm": 500_000,
            "lifecycle": {"state": "active"},
        },
        "22d5a29e55ad08c3541eb8eb9afe577eb5efd1a75e0d37ea1c64eae436db0540",
    ),
    (
        "CrossModalBindingV1",
        "hepta.hnmf.cross-modal-binding.v1",
        {
            "bindingId": "binding:1",
            "eventId": "event:1",
            "spanRefs": ["span:1", "span:2"],
            "alignmentKind": "same_observation",
            "confidencePpm": 900_000,
            "producerManifestSha256": repeated("f"),
        },
        "4f85c20ffc206e5fe472dfd5be8ab7a71e5d79eb8661bce6dcb5a8f8284b777f",
    ),
    (
        "EngramNodeV1",
        "hepta.hnmf.engram-node.v1",
        {
            "nodeId": "node:1",
            "population": "semantic_concept",
            "modalityMask": ["text"],
            "semanticKeys": ["door"],
            "supportManifestSha256": repeated("1"),
            "thresholdQ16": 12,
            "targetActivityPpm": 100_000,
            "confidencePpm": 900_000,
            "validFromUnixMs": 1,
            "validToUnixMs": None,
            "snapshotGeneration": 1,
        },
        "5b7f4f5addf00b7e331d6682e9fb5be99dbc438d4cfc915ac536e8a16dcb23c5",
    ),
    (
        "SynapseV1",
        "hepta.hnmf.synapse.v1",
        {
            "sourceNodeId": "node:1",
            "targetNodeId": "node:2",
            "relation": "associative",
            "weightQ16": 100,
            "delaySteps": 1,
            "plasticityClass": "eligibility_gated",
            "eligibilityPpm": 0,
            "supportManifestSha256": repeated("2"),
            "snapshotGeneration": 1,
        },
        "1649b8d6d428cd485dfbf2c46b2b0b82f41baec6c1cd0bee5da7a511cad93d6c",
    ),
    (
        "MemoryCueV1",
        "hepta.hnmf.memory-cue.v1",
        {
            "cueId": "cue:1",
            "objectiveDigest": repeated("3"),
            "nduStateDigest": repeated("4"),
            "modalities": ["text"],
            "semanticKeys": ["door"],
            "seedNodeIds": ["node:1"],
            "nowUnixMs": 10,
            "resourceBudget": {
                "maximumCandidateEvents": 512,
                "maximumNodes": 4096,
                "maximumSynapses": 32768,
                "maximumActiveNodes": 4096,
                "maximumActivePerPopulation": 64,
                "maximumRecurrentSteps": 4,
                "maximumRecallEvents": 16,
                "maximumActivationPaths": 32,
            },
        },
        "27adab5830e8849e2ac765bf69728bfb10d000caaa639c84e2cec9e3adec5a00",
    ),
    (
        "RecallPacketV1",
        "hepta.hnmf.recall-packet.v1",
        {
            "cueDigest": repeated("5"),
            "eventSnapshotDigest": repeated("6"),
            "engramSnapshotDigest": repeated("7"),
            "selectedEvents": [
                {
                    "eventId": "event:1",
                    "revision": 1,
                    "eventDigest": repeated("8"),
                }
            ],
            "activeNodes": [
                {
                    "nodeId": "node:1",
                    "population": "semantic_concept",
                    "activationPpm": 800_000,
                }
            ],
            "activationPaths": [],
            "contradictions": [],
            "coveragePpm": 900_000,
            "confidencePpm": 800_000,
            "oodPpm": 100_000,
            "abstain": None,
            "resourceReceipt": {
                "candidateEventCount": 1,
                "nodeCount": 1,
                "synapseCount": 0,
                "activeNodeCount": 1,
                "settlingSteps": 1,
            },
        },
        "0a3ec1c285ce6f7c710c975c79497a870c2d9c6a91696e22c16a11c43b0983fc",
    ),
    (
        "OutcomeSignalV1",
        "hepta.hnmf.outcome-signal.v1",
        {
            "episodeId": "episode:1",
            "utilityDeltaPpm": 10_000,
            "predictionErrorPpm": 20_000,
            "noveltyPpm": 30_000,
            "riskPpm": 40_000,
            "oodPpm": 50_000,
            "observerDigest": repeated("9"),
        },
        "78294b30bac6687f2332b4294471d3ba609bb827e0b01ec77280e2eeedc07a0d",
    ),
    (
        "ReplaySelectionReceiptV1",
        "hepta.hnmf.replay-selection-receipt.v1",
        {
            "candidateSetDigest": repeated("a"),
            "selectedEventIds": ["event:1"],
            "sourceBucketCounts": [{"sourceBucket": 1, "selectedCount": 1}],
            "selectionPolicyDigest": repeated("b"),
            "resourceReceipt": {
                "candidateCount": 1,
                "selectedCount": 1,
                "maximumPerSourceBucket": 1,
            },
        },
        "94f4265ca6c39c314e1d350aba45d78dd6b9aa973bfd740f8bb81df0995a5787",
    ),
    (
        "PlasticityBatchV1",
        "hepta.hnmf.plasticity-batch.v1",
        {
            "predecessorGeneration": 1,
            "nextGeneration": 2,
            "outcomeSignalDigest": repeated("c"),
            "weightProposals": [
                {
                    "sourceNodeId": "node:1",
                    "targetNodeId": "node:2",
                    "relation": "associative",
                    "oldWeightQ16": 0,
                    "newWeightQ16": 2048,
                    "deltaPpm": 31_250,
                }
            ],
            "thresholdProposals": [
                {
                    "nodeId": "node:1",
                    "oldThresholdQ16": 0,
                    "newThresholdQ16": -2048,
                    "deltaPpm": -31_250,
                }
            ],
            "currentSnapshotImmutable": True,
            "productionActivationAllowed": False,
        },
        "779fc9779a6a170aba791fd4c984eb35855d5cbc394c37945123bc0ddf8dd41a",
    ),
    (
        "TopologyProposalV1",
        "hepta.hnmf.topology-proposal.v1",
        {
            "proposalId": "topology-proposal:1",
            "predecessorTopologyDigest": repeated("d"),
            "operation": "add",
            "typedNodesEdges": {
                "nodes": [
                    {
                        "nodeId": "node:3",
                        "population": "meta_memory",
                        "label": "new-node",
                    }
                ],
                "edges": [],
            },
            "compatibilityPlanDigest": repeated("e"),
            "resourceDelta": {
                "nodeDelta": 1,
                "edgeDelta": 0,
                "residentBytesUpperBoundDelta": 4096,
            },
            "securityReviewDigest": repeated("f"),
            "lesionPlanDigest": repeated("1"),
            "rollbackPlanDigest": repeated("2"),
            "state": "qualification_required",
        },
        "83fed9c7f5a4677f9564ac36b524cf8865effc27f032ca465d4368c114ac40aa",
    ),
    (
        "ForgetPropagationReceiptV1",
        "hepta.hnmf.forget-propagation-receipt.v1",
        {
            "eventId": "event:1",
            "predecessorGeneration": 1,
            "nextGeneration": 2,
            "retiredNodeIds": ["node:1"],
            "retiredSynapses": [],
            "projectionRebuildRequired": True,
            "artifactRevocationRequired": True,
        },
        "f0f4f746a2c2e3f5a22bd5d5ce1760185d5c6579ef0bb6e5a23b1722edbfd62b",
    ),
]


def canonical(value: object) -> bytes:
    # Python's sorted-key compact JSON is intentionally independent from the
    # Rust recursive writer but implements the same V1 contract.
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_digest(contract: str, payload: object) -> str:
    return hashlib.sha256(
        DOMAIN + contract.encode("ascii") + b"\0" + canonical(payload)
    ).hexdigest()


def main() -> int:
    wire = (ROOT / "codex-rs/hepta-cognitive-types/src/wire.rs").read_text(
        encoding="utf-8"
    )
    tests = (ROOT / "codex-rs/hepta-cognitive-types/src/contract_tests.rs").read_text(
        encoding="utf-8"
    )
    registry = json.loads(
        (ROOT / "docs/contracts/PROTOCOL_SCHEMAS.json").read_text(encoding="utf-8")
    )
    registered = {row["id"]: row for row in registry["protocols"]}

    observed: dict[str, str] = {}
    envelope_sizes: dict[str, int] = {}
    for contract, schema, payload, expected in VECTORS:
        actual = semantic_digest(contract, payload)
        if actual != expected:
            raise SystemExit(f"{contract} canonical digest mismatch: {actual}")
        envelope = {
            "schema": schema,
            "schemaVersion": 1,
            "contract": contract,
            "payload": payload,
        }
        envelope_sizes[contract] = len(canonical(envelope))
        observed[contract] = actual

        row = registered.get(contract)
        if row is None or row.get("canonicalEncoding") != "canonical_json_utf8":
            raise SystemExit(f"{contract} protocol registration is missing or noncanonical")
        for token in (contract, schema):
            if token not in wire:
                raise SystemExit(f"Rust wire implementation missing token: {token}")
        if expected not in tests:
            raise SystemExit(f"Rust golden digest vector is missing: {contract}")

    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_TYPES_V1_CROSS_LANGUAGE_VECTOR",
                "vectorCount": len(VECTORS),
                "digests": observed,
                "canonicalEnvelopeBytes": envelope_sizes,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
