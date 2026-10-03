#!/usr/bin/env python3
"""Independent canonical JSON/digest oracle for shared-experience V2 contracts."""

import hashlib
import json
from pathlib import Path

DOMAIN = b"hepta.cognitive.contract.canonical-json.v1\0"


def repeated(character: str) -> str:
    return character * 64


def canonical(value: object) -> bytes:
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


GRANTS: list[dict[str, object]] = [
    {
        "grantId": "grant:artifact",
        "useClass": {
            "kind": "derived_artifact_use",
            "artifactId": "artifact:candidate",
            "artifactConsumerId": "agent:receiver",
            "artifactLineageSha256": repeated("4"),
        },
        "validFromUnixMs": 100,
        "expiresAtUnixMs": 1_000,
    },
    {
        "grantId": "grant:read",
        "useClass": {
            "kind": "raw_evidence_read",
            "consumerId": "agent:receiver",
            "consumerWorkspaceSha256": repeated("1"),
        },
        "validFromUnixMs": 100,
        "expiresAtUnixMs": 1_000,
    },
    {
        "grantId": "grant:train",
        "useClass": {
            "kind": "purpose_bound_training",
            "trainerId": "learning.operator",
            "purposeId": "purpose:domain-adaptation",
            "parameterScopeSha256": repeated("2"),
            "datasetSplitSha256": repeated("3"),
        },
        "validFromUnixMs": 100,
        "expiresAtUnixMs": 1_000,
    },
]

PUBLICATION: dict[str, object] = {
    "publicationOperationId": "operation:publish",
    "contributionId": "contribution:1",
    "sourceOwnerId": "agent:source",
    "sourceOwnerEpoch": 7,
    "sourceKind": "canonical_memory_event",
    "sourceRecordId": "event:source",
    "sourceRevision": 9,
    "sourceRecordSha256": repeated("5"),
    "semanticContentSha256": repeated("6"),
    "sourceScopeSha256": repeated("7"),
    "environmentSha256": repeated("8"),
    "applicabilitySha256": repeated("9"),
    "publicationPolicySha256": repeated("a"),
    "policyGeneration": 3,
    "destinationScopeIds": ["scope:receiver"],
    "useGrants": GRANTS,
    "retentionLineageSha256": repeated("b"),
    "correctionOfContributionId": None,
    "observedAtUnixMs": 100,
    "expiresAtUnixMs": 2_000,
}

SNAPSHOT: dict[str, object] = {
    "snapshotId": "snapshot:shared",
    "generation": 4,
    "purposeId": "purpose:domain-adaptation",
    "ownerCuts": [
        {
            "ownerId": "agent:source",
            "ownerEpoch": 7,
            "sourceFrontier": 11,
            "memoryFrontier": 12,
            "learningFrontier": 13,
            "deletionFrontier": 2,
            "revocationFrontier": 3,
            "schemaSha256": repeated("c"),
            "policySha256": repeated("d"),
        }
    ],
    "contributionSha256s": [repeated("e")],
    "dependencySha256s": [repeated("f")],
    "unavailableOwnerIds": [],
    "completeness": "complete",
    "snapshotManifestSha256": repeated("1"),
    "deletionFrontierSha256": repeated("2"),
    "revocationFrontierSha256": repeated("3"),
    "createdAtUnixMs": 200,
}

USE_RECEIPT: dict[str, object] = {
    "useOperationId": "operation:read-shared",
    "publicationSha256": repeated("4"),
    "grant": GRANTS[1],
    "sourceOwnerId": "agent:source",
    "sourceRevision": 9,
    "consumerId": "agent:receiver",
    "observedPolicyGeneration": 3,
    "observedRevocationFrontier": 3,
    "payloadSha256": repeated("5"),
    "usedAtUnixMs": 500,
    "finalUseObserved": True,
    "disposition": "delivered",
}

REVOCATION: dict[str, object] = {
    "revocationOperationId": "operation:revoke-shared",
    "contributionId": "contribution:1",
    "publicationSha256": repeated("6"),
    "sourceOwnerId": "agent:source",
    "sourceRevision": 9,
    "predecessorPolicyGeneration": 3,
    "nextPolicyGeneration": 4,
    "revocationFrontier": 4,
    "allUsesRevoked": True,
    "revokedUseGrantIds": [],
    "affectedProjectionSha256s": [repeated("7")],
    "affectedTrainingDatasetSha256s": [repeated("8")],
    "affectedArtifactSha256s": [repeated("9")],
    "pendingOfflineOwnerIds": [],
    "sourceUseBlocked": True,
    "trainingUseBlocked": True,
    "artifactAdoptionBlocked": True,
    "influenceStatus": "pending",
    "influenceProofSha256": None,
    "completeness": "complete",
}

