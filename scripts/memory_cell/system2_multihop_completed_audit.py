"""Independently re-audit completed, SHA-pinned frozen multi-hop Reader answers.

Read-only forensic development work: token substring, citation syntax, and exact
refusal are not independent human judgments of semantic answer adequacy.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from system2_native_receipt import strict_json, verified_archive
from system2_multihop_evidence import ARMS, TASKS, case_manifest, choose, fixed_cases
from system2_multihop_trial import ABSTAIN, TOKEN_RE, census, evaluate

ARCHIVE_SHA = "7a0cb798418e7b00ac5258c26617f05e547be9f4c428bb82fb13428ec98647e2"
GENERATING_COMMIT = "7784872ebb8936865b4245f423d3aa2bb9e0a39d"
READER_IDENTITY = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
READER_PROFILE = "e021a4b0de6103aa7c823c8987f865b1b19db68f9cc66544890e45b90d40a8e3"
REGISTERED_PROMPT_LIMIT = 1024
REGISTERED_GENERATION_LIMIT = 64
SOURCE_FIELDS = (
    "original_id",
    "root",
    "scope",
    "observed_at",
    "source_digest",
    "excerpt",
    "source_start",
    "source_end",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def file_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_completed(path: Path, *, expected_sha=ARCHIVE_SHA, cases=None):
    """Require the external ZIP pin, all internal hashes and the complete 100-cell census."""
    files = verified_archive(path, expected_sha)
    registered = tuple(fixed_cases(TASKS) if cases is None else cases)
    plan = strict_json(files["native/plan.json"])
    if (
        plan.get("source_commit") != GENERATING_COMMIT
        or plan.get("arms") != list(ARMS)
        or plan.get("cohort") != [c.question.identity for c in registered]
        or plan.get("source_manifests") != [case_manifest(c) for c in registered]
        or plan.get("production_accepted") is not False
    ):
        raise ValueError("registered cohort, source or mode drift")
    raw = files["native/raw-answers.jsonl"]
    seal = strict_json(files["native/raw-seal.json"])
    if seal != dict(
        sha256=file_sha(raw), rows=len(registered) * len(ARMS), scoring_started=False
    ):
        raise ValueError("raw-Reader seal or registered population drift")
    rows = [strict_json(line) for line in raw.splitlines()]
    if (
        len(rows) != len(registered) * len(ARMS)
        or census(rows, [c.question.identity for c in registered])["failed"]
    ):
        raise ValueError("missing/failed Reader calls")
    case_by_id = {c.question.identity: c for c in registered}
    seen = set()
    deterministic_prompts = {}
    for row in rows:
        qid, arm = row["qid"], row["arm"]
        if (
            qid not in case_by_id
            or arm not in ARMS
            or (qid, arm) in seen
            or row["status"] != "succeeded"
        ):
            raise ValueError("unknown or duplicate frozen Reader output")
        seen.add((qid, arm))
        case = case_by_id[qid]
        selected = choose(arm, case.question, case.documents)
        if (
            row["source_manifest"] != case_manifest(case)
            or row["selected"] != [d.identity for d in selected]
            or row["selected_count"] != len(selected)
            or row["scanned_document_bytes"]
            != sum(len(d.content.encode()) for d in case.documents)
        ):
            raise ValueError("selector/source identity/cost drift")
        rec = row["reader"]
        if (
            rec["reader_identity"] != READER_IDENTITY
            or rec["reader_profile"] != READER_PROFILE
            or rec["bundle_digest"] != row["bundle_digest"]
            or rec["query_digest"] != digest(asdict(case.question))
            or rec["token_limit"] != REGISTERED_PROMPT_LIMIT
            or rec["trainable_parameters"] != 0
            or rec["answer_postprocessed"] is not False
            or rec["production_accepted"] is not False
            or rec["omitted_evidence_bytes"] != 0
        ):
            raise ValueError("frozen Reader/query/receipt mismatch")
        for name, limit in (
            ("input_tokens", REGISTERED_PROMPT_LIMIT),
            ("generated_tokens", REGISTERED_GENERATION_LIMIT),
        ):
            if type(rec[name]) is not int or not 0 < rec[name] <= limit:
                raise ValueError("unregistered Reader compute")
        for name in ("generated_ids_digest", "input_ids_digest"):
            if not re.fullmatch("[0-9a-f]{64}", rec[name]):
                raise ValueError("unsealed token IDs")
        delivered = rec["delivered_evidence"]
        if len(selected) != len(delivered):
            raise ValueError("undisclosed/missing delivered source")
        for i, (src, proof) in enumerate(zip(selected, delivered, strict=True)):
            expected = dict(
                original_id=src.identity,
                root=src.root,
                scope=src.scope,
                observed_at=src.observed_at,
                source_digest=digest(src.content),
                excerpt=src.content,
                source_start=0,
                source_end=len(src.content.encode()),
            )
            if proof.get("label") != f"E{i + 1}" or any(
                proof.get(k) != expected[k] for k in SOURCE_FIELDS
            ):
                raise ValueError(
                    "returned excerpt detached from immutable source bytes"
                )
        answer = row["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty completed neural answer")
        request = (
            rec["reader_identity"],
            rec["reader_profile"],
            rec["query_digest"],
            rec["input_ids_digest"],
        )
        output = (answer, rec["generated_ids_digest"])
        if (
            request in deterministic_prompts
            and deterministic_prompts[request] != output
        ):
            raise ValueError("identical frozen Reader request changed its output")
        deterministic_prompts[request] = output
    _, scores, summary = evaluate(rows, registered)
    scored = strict_json(files["native/scored.json"])
    old_summary = strict_json(files["native/summary.json"])
    if (
        scored != scores
        or old_summary.get("arms") != summary
        or old_summary.get("census")
        != census(rows, [c.question.identity for c in registered])
        or old_summary.get("source_commit") != GENERATING_COMMIT
    ):
        raise ValueError("old scored results do not replay from raw answers")
    if files["tested-commit.txt"].decode().strip() != GENERATING_COMMIT:
        raise ValueError("hosted checkout does not match generating source")
    return dict(
        files=files,
        plan=plan,
        seal=seal,
        rows=rows,
        cases=registered,
        archive_sha256=expected_sha,
        manifest_entries=len(files) - 1,
        distinct_prompt_requests=len(deterministic_prompts),
    )


def behavior(audited):
    cases = {c.question.identity: c for c in audited["cases"]}
    per_arm = []
    for arm in ARMS:
        rows = [r for r in audited["rows"] if r["arm"] == arm]
        per_arm.append(
            dict(
                arm=arm,
                calls=len(rows),
                complete_source_sets=sum(
                    set(cases[r["qid"]].required_ids).issubset(set(r["selected"]))
                    for r in rows
                ),
                exact_refusals=sum(
                    r["answer"].strip().strip('"').casefold() == ABSTAIN.casefold()
                    for r in rows
                ),
                mentions_target_literal=sum(
                    cases[r["qid"]].answer in r["answer"] for r in rows
                ),
                contains_recognized_token=sum(
                    bool(TOKEN_RE.search(r["answer"])) for r in rows
                ),
                correct_bounded_citations=sum(
                    bool(re.search(r"\[E\d+\]", r["answer"])) for r in rows
                ),
                copies_evidence_label_prefix=sum(
                    bool(re.search(r"\bE\d+:", r["answer"])) for r in rows
                ),
                hit_generation_ceiling=sum(
                    r["reader"]["generated_tokens"] == REGISTERED_GENERATION_LIMIT
                    for r in rows
                ),
                input_tokens=sum(r["reader"]["input_tokens"] for r in rows),
                output_tokens=sum(r["reader"]["generated_tokens"] for r in rows),
            )
        )
    return dict(
        schema="hepta.system2.completed-multihop-reader-audit.v1",
        source_commit=GENERATING_COMMIT,
        archive_sha256=audited["archive_sha256"],
        answer_seal_sha256=audited["seal"]["sha256"],
        immutable_manifest_files=audited["manifest_entries"],
        independent_questions=len(cases),
        answer_attempts=len(audited["rows"]),
        distinct_frozen_requests=audited["distinct_prompt_requests"],
        by_arm=per_arm,
        independent_semantic_judgment=False,
        unverified_token_mentions_not_grounded_answers=True,
        production_accepted=False,
        candidate_disposition="reader_adequacy_preflight_failed",
    )


def run(original: Path, output: Path):
    a = read_completed(original)
    result = behavior(a)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(run(args.archive, args.output), ensure_ascii=False, allow_nan=False)
    )
