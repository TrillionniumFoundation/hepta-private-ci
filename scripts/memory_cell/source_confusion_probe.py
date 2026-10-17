"""Source-only paired confusion probe; never a downstream task-quality claim.

A correct value and a same-scope confusable value are derived exclusively from
admitted source facts. Both have equal tokenizer completion lengths, the same
question and the same evidence-free prompt, before and after a frozen adapter.
This tests whether source writing improves RELATIONAL DISCRIMINATION rather than
merely increasing the probability of any learned source string.
"""

from dataclasses import asdict
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re

from event_projection import EventProjection
from experience_memory import render, source_examples
from native import Question, digest
from source_paraphrase_probe import paraphrase_writer_question
from source_recall_likelihood import (
    ARMS,
    WORDINGS,
    _valid_score,
    conditional_nll,
)

MAX_SCOPES = 2
KINDS = ("target", "distractor")


def eligible_pairs(documents, tokenizer, *, roots, revision=2, maximum=MAX_SCOPES):
    if type(maximum) is not int or not 1 <= maximum <= MAX_SCOPES:
        raise ValueError("bounded confusion scope count required")
    examples, dispositions = source_examples(
        documents, revision=revision, allowed_roots=roots, revoked=set()
    )
    grouped = {}
    for ex in examples:
        q = Question(**ex["query"])
        grouped.setdefault(q.scope, []).append(ex)
    chosen, unavailable = [], []
    for scope in sorted(grouped):
        if len(chosen) >= maximum:
            break
        projection = EventProjection(tuple(d for d in documents if d.scope == scope))
        annotated = []
        for ex in grouped[scope]:
            facts = [projection.facts[key] for key in ex["sources"]]
            if not facts or len({(f["entity"], f["attribute"]) for f in facts}) != 1:
                raise ValueError("source-derived facts differ from certified relation")
            entity, attribute = facts[0]["entity"], facts[0]["attribute"]
            annotated.append((ex, entity, attribute))
        choices = []
        for positive, entity, attribute in annotated:
            for negative, other_entity, other_attribute in annotated:
                if positive["query"]["identity"] == negative["query"]["identity"]:
                    continue
                if positive["target"] == negative["target"]:
                    continue
                if attribute == other_attribute and entity != other_entity:
                    category = "same_attribute_other_entity"
                elif entity == other_entity and attribute != other_attribute:
                    category = "same_entity_other_attribute"
                else:
                    continue
                a = tokenizer.encode(positive["target"], add_special_tokens=False)
                b = tokenizer.encode(negative["target"], add_special_tokens=False)
                if not a or not b or len(a) != len(b):
                    continue
                choices.append(
                    (
                        0 if category == "same_attribute_other_entity" else 1,
                        positive["query"]["identity"],
                        negative["query"]["identity"],
                        positive,
                        negative,
                        category,
                        len(a),
                    )
                )
        if not choices:
            unavailable.append(scope)
            continue
        _, _, _, positive, negative, category, tokens = min(
            choices, key=lambda x: x[:3]
        )
        chosen.append(
            dict(
                scope=scope,
                positive=positive,
                negative=negative,
                negative_category=category,
                completion_tokens=tokens,
            )
        )
    return tuple(chosen), tuple(unavailable), dispositions


