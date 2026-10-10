"""Past-only evidence-sufficiency curriculum from external review CLAIMS.

This is a dataset projection, not a trainer or an independent label issuer.
No reference answer is synthesized. Temporal/entity/procedural semantics must be
established by the external reviewer or executable outcome owner, not this code.
"""

from dataclasses import asdict

from evidence_bundle import observed_time
from native import Question, digest
from reviewed_bundle import SCHEMA, conditions


def project_curriculum(plan, package, *, through, training_ids, forbidden_ids,
                       forbidden_families, forbidden_roots, revoked):
    if (
        package.get("schema") != SCHEMA
        or set(package) != {"schema", "base_plan_digest", "reviews"}
        or not isinstance(package["reviews"], dict)
        or package.get("base_plan_digest") != digest(plan)
        or not isinstance(training_ids, frozenset)
        or not isinstance(forbidden_ids, frozenset)
        or training_ids & forbidden_ids
    ):
        raise ValueError("disjoint explicit training cut and pinned review required")
    cases = {c["question"]["identity"]: c for c in plan["cases"]}
    if len(cases) != len(plan["cases"]) or not training_ids <= cases.keys():
        raise ValueError("missing or duplicate training case")
    cutoff = observed_time(through)
    examples, dispositions = [], []
    for qid in sorted(training_ids):
        case = cases[qid]
        q = Question(**case["question"])
        # Check all indexed originals, not only the eventual positive windows.
        roots = {d["root"] for d in case["originals"]}
        if (
            case["family"] in forbidden_families
            or roots & (forbidden_roots | revoked)
            or observed_time(q.observed_at) > cutoff
            or any(observed_time(d["observed_at"]) > cutoff for d in case["originals"])
        ):
            raise ValueError("future, held-out or withdrawn training experience")
        review = package["reviews"].get(qid)
        if review is None:
            dispositions.append(dict(query_id=qid, status="missing_review_not_negative"))
            continue
        if observed_time(review["reviewed_at"]) > cutoff:
            raise ValueError("review not available at training cutoff")
        projected = conditions(case, review, revoked=revoked)
        full = projected["reviewed_minimal"]
        for name, value in projected.items():
            missing = value["omitted_requirement"]
            examples.append(dict(
                query=asdict(q), family=case["family"], source_roots=sorted(roots),
                query_digest=digest(asdict(q)), context=value["delivered_evidence"],
                bundle_digest=value["bundle_digest"], paired_full_digest=full["bundle_digest"],
                omitted_requirement=missing,
                target="reviewer_claimed_complete" if missing is None else "reviewer_claimed_missing",
                annotation_digest=digest(review), review_basis=review["review_basis"],
                label_independently_verified=False, training_cutoff=through,
            ))
        dispositions.append(dict(query_id=qid, status="projected_external_claims",
                                 examples=len(projected)))
    return dict(
        schema="hepta.past-evidence-curriculum.v1", through=through,
        plan_digest=digest(plan), review_digest=digest(package),
        examples=examples, dispositions=dispositions,
        gold_answers_accessed=False, optimizer_executed=False,
        independent_review_authenticated=False, production_accepted=False,
    )
