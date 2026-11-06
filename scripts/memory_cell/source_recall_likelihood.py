"""Source-only teacher-forced knowledge probe; NOT answer generation or acceptance.

Score the same precommitted source fact under the base and source-written
adapter, with the training question and a source-derived alternate wording.
This distinguishes conditional probability movement from greedy readout.
No evaluation task, gold test answer, or reference-only evidence is loaded.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from experience_memory import render
from native import Question, digest
from source_paraphrase_probe import paraphrase_writer_question
from source_recall_probe import source_probe_plan

ARMS = ("base", "memory")
COMPLETIONS = ("target", "refusal")
WORDINGS = ("training", "paraphrase")
REFUSAL = "I do not have enough evidence."
MAX_SCOPES = 8


def conditional_nll(reader, prompt, completion, arm):
    """One real no-gradient, same-prompt conditional likelihood measurement.

    The reference completion is teacher-forced for DIAGNOSIS, never inserted
    into a generation prompt or trained on during this diagnostic.
    """
    from experience_inference import frozen_adapter_mode
    from grounded_protocol import completion_ids
    from source_completion_loss import completion_loss

    if (
        arm not in ARMS
        or not prompt
        or not isinstance(completion, str)
        or not completion
    ):
        raise ValueError("bounded real likelihood input required")
    ids, labels = completion_ids(reader.tokenizer, prompt, completion, maximum=2112)
    started = time.perf_counter()
    with frozen_adapter_mode(reader.model, enabled=arm == "memory"):
        loss, projection = completion_loss(
            reader.model, ids, labels, backend="supervised_positions"
        )
    value = float(loss.detach())
    if not math.isfinite(value) or value < 0:
        raise ValueError("nonfinite actual conditional negative log likelihood")
    return dict(
        mean_nll=value,
        input_tokens=projection["input_tokens"],
        supervised_tokens=projection["supervised_tokens"],
        seconds=time.perf_counter() - started,
    )


def _valid_score(result, prefix):
    if not isinstance(result, dict) or set(result) != {
        "mean_nll",
        "input_tokens",
        "supervised_tokens",
        "seconds",
    }:
        raise ValueError("incomplete conditional likelihood receipt")
    if (
        type(result["mean_nll"]) not in (int, float)
        or not math.isfinite(result["mean_nll"])
        or result["mean_nll"] < 0
        or type(result["seconds"]) not in (int, float)
        or not math.isfinite(result["seconds"])
        or result["seconds"] < 0
        or type(result["input_tokens"]) is not int
        or type(result["supervised_tokens"]) is not int
        or result["input_tokens"] <= prefix
        or not 1 <= result["supervised_tokens"] == result["input_tokens"] - prefix
        or result["input_tokens"] > 2112
    ):
        raise ValueError("invalid conditional likelihood/count/cost receipt")


def summarize(rows, scopes):
    expected = {
        (wording, scope, arm, completion)
        for wording in WORDINGS
        for scope in scopes
        for arm in ARMS
        for completion in COMPLETIONS
    }
    keys = [(r["wording"], r["scope"], r["arm"], r["completion_kind"]) for r in rows]
    if (
        len(rows) != len(expected)
        or len(set(keys)) != len(keys)
        or set(keys) != expected
    ):
        raise ValueError("incomplete original likelihood comparison census")
    grouped = {
        (r["wording"], r["scope"], r["arm"], r["completion_kind"]): r for r in rows
    }
    result = {}
    for wording in WORDINGS:
        full = improved_target = improved_margin = 0
        target_change = margin_change = 0.0
        for scope in scopes:
            subset = [
                grouped[(wording, scope, arm, kind)]
                for arm in ARMS
                for kind in COMPLETIONS
            ]
            if len({r["prompt_sha256"] for r in subset}) != 1:
                raise ValueError("base and adapter did not score the same question")
            if any(r["status"] != "succeeded" for r in subset):
                continue
            scores = {(r["arm"], r["completion_kind"]): r["mean_nll"] for r in subset}
            # Smaller negative log-likelihood means higher mean token probability.
            change = scores["base", "target"] - scores["memory", "target"]
            baseline_margin = scores["base", "refusal"] - scores["base", "target"]
            memory_margin = scores["memory", "refusal"] - scores["memory", "target"]
            full += 1
            target_change += change
            margin_change += memory_margin - baseline_margin
            improved_target += change > 0
            improved_margin += memory_margin > baseline_margin
        result[wording] = dict(
            planned_source_scopes=len(scopes),
            complete_base_adapter_pairs=full,
            missing_or_failed_scopes=len(scopes) - full,
            target_mean_nll_decreased_count=improved_target,
            relative_target_refusal_margin_improved_count=improved_margin,
            mean_target_nll_change=(target_change / full if full else None),
            mean_relative_margin_change=(margin_change / full if full else None),
            mean_token_nll_is_not_greedy_answer_success=True,
        )
    return result


def probe(
    reader,
    documents,
    output,
    *,
    snapshot_sha,
    writer_source,
    source_commit,
    maximum=MAX_SCOPES,
    scorer=conditional_nll,
    training=None,
):
    if (
        output.exists()
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot_sha)
        or not re.fullmatch(r"[0-9a-f]{40}", writer_source)
        or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or not callable(scorer)
        or type(maximum) is not int
        or not 1 <= maximum <= MAX_SCOPES
        or {d.root for d in documents} != reader.roots
        or {d.scope for d in documents} != reader.scopes
    ):
        raise ValueError("unbound or previously written likelihood probe")
    examples, dispositions = source_probe_plan(
        documents, revision=2, roots=reader.roots, maximum=maximum
    )
    from source_probe_exposure import verified_visits

    exposure, exposure_digest = (
        verified_visits(documents, reader.tokenizer, training)
        if training is not None
        else (None, None)
    )
    original_questions = tuple(ex["query"]["identity"] for ex in examples)
    if exposure is not None and not set(original_questions).issubset(exposure):
        raise ValueError("teacher-forced source question absent from writer schedule")
    visits = tuple(
        exposure[q] if exposure is not None else None for q in original_questions
    )
    scopes = tuple(Question(**x["query"]).scope for x in examples)
    if len(scopes) != len(set(scopes)):
        raise ValueError("duplicate source-only probe scope")
    prompts = []
    for wording in WORDINGS:
        for ex in examples:
            question = (
                Question(**ex["query"])
                if wording == "training"
                else paraphrase_writer_question(ex)
            )
            prompt = render(reader.tokenizer, question, [], [])
            original_id = ex["query"]["identity"]
            index = original_questions.index(original_id)
            prompts.append(
                (wording, question, prompt, ex["target"], original_id, visits[index])
            )
    # Pin the question/prompt identities before opening the diagnostic target.
    plan = dict(
        schema="hepta.source-recall-likelihood.plan.v1",
        snapshot_sha256=snapshot_sha,
        writer_source=writer_source,
        probe_source=source_commit,
        reader_identity=reader.identity,
        reader_profile=reader.profile,
        source_roots_sha256=digest(sorted(reader.roots)),
        scopes=list(scopes),
        wordings=list(WORDINGS),
        training_exposure_verified=exposure is not None,
        training_schedule_sha256=exposure_digest,
        source_question_optimizer_visits=list(visits),
        unvisited_question_is_not_independent_holdout=True,
        questions=[
            dict(
                wording=w,
                question=asdict(q),
                prompt_sha256=digest(p),
                target_digest=digest(target),
                training_question_id=original_id,
                optimizer_visits=count,
            )
            for w, q, p, target, original_id, count in prompts
        ],
        unresolved_source_facts=len(dispositions),
        all_evidence_views_empty=True,
        teacher_forced_reference_only_for_diagnostic=True,
        future_evaluation_plan_or_answers_used=False,
        production_accepted=False,
    )
    output.mkdir()
    (output / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )
    rows = []
    with (output / "raw-likelihoods.jsonl").open("x", encoding="utf-8") as stream:
        for wording, question, prompt, target, original_id, count in prompts:
            for arm in ARMS:
                for kind in COMPLETIONS:
                    value = target if kind == "target" else REFUSAL
                    row = dict(
                        wording=wording,
                        question_id=question.identity,
                        scope=question.scope,
                        arm=arm,
                        completion_kind=kind,
                        prompt_sha256=digest(prompt),
                        target_digest=digest(target),
                        delivered_evidence=[],
                        teacher_forced_not_generated=True,
                        training_question_id=original_id,
                        source_example_optimizer_visits=count,
                    )
                    try:
                        receipt = scorer(reader, prompt, value, arm)
                        _valid_score(receipt, len(prompt))
                        row.update(status="succeeded", **receipt)
                    except Exception as error:
                        row.update(
                            status="failed",
                            error_type=type(error).__name__,
                            error=str(error)[:512],
                        )
                    stream.write(
                        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                    rows.append(row)
    reader.verify_frozen()
    summary = summarize(rows, scopes)
    by_exposure = {}
    for category in ("visited", "unvisited", "unknown"):
        scoped = tuple(
            scope
            for scope, count in zip(scopes, visits, strict=True)
            if (
                (
                    "unknown"
                    if count is None
                    else "visited"
                    if count > 0
                    else "unvisited"
                )
                == category
            )
        )
        scoped_set = set(scoped)
        by_exposure[category] = summarize(
            [row for row in rows if row["scope"] in scoped_set], scoped
        )
    report = dict(
        schema="hepta.source-recall-likelihood.diagnostic.v1",
        source_commit=source_commit,
        snapshot_sha256=snapshot_sha,
        original_plan_sha256=hashlib.sha256(
            (output / "plan.json").read_bytes()
        ).hexdigest(),
        original_records_sha256=hashlib.sha256(
            (output / "raw-likelihoods.jsonl").read_bytes()
        ).hexdigest(),
        planned_records=len(rows),
        completed_records=sum(r["status"] == "succeeded" for r in rows),
        score_comparisons=summary,
        training_exposure_verified=exposure is not None,
        training_schedule_sha256=exposure_digest,
        visited_source_questions=sum(v > 0 for v in visits if v is not None),
        unvisited_source_questions=sum(v == 0 for v in visits if v is not None),
        by_exposure=by_exposure,
        experiment_scores_source_training_facts_only=True,
        all_input_evidence_empty=True,
        prediction_did_not_generate_answers=True,
        independently_reviewed_semantic_precision=None,
        parameter_memory_task_gain=None,
        independent_future_windows=0,
        production_accepted=False,
    )
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), flush=True)
    if report["completed_records"] != len(rows):
        raise ValueError("incomplete likelihood observations retained in journal")
    return report


def main():
    from event_memory_trial import read
    from experience_memory import ExperienceReader
    from experience_write_trial import model_inputs, original_documents
    from native import digest
    from pretrained import LoRAReader

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "model", "snapshot", "output"):
        parser.add_argument(name, type=Path)
    for name in ("source-sha", "stage-sha", "ready-sha", "source-commit"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--maximum", type=int, default=MAX_SCOPES)
    args = parser.parse_args()
    ready = read(args.snapshot / "READY.json", args.ready_sha)
    if (
        ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("source-only snapshot has not been admitted")
    docs = original_documents(args.sources, args.source_sha)
    if digest([asdict(d) for d in docs]) != ready["source_documents_digest"]:
        raise ValueError("source roots changed after writing")
    _, inventory = model_inputs(args.model, args.stage_sha)
    if inventory["inventory_digest"] != ready["base_identity"]:
        raise ValueError("likelihood reader differs from committed source model")
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
    for p in reader.model.parameters():
        p.requires_grad_(False)
    if reader.profile != ready["reader_profile"]:
        raise ValueError("source reader prompt profile drift")
    return probe(
        reader,
        docs,
        args.output,
        snapshot_sha=args.ready_sha,
        writer_source=ready["writer_source"],
        source_commit=args.source_commit,
        maximum=args.maximum,
        training=ready["training"],
    )


if __name__ == "__main__":
    main()
