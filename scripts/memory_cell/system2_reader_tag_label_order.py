"""Frozen Qwen 0.5B TAG-code evidence-label × source-order diagnostic.

Research-only fixed new 20 synthetic questions (80:100). An already observed
20/20 single-fact TAG code copying rate does not establish grounded answer
selection or refusal. Compare presence of E labels on the SAME source bytes,
model, instruction and greedy decoder. Never call a semantic oracle online.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import re
import time

from native import digest as native_digest
from system2_multihop_evidence import digest, make_case, parse_relation
from system2_multihop_trial import ABSTAIN, evidence
from system2_onehop_reader import OneHopCase
from system2_reader_capacity_reference import (
    MODEL_ID,
    MODEL_REV,
    PinnedReferenceReader,
    selected,
)
from system2_reader_lexical_factorial import (
    MAX_NEW_TOKENS,
    TOKEN_LIMIT,
    messages,
    system_instruction,
    transform,
)
from system2_reader_paired_capacity_audit import STRONG_READER_ID, open_strong

SCHEMA = "hepta.system2.frozen-qwen-tag-label-order.v1"
PARENT_SHA = "853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37"
PROFILE = "credential_tag"
CASES = 20
INDICES = range(80, 100)
ARMS = (
    "single_fact",
    "target_decoy_first",
    "target_decoy_last",
    "decoy_only",
    "no_evidence",
)
POSITIVE = ARMS[:3]
PRESENTATIONS = ("labeled", "unlabeled")
POSITIONS = tuple((arm, view) for arm in ARMS[:-1] for view in PRESENTATIONS) + (
    ("no_evidence", "unlabeled"),
)
PLANNED = CASES * len(POSITIONS)
HEX = re.compile(r"[0-9a-f]{40}\Z")
TAG = re.compile(r"\bTAG-[A-F0-9]{7}\b")
LABEL_ONLY = re.compile(r"\s*E\d+(?:[\s,;]+E\d+)*\s*", re.I)


def write(path, item):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(
            item, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        f.write("\n")


def append(path, item):
    with Path(path).open("a", encoding="utf8") as f:
        f.write(
            json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def cohort():
    result = []
    for i in INDICES:
        old = make_case(i)
        facts = [
            (d, relation)
            for d in old.documents
            if (relation := parse_relation(d))
            and relation[0] == "device"
            and relation[2] == "token"
            and relation[3] == old.answer
        ]
        if len(facts) != 1:
            raise ValueError("ambiguous single-hop target")
        doc, relation = facts[0]
        device = relation[1]
        question = replace(
            old.question,
            identity="onehop:" + digest((old.question.identity, device))[:24],
            family="synthetic-single-hop",
            content=f"Which clearance token is required by device {device}?",
        )
        result.append(
            OneHopCase(
                question, old.documents, old.answer, doc.identity, old.question.identity
            )
        )
    if len(result) != CASES or len({r.question.identity for r in result}) != CASES:
        raise ValueError("question count or identity changed")
    return tuple(result)


def choose(case, arm):
    """Fixed source choice uses question and document bytes, never case.answer."""
    if arm == "target_decoy_last":
        return tuple(reversed(selected(case, "target_decoy_two_first")))
    mapping = dict(
        single_fact="single_fact",
        target_decoy_first="target_decoy_two_first",
        decoy_only="decoy_one",
        no_evidence="no_evidence",
    )
    if arm not in mapping:
        raise ValueError("unknown evidence arm")
    return selected(case, mapping[arm])


def context(case, arm):
    """Return TAG-transformed source bytes after choosing on observable source."""
    old_docs = choose(case, arm)
    transformed, mapping = transform(case, PROFILE)
    docs = tuple(mapping[d.identity] for d in old_docs)
    complete = transformed.required_id in {d.identity for d in docs}
    if (
        complete != (arm in POSITIVE)
        or len({d.identity for d in docs}) != len(docs)
        or len(docs)
        != (2 if arm.startswith("target_decoy") else 0 if arm == "no_evidence" else 1)
    ):
        raise ValueError("source selection or certificate changed")
    return transformed, docs


def render(case, delivered, presentation):
    """Labeled version EXACTLY matches original factorial message template."""
    if presentation not in PRESENTATIONS:
        raise ValueError("unregistered transport variant")
    result = messages(case, delivered, PROFILE)
    if presentation == "unlabeled":
        user = json.loads(result[1]["content"])
        for row in user["evidence"]:
            if "label" not in row:
                raise ValueError("missing original E label")
            del row["label"]
        result[1]["content"] = json.dumps(
            user, ensure_ascii=False, separators=(",", ":")
        )
    if result[0]["content"] != system_instruction(PROFILE) or len(result) != 2:
        raise ValueError("registered instruction changed")
    return result


def infer(reader, case, docs, arm, presentation):
    import torch

    variant, expected_docs = context(case, arm)
    if [d.identity for d in docs] != [d.identity for d in expected_docs]:
        raise ValueError("delivery changed before inference")
    bundle, originals, frontier = evidence(
        variant, docs, "tag-label:" + arm + ":" + presentation
    )
    bundle.validate(variant.question, originals, frontier=frontier, revoked=set())
    delivered = bundle.delivered()
    token_ids = reader.tokenizer.apply_chat_template(
        render(variant, delivered, presentation),
        tokenize=True,
        add_generation_prompt=True,
    )
    if (
        not token_ids
        or len(token_ids) > TOKEN_LIMIT
        or len(token_ids) + MAX_NEW_TOKENS > reader.model.config.max_position_embeddings
        or reader.model.training
        or any(p.requires_grad for p in reader.model.parameters())
    ):
        raise ValueError("unregistered or mutated Qwen input")
    tensor = torch.tensor([token_ids], dtype=torch.long)
    cpu0, wall0 = time.process_time_ns(), time.perf_counter_ns()
    with torch.inference_mode():
        output = reader.model.generate(
            input_ids=tensor,
            attention_mask=torch.ones_like(tensor),
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            num_beams=1,
            use_cache=True,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
    cpu_ns = time.process_time_ns() - cpu0
    wall_ns = time.perf_counter_ns() - wall0
    generated = output[0, len(token_ids) :].tolist()
    if not 1 <= len(generated) <= MAX_NEW_TOKENS:
        raise ValueError("unexpected decoding length")
    answer = reader.tokenizer.decode(
        generated, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if type(answer) is not str or not answer.strip():
        raise ValueError("Reader returned no answer")
    bundle.validate(variant.question, originals, frontier=frontier, revoked=set())
    receipt = dict(
        reader_identity=reader.identity,
        reader_profile=native_digest(
            (
                MODEL_ID,
                MODEL_REV,
                PROFILE,
                system_instruction(PROFILE),
                MAX_NEW_TOKENS,
                reader.tokenizer.chat_template,
            )
        ),
        model_id=MODEL_ID,
        revision=MODEL_REV,
        input_ids_digest=native_digest(token_ids),
        generated_ids_digest=native_digest(generated),
        input_tokens=len(token_ids),
        generated_tokens=len(generated),
        question_digest=native_digest(asdict(variant.question)),
        bundle_digest=bundle.seal(),
        delivered_evidence=delivered,
        cpu_time_ns=cpu_ns,
        wall_time_ns=wall_ns,
        answer_postprocessed=False,
        trainable_parameters=0,
        production_accepted=False,
    )
    return answer, receipt


def grade(case, arm, answer):
    if arm not in ARMS or not isinstance(answer, str) or not answer.strip():
        raise ValueError("failed or unregistered Reader answer")
    target, _ = transform(case, PROFILE)
    sufficient = arm in POSITIVE
    exact = answer.strip() == target.answer
    refusal = answer.strip() == ABSTAIN
    return dict(
        sufficient=sufficient,
        exact_answer=exact,
        appropriate_refusal=not sufficient and refusal,
        over_refusal=sufficient and refusal,
        target_mentioned=target.answer in answer.upper(),
        unsupported_tag_copy=not sufficient and bool(TAG.search(answer.upper())),
        label_only_echo=bool(LABEL_ONLY.fullmatch(answer)),
        strict_success=exact if sufficient else refusal,
        independent_semantic_human_review=False,
    )


def contrasts(rows, cases):
    expected = {
        (case.question.identity, arm, view) for case in cases for arm, view in POSITIONS
    }
    mapped = {}
    for row in rows:
        key = (row["qid"], row["arm"], row["presentation"])
        if key not in expected or key in mapped or row.get("status") != "succeeded":
            raise ValueError("unknown/duplicate/failed Reader position")
        mapped[key] = row
    if len(mapped) != PLANNED or set(mapped) != expected:
        raise ValueError("incomplete labeled-versus-unlabeled census")
    by_arm = []
    for arm in ARMS:
        views = ("unlabeled",) if arm == "no_evidence" else PRESENTATIONS
        for view in views:
            group = [mapped[case.question.identity, arm, view] for case in cases]
            outcome = [
                grade(c, arm, r["answer"]) for c, r in zip(cases, group, strict=True)
            ]
            by_arm.append(
                dict(
                    arm=arm,
                    presentation=view,
                    questions=len(group),
                    exact_answers=sum(g["exact_answer"] for g in outcome),
                    appropriate_refusals=sum(g["appropriate_refusal"] for g in outcome),
                    over_refusals=sum(g["over_refusal"] for g in outcome),
                    label_only_echoes=sum(g["label_only_echo"] for g in outcome),
                    unsupported_tag_copies=sum(
                        g["unsupported_tag_copy"] for g in outcome
                    ),
                    strict_successes=sum(g["strict_success"] for g in outcome),
                    input_tokens=sum(r["reader"]["input_tokens"] for r in group),
                    output_tokens=sum(r["reader"]["generated_tokens"] for r in group),
                    decoder_cpu_ns=sum(r["reader"]["cpu_time_ns"] for r in group),
                )
            )
    pairs = []
    for arm in ARMS[:-1]:
        for metric in (
            "exact_answer",
            "strict_success",
            "over_refusal",
            "label_only_echo",
            "unsupported_tag_copy",
        ):
            both = labeled_only = unlabeled_only = neither = 0
            gaps = []
            for case in cases:
                a = mapped[case.question.identity, arm, "labeled"]
                b = mapped[case.question.identity, arm, "unlabeled"]
                ga = grade(case, arm, a["answer"])[metric]
                gb = grade(case, arm, b["answer"])[metric]
                both += int(ga and gb)
                labeled_only += int(ga and not gb)
                unlabeled_only += int(gb and not ga)
                neither += int(not ga and not gb)
                gaps.append(b["reader"]["input_tokens"] - a["reader"]["input_tokens"])
            pairs.append(
                dict(
                    arm=arm,
                    metric=metric,
                    both=both,
                    labeled_only=labeled_only,
                    unlabeled_only=unlabeled_only,
                    neither=neither,
                    prompt_token_gap_by_question=gaps,
                    semantic_causality_not_identified=True,
                )
            )
    gate = {x["arm"]: x for x in by_arm if x["presentation"] == "unlabeled"}
    eligible = (
        all(gate[arm]["strict_successes"] >= 15 for arm in POSITIVE)
        and gate["decoy_only"]["strict_successes"] >= 18
        and gate["no_evidence"]["strict_successes"] >= 18
    )
    return (
        by_arm,
        pairs,
        (
            "independent_natural_confirmation_required"
            if eligible
            else "tag_label_selection_not_qualified"
        ),
    )


def run(output, reader, *, parent_archive, source_commit, infer_fn=infer):
    if (
        not isinstance(source_commit, str)
        or not HEX.fullmatch(source_commit)
        or reader.identity != STRONG_READER_ID
    ):
        raise ValueError("exact generating SHA and frozen 0.5B model required")
    parent = Path(parent_archive)
    if hashlib.sha256(parent.read_bytes()).hexdigest() != PARENT_SHA:
        raise ValueError("external original Qwen archive mismatch")
    archived, plan, original = open_strong(parent)
    if (
        len(original) != 160
        or plan["reference_reader_identity"] != reader.identity
        or json.loads(archived["reference-inventory.json"])["model_snapshot_inventory"]
        != reader.inventory
    ):
        raise ValueError("pinned model/source inventory drift")
    cases = cohort()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "plan.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            original_archive_sha256=PARENT_SHA,
            original_model_identity=reader.identity,
            questions=[c.question.identity for c in cases],
            arms=list(ARMS),
            presentations=list(PRESENTATIONS),
            positions=list(POSITIONS),
            planned_model_calls=PLANNED,
            factor="JSON label property only; named source order separately controlled",
            source_index_range=[INDICES.start, INDICES.stop],
            primary_profile="unlabeled",
            fixed_prefix="TAG-",
            no_training_or_gold_dependent_selection=True,
            input_token_lengths_may_differ=True,
            compute_matched=False,
            production_accepted=False,
        ),
    )
    positions = [(case, arm, view) for case in cases for arm, view in POSITIONS]
    positions.sort(
        key=lambda x: (
            x[0].question.identity,
            (
                ARMS.index(x[1])
                + PRESENTATIONS.index(x[2])
                + int(digest(x[0].question.identity)[:8], 16)
            )
            % len(POSITIONS),
        )
    )
    rows = []
    try:
        for case, arm, view in positions:
            record = dict(
                qid=case.question.identity, arm=arm, presentation=view, status="started"
            )
            append(output / "starts.jsonl", record)
            try:
                variant, docs = context(case, arm)
                answer, receipt = infer_fn(reader, case, docs, arm, view)
                bundle, _, _ = evidence(variant, docs, "tag-label:" + arm + ":" + view)
                if (
                    not isinstance(answer, str)
                    or not answer.strip()
                    or receipt.get("reader_identity") != reader.identity
                    or receipt.get("bundle_digest") != bundle.seal()
                    or receipt.get("delivered_evidence") != bundle.delivered()
                    or receipt.get("question_digest")
                    != native_digest(asdict(variant.question))
                    or receipt.get("answer_postprocessed") is not False
                    or receipt.get("trainable_parameters") != 0
                    or receipt.get("input_tokens", 0) > TOKEN_LIMIT
                    or receipt.get("generated_tokens", 0) > MAX_NEW_TOKENS
                ):
                    raise ValueError("Reader/source/answer receipt mismatched")
                record.update(
                    status="succeeded",
                    answer=answer,
                    reader=receipt,
                    selected=[d.identity for d in docs],
                )
            except BaseException as exc:
                record.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    work_may_be_incomplete=True,
                )
                append(output / "raw-answers.jsonl", record)
                raise
            rows.append(record)
            append(output / "raw-answers.jsonl", record)
        if len(rows) != PLANNED:
            raise ValueError("missing planned model calls")
        raw = (output / "raw-answers.jsonl").read_bytes()
        raw_sha = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=raw_sha, rows=PLANNED, scoring_started=False),
        )
        summary, pairs, disposition = contrasts(rows, cases)
        write(
            output / "scored-summary.json",
            dict(
                schema=SCHEMA,
                source_commit=source_commit,
                raw_sha256=raw_sha,
                model_calls=PLANNED,
                completed=PLANNED,
                failed=0,
                by_arm=summary,
                paired_effects=pairs,
                candidate_disposition=disposition,
                compute_matched=False,
                independent_natural_task_evidence=False,
                general_NDU_FBSDE_gain=False,
                production_accepted=False,
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != raw_sha
        ):
            raise ValueError("prediction seal changed during scoring")
        reader.verify_frozen()
        return dict(
            raw_seal=raw_sha,
            candidate_disposition=disposition,
            completed=PLANNED,
            by_arm=summary,
        )
    except BaseException as exc:
        write(
            output / "failure.json",
            dict(
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                recorded=len(rows),
                planned=PLANNED,
                incomplete_work_not_free=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent", type=Path)
    parser.add_argument("reader", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    if not args.development:
        raise ValueError("explicit research-only execution required")
    reader = PinnedReferenceReader(args.reader)
    result = run(
        args.output,
        reader,
        parent_archive=args.parent,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(
                completed=result["completed"],
                disposition=result["candidate_disposition"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
