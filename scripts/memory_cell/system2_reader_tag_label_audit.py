"""Read-only, externally SHA-pinned audit of completed 180-call Qwen TAG trial.

This module executes ZERO model calls. It validates the original archive and
all original source, prompt, Reader and score identities before reporting
paired answer/copy/refusal/token/cost outcomes. Synthetic ground truth is
not a human sufficiency or generalization judgment.
"""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
import re

from native import digest as native_digest
from system2_multihop_trial import evidence
from system2_native_receipt import strict_json, verified_archive
from system2_reader_capacity_reference import MODEL_ID, MODEL_REV
from system2_reader_paired_capacity_audit import STRONG_READER_ID
from system2_reader_tag_label_order import (
    ARMS,
    CASES,
    MAX_NEW_TOKENS,
    PARENT_SHA,
    PLANNED,
    POSITIONS,
    PRESENTATIONS,
    SCHEMA,
    TOKEN_LIMIT,
    cohort,
    context,
    contrasts,
    grade,
    render,
)

ARCHIVE_SHA256 = "8da46b3965f8a6aa9919877c8165e6a2d06f3298921e645d91f7cddfcf9b8761"
GENERATING_COMMIT = "56968236c1281908674101568b229c6a1c03359d"
GENERATING_TREE = "9d5651917c858bb0b875779f6057f4b15327340c"
GENERATING_CODE_BLOB = "dff0a829ac0be203654ee8d4015419e8a4af8038"
REQUIRED = (
    "tested-commit.txt",
    "tested-tree.txt",
    "reader-inventory.json",
    "source/system2_reader_tag_label_order.py",
    "trial/plan.json",
    "trial/raw-answers.jsonl",
    "trial/raw-seal.json",
    "trial/scored-summary.json",
)
DIGEST64 = re.compile(r"[0-9a-f]{64}\Z")


def git_blob_sha(data):
    """Git's content-addressed blob identity, NOT an ordinary file SHA256."""
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_receipt(row, case, arm, view):
    """Validate a completed response against original *full* source bytes."""
    if (
        row.get("qid") != case.question.identity
        or row.get("arm") != arm
        or row.get("presentation") != view
        or row.get("status") != "succeeded"
        or type(row.get("answer")) is not str
        or not row["answer"].strip()
    ):
        raise ValueError("question, arm, status or original raw answer drift")
    source, docs = context(case, arm)
    selected = [d.identity for d in docs]
    if row.get("selected") != selected:
        raise ValueError("selected source identity drift")
    bundle, originals, frontier = evidence(
        source, docs, "tag-label:" + arm + ":" + view
    )
    bundle.validate(source.question, originals, frontier=frontier, revoked=set())
    receipt = row.get("reader")
    if type(receipt) is not dict:
        raise ValueError("missing frozen Reader receipt")
    if (
        receipt.get("reader_identity") != STRONG_READER_ID
        or receipt.get("model_id") != MODEL_ID
        or receipt.get("revision") != MODEL_REV
        or receipt.get("question_digest") != native_digest(asdict(source.question))
        or receipt.get("bundle_digest") != bundle.seal()
        or receipt.get("delivered_evidence") != bundle.delivered()
        or receipt.get("answer_postprocessed") is not False
        or receipt.get("trainable_parameters") != 0
        or receipt.get("production_accepted") is not False
    ):
        raise ValueError("Reader/model/source/excerpt/provenance receipt drift")
    for name, upper in (
        ("input_tokens", TOKEN_LIMIT),
        ("generated_tokens", MAX_NEW_TOKENS),
    ):
        value = receipt.get(name)
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError("invalid token count or overbudget model attempt")
    for name in ("cpu_time_ns", "wall_time_ns"):
        value = receipt.get(name)
        if type(value) is not int or value < 0:
            raise ValueError("unaccounted or invalid recorded compute")
    for name in ("input_ids_digest", "generated_ids_digest"):
        if type(receipt.get(name)) is not str or not DIGEST64.fullmatch(receipt[name]):
            raise ValueError("missing exact frozen token fingerprint")
    if (
        not isinstance(receipt.get("reader_profile"), str)
        or not receipt["reader_profile"]
    ):
        raise ValueError("missing frozen prompt/decoder profile")

    # No tokenizer/model is used here.  The original producer's reconstruction
    # is rechecked structurally: the only view change is removing the "label"
    # JSON property; order, text and all source bytes must stay equal.
    user = json.loads(render(source, bundle.delivered(), view)[1]["content"])
    control = json.loads(render(source, bundle.delivered(), "labeled")[1]["content"])
    for item in control["evidence"]:
        item.pop("label")
    if view == "unlabeled":
        if user != control:
            raise ValueError("unlabeled prompt changed anything beyond label keys")
    else:
        labeled = json.loads(
            render(source, bundle.delivered(), "labeled")[1]["content"]
        )
        if user != labeled:
            raise ValueError("labeled prompt changed")
    return grade(case, arm, row["answer"])