def summarize(rows, pairs):
    expected = {
        (pair["scope"], wording, arm, kind)
        for pair in pairs
        for wording in WORDINGS
        for arm in ARMS
        for kind in KINDS
    }
    keyed = {
        (r["scope"], r["wording"], r["arm"], r["completion_kind"]): r for r in rows
    }
    if len(keyed) != len(rows) or set(keyed) != expected:
        raise ValueError("missing, duplicated or substituted likelihood observation")
    summary = {}
    for wording in WORDINGS:
        complete = improved = corrected = regressed = 0
        margin_deltas = []
        for pair in pairs:
            scope = pair["scope"]
            values = {
                (arm, kind): keyed[(scope, wording, arm, kind)]
                for arm in ARMS
                for kind in KINDS
            }
            if len({r["prompt_sha256"] for r in values.values()}) != 1:
                raise ValueError("paired arms/targets changed the question or prompt")
            if any(r["status"] != "succeeded" for r in values.values()):
                continue
            if len({r["supervised_tokens"] for r in values.values()}) != 1:
                raise ValueError("comparison changed supervised token length")
            base = (
                values["base", "distractor"]["mean_nll"]
                - values["base", "target"]["mean_nll"]
            )
            learned = (
                values["memory", "distractor"]["mean_nll"]
                - values["memory", "target"]["mean_nll"]
            )
            change = learned - base
            margin_deltas.append(change)
            complete += 1
            improved += change > 0
            corrected += base <= 0 < learned
            regressed += base > 0 >= learned
        summary[wording] = dict(
            planned_pairs=len(pairs),
            complete_pairs=complete,
            missing_or_failed_pairs=len(pairs) - complete,
            positive_margin_delta_pairs=improved,
            wrong_to_correct_pairs=corrected,
            correct_to_wrong_pairs=regressed,
            mean_margin_delta=sum(margin_deltas) / complete if complete else None,
            same_length_mean_token_nll_not_answer_accuracy=True,
        )
    return summary


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
        or {d.root for d in documents} != reader.roots
        or {d.scope for d in documents} != reader.scopes
    ):
        raise ValueError("source-confusion snapshot identity/authority mismatch")
    pairs, unavailable, dispositions = eligible_pairs(
        documents, reader.tokenizer, roots=reader.roots, maximum=maximum
    )
    from source_probe_exposure import verified_visits

    visits, exposure_digest = (
        verified_visits(documents, reader.tokenizer, training)
        if training is not None
        else (None, None)
    )
    if visits is not None and any(
        p["positive"]["query"]["identity"] not in visits
        or p["negative"]["query"]["identity"] not in visits
        for p in pairs
    ):
        raise ValueError("source question absent from registered write schedule")
    prepared = []
    for pair in pairs:
        for wording in WORDINGS:
            question = (
                Question(**pair["positive"]["query"])
                if wording == "training"
                else paraphrase_writer_question(pair["positive"])
            )
            prompt = render(reader.tokenizer, question, [], [])
            prepared.append((pair, wording, question, prompt))
    plan = dict(
        schema="hepta.source-confusion.plan.v1",
        snapshot_sha256=snapshot_sha,
        writer_source=writer_source,
        probe_source=source_commit,
        reader_identity=reader.identity,
        reader_profile=reader.profile,
        source_roots_sha256=digest(sorted(reader.roots)),
        all_model_evidence_empty=True,
        actual_training_exposure_verified=visits is not None,
        training_schedule_sha256=exposure_digest,
        comparisons=[
            dict(
                scope=p["scope"],
                category=p["negative_category"],
                question=asdict(q),
                prompt_sha256=digest(prompt),
                target_digest=digest(p["positive"]["target"]),
                distractor_digest=digest(p["negative"]["target"]),
                target_training_question_id=p["positive"]["query"]["identity"],
                distractor_training_question_id=p["negative"]["query"]["identity"],
                positive_optimizer_visits=(
                    visits[p["positive"]["query"]["identity"]]
                    if visits is not None
                    else None
                ),
                distractor_optimizer_visits=(
                    visits[p["negative"]["query"]["identity"]]
                    if visits is not None
                    else None
                ),
                equal_completion_tokens=p["completion_tokens"],
                wording=wording,
            )
            for p, wording, q, prompt in prepared
        ],
        ineligible_scopes=list(unavailable),
        source_dispositions=len(dispositions),
        publisher_test_questions_or_answers_consumed=False,
        no_independent_source_family_added=True,
        production_accepted=False,
    )
    output.mkdir()
    plan_path = output / "plan.json"
    with plan_path.open("x", encoding="utf-8") as stream:
        json.dump(plan, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    rows = []
    raw_path = output / "raw-likelihoods.jsonl"
    with raw_path.open("x", encoding="utf-8") as stream:
        for pair, wording, question, prompt in prepared:
            for arm in ARMS:
                for kind in KINDS:
                    completion = (
                        pair["positive"]["target"]
                        if kind == "target"
                        else pair["negative"]["target"]
                    )
                    row = dict(
                        scope=pair["scope"],
                        question_id=question.identity,
                        wording=wording,
                        arm=arm,
                        completion_kind=kind,
                        negative_category=pair["negative_category"],
                        prompt_sha256=digest(prompt),
                        completion_sha256=digest(completion),
                        delivered_evidence=[],
                        supervised_completion_tokens=pair["completion_tokens"] + 1,
                        teacher_forced_not_generated=True,
                    )
                    try:
                        score = scorer(reader, prompt, completion, arm)
                        _valid_score(score, len(prompt))
                        if score["supervised_tokens"] != pair["completion_tokens"] + 1:
                            raise ValueError("different completion tokenizer length")
                        row.update(status="succeeded", **score)
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
    summary = summarize(rows, pairs)
    report = dict(
        schema="hepta.source-confusion.diagnostic.v1",
        generating_source=source_commit,
        snapshot_sha256=snapshot_sha,
        plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        available_relation_pairs=len(pairs),
        comparison_eligible=bool(pairs),
        no_eligible_pair_cannot_establish_gain=True,
        scanned_source_scopes=len(pairs) + len(unavailable),
        unavailable_source_scopes=len(unavailable),
        scores_expected=len(pairs) * len(WORDINGS) * len(ARMS) * len(KINDS),
        scores_completed=sum(r["status"] == "succeeded" for r in rows),
        results_by_wording=summary,
        reader_frozen_verified=True,
        source_only_supervision_not_future_task=True,
        independent_semantic_precision=None,
        actual_end_to_end_task_gain=None,
        significance_established=False,
        production_accepted=False,
    )
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False), flush=True)
    if report["scores_completed"] != report["scores_expected"]:
        raise ValueError("incomplete source-confusion observations retained")
    return report


