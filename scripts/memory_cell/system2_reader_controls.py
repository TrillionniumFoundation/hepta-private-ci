"""Research diagnostic consumption of externally authenticated human review claims.

No key generation or authoring of sufficient-evidence verdicts. The trust registry
must be supplied/pinned independently of the review package. Cryptographic
identity authentication does not prove a claim's semantic truth or independence.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import re

CONDITIONS = (
    "no_evidence",
    "ordinary_retrieval",
    "human_sufficient",
    "critical_premise_removed",
)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def authenticate_review(
    envelope, registry, *, query_digest, frontier, experiment_authors, now=None
):
    """The caller authenticates/pins registry bytes outside the submitted review.

    Test signatures are fixtures, not real human observations. No network or
    production activation exists in this module.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    now = now or datetime.now(timezone.utc)
    if not isinstance(envelope, dict) or set(envelope) != {"review", "signature"}:
        raise ValueError("unknown review envelope")
    if (
        not isinstance(registry, dict)
        or set(registry) != {"schema", "reviewers"}
        or registry["schema"] != "hepta.system2.review-trust.v1"
    ):
        raise ValueError("unknown externally pinned registry")
    review = envelope["review"]
    reviewer = review["reviewer_id"]
    entry = registry["reviewers"].get(reviewer)
    if (
        not entry
        or reviewer in experiment_authors
        or entry.get("role") != "independent_human"
        or entry.get("revoked") is not False
        or review.get("review_basis") != "external_review"
        or review.get("claim") != "jointly_sufficient_and_each_requirement_necessary"
        or review.get("query_digest") != query_digest
        or review.get("source_frontier") != frontier
    ):
        raise ValueError("unadmitted reviewer, claim, query or source frontier")
    valid_from = datetime.fromisoformat(entry["valid_from"].replace("Z", "+00:00"))
    valid_until = datetime.fromisoformat(entry["valid_until"].replace("Z", "+00:00"))
    reviewed = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    if (
        any(t.tzinfo is None for t in (now, valid_from, valid_until, reviewed))
        or not valid_from <= reviewed <= now <= valid_until
    ):
        raise ValueError("review identity expired/not yet valid/unknown timezone")
    key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(entry["public_key"], validate=True)
    )
    key.verify(
        base64.b64decode(envelope["signature"], validate=True), canonical(review)
    )
    return dict(
        review_digest=hashlib.sha256(canonical(review)).hexdigest(),
        reviewer_id=reviewer,
        authenticated_identity_under_supplied_registry=True,
        semantic_truth_proven_by_signature=False,
        production_accepted=False,
    )


def load_pinned_json(path, expected, *, maximum=4 * 1024 * 1024):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise ValueError("external SHA256 pin required")
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("non-symlink pinned input required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("pinned input budget/digest mismatch")

    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("duplicate JSON key")
            result[k] = v
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON input")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def reviewed_conditions(case, envelope, registry, *, experiment_authors, revoked):
    """Reuse original-byte checks and grouped premise deletion from reviewed_bundle."""
    from reviewed_bundle import conditions
    from native import digest

    receipt = authenticate_review(
        envelope,
        registry,
        query_digest=digest(case["question"]),
        frontier=case["frontier"],
        experiment_authors=experiment_authors,
    )
    projected = conditions(case, envelope["review"], revoked=revoked)
    # Fix the deletion choice from the external requirement order, not model scores.
    requirement = envelope["review"]["requirements"][0]
    return {
        "human_sufficient": projected["reviewed_minimal"],
        "critical_premise_removed": projected["reviewed_without_" + requirement],
    }, receipt


def diagnostic_census(records, question_ids):
    expected = {(qid, c) for qid in question_ids for c in CONDITIONS}
    actual = [(r["question_id"], r["condition"]) for r in records]
    if (
        len(question_ids) != len(set(question_ids))
        or len(actual) != len(set(actual))
        or set(actual) != expected
    ):
        raise ValueError("incomplete/duplicated reader diagnostic census")
    if any(r["status"] not in {"succeeded", "failed", "unavailable"} for r in records):
        raise ValueError("unknown diagnostic status")
    missing = sum(r["status"] != "succeeded" for r in records)
    return dict(
        planned=len(expected),
        recorded=len(actual),
        missing_or_failed=missing,
        reader_adequacy_established=False,
        next_gate="independent answer adjudication"
        if not missing
        else "complete required evidence/interventions",
        no_oracle_imputation=True,
    )
