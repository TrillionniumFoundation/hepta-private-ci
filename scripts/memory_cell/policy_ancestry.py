"""Bound source references for a transferred experimental policy.

These references preserve withdrawal dependencies, not permission, provenance
attestation or independently observed time. Training text is not reader evidence.
The existing policy consumer must validate the training source view separately.
"""

import hashlib
import re

from evidence_bundle import MAX_INDEX_BYTES, observed_time

SCHEMA = "hepta.frozen-experience-session.v3"
FIELDS = {"identity", "root", "scope", "observed_at", "content_sha256", "bytes"}


def validate_support(entries, *, through, policy_roots):
    if not isinstance(entries, (list, tuple)) or not 1 <= len(entries) <= 10000:
        raise ValueError("bounded policy support required")
    identities, roots, total = set(), set(), 0
    for row in entries:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError("policy support reference shape")
        if any(
            not isinstance(row[k], str)
            or not row[k]
            or "\0" in row[k]
            or len(row[k].encode()) > 4096
            for k in ("identity", "root", "scope", "observed_at")
        ):
            raise ValueError("policy support identity bound")
        if (
            row["identity"] in identities
            or not isinstance(row["content_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["content_sha256"])
            or type(row["bytes"]) is not int
            or not 1 <= row["bytes"] <= MAX_INDEX_BYTES
            or observed_time(row["observed_at"]) > observed_time(through)
        ):
            raise ValueError("duplicate, invalid or future policy ancestor")
        identities.add(row["identity"])
        roots.add(row["root"])
        total += row["bytes"]
    if total > MAX_INDEX_BYTES or not roots <= set(policy_roots):
        raise ValueError("unbound or oversized policy ancestry")
    return roots


def source_references(documents, *, through, policy_roots):
    if not isinstance(documents, (list, tuple)) or not 1 <= len(documents) <= 10000:
        raise ValueError("bounded original policy sources required")
    entries = [
        dict(
            identity=d.identity,
            root=d.root,
            scope=d.scope,
            observed_at=d.observed_at,
            content_sha256=hashlib.sha256(d.content.encode()).hexdigest(),
            bytes=len(d.content.encode()),
        )
        for d in documents
    ]
    validate_support(entries, through=through, policy_roots=policy_roots)
    return sorted(entries, key=lambda r: r["identity"])
