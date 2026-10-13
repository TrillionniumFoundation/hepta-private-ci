"""Same frozen Qwen, source-only neighboring turns versus original lexical k8.

The evaluation targets are physically absent from plan/generate.  All 16 raw
model outcomes are committed before a separate process opens publisher labels.
Previously exposed LoCoMo examples are development diagnostics, not new evidence
for independent generalization or production acceptance.
"""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re

from locomo_frozen_reader_pair import (
    LIMIT,
    bundle_for,
    frozen_qwen_cpu_threads,
    metric,
    original_document,
    source_plan,
    write_once,
)
from locomo_neighbor_retrieval import (
    ARMS,
    decisions,
)
from locomo_ninearm_source_replay import (
    ZIPS,
    canonical,
    compute,
    load_public,
    sha,
    strict_json,
    verify_original_six,
)
from locomo_refusal_attribution import EXPECTED_ZIPS, MODEL_ID as EXPECTED_MODEL_ID, _originals

SCHEMA = "hepta.locomo.neighbor-frozen-reader.v1"
NEW_ARM = "neighbor_k8_bytebound"
OLD_ARM = "lexical_k8"
CASES = 16
ORIGINAL_READER_SHA = EXPECTED_ZIPS["reader"]


def source_only(public_root):
    """Reconstruct all 80 rankings without ever opening any target ZIP."""
    cases, documents, _ = source_plan(public_root)
    population, originals = load_public(public_root)
    frozen = compute(population, originals)
    if verify_original_six(public_root, frozen) != 480:
        raise ValueError("original six retrieval arms were not reproduced")
    ranking = decisions(population, originals, frozen)
    return cases, documents, ranking


def selected_for_evaluation(cases, ranking):
    table = {
        (row["question_id"], row["arm"]): row
        for row in ranking
    }
    if (
        len(ranking) != 160
        or len(table) != 160
        or len(cases) != CASES
        or len({c["question_id"] for c in cases}) != CASES
    ):
        raise ValueError("original question or neighbor retrieval census changed")
    chosen = []
    for case in cases:
        qid = case["question_id"]
        baseline = table[qid, OLD_ARM]
        candidate = table[qid, NEW_ARM]
        if (
            baseline["source_census_sha256"] != case["source_census_sha256"]
            or candidate["source_census_sha256"] != case["source_census_sha256"]
            or baseline["family_proxy_digest"] != case["family_proxy_digest"]
            or candidate["family_proxy_digest"] != case["family_proxy_digest"]
            or baseline["split"] != "evaluation"
            or candidate["split"] != "evaluation"
            or candidate["selected_source_bytes"] > baseline["selected_source_bytes"]
            or len(candidate["selected"]) > 8
            or len(set(candidate["selected"])) != len(candidate["selected"])
            or not set(candidate["selected"]) <= set(case["source_ids"])
        ):
            raise ValueError("selected neighbor evidence changed original pool or cost")
        chosen.append(candidate)
    return chosen


def plan(public_root, output):
    cases, _, ranking = source_only(public_root)
    selected_for_evaluation(cases, ranking)
    output.mkdir(parents=True, exist_ok=False)
    raw = b"".join(canonical(row) + b"\n" for row in ranking)
    write_once(output / "source-only-decisions.jsonl", raw)
    ready = dict(
        schema=SCHEMA + ".source-plan.v1",
        source_only_decisions_sha256=sha(raw),
        original_public_sha256=ZIPS["public"][1],
        original_decisions_sha256=ZIPS["decisions"][1],
        questions=CASES,
        source_only_decisions=160,
        labels_available_before_generation=False,
        selected_without_gold=True,
        training_updates=0,
        production_accepted=False,
    )
    write_once(output / "READY.json", canonical(ready) + b"\n")
    return ready


