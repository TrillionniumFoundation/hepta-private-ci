"""Source-only greedy-vs-beam readout factorial on the SAME frozen reader.

This separates decoder search from adapter effects. It cannot prove a factual
memory gain, because the questions and targets are derived from training sources.
No test plan, answer list, alternate candidate text or source evidence is
passed to either decoder. Original model outputs are journaled before scoring.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

from bundle_reader import GENERATION
from experience_memory import ExperienceReader, render
from native import Question, digest
from source_paraphrase_probe import paraphrase_writer_question
from source_recall_probe import ARMS, actual_generate, probe, source_probe_plan

DECODERS = ("greedy", "beam2")
MAX_SCOPES = 8


def beam2_generate(reader, prompt, arm):
    """Search change only: same model, prompt, tokens, and source-free input."""
    import torch
    from experience_inference import frozen_adapter_mode

    if arm not in ARMS or not prompt:
        raise ValueError("unregistered readout arm")
    if (
        len(prompt) + GENERATION["max_new_tokens"]
        > reader.model.config.max_position_embeddings
    ):
        raise ValueError("bounded beam prompt exceeds model positions")
    x = torch.tensor([prompt], dtype=torch.long)
    settings = GENERATION | {
        "num_beams": 2,
        "num_return_sequences": 1,
        "length_penalty": 1.0,
        "early_stopping": True,
    }
    started = time.perf_counter()
    with frozen_adapter_mode(reader.model, enabled=arm == "memory"):
        result = reader.model.generate(
            input_ids=x,
            attention_mask=torch.ones_like(x),
            **settings,
            eos_token_id=reader.tokenizer.eos_token_id,
            pad_token_id=reader.tokenizer.eos_token_id,
        )
    ids = result[0, len(prompt) :].tolist()
    answer = reader.tokenizer.decode(
        ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    if not answer.strip():
        raise ValueError("empty beam answer")
    return answer, len(ids), time.perf_counter() - started


def _keyed(rows, targets):
    expected = {(qid, arm) for qid in targets for arm in ARMS}
    keys = [(row["question_id"], row["arm"]) for row in rows]
    if (
        len(rows) != len(expected)
        or len(set(keys)) != len(rows)
        or set(keys) != expected
    ):
        raise ValueError("incomplete or duplicated source readout census")
    result = dict(zip(keys, rows, strict=True))
    for (qid, _arm), row in result.items():
        if (
            row["status"] not in ("succeeded", "failed")
            or row["delivered_evidence"] != []
            or not isinstance(row["prompt_sha256"], str)
            or not row["prompt_sha256"]
            or type(row["input_tokens"]) is not int
            or row["input_tokens"] <= 0
            or not isinstance(row["source_training_question_id"], str)
        ):
            raise ValueError("source readout is not bound to an empty context")
        if row["status"] == "succeeded":
            if (
                not isinstance(row.get("answer"), str)
                or not row["answer"].strip()
                or type(row.get("generated_tokens")) is not int
                or not 1 <= row["generated_tokens"] <= GENERATION["max_new_tokens"]
                or type(row.get("seconds")) not in (int, float)
                or not math.isfinite(row["seconds"])
                or row["seconds"] < 0
            ):
                raise ValueError("invalid generated answer or cost")
        if qid not in targets:
            raise ValueError("unexpected source question")
    return result


def summarize(greedy_rows, beam_rows, targets):
    """Paired factual-string success, not official QA or semantic citation quality."""
    if (
        not isinstance(targets, dict)
        or not 1 <= len(targets) <= MAX_SCOPES
        or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in targets.items()
        )
    ):
        raise ValueError("bounded original source-target census required")
    indexed = {
        "greedy": _keyed(greedy_rows, targets),
        "beam2": _keyed(beam_rows, targets),
    }
    for decoder in DECODERS:
        for qid in targets:
            base, memory = (indexed[decoder][qid, arm] for arm in ARMS)
            for key in (
                "prompt_sha256",
                "input_tokens",
                "scope",
                "source_training_question_id",
                "source_example_optimizer_visits",
            ):
                if base[key] != memory[key]:
                    raise ValueError("decoder compared different base/adapter inputs")
    for qid in targets:
        for arm in ARMS:
            a, b = (indexed[decoder][qid, arm] for decoder in DECODERS)
            for key in (
                "prompt_sha256",
                "input_tokens",
                "scope",
                "source_training_question_id",
                "source_example_optimizer_visits",
            ):
                if a[key] != b[key]:
                    raise ValueError("decoder comparison changed question or exposure")

    def score(a, b):
        complete = wins = losses = different = success_a = success_b = 0
        for qid, target in targets.items():
            left, right = a(qid), b(qid)
            if left["status"] != "succeeded" or right["status"] != "succeeded":
                continue
            complete += 1
            la = left["answer"].strip() == target
            rb = right["answer"].strip() == target
            success_a += int(la)
            success_b += int(rb)
            wins += int(rb and not la)
            losses += int(la and not rb)
            different += int(left["answer"] != right["answer"])
        missing = len(targets) - complete
        return dict(
            planned_pairs=len(targets),
            complete_pairs=complete,
            baseline_exact=success_a,
            candidate_exact=success_b,
            candidate_wins=wins,
            candidate_losses=losses,
            missing_pairs=missing,
            changed_outputs=different,
            all_planned_effect_bounds=[
                (wins - losses - missing) / len(targets),
                (wins - losses + missing) / len(targets),
            ],
            significance_established=False,
        )

    decoding = {
        arm: score(
            lambda qid: indexed["greedy"][qid, arm],
            lambda qid: indexed["beam2"][qid, arm],
        )
        for arm in ARMS
    }
    adaptation = {
        decoder: score(
            lambda qid: indexed[decoder][qid, "base"],
            lambda qid: indexed[decoder][qid, "memory"],
        )
        for decoder in DECODERS
    }
    interactions = []
    for qid, target in targets.items():
        group = {
            (decoder, arm): indexed[decoder][qid, arm]
            for decoder in DECODERS
            for arm in ARMS
        }
        if any(x["status"] != "succeeded" for x in group.values()):
            continue
        success = {
            key: int(value["answer"].strip() == target) for key, value in group.items()
        }
        interactions.append(
            (success["beam2", "memory"] - success["greedy", "memory"])
            - (success["beam2", "base"] - success["greedy", "base"])
        )
    return dict(
        schema="hepta.source-decode-factorial.v1",
        planned_questions=len(targets),
        observed_four_arm_interactions=len(interactions),
        missing_four_arm_interactions=len(targets) - len(interactions),
        decoder_effect_holding_adapter_fixed=decoding,
        adapter_effect_holding_decoder_fixed=adaptation,
        observed_interaction_mean=(
            sum(interactions) / len(interactions) if interactions else None
        ),
        all_four_arm_predictions_are_from_actual_generation=True,
        no_candidate_values_or_targets_supplied_to_generation=True,
        source_training_questions_are_not_independent_holdout=True,
        changed_decoding_is_not_a_lora_gain=True,
        independent_citation_semantics=None,
        population_superiority_established=False,
        production_accepted=False,
    )


def paired_probe(
    reader,
    documents,
    output,
    *,
    snapshot_sha,
    writer_source,
    source_commit,
    question_mode="paraphrase",
    maximum=MAX_SCOPES,
    training=None,
    greedy=actual_generate,
    beam=beam2_generate,
):
    if (
        output.exists()
        or question_mode not in ("training", "paraphrase")
        or type(maximum) is not int
        or not 1 <= maximum <= MAX_SCOPES
        or not callable(greedy)
        or not callable(beam)
    ):
        raise ValueError("new bounded paired source readout required")
    selected, _ = source_probe_plan(
        documents, revision=2, roots=reader.roots, maximum=maximum
    )
    questions = [
        paraphrase_writer_question(item)
        if question_mode == "paraphrase"
        else Question(**item["query"])
        for item in selected
    ]
    targets = {
        q.identity: item["target"] for q, item in zip(questions, selected, strict=True)
    }
    if len(targets) != len(questions):
        raise ValueError("duplicate source question")
    # Render the full REAL Reader input, including explicit source scope,
    # before any model call. Equal input tokens for different questions
    # cannot count as two independent tests, even if labels differ.
    planned_prompts = {
        q.identity: digest(render(reader.tokenizer, q, [], [])) for q in questions
    }
    if len(set(planned_prompts.values())) != len(questions):
        raise ValueError(
            "colliding source questions have indistinguishable Reader prompts"
        )
    output.mkdir()
    plan = dict(
        schema="hepta.source-decode-factorial.plan.v1",
        snapshot_sha256=snapshot_sha,
        writer_source=writer_source,
        probe_source=source_commit,
        source_roots_sha256=digest(sorted(reader.roots)),
        reader_identity=reader.identity,
        reader_profile=reader.profile,
        question_mode=question_mode,
        questions=[asdict(q) for q in questions],
        source_targets_sha256=digest(targets),
        exact_empty_context_prompt_sha256_by_question=planned_prompts,
        exact_prompt_collision_rejected_before_generation=True,
        options=dict(
            greedy=GENERATION,
            beam2=GENERATION
            | {
                "num_beams": 2,
                "num_return_sequences": 1,
                "length_penalty": 1.0,
                "early_stopping": True,
            },
        ),
        task_labels_or_evaluation_plan_loaded=False,
        production_accepted=False,
    )
    (output / "plan.json").write_text(
        json.dumps(plan, allow_nan=False, indent=2) + "\n"
    )
    for decoder, generator in (("greedy", greedy), ("beam2", beam)):
        probe(
            reader,
            documents,
            output / decoder,
            snapshot_sha=snapshot_sha,
            writer_source=writer_source,
            source_commit=source_commit,
            revision=2,
            maximum=maximum,
            generate=generator,
            question_mode=question_mode,
            training=training,
        )

    def unique_object(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate journal field")
            result[key] = value
        return result

    def reject_nonfinite(value):
        raise ValueError("nonfinite journal value")

    records = {}
    digests = {}
    for decoder in DECODERS:
        original = (output / decoder / "raw-answers.jsonl").read_bytes()
        records[decoder] = [
            json.loads(
                line, object_pairs_hook=unique_object, parse_constant=reject_nonfinite
            )
            for line in original.decode().splitlines()
        ]
        digests[decoder] = hashlib.sha256(original).hexdigest()
    # Reject a tokenizer/prompt drift after preregistration. All raw
    # journal rows exist before these checks and before target scoring.
    for decoder in DECODERS:
        for row in records[decoder]:
            if row["prompt_sha256"] != planned_prompts.get(row["question_id"]):
                raise ValueError(
                    "actual Reader prompt differs from preregistered input"
                )
    result = summarize(records["greedy"], records["beam2"], targets)
    result.update(
        generating_commit=source_commit,
        source_snapshot_sha256=snapshot_sha,
        paired_plan_sha256=hashlib.sha256(
            (output / "plan.json").read_bytes()
        ).hexdigest(),
        journal_sha256=digests,
        actual_generator_calls=sum(
            row["status"] == "succeeded"
            for decoder in DECODERS
            for row in records[decoder]
        ),
        review_is_not_independent=True,
    )
    with (output / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, allow_nan=False), flush=True)
    return result


def main():
    from event_memory_trial import read
    from experience_write_trial import model_inputs, original_documents
    from pretrained import LoRAReader

    parser = argparse.ArgumentParser(description=__doc__)
    for item in ("sources", "model", "snapshot", "output"):
        parser.add_argument(item, type=Path)
    for item in ("source-sha", "stage-sha", "ready-sha", "source-commit"):
        parser.add_argument("--" + item, required=True)
    parser.add_argument(
        "--question-mode", choices=("training", "paraphrase"), default="paraphrase"
    )
    parser.add_argument("--maximum", type=int, default=MAX_SCOPES)
    args = parser.parse_args()
    ready = read(args.snapshot / "READY.json", args.ready_sha)
    if (
        ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("uncommitted source-only snapshot")
    documents = original_documents(args.sources, args.source_sha)
    if digest([asdict(d) for d in documents]) != ready["source_documents_digest"]:
        raise ValueError("source snapshot changed")
    _, inventory = model_inputs(args.model, args.stage_sha)
    if inventory["inventory_digest"] != ready["base_identity"]:
        raise ValueError("different reader identity")
    reader = ExperienceReader(
        args.model / "reader", expected_inventory=ready["base_identity"]
    )
    LoRAReader.load_candidate(
        reader,
        args.snapshot / "adapter",
        expected_manifest_sha256=ready["manifest_sha"],
        scope=reader.scope,
        allowed_roots={d.root for d in documents},
        revoked=set(),
    )
    reader.scopes = set(ready["scopes"])
    for parameter in reader.model.parameters():
        parameter.requires_grad_(False)
    if reader.profile != ready["reader_profile"]:
        raise ValueError("reader profile changed")
    paired_probe(
        reader,
        documents,
        args.output,
        snapshot_sha=args.ready_sha,
        writer_source=ready["writer_source"],
        source_commit=args.source_commit,
        question_mode=args.question_mode,
        maximum=args.maximum,
        training=ready["training"],
    )


if __name__ == "__main__":
    main()