def main():
    from event_memory_trial import read
    from experience_memory import ExperienceReader
    from experience_write_trial import model_inputs, original_documents
    from native import digest
    from pretrained import LoRAReader

    parser = argparse.ArgumentParser(description=__doc__)
    for item in ("sources", "model", "snapshot", "output"):
        parser.add_argument(item, type=Path)
    for key in ("source-sha", "stage-sha", "ready-sha", "source-commit"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--maximum", type=int, default=MAX_SCOPES)
    a = parser.parse_args()
    ready = read(a.snapshot / "READY.json", a.ready_sha)
    if (
        ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("not a committed pre-task source-only snapshot")
    docs = original_documents(a.sources, a.source_sha)
    if digest([asdict(d) for d in docs]) != ready["source_documents_digest"]:
        raise ValueError("source documents differ from the committed writer")
    _, inventory = model_inputs(a.model, a.stage_sha)
    if inventory["inventory_digest"] != ready["base_identity"]:
        raise ValueError("different pretrained reader or model files")
    reader = ExperienceReader(
        a.model / "reader", expected_inventory=ready["base_identity"]
    )
    LoRAReader.load_candidate(
        reader,
        a.snapshot / "adapter",
        expected_manifest_sha256=ready["manifest_sha"],
        scope=reader.scope,
        allowed_roots={d.root for d in docs},
        revoked=set(),
    )
    reader.scopes = set(ready["scopes"])
    for parameter in reader.model.parameters():
        parameter.requires_grad_(False)
    if reader.profile != ready["reader_profile"]:
        raise ValueError("reader profile changed after source writing")
    return probe(
        reader,
        docs,
        a.output,
        snapshot_sha=a.ready_sha,
        writer_source=ready["writer_source"],
        source_commit=a.source_commit,
        maximum=a.maximum,
        training=ready["training"],
    )


if __name__ == "__main__":
    main()