def paired_measure(rows, cases):
    """Mandatory exact 20-question denominators, with no failed-row imputation."""
    expected = {
        (case.question.identity, arm, view) for case in cases for arm, view in POSITIONS
    }
    matched = {}
    metric = {}
    profiles = set()
    for row in rows:
        key = (row.get("qid"), row.get("arm"), row.get("presentation"))
        if key in matched or key not in expected:
            raise ValueError("duplicate/extra Reader prediction position")
        case = next(c for c in cases if c.question.identity == key[0])
        metric[key] = verify_receipt(row, case, key[1], key[2])
        profiles.add(row["reader"]["reader_profile"])
        matched[key] = row
    if len(matched) != PLANNED or set(matched) != expected or len(profiles) != 1:
        raise ValueError("incomplete planned Reader trial or mixed Reader profiles")

    by_arm, original_pairs, disposition = contrasts(rows, cases)
    views = {}
    for arm in ARMS:
        names = ("unlabeled",) if arm == "no_evidence" else PRESENTATIONS
        for view in names:
            part = [matched[c.question.identity, arm, view] for c in cases]
            graded = [metric[c.question.identity, arm, view] for c in cases]
            views[arm + "/" + view] = dict(
                questions=CASES,
                exact=sum(g["exact_answer"] for g in graded),
                refused=sum(g["appropriate_refusal"] for g in graded),
                over_refused=sum(g["over_refusal"] for g in graded),
                source_label_echo=sum(g["label_only_echo"] for g in graded),
                unsupported_tag_copy=sum(g["unsupported_tag_copy"] for g in graded),
                strict_success=sum(g["strict_success"] for g in graded),
                prompt_tokens=sum(x["reader"]["input_tokens"] for x in part),
                generated_tokens=sum(x["reader"]["generated_tokens"] for x in part),
                decoder_cpu_ns=sum(x["reader"]["cpu_time_ns"] for x in part),
            )
    discordance = {}
    for arm in ARMS[:-1]:
        for item in original_pairs:
            if item["arm"] == arm and item["metric"] in (
                "exact_answer",
                "strict_success",
                "label_only_echo",
                "unsupported_tag_copy",
            ):
                discordance[arm + "/" + item["metric"]] = dict(
                    both=item["both"],
                    labeled_only=item["labeled_only"],
                    unlabeled_only=item["unlabeled_only"],
                    neither=item["neither"],
                    prompt_token_gap_by_question=item["prompt_token_gap_by_question"],
                )
    return views, discordance, by_arm, original_pairs, disposition


