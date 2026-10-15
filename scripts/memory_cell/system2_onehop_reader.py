"""Frozen Reader basic grounded reading versus unsupported answer copying.

Synthetic, exposure-controlled research, not learned NDU/production qualification.
Single-hop tasks reuse the same twenty already-exposed device/token facts as the
completed 100-call multi-hop trial. One correct source must be cited, not just
its token repeated. No gold answer is seen by selection or by the Reader.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import time

from system2_multihop_evidence import (
    TASKS,
    SyntheticDoc,
    SyntheticQuestion,
    digest,
    make_case,
    parse_relation,
)
from system2_multihop_trial import (
    ABSTAIN,
    CITATION_RE,
    TOKEN_RE,
    append,
    evidence,
    write,
)

ARMS = ("single_fact", "fact_plus_distractors", "distractors_only", "no_evidence")
DEVICE_QUESTION = re.compile(
    r"^Which clearance token is required by device (DEV-[A-F0-9]+)\?$"
)
SOURCE_COMMIT = "7784872ebb8936865b4245f423d3aa2bb9e0a39d"
READER_IDENTITY = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
READER_PROFILE = "e021a4b0de6103aa7c823c8987f865b1b19db68f9cc66544890e45b90d40a8e3"


@dataclass(frozen=True)
class OneHopCase:
    question: SyntheticQuestion
    documents: tuple[SyntheticDoc, ...]
    answer: str
    required_id: str
    original_question_id: str


def cases():
    result = []
    for i in range(TASKS):
        base = make_case(i)
        device = next(
            e[1]
            for d in base.documents
            if (e := parse_relation(d))
            and e[0] == "device"
            and e[2] == "token"
            and e[3] == base.answer
        )
        sources = [
            d
            for d in base.documents
            if (e := parse_relation(d))
            and e[0] == "device"
            and e[1] == device
            and e[2] == "token"
        ]
        if len(sources) != 1:
            raise ValueError("single target relation must be unique")
        qid = "onehop:" + digest((base.question.identity, device))[:24]
        q = replace(
            base.question,
            identity=qid,
            family="synthetic-single-hop",
            content=f"Which clearance token is required by device {device}?",
        )
        result.append(
            OneHopCase(
                q,
                base.documents,
                base.answer,
                sources[0].identity,
                base.question.identity,
            )
        )
    if len(result) != TASKS or len({c.question.identity for c in result}) != TASKS:
        raise ValueError("one-hop cohort drift")
    return tuple(result)


def select(question, documents, arm):
    """Grounding is a deterministic observable exact-entity lookup, not a gold label."""
    if (
        arm not in ARMS
        or not isinstance(documents, (tuple, list))
        or not 1 <= len(documents) <= 16
    ):
        raise ValueError("unregistered selection")
    match = DEVICE_QUESTION.fullmatch(question.content)
    if not match or len({d.identity for d in documents}) != len(documents):
        raise ValueError("unknown task or duplicate source")
    if any(
        d.scope != question.scope or d.observed_at > question.observed_at
        for d in documents
    ):
        raise ValueError("ineligible source")
    target = match.group(1)
    source = []
    decoys = []
    for doc in documents:
        e = parse_relation(doc)
        if e and e[0] == "device" and e[2] == "token":
            (source if e[1] == target else decoys).append(doc)
    if len(source) != 1 or len(decoys) < 2:
        raise ValueError("ambiguous/missing direct fact or decoys")
    decoys.sort(key=lambda doc: doc.identity)
    if arm == "single_fact":
        return tuple(source)
    if arm == "fact_plus_distractors":
        return tuple(source + decoys[:2])
    if arm == "distractors_only":
        return tuple(decoys[:3])
    return ()


def evaluate_one(case, arm, ids, answer):
    if arm not in ARMS or not isinstance(answer, str) or not answer.strip():
        raise ValueError("unknown arm or empty answer")
    chosen = select(case.question, case.documents, arm)
    if ids != [d.identity for d in chosen]:
        raise ValueError("sealed source ordering changed")
    sufficient = case.required_id in ids
    if sufficient != (arm in ("single_fact", "fact_plus_distractors")):
        raise ValueError("evidence completeness changed")
    found = TOKEN_RE.findall(answer.upper())
    exact = len(found) == 1 and found[0] == case.answer
    labels = [x.upper() for x in CITATION_RE.findall(answer)]
    mapping = {f"E{i + 1}": doc.identity for i, doc in enumerate(chosen)}
    valid = bool(labels) and all(label in mapping for label in labels)
    cites_target = valid and case.required_id in {mapping[label] for label in labels}
    abstained = answer.strip().strip('"').casefold() == ABSTAIN.casefold()
    return dict(
        evidence_sufficient=sufficient,
        token_exact=exact,
        target_token_mentioned=case.answer in answer.upper(),
        valid_citation_syntax=valid,
        cites_direct_fact=cites_target,
        strict_abstention=abstained,
        grounded_answer_success=(sufficient and exact and cites_target),
        unsupported_answer=(not sufficient and bool(found)),
        conditional_task_success=(exact and cites_target if sufficient else abstained),
        independent_semantic_review=False,
    )


def score(rows, registered):
    expected = {(c.question.identity, arm) for c in registered for arm in ARMS}
    actual = [(row["qid"], row["arm"]) for row in rows]
    if (
        len(actual) != len(expected)
        or len(set(actual)) != len(actual)
        or set(actual) != expected
    ):
        raise ValueError("missing, duplicate or unexpected Reader call")
    known = {c.question.identity: c for c in registered}
    scored = []
    for row in rows:
        if row["status"] == "failed":
            scored.append(
                dict(
                    qid=row["qid"],
                    arm=row["arm"],
                    status="failed",
                    grounded_answer_success=None,
                    conditional_task_success=None,
                )
            )
        elif row["status"] == "succeeded":
            case = known[row["qid"]]
            scored.append(
                dict(
                    qid=row["qid"],
                    arm=row["arm"],
                    status="succeeded",
                    **evaluate_one(case, row["arm"], row["selected"], row["answer"]),
                )
            )
        else:
            raise ValueError("unrecognized Reader status")
    summaries = []
    for arm in ARMS:
        group = [r for r in scored if r["arm"] == arm]
        ok = [r for r in group if r["status"] == "succeeded"]
        summaries.append(
            dict(
                arm=arm,
                planned=len(group),
                completed=len(ok),
                evidence_sufficient=sum(r["evidence_sufficient"] for r in ok),
                grounded_answer_success=sum(r["grounded_answer_success"] for r in ok),
                strict_abstentions=sum(r["strict_abstention"] for r in ok),
                unsupported_answers=sum(r["unsupported_answer"] for r in ok),
                target_token_mentions=sum(r["target_token_mentioned"] for r in ok),
                conditional_task_success=sum(r["conditional_task_success"] for r in ok),
                failures=len(group) - len(ok),
                unknown_failure_labels=True,
            )
        )
    return scored, summaries


def run(output, reader, *, source_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact generating commit required")
    registered = cases()
    output.mkdir(parents=True, exist_ok=False)
    combos = [(case, arm) for case in registered for arm in ARMS]
    combos.sort(
        key=lambda item: (
            item[0].question.identity,
            (ARMS.index(item[1]) + int(digest(item[0].question.identity)[:8], 16))
            % len(ARMS),
        )
    )
    write(
        output / "plan.json",
        dict(
            schema="hepta.system2.onehop-reader.v1",
            source_commit=source_commit,
            prior_multihop_source_commit=SOURCE_COMMIT,
            question_ids=[c.question.identity for c in registered],
            original_multihop_question_ids=[c.original_question_id for c in registered],
            required_count=1,
            arms=list(ARMS),
            planned=len(combos),
            reader_identity=READER_IDENTITY,
            reader_profile=READER_PROFILE,
            frozen_reader_input_limit=1024,
            frozen_reader_generation_limit=64,
            synthetic_exposed_source_facts=True,
            no_new_training_or_oracle=True,
            production_accepted=False,
        ),
    )
    rows = []
    try:
        for case, arm in combos:
            started = time.perf_counter()
            row = dict(qid=case.question.identity, arm=arm, status="started")
            append(output / "starts.jsonl", row)
            try:
                selected = select(case.question, case.documents, arm)
                row["selected"] = [d.identity for d in selected]
                row["all_document_bytes_scanned"] = sum(
                    len(d.content.encode()) for d in case.documents
                )
                bundle, originals, frontier = evidence(case, selected, arm)
                row["bundle_digest"] = bundle.seal()
                answer, receipt = reader.answer(
                    case.question,
                    bundle,
                    originals,
                    frontier=frontier,
                    revoked=set(),
                    token_limit=1024,
                )
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("blank output")
                if (
                    receipt["reader_identity"] != READER_IDENTITY
                    or receipt["reader_profile"] != READER_PROFILE
                    or receipt["bundle_digest"] != row["bundle_digest"]
                    or receipt["trainable_parameters"] != 0
                    or receipt["answer_postprocessed"] is not False
                    or receipt["token_limit"] != 1024
                    or receipt["generated_tokens"] > 64
                ):
                    raise ValueError("frozen Reader/trace changed")
                row.update(status="succeeded", answer=answer, reader=receipt)
            except Exception as exc:
                row.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    uncompleted_work_not_free=True,
                )
            row["elapsed_seconds"] = time.perf_counter() - started
            append(output / "raw-answers.jsonl", row)
            rows.append(row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=len(rows), scoring_started=False),
        )
        scored, summaries = score(rows, registered)
        write(output / "scored.json", scored)
        write(
            output / "summary.json",
            dict(
                planned=len(combos),
                recorded=len(rows),
                failed=sum(row["status"] == "failed" for row in rows),
                source_commit=source_commit,
                arms=summaries,
                independent_human_review=False,
                production_accepted=False,
                candidate_disposition=(
                    "reader_singlehop_preflight_passed"
                    if (
                        summaries[0]["grounded_answer_success"] >= 15
                        and summaries[3]["strict_abstentions"] >= 18
                    )
                    else "reader_singlehop_preflight_failed"
                ),
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("raw answer seal mutated after scoring")
        if any(row["status"] == "failed" for row in rows):
            raise RuntimeError(
                "failed Reader calls retained; complete model evaluation unavailable"
            )
        return summaries
    except BaseException as exc:
        write(
            output / "run-failure.json",
            dict(
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                planned=len(combos),
                recorded=len(rows),
                incomplete_work_not_free=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reader", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if not args.development:
        raise ValueError("explicit research-only run required")
    from bundle_reader import FrozenBundleReader
    from stem_cell_trial import READER

    reader = FrozenBundleReader(args.reader, expected_inventory=READER)
    result = run(
        args.output,
        reader,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    reader.verify_frozen()
    print(json.dumps(result, allow_nan=False, ensure_ascii=False))


if __name__ == "__main__":
    main()
