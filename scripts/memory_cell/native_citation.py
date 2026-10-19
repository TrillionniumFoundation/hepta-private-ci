"""Explicit benchmark-ID to citation-digest adaptation; never a source issuer.

The native dataset uses string group IDs, whereas learning.eval signs 32-byte
source roots. Preserve both namespaces. Never guess the encoding from whether
an ID happens to look like hex, and never change production owner's root IDs.
"""

from __future__ import annotations

import copy

from citation_audit import capture, sha

ROOT_PROFILE = "hepta.memory-benchmark.source-root.v1"


def native_root_digest(identity: str) -> str:
    if not isinstance(identity, str) or not identity or "\0" in identity:
        raise ValueError("invalid native source root")
    raw = identity.encode("utf-8", "strict")
    if len(raw) > 4096:
        raise ValueError("native root byte bound")
    return sha(ROOT_PROFILE.encode() + b"\0" + len(raw).to_bytes(8, "big") + raw)


def capture_native(query, answer, receipt, *, experiment_digest, family_digest):
    """Adapt an actual native reader receipt before creating an unsigned queue.

    Withdrawal of native IDs must use native_root_digest as well. A digest binds
    an ID; it does not attest provenance, permission, temporal independence or
    semantic support. The original model receipt remains byte-for-byte unchanged.
    """
    if not isinstance(receipt, dict) or not isinstance(
        receipt.get("delivered_evidence"), list
    ):
        raise ValueError("missing native delivered evidence")
    sources = receipt["delivered_evidence"]
    if len(sources) > 256:
        raise ValueError("native delivered evidence bound")
    adapted = copy.deepcopy(receipt)
    bindings = {}
    for source in adapted["delivered_evidence"]:
        if not isinstance(source, dict) or "root" not in source:
            raise ValueError("missing native source root")
        identity = source["root"]
        root = native_root_digest(identity)
        bindings[identity] = root
        source["root"] = root
    queue = capture(
        query,
        answer,
        adapted,
        experiment_digest=experiment_digest,
        family_digest=family_digest,
    )
    queue.update(
        schema="hepta.memory-citation.native-queue.v1",
        source_root_profile=ROOT_PROFILE,
        source_root_bindings=[
            {"native_root": identity, "root_digest": bindings[identity]}
            for identity in sorted(bindings)
        ],
    )
    return queue
