"""Frozen Qwen: source-label lexical placebo matched on *input tokens*.

Research-only. On fixed NEW synthetic indices 100:120, contrast E1/E2,
non-E labels whose full tokenized prompt has exactly the same length, and
unlabeled JSON. No labels/answers are used to select a placebo. Equality of
input length is NOT equality of total compute or natural-domain causality.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

SCHEMA = "hepta.system2.qwen-e-label-placebo.v1"
INDICES = range(100, 120)
ARMS = ("target_decoy_first", "target_decoy_last", "decoy_only", "no_evidence")
SUFFICIENT = frozenset(ARMS[:2])
VIEWS = ("e_label", "neutral_alias", "unlabeled")
POSITIONS = tuple((arm, view) for arm in ARMS[:-1] for view in VIEWS) + (
    ("no_evidence", "unlabeled"),
)
ALIAS_LETTERS = tuple("ABCDFGHJKLMNPQRSTUV WXYZ".replace(" ", ""))
PLANNED = len(INDICES) * len(POSITIONS)
PARENT_SHA = "853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37"
STRONG_ID = "ee402c424e3843108772cfb5e20798e858ff5fd38b9204d39539608c522b5301"
TAG = re.compile(r"\bTAG-[A-F0-9]{7}\b")
LABEL_ECHO = re.compile(r"\s*(?:[A-Z]\d+)(?:[\s,;]+[A-Z]\d+)*\s*", re.I)
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(
            value, f, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        f.write("\n")


def append(path, value):
    with Path(path).open("a", encoding="utf8") as f:
        f.write(
            json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def new_cohort():
    from system2_multihop_evidence import (
        make_case,
        parse_relation,
        digest as task_digest,
    )
    from system2_onehop_reader import OneHopCase

    result = []
    for i in INDICES:
        old = make_case(i)
        facts = [
            (doc, rel[1])
            for doc in old.documents
            if (rel := parse_relation(doc))
            and rel[0] == "device"
            and rel[2] == "token"
            and rel[3] == old.answer
        ]
        if len(facts) != 1:
            raise ValueError("ambiguous registered source")
        doc, device = facts[0]
        question = replace(
            old.question,
            identity="onehop:" + task_digest((old.question.identity, device))[:24],
            family="synthetic-single-hop",
            content=f"Which clearance token is required by device {device}?",
        )
        result.append(
            OneHopCase(
                question, old.documents, old.answer, doc.identity, old.question.identity
            )
        )
    if len(result) != 20 or len({x.question.identity for x in result}) != 20:
        raise ValueError("cohort identity drift")
    return tuple(result)


def render_view(base_messages, view, alias_letter=None):
    """Only the label *values* or presence changes; preserve field order/bytes."""
    if view not in VIEWS or len(base_messages) != 2:
        raise ValueError("unregistered view")
    payload = json.loads(base_messages[1]["content"])
    if set(payload) != {"question", "question_time", "evidence"}:
        raise ValueError("user prompt schema drift")
    evidence = payload["evidence"]
    if not isinstance(evidence, list) or len(evidence) > 3:
        raise ValueError("bounded evidence required")
    for i, item in enumerate(evidence, 1):
        if set(item) != {"label", "observed_at", "text"} or item["label"] != f"E{i}":
            raise ValueError("source label or format drift")
        if view == "unlabeled":
            del item["label"]
        elif view == "neutral_alias":
            if alias_letter not in ALIAS_LETTERS:
                raise ValueError("unregistered neutral label candidate")
            item["label"] = f"{alias_letter}{i}"
    if view == "neutral_alias" and not evidence:
        raise ValueError("no alias labels to compare")
    if view != "neutral_alias" and alias_letter is not None:
        raise ValueError("alias only for placebo view")
    out = [dict(base_messages[0]), dict(base_messages[1])]
    out[1]["content"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if out[0] != base_messages[0]:
        raise ValueError("system instruction mutated")
    return out


def token_ids(tokenizer, messages):
    ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True
    )
    if not isinstance(ids, list) or not ids or any(type(x) is not int for x in ids):
        raise ValueError("invalid tokenizer output")
    return ids


def matched_presentations(tokenizer, base_messages):
    """Freeze the FIRST tokenizer-equal neutral alias BEFORE any model call."""
    e_ids = token_ids(tokenizer, render_view(base_messages, "e_label"))
    short_ids = token_ids(tokenizer, render_view(base_messages, "unlabeled"))
    if len(e_ids) <= len(short_ids):
        raise ValueError("labeled original must include additional source tokens")
    for candidate in ALIAS_LETTERS:
        ids = token_ids(
            tokenizer, render_view(base_messages, "neutral_alias", candidate)
        )
        if len(ids) == len(e_ids):
            return dict(
                e_label=(None, e_ids),
                neutral_alias=(candidate, ids),
                unlabeled=(None, short_ids),
            )
    raise ValueError("no tokenizer-length-matched neutral source label; no model calls")


def score(case, arm, text):
    from system2_reader_lexical_factorial import transform
    from system2_multihop_trial import ABSTAIN

    if type(text) is not str or not text.strip() or arm not in ARMS:
        raise ValueError("missing/invalid raw answer")
    target, _ = transform(case, "credential_tag")
    correct = text.strip() == target.answer
    refuse = text.strip() == ABSTAIN
    sufficient = arm in SUFFICIENT
    return dict(
        sufficient=sufficient,
        exact_answer=correct,
        appropriate_refusal=not sufficient and refuse,
        over_refusal=sufficient and refuse,
        unsupported_tag_copy=not sufficient and bool(TAG.search(text.upper())),
        label_only_echo=bool(LABEL_ECHO.fullmatch(text)),
        strict_success=correct if sufficient else refuse,
    )


def summarize(rows, cases):
    expected = {(c.question.identity, a, v) for c in cases for a, v in POSITIONS}
    observed = {(r["qid"], r["arm"], r["view"]) for r in rows}
    if len(rows) != len(expected) or observed != expected:
        raise ValueError("missing, duplicate or extra planned answers")
    if any(r["status"] != "succeeded" for r in rows):
        raise ValueError("failed Reader attempt: leave result unknown")
    case_map = {c.question.identity: c for c in cases}
    result = []
    for arm, v in POSITIONS:
        group = [r for r in rows if r["arm"] == arm and r["view"] == v]
        if len(group) != len(cases) or len({r["qid"] for r in group}) != len(cases):
            raise ValueError("incomplete condition")
        measured = [score(case_map[r["qid"]], arm, r["answer"]) for r in group]
        result.append(
            dict(
                arm=arm,
                view=v,
                count=len(group),
                answers=sum(m["exact_answer"] for m in measured),
                refusals=sum(m["appropriate_refusal"] for m in measured),
                over_refusals=sum(m["over_refusal"] for m in measured),
                unsupported_copies=sum(m["unsupported_tag_copy"] for m in measured),
                label_echoes=sum(m["label_only_echo"] for m in measured),
                strict_success=sum(m["strict_success"] for m in measured),
                input_tokens=sum(r["reader"]["input_tokens"] for r in group),
                output_tokens=sum(r["reader"]["generated_tokens"] for r in group),
                cpu_ns=sum(r["reader"]["cpu_time_ns"] for r in group),
            )
        )
    paired = []
    for arm in ARMS[:-1]:
        group = {(r["qid"], r["view"]): r for r in rows if r["arm"] == arm}
        for x, y in (("e_label", "neutral_alias"), ("neutral_alias", "unlabeled")):
            old_only = new_only = both = neither = 0
            gaps = []
            for c in cases:
                a, b = group[c.question.identity, x], group[c.question.identity, y]
                ga = score(c, arm, a["answer"])["strict_success"]
                gb = score(c, arm, b["answer"])["strict_success"]
                both += int(ga and gb)
                old_only += int(ga and not gb)
                new_only += int(gb and not ga)
                neither += int(not ga and not gb)
                gaps.append(b["reader"]["input_tokens"] - a["reader"]["input_tokens"])
            if x == "e_label" and any(gaps):
                raise ValueError("placebo label token length mismatch")
            paired.append(
                dict(
                    arm=arm,
                    first=x,
                    second=y,
                    both=both,
                    first_only=old_only,
                    second_only=new_only,
                    neither=neither,
                    input_token_gaps=gaps,
                )
            )
    index = {(r["arm"], r["view"]): r for r in result}
    eligible = (
        all(index[arm, "neutral_alias"]["strict_success"] >= 15 for arm in SUFFICIENT)
        and index["decoy_only", "neutral_alias"]["strict_success"] >= 18
        and index["no_evidence", "unlabeled"]["strict_success"] >= 18
    )
    return dict(
        conditions=result,
        paired=paired,
        disposition="independent_domain_confirmation_required"
        if eligible
        else "no_safe_reader_adequacy_gain",
        compute_matched=False,
        input_token_matched_pairs=True,
        independent_natural_task_evidence=False,
        production_accepted=False,
    )


def infer(reader, case, docs, arm, view, alias, ids, bundle, originals, frontier):
    import torch
    from native import digest as native_digest
    from system2_reader_capacity_reference import MODEL_ID, MODEL_REV
    from system2_reader_tag_label_order import MAX_NEW_TOKENS, PROFILE
    from system2_reader_lexical_factorial import system_instruction

    if (
        reader.model.training
        or any(p.requires_grad for p in reader.model.parameters())
        or len(ids) + MAX_NEW_TOKENS > reader.model.config.max_position_embeddings
    ):
        raise ValueError("unfrozen or overlength model")
    x = torch.tensor([ids], dtype=torch.long)
    cpu0, wall0 = time.process_time_ns(), time.perf_counter_ns()
    with torch.inference_mode():
        output = reader.model.generate(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            num_beams=1,
            use_cache=True,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
    cpu_ns = time.process_time_ns() - cpu0
    wall_ns = time.perf_counter_ns() - wall0
    emitted = output[0, len(ids) :].tolist()
    if not 1 <= len(emitted) <= MAX_NEW_TOKENS:
        raise ValueError("unexpected decoder output")
    answer = reader.tokenizer.decode(
        emitted, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if not answer.strip():
        raise ValueError("empty frozen answer")
    bundle.validate(case.question, originals, frontier=frontier, revoked=set())
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
        input_ids_digest=native_digest(ids),
        generated_ids_digest=native_digest(emitted),
        input_tokens=len(ids),
        generated_tokens=len(emitted),
        question_digest=native_digest(asdict(case.question)),
        bundle_digest=bundle.seal(),
        delivered_evidence=bundle.delivered(),
        cpu_time_ns=cpu_ns,
        wall_time_ns=wall_ns,
        answer_postprocessed=False,
        trainable_parameters=0,
        production_accepted=False,
        placebo_alias=alias,
        original_evidence_labels_preserved_in_receipt=True,
    )
    return answer, receipt


def run(output, reader, *, parent_archive, source_commit, infer_fn=infer):
    if (
        not isinstance(source_commit, str)
        or not COMMIT.fullmatch(source_commit)
        or reader.identity != STRONG_ID
    ):
        raise ValueError("exact research commit and pinned frozen 0.5B required")
    from system2_reader_tag_label_order import (
        PARENT_SHA as PIN,
        PROFILE,
        MAX_NEW_TOKENS,
        TOKEN_LIMIT,
        context,
    )
    from system2_reader_capacity_reference import MODEL_ID, MODEL_REV
    from system2_reader_lexical_factorial import messages
    from system2_reader_paired_capacity_audit import open_strong
    from system2_multihop_trial import evidence

    parent = Path(parent_archive)
    if hashlib.sha256(parent.read_bytes()).hexdigest() != PIN or PIN != PARENT_SHA:
        raise ValueError("original source zip pin mismatch")
    archive, plan, old = open_strong(parent)
    pinned = json.loads(archive["reference-inventory.json"])
    if (
        len(old) != 160
        or plan["reference_reader_identity"] != reader.identity
        or pinned["model_snapshot_inventory"] != reader.inventory
        or pinned["model_id"] != MODEL_ID
        or pinned["revision"] != MODEL_REV
    ):
        raise ValueError("frozen original model/source changed")
    cases = new_cohort()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "plan.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            parent_sha256=PIN,
            model_id="Qwen/Qwen2.5-0.5B-Instruct",
            model_revision="a338b55dd21219a5f4da42bc11a9313d1a27d4cc",
            reader_identity=STRONG_ID,
            question_ids=[c.question.identity for c in cases],
            indices=[INDICES.start, INDICES.stop],
            arms=list(ARMS),
            views=list(VIEWS),
            positions=list(POSITIONS),
            original_source_bytes_unchanged=True,
            no_training_or_gold_dependent_label_selection=True,
            planned_model_calls=PLANNED,
            pretrained_weights_frozen=True,
            token_equal_e_versus_alias_required=True,
            full_cpu_cost_matched=False,
            production_accepted=False,
        ),
    )
    # Preflight and FREEZE all aliases and prompt fingerprints BEFORE inference.
    frozen = {}
    try:
        for case in cases:
            for arm in ARMS:
                if arm == "no_evidence":
                    variant, docs = context(case, arm)
                    bundle, originals, frontier = evidence(
                        variant, docs, "tag-placebo:" + arm
                    )
                    base = messages(variant, bundle.delivered(), PROFILE)
                    ids = token_ids(reader.tokenizer, render_view(base, "unlabeled"))
                    frozen[case.question.identity, arm, "unlabeled"] = (
                        variant,
                        docs,
                        bundle,
                        originals,
                        frontier,
                        None,
                        ids,
                    )
                    append(
                        output / "input-preflight.jsonl",
                        dict(
                            qid=case.question.identity,
                            arm=arm,
                            view="unlabeled",
                            alias=None,
                            token_count=len(ids),
                            input_sha256=digest(ids),
                            status="frozen",
                        ),
                    )
                    continue
                variant, docs = context(case, arm)
                bundle, originals, frontier = evidence(
                    variant, docs, "tag-placebo:" + arm
                )
                base = messages(variant, bundle.delivered(), PROFILE)
                selected = matched_presentations(reader.tokenizer, base)
                for view in VIEWS:
                    alias, ids = selected[view]
                    if not 0 < len(ids) <= TOKEN_LIMIT:
                        raise ValueError("reader input over token budget")
                    frozen[case.question.identity, arm, view] = (
                        variant,
                        docs,
                        bundle,
                        originals,
                        frontier,
                        alias,
                        ids,
                    )
                    append(
                        output / "input-preflight.jsonl",
                        dict(
                            qid=case.question.identity,
                            arm=arm,
                            view=view,
                            alias=alias,
                            token_count=len(ids),
                            input_sha256=digest(ids),
                            status="frozen",
                        ),
                    )
        expected = {(c.question.identity, a, v) for c in cases for a, v in POSITIONS}
        if set(frozen) != expected:
            raise ValueError("incomplete input preflight census")
        preflight_sha = hashlib.sha256(
            (output / "input-preflight.jsonl").read_bytes()
        ).hexdigest()
        write(
            output / "input-seal.json",
            dict(sha256=preflight_sha, rows=PLANNED, model_calls_started=False),
        )
        answers = []
        positions = [(case, a, v) for case in cases for a, v in POSITIONS]
        positions.sort(
            key=lambda x: (
                x[0].question.identity,
                (
                    ARMS.index(x[1])
                    + VIEWS.index(x[2])
                    + int(digest(x[0].question.identity)[:8], 16)
                )
                % len(POSITIONS),
            )
        )
        for case, arm, view in positions:
            variant, docs, bundle, originals, frontier, alias, ids = frozen[
                case.question.identity, arm, view
            ]
            row = dict(
                qid=case.question.identity,
                arm=arm,
                view=view,
                status="started",
                alias=alias,
                input_sha256=digest(ids),
            )
            append(output / "starts.jsonl", row)
            try:
                answer, receipt = infer_fn(
                    reader,
                    variant,
                    docs,
                    arm,
                    view,
                    alias,
                    ids,
                    bundle,
                    originals,
                    frontier,
                )
                if (
                    not isinstance(answer, str)
                    or not answer.strip()
                    or receipt.get("reader_identity") != reader.identity
                    or receipt.get("model_id") != MODEL_ID
                    or receipt.get("revision") != MODEL_REV
                    or receipt.get("question_digest")
                    != digest(asdict(variant.question))
                    or receipt.get("bundle_digest") != bundle.seal()
                    or receipt.get("delivered_evidence") != bundle.delivered()
                    or receipt.get("input_ids_digest") != digest(ids)
                    or receipt.get("answer_postprocessed") is not False
                    or receipt.get("trainable_parameters") != 0
                    or receipt.get("input_tokens") != len(ids)
                    or type(receipt.get("generated_tokens")) is not int
                    or not 1 <= receipt["generated_tokens"] <= MAX_NEW_TOKENS
                    or any(
                        type(receipt.get(k)) is not int or receipt[k] < 0
                        for k in ("cpu_time_ns", "wall_time_ns")
                    )
                    or any(
                        type(receipt.get(k)) is not str
                        or not re.fullmatch("[0-9a-f]{64}", receipt[k])
                        for k in ("generated_ids_digest", "reader_profile")
                    )
                ):
                    raise ValueError("frozen answer/prompt provenance drift")
                row.update(
                    status="succeeded",
                    answer=answer,
                    reader=receipt,
                    selected=[d.identity for d in docs],
                )
            except BaseException as exc:
                row.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    inflight_work_unknown=True,
                )
                append(output / "raw-answers.jsonl", row)
                raise
            answers.append(row)
            append(output / "raw-answers.jsonl", row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        raw_sha = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=raw_sha, rows=PLANNED, scoring_started=False),
        )
        report = summarize(answers, cases)
        write(
            output / "summary.json",
            dict(
                schema=SCHEMA,
                source_commit=source_commit,
                input_sha256=preflight_sha,
                raw_sha256=raw_sha,
                planned=PLANNED,
                completed=len(answers),
                failed=0,
                **report,
            ),
        )
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != raw_sha
        ):
            raise ValueError("mutated original model output")
        reader.verify_frozen()
        return report
    except BaseException as exc:
        write(
            output / "failure.json",
            dict(
                schema=SCHEMA,
                planned=PLANNED,
                completed=len((output / "raw-answers.jsonl").read_text().splitlines())
                if (output / "raw-answers.jsonl").exists()
                else 0,
                failure_type=type(exc).__name__,
                error=str(exc)[:512],
                unknown_compute_not_imputed=True,
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
        raise ValueError("explicit registered research mode required")
    from system2_reader_capacity_reference import PinnedReferenceReader

    reader = PinnedReferenceReader(args.reader)
    report = run(
        args.output,
        reader,
        parent_archive=args.parent,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(disposition=report["disposition"], model_calls=PLANNED),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
