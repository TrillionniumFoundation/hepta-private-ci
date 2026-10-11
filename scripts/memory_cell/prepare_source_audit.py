"""Project a complete model-assisted audit without fabricating independent review.

The independent reviewer worklist excludes model answers, model scores and the
assistant's dispositions. All original cases, sources and answer labels survive.
This module stages diagnostics; it never loads a reader or an optimizer.
"""

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path

from composition_evidence import write
from composition_trial import capability_plan
from native import Question, digest
from reviewed_bundle import SCHEMA, augment, strict_read

DECISIONS = {
    "provisional_support",
    "needs_extra_premise",
    "redundant_and_questionable_target",
    "ambiguous_relation",
}


def prepare(source, audit_path, audit_sha, output):
    audit = strict_read(audit_path, audit_sha, 4 * 1024 * 1024)
    if (
        audit.get("schema") != "hepta.source-audit.model-assistance.v1"
        or audit.get("independent_sufficiency_certified") is not False
        or audit.get("training_permitted") is not False
        or audit.get("production_accepted") is not False
    ):
        raise ValueError("model assistance cannot supply independent authority")
    reviewer = audit["reviewer"]
    if (
        reviewer["kind"] != "model_assisted_review"
        or reviewer["human"] is not False
        or reviewer["authenticated_external_identity"] is not False
        or reviewer["independent_of_implementation_author"] is not False
    ):
        raise ValueError("do not impersonate an independent reviewer")
    source = Path(source)
    original = strict_read(
        source / "plan.json", audit["source_plan_sha256"], 64 * 1024 * 1024
    )
    labels = strict_read(
        source / "labels.json", audit["source_labels_sha256"], 64 * 1024 * 1024
    )
    if digest(original) != audit["source_plan_digest"]:
        raise ValueError("audit detached from original source cohort")
    ids = [c["question"]["identity"] for c in original["cases"]]
    reviewed_ids = [r["question_id"] for r in audit["items"]]
    if (
        len(set(ids)) != len(ids)
        or len(set(reviewed_ids)) != len(reviewed_ids)
        or set(ids) != set(reviewed_ids)
        or set(labels) != set(ids)
        or len(ids) != audit["scope"]["original_census"]
        or any(c["phase"] != "capability" for c in original["cases"])
    ):
        raise ValueError("no filtering, replacement or reduced review census")
    # Same existing deterministic retrieval controls; no review labels enter it.
    plan = capability_plan(original)
    entries = {r["question_id"]: r for r in audit["items"]}
    reviews, independent_queue, counts = {}, [], {}
    for case in plan["cases"]:
        q = Question(**case["question"])
        item = entries[q.identity]
        if (
            item["decision"] not in DECISIONS
            or item["query_digest"] != digest(asdict(q))
            or item["source_frontier"] != case["frontier"]
            or item["publication_row_sha256"]
            != labels[q.identity]["publication_review"]["raw_sha256"]
            or not item["rationale"]
            or not item["limits"]
            or item["independent_human_disposition"] is not None
        ):
            raise ValueError("audit statement/source identity mismatch")
        counts[item["decision"]] = counts.get(item["decision"], 0) + 1
        if item["decision"] == "provisional_support":
            spans = item["reviewed_spans"]
            requirements = list(dict.fromkeys(s["requirement"] for s in spans))
            reviews[q.identity] = dict(
                query_digest=digest(asdict(q)),
                source_frontier=case["frontier"],
                reviewer_id=reviewer["id"],
                reviewed_at=reviewer["reviewed_at"],
                review_basis="model_assisted_review",
                claim="jointly_sufficient_and_each_requirement_necessary",
                requirements=requirements,
                spans=spans,
            )
        elif item["reviewed_spans"]:
            raise ValueError("disputed evidence cannot become an accepted bundle")
        independent_queue.append(
            dict(
                question=case["question"],
                originals=case["originals"],
                source_frontier=case["frontier"],
                required_background="Declare every extra factual premise; language interpretation is allowed.",
                request="Independently derive the answer, name sufficient evidence groups, and justify necessity of each group or record insufficient/ambiguous/disputed. Do not use model results.",
                reviewer_identity=None,
                reviewed_at=None,
                judgement=None,
            )
        )
    package = dict(schema=SCHEMA, base_plan_digest=digest(plan), reviews=reviews)
    projected = augment(plan, package, revoked=set())
    for old, new in zip(plan["cases"], projected["cases"], strict=True):
        if any(
            new["conditions"].get(a) != value for a, value in old["conditions"].items()
        ):
            raise ValueError("ordinary control changed")
    out = Path(output)
    out.mkdir()
    write(out / "plan.json", plan)
    write(out / "reviews.json", package)
    write(out / "withdrawals.json", [])
    (out / "labels.json").write_bytes((source / "labels.json").read_bytes())
    (out / "source-audit.json").write_bytes(audit_path.read_bytes())
    write(
        out / "independent-review-inputs.json",
        dict(
            schema="hepta.independent-source-review.queue.v1",
            base_plan_digest=digest(plan),
            cases=independent_queue,
            pending=len(independent_queue),
            completed=0,
            no_assistant_dispositions_or_reader_outputs=True,
        ),
    )
    write(
        out / "audit-census.json",
        dict(
            schema="hepta.source-audit.census.v1",
            original_cases=len(ids),
            audit_sha256=audit_sha,
            decisions=counts,
            provisional_bundles=len(reviews),
            independently_accepted=0,
            complete_census_preserved=True,
            new_facts_or_answers_generated=False,
            optimizer_executed=False,
            production_accepted=False,
        ),
    )
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in out.iterdir()
        if p.is_file()
    }
    write(out / "READY.json", dict(files=files, production_accepted=False))
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "audit", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--audit-sha", required=True)
    args = parser.parse_args()
    print(prepare(args.source, args.audit, args.audit_sha, args.output))