def checked_plan(public_root, planned):
    cases, documents, ranking = source_only(public_root)
    expected = b"".join(canonical(row) + b"\n" for row in ranking)
    actual = (planned / "source-only-decisions.jsonl").read_bytes()
    ready = strict_json((planned / "READY.json").read_bytes())
    if (
        actual != expected
        or ready.get("schema") != SCHEMA + ".source-plan.v1"
        or ready.get("source_only_decisions_sha256") != sha(expected)
        or ready.get("original_public_sha256") != ZIPS["public"][1]
        or ready.get("original_decisions_sha256") != ZIPS["decisions"][1]
        or ready.get("questions") != CASES
        or ready.get("source_only_decisions") != 160
        or ready.get("labels_available_before_generation") is not False
        or ready.get("selected_without_gold") is not True
        or ready.get("training_updates") != 0
        or ready.get("production_accepted") is not False
    ):
        raise ValueError("original source-only plan altered or target exposure")
    return cases, documents, selected_for_evaluation(cases, ranking), sha(actual)


def generate(public_root, planned, model_root, output):
    from event_memory_trial import read
    from reader_reference import MODELS, ReferenceReader
    import torch

    cases, documents, selection, decision_sha = checked_plan(public_root, planned)
    stage_bytes = (model_root / "stage.json").read_bytes()
    stage = strict_json(stage_bytes)
    if (
        stage["tier"] != "qwen-3b"
        or (stage["repository"], stage["revision"]) != MODELS["qwen-3b"]
        or stage["production_accepted"] is not False
    ):
        raise ValueError("unregistered research Reader")
    inventory = read(model_root / "inventory.json", stage["inventory_sha256"])
    frozen_qwen_cpu_threads(torch)
    reader = ReferenceReader(
        model_root / "reader",
        expected_inventory=inventory["inventory_digest"],
    )
    reader.verify_frozen()
    originals = {key: original_document(doc) for key, doc in documents.items()}
    output.mkdir(parents=True, exist_ok=False)
    answers = []
    with (output / "raw-answers.jsonl").open("xb") as stream:
        for case, record in zip(cases, selection, strict=True):
            chosen = record["selected"]
            row = dict(
                question_id=case["question_id"],
                arm=NEW_ARM,
                family_proxy_digest=case["family_proxy_digest"],
                source_census_sha256=case["source_census_sha256"],
                selected=chosen,
            )
            try:
                query, bundle = bundle_for(case, NEW_ARM, originals, chosen)
                answer, receipt = reader.answer(
                    query,
                    bundle,
                    {key: originals[key] for key in chosen},
                    frontier=case["source_census_sha256"],
                    revoked=set(),
                    token_limit=LIMIT,
                )
                row.update(status="succeeded", answer=answer, receipt=receipt)
            except Exception as error:
                row.update(
                    status="failed",
                    error_type=type(error).__name__,
                    error_detail=str(error)[:384],
                )
            stream.write(canonical(row) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            answers.append(row)
    reader.verify_frozen()
    source_commit = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch("[0-9a-f]{40}", source_commit):
        raise ValueError("exact generating commit required")
    payload = (output / "raw-answers.jsonl").read_bytes()
    ready = dict(
        schema=SCHEMA,
        source_commit=source_commit,
        model_identity=reader.identity,
        model_profile=reader.profile,
        model_stage_sha256=sha(stage_bytes),
        source_only_decisions_sha256=decision_sha,
        original_public_sha256=ZIPS["public"][1],
        original_decisions_sha256=ZIPS["decisions"][1],
        original_reference_reader_zip_sha256=ORIGINAL_READER_SHA,
        raw_answers_sha256=sha(payload),
        planned=CASES,
        succeeded=sum(r["status"] == "succeeded" for r in answers),
        failed=sum(r["status"] == "failed" for r in answers),
        input_token_limit=LIMIT,
        max_generated_tokens=64,
        original_gold_accessible_during_generation=False,
        adaptation_steps=0,
        same_frozen_reader=True,
        answer_postprocessing=False,
        independently_reviewed_sufficiency=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
    write_once(output / "READY.json", canonical(ready) + b"\n")
    print(json.dumps({k: v for k, v in ready.items() if "identity" not in k}))
    return ready


def checked_generation(cases, documents, selection, ready, raw, rows, *, commit):
    if (
        ready.get("schema") != SCHEMA
        or ready.get("source_commit") != commit
        or ready.get("raw_answers_sha256") != sha(raw)
        or ready.get("original_public_sha256") != ZIPS["public"][1]
        or ready.get("original_decisions_sha256") != ZIPS["decisions"][1]
        or ready.get("original_reference_reader_zip_sha256") != ORIGINAL_READER_SHA
        or ready.get("planned") != CASES
        or ready.get("input_token_limit") != LIMIT
        or ready.get("max_generated_tokens") != 64
        or ready.get("adaptation_steps") != 0
        or ready.get("same_frozen_reader") is not True
        or ready.get("original_gold_accessible_during_generation") is not False
        or ready.get("answer_postprocessing") is not False
        or ready.get("independently_reviewed_sufficiency") is not False
        or ready.get("semantic_citation_precision") is not None
        or ready.get("production_accepted") is not False
        or not re.fullmatch("[0-9a-f]{64}", ready.get("model_identity", ""))
        or not re.fullmatch("[0-9a-f]{64}", ready.get("model_profile", ""))
        or len(raw) > 4 * 1024 * 1024
        or len(rows) != CASES
        or len(cases) != CASES
        or raw != b"".join(canonical(row) + b"\n" for row in rows)
    ):
        raise ValueError("new Reader journal is incomplete or changed")
    originals = {key: original_document(doc) for key, doc in documents.items()}
    for case, chosen, row in zip(cases, selection, rows, strict=True):
        expected = dict(
            question_id=case["question_id"],
            arm=NEW_ARM,
            family_proxy_digest=case["family_proxy_digest"],
            source_census_sha256=case["source_census_sha256"],
            selected=chosen["selected"],
        )
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("question or selected source drift")
        if row.get("status") == "failed":
            if (
                type(row.get("error_type")) is not str
                or not row["error_type"]
                or "answer" in row
                or "receipt" in row
            ):
                raise ValueError("failure rewritten as answer")
            continue
        if row.get("status") != "succeeded":
            raise ValueError("unregistered Reader result")
        _, bundle = bundle_for(case, NEW_ARM, originals, chosen["selected"])
        receipt = row.get("receipt", {})
        if (
            not isinstance(receipt, dict)
            or receipt.get("reader_identity") != ready["model_identity"]
            or receipt.get("reader_profile") != ready["model_profile"]
            or receipt.get("token_limit") != LIMIT
            or type(receipt.get("input_tokens")) is not int
            or not 0 < receipt["input_tokens"] <= LIMIT
            or type(receipt.get("generated_tokens")) is not int
            or not 0 < receipt["generated_tokens"] <= 64
            or receipt.get("trainable_parameters") != 0
            or receipt.get("answer_postprocessed") is not False
            or receipt.get("delivered_evidence") != bundle.delivered()
            or type(row.get("answer")) is not str
            or not row["answer"].strip()
        ):
            raise ValueError("new source, model, decoder or original bytes changed")
    if (
        sum(r["status"] == "succeeded" for r in rows) != ready["succeeded"]
        or sum(r["status"] == "failed" for r in rows) != ready["failed"]
    ):
        raise ValueError("execution failure denominator changed")
    return rows


def pairs(cases, new, original, targets):
    """Compare actual generated answers; candidate coverage is NOT answer gain."""
    if len(new) != CASES or len(original) != CASES * 2:
        raise ValueError("not a complete matched original population")
    old = {(r["question_id"], r["arm"]): r for r in original}
    if len(old) != CASES * 2:
        raise ValueError("duplicate old Reader answer")
    if set(targets) != {case["question_id"] for case in cases}:
        raise ValueError("changed original target census")
    groups = dict(all=[], answerable=[], unanswerable=[])
    for case, row in zip(cases, new, strict=True):
        qid = case["question_id"]
        annotation = targets[qid]
        group = "unanswerable" if annotation["unanswerable"] else "answerable"
        ref = old.get((qid, OLD_ARM))
        if ref is None:
            raise ValueError("absent original k8 answer")
        item = dict(
            complete=False,
            old_f1=None,
            new_f1=None,
            extra_input_tokens=None,
        )
        if ref["status"] == row["status"] == "succeeded":
            a = metric(ref["answer"], annotation)
            b = metric(row["answer"], annotation)
            if a["eligible"] and b["eligible"]:
                item = dict(
                    complete=True,
                    old_f1=a["f1"],
                    new_f1=b["f1"],
                    extra_input_tokens=(
                        row["receipt"]["input_tokens"]
                        - ref["receipt"]["input_tokens"]
                    ),
                )
        groups["all"].append(item)
        groups[group].append(item)
    result = {}
    for key, rows in groups.items():
        available = [r for r in rows if r["complete"]]
        missing = len(rows) - len(available)
        delta = sum(r["new_f1"] - r["old_f1"] for r in available)
        result[key] = dict(
            planned=len(rows),
            complete=len(available),
            missing_or_unscored=missing,
            baseline_f1_on_complete=(
                sum(r["old_f1"] for r in available) / len(available)
                if available
                else None
            ),
            neighbor_f1_on_complete=(
                sum(r["new_f1"] for r in available) / len(available)
                if available
                else None
            ),
            wins=sum(r["new_f1"] > r["old_f1"] for r in available),
            losses=sum(r["new_f1"] < r["old_f1"] for r in available),
            ties=sum(r["new_f1"] == r["old_f1"] for r in available),
            extra_input_tokens_on_complete=(
                sum(r["extra_input_tokens"] for r in available)
                if available
                else None
            ),
            all_planned_delta_bounds=(
                [(delta - missing) / len(rows), (delta + missing) / len(rows)]
                if rows
                else None
            ),
            bounds_are_missing_outcome_not_statistical_confidence=True,
        )
    return result


def score(public_root, planned, read_root, target_zip, original_zip, score_zip,
          output, *, expected_commit):
    cases, documents, selection, decision_sha = checked_plan(public_root, planned)
    ready = strict_json((read_root / "READY.json").read_bytes())
    raw = (read_root / "raw-answers.jsonl").read_bytes()
    rows = [strict_json(line) for line in raw.splitlines()]
    if ready.get("source_only_decisions_sha256") != decision_sha:
        raise ValueError("source-only selection was replaced after generation")
    checked_generation(
        cases, documents, selection, ready, raw, rows, commit=expected_commit
    )
    originals = _originals(
        dict(
            public=public_root / ZIPS["public"][0],
            decisions=public_root / ZIPS["decisions"][0],
            targets=target_zip,
            reader=original_zip,
            score=score_zip,
        )
    )
    question_map, source_map, _, old_rows, targets, old_report = originals
    if (
        ready["model_identity"] != old_report["reference_model_inventory_identity"]
        or ready["model_identity"] != EXPECTED_MODEL_ID
        or ready["model_profile"] != old_rows[0]["receipt"]["reader_profile"]
        or set(question_map) != {c["question_id"] for c in cases}
        or set(source_map) != set(documents)
    ):
        raise ValueError("different frozen Reader or original question population")
    report = dict(
        schema=SCHEMA + ".comparison.v1",
        source_commit=expected_commit,
        pinned_original_reader_sha256=ORIGINAL_READER_SHA,
        raw_answers_sha256=sha(raw),
        original_baseline_raw_sha256=old_report["original_raw_answers_sha256"],
        source_decisions_sha256=decision_sha,
        planned_questions=CASES,
        original_calls=CASES * 2,
        new_calls=CASES,
        new_successes=ready["succeeded"],
        new_failures=ready["failed"],
        comparisons=pairs(cases, rows, old_rows, targets),
        original_source_support_coverage_is_weak_label_only=True,
        no_gold_seen_by_generator=True,
        model_training_steps=0,
        independent_human_sufficiency_verified=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "report.json", canonical(report) + b"\n")
    print(json.dumps(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("plan", "generate", "score"):
        sub = commands.add_parser(cmd)
        sub.add_argument("public", type=Path)
        if cmd != "plan":
            sub.add_argument("plan", type=Path)
        if cmd == "generate":
            sub.add_argument("model", type=Path)
        if cmd == "score":
            for field in ("generation", "targets_zip", "old_reader_zip", "old_score_zip"):
                sub.add_argument(field, type=Path)
            sub.add_argument("--expected-commit", required=True)
        sub.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.cmd == "plan":
        plan(args.public, args.output)
    elif args.cmd == "generate":
        generate(args.public, args.plan, args.model, args.output)
    else:
        score(
            args.public,
            args.plan,
            args.generation,
            args.targets_zip,
            args.old_reader_zip,
            args.old_score_zip,
            args.output,
            expected_commit=args.expected_commit,
        )


if __name__ == "__main__":
    main()
