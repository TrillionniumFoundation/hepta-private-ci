#!/usr/bin/env python3
"""Independent framing oracle for the Rust final-use context fixture, not authority."""

import copy
import hashlib
import json

from verify_vectors import GRANTS, PUBLICATION, USE_RECEIPT, semantic_digest

EXPECTED = "a5bb8c3dd9f3e56f228e41c098b86a6c735c9a3753c495b828feca15325f6c1f"


def text(value):
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(8, "big") + encoded


def context_bytes():
    publication = copy.deepcopy(PUBLICATION)
    publication["useGrants"] = [GRANTS[1]]
    for key, character in [
        ("sourceRecordSha256", "2"),
        ("semanticContentSha256", "3"),
        ("sourceScopeSha256", "4"),
        ("environmentSha256", "5"),
        ("applicabilitySha256", "6"),
        ("retentionLineageSha256", "7"),
    ]:
        publication[key] = character * 64
    publication_digest = semantic_digest("SharedExperiencePublicationV2", publication)
    receipt = copy.deepcopy(USE_RECEIPT)
    receipt["publicationSha256"] = publication_digest
    receipt["payloadSha256"] = "8" * 64
    receipt_digest = semantic_digest("SharedExperienceUseReceiptV2", receipt)
    return (
        b"hepta.shared-experience.final-use-context.v3\0"
        + bytes.fromhex(publication_digest)
        + bytes.fromhex(receipt_digest)
        + text("canonical_memory_event")
        + text("agent:source")
        # epoch, source, memory, learning, deletion, revocation
        + b"".join(value.to_bytes(8, "big") for value in [7, 11, 12, 13, 2, 3])
        + bytes.fromhex("b" * 64 + "a" * 64)
        + b"".join(text(value) for value in [
            "scope:receiver", "grant:read", "raw_evidence_read", "delivered"
        ])
        + (500).to_bytes(8, "big")
    )


def main():
    preimage = context_bytes()
    actual = hashlib.sha256(preimage).hexdigest()
    if len(preimage) != 361 or actual != EXPECTED:
        raise SystemExit("final-use context v3 golden framing drift")
    print(json.dumps({"profile": "final-use-context.v3", "bytes": len(preimage),
                      "sha256": actual, "scope": "independent_reference_not_native_execution"}))


if __name__ == "__main__":
    main()
