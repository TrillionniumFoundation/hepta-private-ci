"""Frozen 0.5B Reader JSON-vs-lines view, with a fresh fixed confirmation cohort.

A different *user evidence serialization* is tested under the identical frozen
system instruction, original evidence bytes, greedy decoder and model. All 160
completed JSON responses on old forty questions are reused after external SHA,
full source identity and exact 0.5B tokenizer revalidation. Forty additional
exposed-question plain calls and twenty fresh-question plain+JSON comparisons
are research-only, not independent natural-language confirmation.
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

from native import digest as native_digest
from system2_multihop_evidence import digest, make_case, parse_relation
from system2_multihop_trial import evidence
from system2_onehop_reader import OneHopCase
from system2_onehop_label_ablation import (
    MAX_NEW_TOKENS,
    SYSTEM,
    TOKEN_LIMIT,
    prompt_messages,
)
from system2_reader_capacity_reference import (
    ARMS,
    CASE_COUNT,
    COHORTS,
    MODEL_ID,
    MODEL_REV,
    PinnedReferenceReader,
    cohorts,
    outcome,
    selected,
)
from system2_reader_paired_capacity_audit import (
    STRONG_READER_ID,
    STRONG_ZIP_SHA,
    open_strong,
)
from system2_native_receipt import strict_json

SCHEMA = "hepta.system2.frozen-reader-transport.v1"
VIEWS = ("json", "lines")
FRESH_INDICES = range(40, 60)
FRESH_NAME = "fresh_fixed_20"
REPEATED_COHORTS = (*COHORTS, FRESH_NAME)
NEW_CALLS = (2 * CASE_COUNT * len(ARMS)) + (CASE_COUNT * len(ARMS) * len(VIEWS))
REUSED_CALLS = 2 * CASE_COUNT * len(ARMS)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def write(path, value):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(
            value, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        f.write("\n")


def append(path, value):
    with Path(path).open("a", encoding="utf8") as f:
        f.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        )
        f.flush()
        os.fsync(f.fileno())


def extra_cases():
    """Registered 40:60, disjoint from the already exposed 0:40 identities."""
    result = []
    for i in FRESH_INDICES:
        original = make_case(i)
        matches = [
            (doc, rel[1])
            for doc in original.documents
            if (rel := parse_relation(doc))
            and rel[0] == "device"
            and rel[2] == "token"
            and rel[3] == original.answer
        ]
        if len(matches) != 1:
            raise ValueError("fresh target relation ambiguity")
        doc, device = matches[0]
        qid = "onehop:" + digest((original.question.identity, device))[:24]
        query = replace(
            original.question,
            identity=qid,
            family="synthetic-single-hop",
            content=f"Which clearance token is required by device {device}?",
        )
        result.append(
            OneHopCase(
                query,
                original.documents,
                original.answer,
                doc.identity,
                original.question.identity,
            )
        )
    if (
        len(result) != CASE_COUNT
        or len(set(c.question.identity for c in result)) != CASE_COUNT
    ):
        raise ValueError("fresh cohort identity drift")
    return tuple(result)


def registered_cohorts():
    old = cohorts()
    if set(old) != set(COHORTS) or any(len(old[k]) != CASE_COUNT for k in COHORTS):
        raise ValueError("old fixed cohorts changed")
    new = old | {FRESH_NAME: extra_cases()}
    ids = [c.question.identity for group in new.values() for c in group]
    if len(ids) != len(set(ids)) or len(ids) != 3 * CASE_COUNT:
        raise ValueError("cohort overlap")
    return new


def line_messages(query, delivered):
    """Only change the USER transport; keep system text and all source bytes.

    The excerpts are JSON-quoted to preserve data/instruction boundaries.
    Never look at any answer, gold source ID or future annotation here.
    """
    if not isinstance(delivered, list) or len(delivered) > 8:
        raise ValueError("bounded actual delivered evidence list required")
    lines = [
        "Question: " + query.content,
        "Question time: " + query.observed_at,
        "Evidence records (quoted source data):",
    ]
    for entry in delivered:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("label"), str)
            or not isinstance(entry.get("excerpt"), str)
            or not isinstance(entry.get("observed_at"), str)
        ):
            raise ValueError("unbound source entry")
        lines.append(
            f"[{entry['label']}] observed_at={entry['observed_at']} "
            f"text={json.dumps(entry['excerpt'], ensure_ascii=False)}"
        )
    if not delivered:
        lines.append("(none)")
    return [
        dict(role="system", content=SYSTEM),
        dict(role="user", content="\n".join(lines)),
    ]


def expected_parent(source, reader, groups):
    """Reproduce 160 existing Qwen JSON inputs without any repeated inference."""
    files, plan, frozen = open_strong(source)
    inv = strict_json(files["reference-inventory.json"])
    if (
        reader.identity != STRONG_READER_ID
        or plan["reference_reader_identity"] != reader.identity
        or inv.get("model_id") != MODEL_ID
        or inv.get("revision") != MODEL_REV
        or inv.get("model_snapshot_inventory") != reader.inventory
        or plan.get("reference_reader_inventory") != reader.inventory
    ):
        raise ValueError("original frozen 0.5B files/model drift")
    previous = {}
    for cohort in COHORTS:
        for case in groups[cohort]:
            for arm in ARMS:
                key = (case.question.identity, arm)
                row = frozen[key]
                docs = selected(case, arm)
                bundle, originals, frontier = evidence(case, docs, arm)
                bundle.validate(
                    case.question, originals, frontier=frontier, revoked=set()
                )
                delivered = bundle.delivered()
                ids = reader.tokenizer.apply_chat_template(
                    prompt_messages(case.question, delivered, "labeled"),
                    tokenize=True,
                    add_generation_prompt=True,
                )
                receipt = row["reader"]
                if (
                    row["status"] != "succeeded"
                    or row["cohort"] != cohort
                    or row["selected"] != [d.identity for d in docs]
                    or receipt["reader_identity"] != reader.identity
                    or receipt["reader_profile"] != reader.profile
                    or receipt["bundle_digest"] != bundle.seal()
                    or receipt["question_digest"]
                    != native_digest(asdict(case.question))
                    or receipt["delivered_evidence"] != delivered
                    or receipt["input_ids_digest"] != native_digest(ids)
                    or receipt["input_tokens"] != len(ids)
                    or receipt["trainable_parameters"] != 0
                    or receipt["answer_postprocessed"] is not False
                ):
                    raise ValueError("original 0.5B input/source parity drift")
                previous[key] = row
    if len(previous) != REUSED_CALLS:
        raise ValueError("missing previously sealed responses")
    return previous, dict(
        verified_parent_sha256=STRONG_ZIP_SHA,
        baseline_raw_sha256=strict_json(files["trial/raw-seal.json"])["sha256"],
        reused_model_calls=len(previous),
        pinned_snapshot_inventory=reader.inventory,
    )


def run_line_reader(reader, case, docs, arm):
    """Call the exact same Qwen model, 64-token greedy profile, different view."""
    import torch

    bundle, originals, frontier = evidence(case, docs, arm)
    bundle.validate(case.question, originals, frontier=frontier, revoked=set())
    delivered = bundle.delivered()
    messages = line_messages(case.question, delivered)
    tokens_in = reader.tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True
    )
    if not tokens_in or len(tokens_in) > TOKEN_LIMIT:
        raise ValueError("plain input outside bounded Reader tokens")
    if len(tokens_in) + MAX_NEW_TOKENS > reader.model.config.max_position_embeddings:
        raise ValueError("plain Reader context exhausted")
    if reader.model.training or any(p.requires_grad for p in reader.model.parameters()):
        raise ValueError("nonfrozen Qwen model")
    x = torch.tensor([tokens_in], dtype=torch.long)
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
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
    elapsed_cpu, elapsed_wall = (
        time.process_time_ns() - cpu,
        time.perf_counter_ns() - wall,
    )
    generated = out[0, len(tokens_in) :].tolist()
    if not 1 <= len(generated) <= MAX_NEW_TOKENS:
        raise ValueError("unregistered generation length")
    answer = reader.tokenizer.decode(
        generated, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("empty generation")
    bundle.validate(case.question, originals, frontier=frontier, revoked=set())
    return answer, dict(
        reader_identity=reader.identity,
        reader_profile=native_digest((reader.profile, "plain-records.v1")),
        model_id=MODEL_ID,
        model_revision=MODEL_REV,
        generated_ids_digest=native_digest(generated),
        generated_tokens=len(generated),
        input_ids_digest=native_digest(tokens_in),
        input_tokens=len(tokens_in),
        bundle_digest=bundle.seal(),
        question_digest=native_digest(asdict(case.question)),
        delivered_evidence=delivered,
        token_limit=TOKEN_LIMIT,
        trainable_parameters=0,
        answer_postprocessed=False,
        cpu_time_ns=elapsed_cpu,
        wall_time_ns=elapsed_wall,
        production_accepted=False,
        view="lines",
    )


def planned_positions(groups):
    positions = []
    for name in REPEATED_COHORTS:
        for case in groups[name]:
            for arm in ARMS:
                positions.append((name, case, arm, "lines"))
                if name == FRESH_NAME:
                    positions.append((name, case, arm, "json"))
    if (
        len(positions) != NEW_CALLS
        or len({(c.question.identity, a, v) for _, c, a, v in positions}) != NEW_CALLS
    ):
        raise ValueError("new Reader position drift")
    # Fixed hash order counterbalances presentation for *new* questions.
    return sorted(
        positions,
        key=lambda x: (
            x[1].question.identity,
            (ARMS.index(x[2]) + int(digest(x[1].question.identity)[:8], 16))
            % len(ARMS),
            (int(digest(x[1].question.identity)[:8], 16) + VIEWS.index(x[3])) % 2,
        ),
    )


def score_pairs(rows, old, groups):
    all_new = {(r["qid"], r["arm"], r["view"]): r for r in rows}
    if len(all_new) != NEW_CALLS or len(rows) != NEW_CALLS:
        raise ValueError("new Reader census incomplete")
    stats = []
    for name in REPEATED_COHORTS:
        for arm in ARMS:
            left, right = [], []
            for case in groups[name]:
                key = (case.question.identity, arm)
                base = all_new[key + ("json",)] if name == FRESH_NAME else old[key]
                target = all_new[key + ("lines",)]
                if base["status"] != "succeeded" or target["status"] != "succeeded":
                    raise ValueError("unavailable model attempt in completed score")
                oldscore, newscore = (
                    outcome(case, arm, base["answer"]),
                    outcome(case, arm, target["answer"]),
                )
                left.append((base, oldscore))
                right.append((target, newscore))
            stats.append(
                dict(
                    cohort=name,
                    arm=arm,
                    planned=CASE_COUNT,
                    json_exact=sum(item["exact_answer_only"] for _, item in left),
                    lines_exact=sum(item["exact_answer_only"] for _, item in right),
                    json_refusals=sum(item["correct_refusal"] for _, item in left),
                    lines_refusals=sum(item["correct_refusal"] for _, item in right),
                    json_conditional_success=sum(
                        item["conditional_success"] for _, item in left
                    ),
                    lines_conditional_success=sum(
                        item["conditional_success"] for _, item in right
                    ),
                    discordant_json_only=sum(
                        a["conditional_success"] and not b["conditional_success"]
                        for (_, a), (_, b) in zip(left, right, strict=True)
                    ),
                    discordant_lines_only=sum(
                        b["conditional_success"] and not a["conditional_success"]
                        for (_, a), (_, b) in zip(left, right, strict=True)
                    ),
                    json_input_tokens=sum(
                        item["reader"]["input_tokens"] for item, _ in left
                    ),
                    lines_input_tokens=sum(
                        item["reader"]["input_tokens"] for item, _ in right
                    ),
                    json_decoder_tokens=sum(
                        item["reader"]["generated_tokens"] for item, _ in left
                    ),
                    lines_decoder_tokens=sum(
                        item["reader"]["generated_tokens"] for item, _ in right
                    ),
                    json_cpu_ns=sum(item["reader"]["cpu_time_ns"] for item, _ in left),
                    lines_cpu_ns=sum(
                        item["reader"]["cpu_time_ns"] for item, _ in right
                    ),
                    compute_matched=False,
                    independent_natural_language=False,
                )
            )
    return stats


def run(output, reader, *, parent_archive, source_commit, groups=None):
    if (
        not isinstance(source_commit, str)
        or not COMMIT_PATTERN.fullmatch(source_commit)
        or reader.identity != STRONG_READER_ID
    ):
        raise ValueError("exact study SHA and original frozen model required")
    groups = registered_cohorts() if groups is None else groups
    if set(groups) != set(REPEATED_COHORTS) or any(
        len(v) != CASE_COUNT for v in groups.values()
    ):
        raise ValueError("registered case counts only")
    baseline, verified = expected_parent(parent_archive, reader, groups)
    positions = planned_positions(groups)
    output.mkdir(exist_ok=False, parents=True)
    write(
        output / "plan.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            prior_0_5b_source_sha256=verified["verified_parent_sha256"],
            parent_raw_seal=verified["baseline_raw_sha256"],
            reused_json_calls=REUSED_CALLS,
            actual_new_calls=NEW_CALLS,
            frozen_revision=MODEL_REV,
            reference_reader_identity=reader.identity,
            views=list(VIEWS),
            cohorts={k: [c.question.identity for c in v] for k, v in groups.items()},
            arms=list(ARMS),
            evidence_bytes_unchanged=True,
            system_prompt_unchanged=True,
            greedy_output_token_limit=MAX_NEW_TOKENS,
            only_user_evidence_transport_changes=True,
            source_ids_never_replaced_or_truncated=True,
            no_training_or_online_gold_labels=True,
            not_compute_matched=True,
            prior_exposure_is_not_independent=False,
            independent_natural_language=False,
            production_accepted=False,
        ),
    )
    rows = []
    try:
        for name, case, arm, view in positions:
            row = dict(
                cohort=name,
                qid=case.question.identity,
                arm=arm,
                view=view,
                status="started",
            )
            append(output / "starts.jsonl", row)
            try:
                docs = selected(case, arm)
                selected_ids = [doc.identity for doc in docs]
                row["selected"] = selected_ids
                answer, receipt = (
                    reader.answer(case, docs, arm)
                    if view == "json"
                    else run_line_reader(reader, case, docs, arm)
                )
                bundle, _, _ = evidence(case, docs, arm)
                if (
                    not isinstance(answer, str)
                    or not answer.strip()
                    or receipt["reader_identity"] != reader.identity
                    or receipt["bundle_digest"] != bundle.seal()
                    or receipt["delivered_evidence"] != bundle.delivered()
                    or receipt["model_revision"] != MODEL_REV
                    or receipt["token_limit"] != TOKEN_LIMIT
                    or receipt["trainable_parameters"] != 0
                    or receipt["answer_postprocessed"] is not False
                ):
                    raise ValueError("model/evidence/output parity drift")
                row.update(answer=answer, reader=receipt, status="succeeded")
            except BaseException as exc:
                row.update(
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    unfinished_work_unknown=True,
                )
                append(output / "raw-answers.jsonl", row)
                raise
            append(output / "raw-answers.jsonl", row)
            rows.append(row)
        raw = (output / "raw-answers.jsonl").read_bytes()
        seal = hashlib.sha256(raw).hexdigest()
        write(
            output / "raw-seal.json",
            dict(sha256=seal, rows=NEW_CALLS, scoring_started=False),
        )
        stats = score_pairs(rows, baseline, groups)
        by_key = {(r["qid"], r["arm"], r["view"]): r for r in rows}
        pairs = []
        for cohort in REPEATED_COHORTS:
            for case in groups[cohort]:
                for arm in ARMS:
                    key = (case.question.identity, arm)
                    before = (
                        by_key[key + ("json",)]
                        if cohort == FRESH_NAME
                        else baseline[key]
                    )
                    after = by_key[key + ("lines",)]
                    pairs.append(
                        dict(
                            qid=key[0],
                            cohort=cohort,
                            arm=arm,
                            baseline_view="json",
                            new_view="lines",
                            baseline_score=outcome(case, arm, before["answer"]),
                            new_score=outcome(case, arm, after["answer"]),
                            baseline_input_tokens=before["reader"]["input_tokens"],
                            new_input_tokens=after["reader"]["input_tokens"],
                            baseline_output_tokens=before["reader"]["generated_tokens"],
                            new_output_tokens=after["reader"]["generated_tokens"],
                            baseline_cpu_ns=before["reader"]["cpu_time_ns"],
                            new_cpu_ns=after["reader"]["cpu_time_ns"],
                            sourced_original_answer=cohort != FRESH_NAME,
                        )
                    )
        if len(pairs) != REUSED_CALLS + CASE_COUNT * len(ARMS):
            raise ValueError("incomplete paired-source outcome census")
        write(output / "paired-scores.json", pairs)
        # Eligibility is fixed BEFORE looking at outcomes, on NEW question IDs only.
        fresh = [r for r in stats if r["cohort"] == FRESH_NAME]
        eligible = all(
            r["lines_conditional_success"] >= (15 if r["arm"] in ARMS[:2] else 18)
            for r in fresh
        ) and all(r["discordant_json_only"] == 0 for r in fresh)
        summary = dict(
            schema=SCHEMA,
            source_commit=source_commit,
            planned_new=NEW_CALLS,
            recorded_new=len(rows),
            failed_new=0,
            prior_json_reused=REUSED_CALLS,
            prediction_sha256=seal,
            results=stats,
            candidate_disposition=(
                "independent_confirmation_required"
                if eligible
                else "reader_transport_not_qualified"
            ),
            model_parameters_frozen=True,
            no_new_training=True,
            compute_matched=False,
            independent_semantic_approval=False,
            general_NDU_FBSDE_gain=False,
            production_accepted=False,
        )
        write(output / "summary.json", summary)
        if (
            hashlib.sha256((output / "raw-answers.jsonl").read_bytes()).hexdigest()
            != seal
        ):
            raise ValueError("prediction seal mutated after score")
        reader.verify_frozen()
        return summary
    except BaseException as exc:
        write(
            output / "failure.json",
            dict(
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                planned=NEW_CALLS,
                recorded=len(rows),
                cost_of_inflight_call_unknown=True,
                complete=False,
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
        source_commit=os.getenv("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(
                planned=result["planned_new"],
                recorded=result["recorded_new"],
                disposition=result["candidate_disposition"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
