"""Bounded source recall: in-training wording or source-derived paraphrase.

Checks whether a committed source-written adapter can recall its OWN training
facts in the exact writer prompt format. This is not generalization, QA gain,
independent review, citation entailment or production qualification.
"""

from dataclasses import asdict
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from bundle_reader import GENERATION
from experience_inference import frozen_adapter_mode
from experience_memory import render, source_examples
from native import Question, digest
from source_paraphrase_probe import paraphrase_writer_question

ARMS = ("base", "memory")
MAX_SCOPES = 16
CITE = re.compile(r"\[E[1-9][0-9]*\]")


def source_probe_plan(documents, *, revision, roots, maximum=MAX_SCOPES):
    if type(maximum) is not int or not 1 <= maximum <= MAX_SCOPES:
        raise ValueError("bounded source-only scope sample required")
    examples, dispositions = source_examples(
        documents, revision=revision, allowed_roots=roots, revoked=set()
    )
    by_scope = {}
    for item in examples:
        query = Question(**item["query"])
        by_scope.setdefault(query.scope, item)
    selected = tuple(by_scope[key] for key in sorted(by_scope)[:maximum])
    if not selected:
        raise ValueError("no unambiguous source-only probes")
    return selected, dispositions


def actual_generate(reader, prompt, mode):
    """Same frozen greedy generation budget as the registered task reader."""
    import torch

    if mode not in ARMS or not prompt:
        raise ValueError("unregistered source probe")
    if (
        len(prompt) + GENERATION["max_new_tokens"]
        > reader.model.config.max_position_embeddings
    ):
        raise ValueError("probe would overflow model position limit")
    x = torch.tensor([prompt], dtype=torch.long)
    start = time.perf_counter()
    with frozen_adapter_mode(reader.model, enabled=mode == "memory"):
        output = reader.model.generate(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            **GENERATION,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
    generated = output[0, len(prompt) :].tolist()
    answer = reader.tokenizer.decode(
        generated, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if not answer.strip():
        raise ValueError("probe returned empty generation")
    return answer, len(generated), time.perf_counter() - start


def probe(
    reader,
    documents,
    output,
    *,
    snapshot_sha,
    writer_source,
    source_commit,
    revision=2,
    maximum=MAX_SCOPES,
    generate=actual_generate,
    question_mode="training",
    training=None,
):
    if (
        question_mode not in ("training", "paraphrase")
        or output.exists()
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha)
        or not re.fullmatch(r"[0-9a-f]{40}", writer_source)
        or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or {d.root for d in documents} != reader.roots
        or {d.scope for d in documents} != reader.scopes
    ):
        raise ValueError("source-probe snapshot identity/scope mismatch")
    selected, unknown = source_probe_plan(
        documents, revision=revision, roots=reader.roots, maximum=maximum
    )
    # A source-derived writer question may never have received an optimizer
    # update. Recompute its exact schedule from the committed source and tokens.
    # Missing training metadata in fixture-only uses means exposure is UNKNOWN.
    from source_probe_exposure import verified_visits

    exposure, schedule_digest = (
        verified_visits(documents, reader.tokenizer, training)
        if training is not None
        else (None, None)
    )
    source_ids = tuple(item["query"]["identity"] for item in selected)
    if exposure is not None and not set(source_ids).issubset(exposure):
        raise ValueError("selected source question absent from writer schedule")
    visit_counts = tuple(
        exposure[q] if exposure is not None else None for q in source_ids
    )
    all_visited = exposure is not None and all(count > 0 for count in visit_counts)
    questions = tuple(
        paraphrase_writer_question(item)
        if question_mode == "paraphrase"
        else Question(**item["query"])
        for item in selected
    )
    # No target or evaluation-plan value is handed to generation. Each scope
    # contributes its first fixed training example, regardless of outcomes.
    output.mkdir()
    plan = dict(
        schema="hepta.source-recall.probe-plan.v1",
        snapshot_sha256=snapshot_sha,
        writer_source=writer_source,
        probe_source=source_commit,
        source_roots_sha256=digest(sorted(reader.roots)),
        reader_identity=reader.identity,
        reader_profile=reader.profile,
        source_questions=[asdict(q) for q in questions],
        selection="first-unambiguous-training-fact-per-sorted-scope",
        question_mode=question_mode,
        source_derived_untrained_question_wording=question_mode == "paraphrase",
        unresolved_source_dispositions=len(unknown),
        task_plan_or_test_labels_loaded=False,
        in_sample_training_recall=question_mode == "training" and all_visited,
        training_exposure_verified=exposure is not None,
        training_schedule_sha256=schedule_digest,
        source_training_question_ids=list(source_ids),
        source_example_optimizer_visits=list(visit_counts),
        unvisited_question_is_not_independent_holdout=True,
        production_accepted=False,
    )
    (output / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )
    records = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for q, training_question_id, visits in zip(
            questions, source_ids, visit_counts, strict=True
        ):
            prompt = render(reader.tokenizer, q, [], [])
            for arm in ARMS:
                row = dict(
                    question_id=q.identity,
                    scope=q.scope,
                    arm=arm,
                    prompt_sha256=digest(prompt),
                    input_tokens=len(prompt),
                    delivered_evidence=[],
                    source_training_question_id=training_question_id,
                    source_example_optimizer_visits=visits,
                    result_is_in_sample_training_recall=(
                        question_mode == "training" and visits > 0
                        if visits is not None
                        else None
                    ),
                )
                try:
                    answer, generated, seconds = generate(reader, prompt, arm)
                    if (
                        not isinstance(answer, str)
                        or not answer.strip()
                        or type(generated) is not int
                        or not 1 <= generated <= GENERATION["max_new_tokens"]
                        or type(seconds) not in (int, float)
                        or not math.isfinite(seconds)
                        or seconds < 0
                    ):
                        raise ValueError("invalid model generation receipt")
                    row.update(
                        status="succeeded",
                        answer=answer,
                        generated_tokens=generated,
                        seconds=seconds,
                    )
                except Exception as error:
                    row.update(
                        status="failed",
                        error_type=type(error).__name__,
                        error=str(error)[:512],
                    )
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                records.append(row)
    reader.verify_frozen()
    targets = {
        q.identity: item["target"] for q, item in zip(questions, selected, strict=True)
    }
    seen = {(r["question_id"], r["arm"]) for r in records}
    if len(seen) != len(records) or len(records) != len(questions) * len(ARMS):
        raise ValueError("incomplete probe census")
    stats = {
        arm: dict(
            planned=len(questions),
            succeeded=0,
            failed=0,
            exact_targets=0,
            unsupported_citation_answers=0,
            output_tokens=0,
            observed_seconds=0.0,
        )
        for arm in ARMS
    }
    # Keep answer quality split by actual optimizer exposure; an unvisited
    # target is not an independent future task or a failed memorization test.
    by_exposure = {
        arm: {
            category: dict(planned=0, succeeded=0, failed=0, exact_targets=0)
            for category in ("visited", "unvisited", "unknown")
        }
        for arm in ARMS
    }
    results = {}
    for row in records:
        visits = row["source_example_optimizer_visits"]
        category = (
            "unknown" if visits is None else "visited" if visits > 0 else "unvisited"
        )
        cohort = by_exposure[row["arm"]][category]
        cohort["planned"] += 1
        arm = row["arm"]
        item = stats[arm]
        if row["status"] == "failed":
            item["failed"] += 1
            cohort["failed"] += 1
            continue
        item["succeeded"] += 1
        cohort["succeeded"] += 1
        item["output_tokens"] += row["generated_tokens"]
        item["observed_seconds"] += row["seconds"]
        cites = len(CITE.findall(row["answer"]))
        item["unsupported_citation_answers"] += int(cites > 0)
        # Strict writer target: no fabricated citation or post-hoc rewriting.
        correct = row["answer"].strip() == targets[row["question_id"]]
        item["exact_targets"] += int(correct)
        cohort["exact_targets"] += int(correct)
        results[(row["question_id"], arm)] = correct
    wins = losses = paired = 0
    for q in questions:
        a, b = (results.get((q.identity, arm)) for arm in ARMS)
        if a is None or b is None:
            continue
        paired += 1
        wins += int(b and not a)
        losses += int(a and not b)
    raw = (output / "raw-answers.jsonl").read_bytes()
    report = dict(
        schema="hepta.source-recall.diagnostic.v1",
        generating_commit=source_commit,
        writer_source=writer_source,
        snapshot_sha256=snapshot_sha,
        plan_sha256=hashlib.sha256((output / "plan.json").read_bytes()).hexdigest(),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        selected_train_facts=len(questions),
        training_exposure_verified=exposure is not None,
        training_schedule_sha256=schedule_digest,
        visited_source_questions=sum(
            count > 0 for count in visit_counts if count is not None
        ),
        unvisited_source_questions=sum(
            count == 0 for count in visit_counts if count is not None
        ),
        by_exposure=by_exposure,
        model_calls=len(records) - sum(s["failed"] for s in stats.values()),
        arms=stats,
        compared_pairs=paired,
        memory_wins=wins,
        memory_losses=losses,
        unknown_pair_bounds=[
            (wins - losses - (len(questions) - paired)) / len(questions),
            (wins - losses + (len(questions) - paired)) / len(questions),
        ],
        input_is_trained_source_question=question_mode == "training" and all_visited,
        source_derived_untrained_query_paraphrase=question_mode == "paraphrase",
        zero_task_questions_or_labels_consumed=True,
        new_independent_holdout_observations=0,
        semantic_citation_precision=None,
        significance_established=False,
        production_accepted=False,
    )
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), flush=True)
    if any(s["failed"] for s in stats.values()):
        raise ValueError("source probe failures retained in original journal")
    return report