def audit_files(files, *, expected_source_sha=ARCHIVE_SHA256):
    if not set(REQUIRED).issubset(files):
        raise ValueError("incomplete archived source/answer/evidence inventory")
    if files["tested-commit.txt"].decode().strip() != GENERATING_COMMIT:
        raise ValueError("original generating commit mismatch")
    if files["tested-tree.txt"].decode().strip() != GENERATING_TREE:
        raise ValueError("original tested tree mismatch")
    if (
        git_blob_sha(files["source/system2_reader_tag_label_order.py"])
        != GENERATING_CODE_BLOB
    ):
        raise ValueError("original model runner Git blob mismatch")
    inventory = strict_json(files["reader-inventory.json"])
    if inventory.get("model") != MODEL_ID or inventory.get("revision") != MODEL_REV:
        raise ValueError("original pinned Qwen snapshot identity changed")
    plan = strict_json(files["trial/plan.json"])
    cohort_ids = [c.question.identity for c in cohort()]
    if (
        plan.get("source_commit") != GENERATING_COMMIT
        or plan.get("schema") != SCHEMA
        or plan.get("original_archive_sha256") != PARENT_SHA
        or plan.get("original_model_identity") != STRONG_READER_ID
        or plan.get("questions") != cohort_ids
        or plan.get("arms") != list(ARMS)
        or plan.get("presentations") != list(PRESENTATIONS)
        or plan.get("positions") != [list(x) for x in POSITIONS]
        or plan.get("planned_model_calls") != PLANNED
        or plan.get("production_accepted") is not False
        or plan.get("compute_matched") is not False
    ):
        raise ValueError("source cohort, cost regime or experiment plan drift")

    raw = files["trial/raw-answers.jsonl"]
    seal = strict_json(files["trial/raw-seal.json"])
    raw_sha = hashlib.sha256(raw).hexdigest()
    if seal != dict(sha256=raw_sha, rows=PLANNED, scoring_started=False):
        raise ValueError("original pre-scoring raw answer seal is absent or changed")
    start_lines = files.get("trial/starts.jsonl", b"").splitlines()
    if len(start_lines) != PLANNED:
        raise ValueError("missing original started Reader attempt records")
    started = [strict_json(x) for x in start_lines]
    rows = [strict_json(line) for line in raw.splitlines()]
    if len(rows) != PLANNED:
        raise ValueError("partial/duplicated original Reader answers")
    positions = [(r["qid"], r["arm"], r["presentation"]) for r in rows]
    starts = [(r["qid"], r["arm"], r["presentation"]) for r in started]
    if positions != starts or any(r.get("status") != "started" for r in started):
        raise ValueError("missing model calls or misbound start journal")

    cases = cohort()
    views, discordance, by_arm, paired, disposition = paired_measure(rows, cases)
    original = strict_json(files["trial/scored-summary.json"])
    if (
        original.get("raw_sha256") != raw_sha
        or original.get("source_commit") != GENERATING_COMMIT
        or original.get("model_calls") != PLANNED
        or original.get("completed") != PLANNED
        or original.get("failed") != 0
        or original.get("by_arm") != by_arm
        or original.get("paired_effects") != paired
        or original.get("candidate_disposition") != disposition
        or original.get("production_accepted") is not False
        or original.get("compute_matched") is not False
    ):
        raise ValueError(
            "archived post-seal source score does not independently replay"
        )

    return dict(
        schema="hepta.system2.qwen-tag-label-retrospective.v1",
        source_archive_sha256=expected_source_sha,
        source_commit=GENERATING_COMMIT,
        source_tree=GENERATING_TREE,
        raw_answers_sha256=raw_sha,
        verified_manifest_entries=len(files) - 1,
        question_count=CASES,
        complete_model_attempts=PLANNED,
        failed=0,
        reader_profiles=len({r["reader"]["reader_profile"] for r in rows}),
        original_disposition=disposition,
        per_condition=views,
        per_pair_discordance=discordance,
        compute_matched=False,
        labels_and_prompt_tokens_confounded=True,
        same_20_questions_not_independent=True,
        human_semantic_judgment=False,
        new_neural_calls=0,
        production_accepted=False,
        next_stage=(
            "independent_reader_capacity_and_refusal_controls_required"
            if disposition != "independent_natural_confirmation_required"
            else "independent_new_task_confirmation_required"
        ),
    )


def run(archive_path, output_path):
    files = verified_archive(Path(archive_path), ARCHIVE_SHA256)
    outcome = audit_files(files)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf8") as stream:
        json.dump(
            outcome,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    outcome = run(args.archive, args.output)
    print(
        "SEALED_TAG_LABEL_READOUT="
        + json.dumps(
            dict(
                questions=outcome["question_count"],
                attempts=outcome["complete_model_attempts"],
                disposition=outcome["original_disposition"],
                per_condition=outcome["per_condition"],
                per_pair_discordance=outcome["per_pair_discordance"],
                new_neural_calls=0,
            ),
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
