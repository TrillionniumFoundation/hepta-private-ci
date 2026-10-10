"""Project externally supplied minimal-evidence reviews into OFFLINE diagnostics.

Review hashes authenticate bytes, not a reviewer or semantic truth. This module
has no signing key, generation access, selection API or production admission.
Ordinary retrieved conditions are copied unchanged. Missing reviews stay missing.
"""

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from evidence_bundle import EvidenceBundle, EvidenceSpan, observed_time
from native import Document, Question, digest

SCHEMA = "hepta.minimal-evidence.review.v1"
MAX_REVIEW_BYTES = 4 * 1024 * 1024


def strict_read(path, expected, bound):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("external SHA-256 pin required")
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("non-symlink input required")
    with path.open("rb") as stream:
        raw = stream.read(bound + 1)
    if len(raw) > bound or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("input exceeds budget or differs from external pin")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("nonfinite JSON number: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def conditions(case, review, *, revoked):
    """Consume reviewer claims; never turn a publisher source ID into an oracle.

    Every required span has an explicit reviewer-supplied requirement. Leave-one-
    requirement-out removes the whole group, not arbitrary answer substrings.
    Neither omission nor an old fact relabels a real-world question unanswerable.
    """
    q = Question(**case["question"])
    originals = {
        d["identity"]: Document(**(d | {"assets": tuple(d["assets"])}))
        for d in case["originals"]
    }
    if len(originals) != len(case["originals"]):
        raise ValueError("duplicate original source")
    required = {
        "query_digest", "source_frontier", "reviewer_id", "reviewed_at",
        "review_basis", "claim", "requirements", "spans",
    }
    if not isinstance(review, dict) or set(review) != required:
        raise ValueError("unknown minimal-evidence review")
    if (
        review["query_digest"] != digest(asdict(q))
        or review["source_frontier"] != case["frontier"]
        or review["claim"] != "jointly_sufficient_and_each_requirement_necessary"
        or review["review_basis"] not in ("external_review", "authored_fixture")
        or not isinstance(review["reviewer_id"], str)
        or not 1 <= len(review["reviewer_id"].encode()) <= 1024
    ):
        raise ValueError("review query/frontier/basis mismatch")
    observed_time(review["reviewed_at"])
    requirements = review["requirements"]
    if (
        not isinstance(requirements, list)
        or not 1 <= len(requirements) <= 8
        or any(not isinstance(r, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", r)
               for r in requirements)
        or len(set(requirements)) != len(requirements)
        or not isinstance(review["spans"], list)
        or not 1 <= len(review["spans"]) <= 8
    ):
        raise ValueError("bounded named requirements/spans required")
    spans, groups = [], []
    for item in review["spans"]:
        if not isinstance(item, dict) or set(item) != {
            "source_id", "source_digest", "start", "end", "requirement",
        } or item["requirement"] not in requirements:
            raise ValueError("unknown requirement or span fields")
        source = originals[item["source_id"]]
        a, b = item["start"], item["end"]
        raw = source.content.encode("utf-8", "strict")
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(raw):
            raise ValueError("invalid byte offsets")
        span = EvidenceSpan(
            source.identity, source.root, source.scope, source.session,
            source.observed_at, a, b, raw[a:b].decode("utf-8", "strict"),
            item["source_digest"],
        )
        span.validate(source, q, revoked)
        # Overlap can make leave-one-out leak a removed prerequisite.
        if any(s.source_id == span.source_id and max(s.start, a) < min(s.end, b)
               for s in spans):
            raise ValueError("overlapping reviewed fragments")
        spans.append(span)
        groups.append(item["requirement"])
    if set(groups) != set(requirements):
        raise ValueError("uncovered reviewer requirement")
    result = {}
    for omitted in (None, *requirements):
        selected = tuple(s for s, group in zip(spans, groups) if group != omitted)
        bundle = EvidenceBundle(digest(asdict(q)), case["frontier"], selected,
                                "reviewed_minimal" if omitted is None else "reviewed_omission")
        bundle.validate(q, originals, frontier=case["frontier"], revoked=revoked)
        name = "reviewed_minimal" if omitted is None else "reviewed_without_" + omitted
        result[name] = dict(
            bundle=asdict(bundle), bundle_digest=bundle.seal(),
            delivered_evidence=bundle.delivered(), token_limit=4096,
            review_digest=digest(review), omitted_requirement=omitted,
            oracle_kind="external_claim_not_authenticated_here",
            independent_review=False, sufficient_context_certified=False,
            world_answerability_unchanged=True,
        )
    return result


def augment(plan, package, *, revoked):
    if (
        plan.get("schema") != "hepta.bundle-diagnostic.plan.v1"
        or not isinstance(package, dict)
        or set(package) != {"schema", "base_plan_digest", "reviews"}
        or package["schema"] != SCHEMA
        or package["base_plan_digest"] != digest(plan)
        or not isinstance(package["reviews"], dict)
        or not isinstance(revoked, set)
    ):
        raise ValueError("review package must bind the complete original plan")
    qids = [c["question"]["identity"] for c in plan["cases"]]
    if len(qids) != len(set(qids)) or set(package["reviews"]) - set(qids):
        raise ValueError("duplicate plan case or surplus review")
    result = copy.deepcopy(plan)
    result["review_projection"] = dict(
        review_package_digest=digest(package), base_plan_digest=digest(plan),
        externally_authenticated=False, production_accepted=False,
    )
    for case in result["cases"]:
        if any(k.startswith("reviewed_") for k in case["conditions"]):
            raise ValueError("cannot overwrite a previous review projection")
        review = package["reviews"].get(case["question"]["identity"])
        additions = conditions(case, review, revoked=revoked) if review is not None else {
            "reviewed_minimal": dict(status="unavailable", reason="missing_external_review")
        }
        case["conditions"].update(additions)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "reviews", "withdrawals", "output"):
        parser.add_argument(name, type=Path)
    for name in ("plan_sha", "reviews_sha", "withdrawals_sha"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    args = parser.parse_args()
    plan = strict_read(args.plan, args.plan_sha, 64 * 1024 * 1024)
    reviews = strict_read(args.reviews, args.reviews_sha, MAX_REVIEW_BYTES)
    withdrawal = strict_read(args.withdrawals, args.withdrawals_sha, MAX_REVIEW_BYTES)
    if not isinstance(withdrawal, list) or any(not isinstance(x, str) for x in withdrawal):
        raise ValueError("explicit current withdrawal list required")
    projected = augment(plan, reviews, revoked=set(withdrawal))
    # Existing run_reader consumes this plan; actual token overflow remains unavailable.
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(projected, out, ensure_ascii=False, allow_nan=False, indent=2)
        out.write("\n")