def main():
    from experience_write_trial import model_inputs, original_documents
    from event_memory_trial import read
    from experience_memory import ExperienceReader
    from pretrained import LoRAReader

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "model", "snapshot", "output"):
        parser.add_argument(name, type=Path)
    for name in ("source-sha", "stage-sha", "ready-sha", "source-commit"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--question-mode", choices=("training", "paraphrase"), default="training"
    )
    args = parser.parse_args()
    ready = read(args.snapshot / "READY.json", args.ready_sha)
    if (
        ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("not an unconsumed research-only source snapshot")
    docs = original_documents(args.sources, args.source_sha)
    if digest([asdict(d) for d in docs]) != ready["source_documents_digest"]:
        raise ValueError("source content differs from source-writer snapshot")
    _, inventory = model_inputs(args.model, args.stage_sha)
    if inventory["inventory_digest"] != ready["base_identity"]:
        raise ValueError("source probe uses a different pretrained reader")
    reader = ExperienceReader(
        args.model / "reader", expected_inventory=ready["base_identity"]
    )
    LoRAReader.load_candidate(
        reader,
        args.snapshot / "adapter",
        expected_manifest_sha256=ready["manifest_sha"],
        scope=reader.scope,
        allowed_roots={d.root for d in docs},
        revoked=set(),
    )
    reader.scopes = set(ready["scopes"])
    for parameter in reader.model.parameters():
        parameter.requires_grad_(False)
    if reader.profile != ready["reader_profile"]:
        raise ValueError("source probe changed reader profile")
    probe(
        reader,
        docs,
        args.output,
        snapshot_sha=args.ready_sha,
        writer_source=ready["writer_source"],
        source_commit=args.source_commit,
        question_mode=args.question_mode,
        training=ready["training"],
    )


if __name__ == "__main__":
    main()