VECTORS: list[tuple[str, str, dict[str, object], str]] = [
    (
        "SharedExperiencePublicationV2",
        "hepta.shared-experience.publication.v2",
        PUBLICATION,
        "9bae7ba4f327b65832a0f4860c50b10c5ced877eadcea532afb4e973491e882e",
    ),
    (
        "SharedExperienceSnapshotV2",
        "hepta.shared-experience.snapshot.v2",
        SNAPSHOT,
        "9d6c35998edf88d3d283deea10a8eb0df9edae6d6004e92475c39626d86f8128",
    ),
    (
        "SharedExperienceUseReceiptV2",
        "hepta.shared-experience.use-receipt.v2",
        USE_RECEIPT,
        "32133156afa841cd9352853a48d19cacbb9c07df83ce45f3197e5ead6b8eae04",
    ),
    (
        "SharedExperienceRevocationReceiptV2",
        "hepta.shared-experience.revocation-receipt.v2",
        REVOCATION,
        "01b91dad36e1963c000b7003b74cc2d0cb56d4c36d81ef9b5b3b56d30d55cb1b",
    ),
]


def invalid_payload(contract: str, p: dict) -> bool:
    """Independent rejection oracle for the shared, checked-in semantic corpus."""
    if contract == "SharedExperiencePublicationV2":
        grants = p["useGrants"]
        ids = [g["grantId"] for g in grants]
        return (
            p["sourceKind"] not in {"canonical_memory_event", "owner_memory_revision"}
            or p["correctionOfContributionId"] == p["contributionId"]
            or ids != sorted(set(ids))
            or any(g["expiresAtUnixMs"] > p["expiresAtUnixMs"] for g in grants)
        )
    if contract == "SharedExperienceSnapshotV2":
        owners = [row["ownerId"] for row in p["ownerCuts"]]
        missing = p["unavailableOwnerIds"]
        return (len(owners) + len(missing) > 64 or owners != sorted(set(owners))
                or (p["completeness"] == "partial" and not missing))
    if contract == "SharedExperienceUseReceiptV2":
        grant = p["grant"]
        use = grant["useClass"]
        consumer = use.get("consumerId", use.get("trainerId", use.get("artifactConsumerId")))
        expected = {"raw_evidence_read": "delivered", "purpose_bound_training": "training_batch_materialized", "derived_artifact_use": "artifact_adopted"}[use["kind"]]
        success = p["disposition"] in {"delivered", "training_batch_materialized", "artifact_adopted"}
        return (p["consumerId"] != consumer or success != p["finalUseObserved"]
                or (success and (p["disposition"] != expected or not grant["validFromUnixMs"] <= p["usedAtUnixMs"] < grant["expiresAtUnixMs"])))
    if contract == "SharedExperienceRevocationReceiptV2":
        missing = p["pendingOfflineOwnerIds"]
        return (len(missing) > 64 or (p["completeness"] == "complete" and bool(missing))
                or (p["influenceStatus"] == "proved_removed" and p["influenceProofSha256"] is None))
    raise ValueError(f"unregistered negative contract: {contract}")


def verify_negative_semantics() -> list[str]:
    document = json.loads(Path(__file__).with_name("negative-vectors.json").read_text())
    rejected = []
    for case in document["cases"]:
        envelope = json.loads(case["wire"])
        if canonical(envelope).decode() != case["wire"]:
            raise SystemExit(f"noncanonical negative vector: {case['name']}")
        if not invalid_payload(case["contract"], envelope["payload"]):
            raise SystemExit(f"negative semantic oracle accepted: {case['name']}")
        rejected.append(case["name"])
    return rejected


def main() -> None:
    digests: dict[str, str] = {}
    envelope_bytes: dict[str, int] = {}
    for contract, schema, payload, expected in VECTORS:
        actual = semantic_digest(contract, payload)
        if actual != expected:
            raise SystemExit(f"digest mismatch for {contract}: {actual} != {expected}")
        envelope = {
            "schema": schema,
            "schemaVersion": 1,
            "contract": contract,
            "payload": payload,
        }
        digests[contract] = actual
        envelope_bytes[contract] = len(canonical(envelope))

    rejected = verify_negative_semantics()
    if len(rejected) != 14:
        raise SystemExit(f"negative semantic vector drift: {rejected}")

    print(
        json.dumps(
            {
                "status": "PASS_COGNITIVE_TYPES_V2_CROSS_LANGUAGE_VECTOR",
                "vectorCount": len(VECTORS),
                "negativeVectorCount": len(rejected),
                "digests": digests,
                "canonicalEnvelopeBytes": envelope_bytes,
                "rejectedSemantics": rejected,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
