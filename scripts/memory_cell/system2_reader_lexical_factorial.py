"""Frozen 0.5B Reader: 2x2 credential wording versus identifier prefix.

New fixed fictional device/token cases 60:80. Same original checkpoint,
greedy decoder and four evidence arms. A lexical profile transforms ALL
source facts and the question consistently without using target labels to
select evidence; only post-seal scoring sees the expected answer.
Not proof of safety-trigger causality, natural-domain transfer or NDU learning.
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
from system2_onehop_label_ablation import SYSTEM, MAX_NEW_TOKENS, TOKEN_LIMIT
from system2_reader_capacity_reference import (
    ARMS,
    MODEL_ID,
    MODEL_REV,
    PinnedReferenceReader,
    selected,
)
from system2_reader_paired_capacity_audit import STRONG_READER_ID, open_strong
from system2_native_receipt import strict_json

PROFILES = ("credential_tok", "inventory_tok", "credential_tag", "inventory_tag")
NEW_INDICES = range(60, 80)
QUESTIONS = 20
CALLS = QUESTIONS * len(ARMS) * len(PROFILES)
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SCHEMA = "hepta.system2.frozen-reader-lexical-factorial.v1"
POSITIVE = ("single_fact", "target_decoy_two_first")


def write(path, item):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(
            item, f, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        f.write("\n")


def append(path, item):
    with Path(path).open("a", encoding="utf8") as f:
        f.write(
            json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def base_cases():
    results = []
    for index in NEW_INDICES:
        original = make_case(index)
        options = [
            (doc, rel[1])
            for doc in original.documents
            if (rel := parse_relation(doc))
            and rel[0] == "device"
            and rel[2] == "token"
            and rel[3] == original.answer
        ]
        if len(options) != 1:
            raise ValueError("ambiguous original target fact")
        target, device = options[0]
        q = replace(
            original.question,
            identity="onehop:" + digest((original.question.identity, device))[:24],
            family="synthetic-single-hop",
            content=f"Which clearance token is required by device {device}?",
        )
        results.append(
            OneHopCase(
                q,
                original.documents,
                original.answer,
                target.identity,
                original.question.identity,
            )
        )
    if (
        len(results) != QUESTIONS
        or len({x.question.identity for x in results}) != QUESTIONS
    ):
        raise ValueError("not twenty new task identities")
    return tuple(results)


def factors(profile):
    if profile not in PROFILES:
        raise ValueError("unregistered lexical treatment")
    return profile.startswith("inventory"), profile.endswith("tag")


def transform(case, profile):
    """Offline registered grammar substitution with unique byte-bound sources."""
    benign, tag = factors(profile)
    answer = case.answer.replace("TOK-", "TAG-") if tag else case.answer
    docs = []
    mapping = {}
    for doc in case.documents:
        text = doc.content
        if benign:
            text = text.replace("requires clearance token", "has inventory code")
        if tag:
            text = text.replace("TOK-", "TAG-")
        updated = replace(
            doc,
            identity="doc:" + digest((doc.identity, profile, text))[:24],
            root="root:" + digest((doc.root, profile, text)),
            content=text,
        )
        docs.append(updated)
        mapping[doc.identity] = updated
    question = case.question.content
    if benign:
        question = question.replace(
            "Which clearance token is required by",
            "Which inventory code is assigned to",
        )
    new = OneHopCase(
        replace(
            case.question,
            identity="lexical:" + digest((case.question.identity, profile))[:24],
            content=question,
        ),
        tuple(docs),
        answer,
        mapping[case.required_id].identity,
        case.original_question_id,
    )
    if not new.answer.startswith("TAG-" if tag else "TOK-") or len(
        {d.identity for d in docs}
    ) != len(docs):
        raise ValueError("lexical provenance/target drift")
    return new, mapping


def system_instruction(profile):
    benign, tag = factors(profile)
    text = SYSTEM
    if benign:
        text = text.replace("clearance token", "inventory code")
        text = text.replace(" token, no explanation", " code, no explanation")
    if tag:
        text = text.replace("TOK-", "TAG-")
    if text == "" or "I do not have enough evidence." not in text:
        raise ValueError("absent original evidence refusal boundary")
    return text


def delivery(case, arm, profile):
    """Choose on observable ORIGINAL source text; never inspect case.answer."""
    redacted = replace(case, answer="<redacted-gold>")
    selected_old = selected(redacted, arm)
    transformed, mapping = transform(case, profile)
    chosen = tuple(mapping[d.identity] for d in selected_old)
    if len({d.identity for d in chosen}) != len(chosen) or (
        transformed.required_id in {d.identity for d in chosen}
    ) != (arm in POSITIVE):
        raise ValueError("changed registered evidence sufficiency")
    return transformed, chosen


def messages(case, delivered, profile):
    """Same JSON transport, preserve complete original quoted text and E labels."""
    payload = dict(
        question=case.question.content,
        question_time=case.question.observed_at,
        evidence=[
            dict(label=x["label"], observed_at=x["observed_at"], text=x["excerpt"])
            for x in delivered
        ],
    )
    return [
        dict(role="system", content=system_instruction(profile)),
        dict(
            role="user",
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ),
    ]


def run_frozen(reader, case, docs, arm, profile):
    import torch

    variant, chosen = delivery(case, arm, profile)
    if [x.identity for x in chosen] != [x.identity for x in docs]:
        raise ValueError("chosen source mismatch")
    bundle, originals, frontier = evidence(
        variant, chosen, "lexical:" + profile + ":" + arm
    )
    bundle.validate(variant.question, originals, frontier=frontier, revoked=set())
    delivered = bundle.delivered()
    ids = reader.tokenizer.apply_chat_template(
        messages(variant, delivered, profile), tokenize=True, add_generation_prompt=True
    )
    if (
        not ids
        or len(ids) > TOKEN_LIMIT
        or len(ids) + MAX_NEW_TOKENS > reader.model.config.max_position_embeddings
        or reader.model.training
        or any(p.requires_grad for p in reader.model.parameters())
    ):
        raise ValueError("unregistered or mutable frozen model input")
    x = torch.tensor([ids], dtype=torch.long)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    with torch.inference_mode():
        out = reader.model.generate(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            num_beams=1,
            use_cache=True,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
    cpu = time.process_time_ns() - start_cpu
    wall = time.perf_counter_ns() - start_wall
    emitted = out[0, len(ids) :].tolist()
    if not 1 <= len(emitted) <= MAX_NEW_TOKENS:
        raise ValueError("invalid generated tokens")
    answer = reader.tokenizer.decode(
        emitted, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if type(answer) is not str or not answer.strip():
        raise ValueError("empty frozen Reader answer")
    bundle.validate(variant.question, originals, frontier=frontier, revoked=set())
    receipt = dict(
        reader_identity=reader.identity,
        reader_profile=reader.profile,
        model_id=MODEL_ID,
        revision=MODEL_REV,
        input_ids_digest=native_digest(ids),
        generated_ids_digest=native_digest(emitted),
        input_tokens=len(ids),
        generated_tokens=len(emitted),
        bundle_digest=bundle.seal(),
        delivered_evidence=delivered,
        query_digest=native_digest(asdict(variant.question)),
        cpu_time_ns=cpu,
        wall_time_ns=wall,
        trainable_parameters=0,
        answer_postprocessed=False,
        production_accepted=False,
    )
    return answer, receipt


def score(case, arm, profile, answer):
    variant, _ = transform(case, profile)
    if type(answer) is not str or not answer.strip() or arm not in ARMS:
        raise ValueError("empty or unregistered answer")
    exact = answer.strip() == variant.answer
    refusal = answer.strip() == ABSTAIN
    sufficient = arm in POSITIVE
    return dict(
        sufficient=sufficient,
        exact_answer=exact,
        exact_refusal=refusal,
        over_refusal=sufficient and refusal,
        unsupported_token_copy=not sufficient
        and bool(re.search(r"\b(?:TOK|TAG)-[A-F0-9]{7}\b", answer, re.I)),
        task_success=exact if sufficient else refusal,
        independent_human_review=False,
    )


def run(output, reader, *, parent_archive, source_commit):
    if (
        not isinstance(source_commit, str)
        or not COMMIT.fullmatch(source_commit)
        or reader.identity != STRONG_READER_ID
    ):
        raise ValueError("exact source SHA and original model required")
    files, plan, old = open_strong(parent_archive)
    inventory = strict_json(files["reference-inventory.json"])
    if (
        len(old) != 160
        or inventory["model_snapshot_inventory"] != reader.inventory
        or inventory["revision"] != MODEL_REV
        or inventory["model_id"] != MODEL_ID
        or plan["reference_reader_identity"] != reader.identity
    ):
        raise ValueError("0.5B original inventory drift")
    tasks = base_cases()
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "plan.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            reader_identity=reader.identity,
            original_archive_sha256=hashlib.sha256(
                Path(parent_archive).read_bytes()
            ).hexdigest(),
            questions=[c.question.identity for c in tasks],
            profiles=list(PROFILES),
            arms=list(ARMS),
            expected_model_calls=CALLS,
            new_task_range=[60, 80],
            cross_condition_question_overlap=True,
            actual_compute_matched=False,
            learned_updates=0,
            online_gold_labels=False,
            same_model_weight_and_tokenizer=True,
            production_accepted=False,
        ),
    )
    positions = [
        (case, arm, profile) for case in tasks for arm in ARMS for profile in PROFILES
    ]
    positions.sort(
        key=lambda q: (
            q[0].question.identity,
            (
                ARMS.index(q[1])
                + PROFILES.index(q[2])
                + int(digest(q[0].question.identity)[:8], 16)
            )
            % len(PROFILES),
            PROFILES.index(q[2]),
        )
    )
    rows = []
    try:
        for case, arm, profile in positions:
            entry = dict(
                qid=case.question.identity, arm=arm, profile=profile, status="started"
            )
            append(output / "starts.jsonl", entry)
            try:
                variant, docs = delivery(case, arm, profile)
                answer, receipt = run_frozen(reader, case, docs, arm, profile)
                if (
                    receipt["bundle_digest"]
                    != evidence(variant, docs, "lexical:" + profile + ":" + arm)[
                        0
                    ].seal()
                    or receipt["reader_identity"] != reader.identity
                ):
                    raise ValueError("result/proof bundle not bound")
                entry.update(
                    status="succeeded",
                    answer=answer,
                    reader=receipt,
                    selected=[d.identity for d in docs],
                )
            except BaseException as exc:
                entry.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    unknown_inflight_work=True,
                )
                append(output / "raw-answers.jsonl", entry)
                raise
            rows.append(entry)
            append(output / "raw-answers.jsonl", entry)
        raw = (output / "raw-answers.jsonl").read_bytes()
        rawsha = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=rawsha, rows=CALLS, scoring_started=False),
        )
        by_key = {(r["qid"], r["arm"], r["profile"]): r for r in rows}
        if len(rows) != CALLS or len(by_key) != CALLS:
            raise ValueError("incomplete factorial census")
        detail = []
        for case in tasks:
            for arm in ARMS:
                for profile in PROFILES:
                    row = by_key[case.question.identity, arm, profile]
                    result = score(case, arm, profile, row["answer"])
                    detail.append(
                        dict(qid=row["qid"], arm=arm, profile=profile, **result)
                    )
        write(output / "scored.json", detail)
        summary = []
        for profile in PROFILES:
            for arm in ARMS:
                part = [
                    x for x in detail if x["profile"] == profile and x["arm"] == arm
                ]
                actual = [
                    r for r in rows if r["profile"] == profile and r["arm"] == arm
                ]
                summary.append(
                    dict(
                        profile=profile,
                        arm=arm,
                        questions=len(part),
                        exact_answers=sum(x["exact_answer"] for x in part),
                        refusal_outputs=sum(x["exact_refusal"] for x in part),
                        appropriate_refusals=sum(
                            x["exact_refusal"] and not x["sufficient"] for x in part
                        ),
                        over_refusals=sum(x["over_refusal"] for x in part),
                        strict_successes=sum(x["task_success"] for x in part),
                        unsupported_token_copies=sum(
                            x["unsupported_token_copy"] for x in part
                        ),
                        input_tokens=sum(x["reader"]["input_tokens"] for x in actual),
                        output_tokens=sum(
                            x["reader"]["generated_tokens"] for x in actual
                        ),
                        decoder_cpu_ns=sum(x["reader"]["cpu_time_ns"] for x in actual),
                    )
                )
        # Fixed criterion never chooses a favorable variant post-hoc.
        benign = [r for r in summary if r["profile"] == "inventory_tag"]
        qualified = all(
            r["strict_successes"] >= (15 if r["arm"] in POSITIVE else 18)
            for r in benign
        )
        result = dict(
            schema=SCHEMA,
            source_commit=source_commit,
            raw_answer_sha256=rawsha,
            model_calls=CALLS,
            completed=CALLS,
            failures=0,
            results=summary,
            disposition=(
                "independent_language_confirmation_required"
                if qualified
                else "lexical_factorial_not_qualified"
            ),
            no_reader_training=True,
            compute_matched=False,
            policy_refusal_cause_proven=False,
            independent_natural_task_evidence=False,
            production_accepted=False,
        )
        write(output / "summary.json", result)
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != rawsha
        ):
            raise ValueError("sealed responses changed")
        reader.verify_frozen()
        return result
    except BaseException as exc:
        write(
            output / "failure.json",
            dict(
                type=type(exc).__name__,
                message=str(exc)[:512],
                recorded=len(rows),
                planned=CALLS,
                complete=False,
                unknown_work_never_assumed_free=True,
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
        raise ValueError("explicit research mode required")
    reader = PinnedReferenceReader(args.reader)
    result = run(
        args.output,
        reader,
        parent_archive=args.parent,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(model_calls=result["model_calls"], disposition=result["disposition"]),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
