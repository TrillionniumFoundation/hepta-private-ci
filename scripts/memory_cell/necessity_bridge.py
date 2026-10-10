"""Bind pinned published two-fact votes into the existing evidence review interface.

The original eOBQA crowd votes are real published observations, but they are
anonymous, without individual timestamps and do not certify that EACH fact is
necessary, jointly sufficient, or independently adjudicated for Hepta. This
adapter never produces a reviewed_minimal oracle or production authorization.

Only the publisher's original question/fact strings enter the frozen reader.
The answer key and vote rows remain offline, opened for scoring after generation.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import re

from composition_evidence import sha, write
from native import Question, digest
from necessity_data import (
    CHAIN_BLOB,
    LIMITS,
    OBQA_SHA,
    PROFILE,
    decision,
    make_case,
    verified_chains,
    verified_questions,
)
from reviewed_bundle import SCHEMA, augment, strict_read

REVIEWER = "eobqa:three-anonymous-published-votes"
CLAIM = "published_two_fact_support_not_minimality"
MAX_CHAIN_BYTES = 1024 * 1024
MAX_QUESTIONS_BYTES = 2 * 1024 * 1024
CAPABILITY = "capability"


def _read_binary(path: Path, maximum: int) -> bytes:
    if (
        path.is_symlink()
        or any(p.is_symlink() for p in path.parents)
        or not path.is_file()
        or not 1 <= path.stat().st_size <= maximum
    ):
        raise ValueError("regular bounded publisher input required")
    return path.read_bytes()


def project(plan, labels, chains, questions, *, revoked):
    """Validate the ENTIRE original cohort before exposing any candidate review.

    No answer text, benchmark gold, reviewer identity or review timestamp is
    invented. All missing/disputed publisher rows remain in the original census.
    """
    if (
        plan.get("schema") != "hepta.bundle-diagnostic.plan.v1"
        or plan.get("profile") != PROFILE
        or plan.get("chain_blob") != CHAIN_BLOB
        or plan.get("original_question_archive_sha256") != OBQA_SHA
        or plan.get("frozen_counts") != LIMITS
        or not isinstance(labels, dict)
        or not isinstance(revoked, set)
    ):
        raise ValueError("not the exact registered publisher plan")
    rows = verified_chains(chains)
    originals, _ = verified_questions(questions)
    if plan.get("dataset_sha256") != sha(chains):
        raise ValueError("plan detached from pinned publisher votes")
    by_hash = {r["raw_sha256"]: r for r in rows}
    if len(by_hash) != len(rows):
        raise ValueError("duplicate raw published chain identity")
    cases = plan["cases"]
    ids = [c["question"]["identity"] for c in cases]
    if (
        len(ids) != sum(LIMITS.values())
        or len(set(ids)) != len(ids)
        or set(ids) != set(labels)
        or any(sum(c["phase"] == phase for c in cases) != total
               for phase, total in LIMITS.items())
        or len({c["family"] for c in cases}) != len(cases)
    ):
        raise ValueError("lost question, phase or independent grouping")
    reviews, provenance = {}, []
    for case in cases:
        query = Question(**case["question"])
        entry = labels[query.identity]
        if not isinstance(entry, dict) or entry.get("reviewed_at") is not None:
            raise ValueError("publication has no individual reviewer timestamp")
        record = entry.get("publication_review")
        if not isinstance(record, dict):
            raise ValueError("missing original publication vote row")
        pinned = by_hash.get(record.get("raw_sha256"))
        if (
            pinned != {k: v for k, v in record.items() if k != "family"}
            or record.get("family") != case["family"]
            or decision(pinned, originals) != "eligible_published_unanimous_claim"
        ):
            raise ValueError("published vote row is not valid or selected")
        qid = pinned["row"]["QID"]
        if query.identity != "eobqa:" + qid:
            raise ValueError("published question identity drift")
        if not re.fullmatch(r"eobqa-group:[0-9a-f]{64}", case["family"]):
            raise ValueError("publisher connected-source family lost")
        reconstructed, expected_label = make_case(
            pinned | {"family": case["family"]},
            originals[qid],
            [d["content"] for d in case["originals"][2:]],
            query.observed_at,
            case["phase"],
        )
        if reconstructed != case or expected_label != entry:
            raise ValueError("source facts, answer, options or noise mutated")
        selected = reconstructed["conditions"]["publisher_pair"]["bundle"]["selected"]
        if len(selected) != 2:
            raise ValueError("publisher pair no longer contains two exact spans")
        review = dict(
            query_digest=digest(asdict(query)),
            source_frontier=case["frontier"],
            reviewer_id=REVIEWER,
            reviewed_at=None,
            review_basis="published_three_vote_chain",
            claim=CLAIM,
            requirements=["fact1", "fact2"],
            spans=[
                dict(
                    source_id=span["source_id"],
                    source_digest=span["source_digest"],
                    start=span["start"],
                    end=span["end"],
                    requirement="fact" + str(i),
                )
                for i, span in enumerate(selected, 1)
            ],
        )
        reviews[query.identity] = review
        provenance.append(
            dict(
                question_id=query.identity,
                phase=case["phase"],
                source_family=case["family"],
                publication_line=pinned["line"],
                publication_row_sha256=pinned["raw_sha256"],
                original_question_digest=digest(originals[qid]),
                vote_tokens=pinned["row"]["Turks"].split(),
                individual_reviewer_id_available=False,
                original_review_time_available=False,
                independent_necessity_verified=False,
                independently_sufficient_verified=False,
            )
        )
    package = dict(schema=SCHEMA, base_plan_digest=digest(plan), reviews=reviews)
    augmented = augment(plan, package, revoked=revoked)
    if len(augmented["cases"]) != len(cases):
        raise ValueError("projection filtered native questions")
    for old, new in zip(cases, augmented["cases"], strict=True):
        for key, value in old["conditions"].items():
            if new["conditions"].get(key) != value:
                raise ValueError("ordinary retrieval control mutated")
        for review_arm, original_arm in (
            ("publisher_claim_pair", "publisher_pair"),
            ("publisher_claim_without_fact1", "without_fact1"),
            ("publisher_claim_without_fact2", "without_fact2"),
        ):
            a = new["conditions"][review_arm]
            b = new["conditions"][original_arm]
            if (
                a["bundle"]["selected"] != b["bundle"]["selected"]
                or a["delivered_evidence"] != b["delivered_evidence"]
                or a["independent_review"] is not False
                or a["sufficient_context_certified"] is not False
            ):
                raise ValueError("publication review could change evidence or authority")
    capability = deepcopy(augmented)
    capability["cases"] = [c for c in capability["cases"] if c["phase"] == CAPABILITY]
    if len(capability["cases"]) != LIMITS[CAPABILITY]:
        raise ValueError("partial capability census")
    stats = dict(
        schema="hepta.publisher-review-bridge.receipt.v1",
        registered_profile=PROFILE,
        original_chains=len(rows),
        original_questions=len(originals),
        selected_records=len(cases),
        capability_questions=len(capability["cases"]),
        published_three_vote_claims=len(reviews),
        review_package_digest=digest(package),
        original_plan_digest=digest(plan),
        projected_plan_digest=digest(augmented),
        capability_plan_digest=digest(capability),
        original_publisher_votes_used=True,
        individual_reviewers_authenticated=False,
        independently_reviewed_minimal_sets=0,
        publisher_fact_necessity_certified=False,
        publisher_fact_sufficiency_certified=False,
        prospective_windows=0,
        optimizer_executed=False,
        production_accepted=False,
    )
    return package, augmented, capability, provenance, stats


def export(source: Path, destination: Path):
    ready = json.loads(_read_binary(source / "READY.json", 4096))
    plan = strict_read(source / "plan.json", ready["plan_sha256"], 64 * 1024 * 1024)
    labels = strict_read(source / "labels.json", ready["labels_sha256"], 64 * 1024 * 1024)
    raw = _read_binary(source / "reviews.tsv", MAX_CHAIN_BYTES)
    questions = _read_binary(source / "openbookqa.zip", MAX_QUESTIONS_BYTES)
    package, augmented, capability, votes, stats = project(
        plan, labels, raw, questions, revoked=set()
    )
    # No intermediate partially validated output masquerades as READY.
    destination.mkdir()
    for name, obj in (
        ("publisher-review-package.json", package),
        ("projected-plan.json", augmented),
        ("capability-plan.json", capability),
        ("published-row-provenance.json", votes),
        ("review-bridge-census.json", stats),
    ):
        write(destination / name, obj)
    (destination / "SCOPE.txt").write_text(
        "Published anonymous votes are NOT independently verified necessary/sufficient"
        " evidence, not current-world truth and not Hepta production authorization.\n"
        "No model answered, no optimizer trained, and no human identities/timestamps"
        " or signatures were invented by this projection.\n"
        "The original publisher QA labels stay in source/labels.json; they enter"
        " run_reader only AFTER raw answers are durably written.\n",
        encoding="utf-8",
    )
    files = {p.name: sha(p.read_bytes()) for p in destination.iterdir() if p.is_file()}
    write(
        destination / "READY.json",
        dict(
            files=files,
            capability_sha256=files["capability-plan.json"],
            original_labels_sha256=ready["labels_sha256"],
            source_commit=plan["source_commit"],
            independently_reviewed_minimal_sets=0,
            production_accepted=False,
        ),
    )
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output), indent=2))
