"""Frozen-reader candidate-space capacity diagnosis, not memory learning.

All candidates are mined from the ORIGINAL complete scope before seeing targets;
this is an answer-space oracle and NOT a deployable no-evidence/RAG baseline.
A single unchanged reader, prompt, budget and candidate set span every evidence
arm. Scores come from genuine conditional next-token likelihoods, not heuristics.
Only after all scores are fsynced are the original answer labels opened.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import zipfile

import torch

from offline_event_reader_trial import ARCHIVE_SHA, ARMS, inputs, messages, write
from offline_smol_reader import OriginalSmol, PROFILE, PINS, digest

SCHEMA = "hepta.memory.frozen-reader-candidate-ceiling.v1"
OUTPUT_LIMIT = 64
INPUT_LIMIT = 2048
MAX_CHOICES = 12
CHOICE = re.compile(r"(?:site|mode)_[0-9a-f]{8}\Z")


def candidates(case, originals):
    """Admit all scope values, including distractors, without target access."""
    query = case["query"]
    options = set()
    for source in originals.values():
        if source["scope"] != query["scope"]:
            continue
        if source["observed_at"] > query["observed_at"]:
            raise ValueError("future source in frozen scope")
        row = json.loads(source["content"])
        if (
            row["id"] != source["identity"]
            or row["schema"] != "hepta.controlled-event.v1"
        ):
            raise ValueError("source identity or schema changed")
        value = row["value"]
        if isinstance(value, str) and CHOICE.fullmatch(value):
            options.add(value)
    if not 2 <= len(options) <= MAX_CHOICES:
        raise ValueError("bounded nontrivial answer-space required")
    return tuple(
        sorted(options, key=lambda v: digest((ARCHIVE_SHA, query["identity"], v)))
    )


def candidate_score(reader, logits, cache, text):
    """Score forced continuation without altering original prompt or weights."""
    ids = reader.tokenizer.encode(" " + text)
    if not 1 <= len(ids) <= 32 or any(type(t) is not int for t in ids):
        raise ValueError("bounded forced continuation required")
    parts = []
    working_cache = cache
    for i, token in enumerate(ids):
        if i:
            logits, working_cache = reader.forward([ids[i - 1]], working_cache)
        parts.append(float(torch.log_softmax(logits.float(), -1)[token]))
    return dict(
        token_digest=digest(ids),
        token_count=len(ids),
        log_likelihood=sum(parts),
        mean_log_likelihood=sum(parts) / len(parts),
    )


def analyze(plan, originals, reader, output, source_commit):
    if len(plan["cases"]) != 8 or tuple(plan["arms"]) != ARMS:
        raise ValueError("frozen evaluation cohort changed")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact generating source commit required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    groups = []
    for case in plan["cases"]:
        opts = candidates(case, originals)
        groups.append(
            dict(
                question_id=case["query"]["identity"],
                kind=case["kind"],
                candidates=list(opts),
                option_digest=digest(opts),
                candidate_digest=case["candidate_digest"],
            )
        )
    write(
        output / "preregistered.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            weights_sha256=PINS["model.safetensors"],
            source_archive_sha256=ARCHIVE_SHA,
            reader_profile=PROFILE,
            same_original_prompt=True,
            candidate_pool_source="all_original_scope_events_without_labels",
            candidate_pool_is_oracle=True,
            candidate_visibility="forced_scoring_only",
            ranking_policy="highest_mean_next_token_log_probability",
            tie_breaker="candidate_digest_order",
            input_budget=INPUT_LIMIT,
            output_budget=OUTPUT_LIMIT,
            zero_training=True,
            prior_public_test_exposure=True,
            task_success_not_certified=True,
            independent_human_oracle=False,
            production_accepted=False,
            groups=groups,
            arms=list(ARMS),
        ),
    )
    rows = []
    with (output / "candidate-scores.jsonl").open("x", encoding="utf-8") as journal:
        for case, group in zip(plan["cases"], groups, strict=True):
            for arm in ARMS:
                request = messages(case, arm, originals)
                prompt = reader.tokenizer.render(request)
                prompt_ids = reader.tokenizer.encode(prompt)
                if not 1 <= len(prompt_ids) <= INPUT_LIMIT:
                    raise ValueError("unregistered full prompt budget")
                start = time.perf_counter()
                with torch.inference_mode():
                    logits, cache = reader.forward(prompt_ids)
                    scored = [
                        dict(
                            value=value, **candidate_score(reader, logits, cache, value)
                        )
                        for value in group["candidates"]
                    ]
                ordered = sorted(
                    scored,
                    key=lambda x: (
                        -x["mean_log_likelihood"],
                        group["candidates"].index(x["value"]),
                    ),
                )
                row = dict(
                    question_id=group["question_id"],
                    kind=group["kind"],
                    arm=arm,
                    reader_identity=reader.identity,
                    reader_profile=PROFILE,
                    input_digest=digest(prompt_ids),
                    input_tokens=len(prompt_ids),
                    option_digest=group["option_digest"],
                    candidate_digest=group["candidate_digest"],
                    candidates=scored,
                    chosen=ordered[0]["value"],
                    ranking=list(x["value"] for x in ordered),
                    inference_seconds=time.perf_counter() - start,
                    actually_evaluated_hypotheses=len(scored),
                )
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                rows.append(row)
                print(
                    f"{len(rows)}/{8 * len(ARMS)} {row['question_id']} {arm}",
                    flush=True,
                )
    reader.verify_frozen()
    with zipfile.ZipFile(os.environ["HEPTA_ORIGINAL_EVENT_ARCHIVE"]) as z:
        raw = z.read("observations/labels.json")
    if hashlib.sha256(raw).hexdigest() != plan["labels_sha"]:
        raise ValueError("labels changed after pre-inference journal")
    labels = {x["id"]: x for x in json.loads(raw)}
    for row in rows:
        target = labels[row["question_id"]]["expected"]
        row["oracle_answer_in_pool"] = target in [x["value"] for x in row["candidates"]]
        row["diagnostic_choice_correct"] = row["chosen"] == target
        row["target_rank"] = (
            row["ranking"].index(target) + 1 if row["oracle_answer_in_pool"] else None
        )
    by_arm = {}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        by_arm[arm] = dict(
            planned=len(subset),
            chosen_correct=sum(r["diagnostic_choice_correct"] for r in subset),
            oracle_answer_in_pool=sum(r["oracle_answer_in_pool"] for r in subset),
            scored_candidates=sum(r["actually_evaluated_hypotheses"] for r in subset),
            prompt_tokens=sum(r["input_tokens"] for r in subset),
            inference_seconds=sum(r["inference_seconds"] for r in subset),
        )
    result = dict(
        schema=SCHEMA,
        source_commit=source_commit,
        raw_scores_sha256=hashlib.sha256(
            (output / "candidate-scores.jsonl").read_bytes()
        ).hexdigest(),
        actual_inferences=len(rows),
        actual_model_weights=PINS["model.safetensors"],
        zero_training=True,
        full_runtime_seconds=time.perf_counter() - started,
        by_arm=by_arm,
        is_answer_space_oracle=True,
        same_prompt_and_reader_as_original_six_arm=True,
        candidate_selection_inspected_full_original_sources=True,
        task_execution_evaluated=False,
        generated_citations_evaluated=False,
        production_accepted=False,
        new_source_families=0,
        unsupported_qualification="choice_rank_is_not_usable_memory_or_reader_task_success",
    )
    write(output / "result.json", result)
    return result


def run(archive, reader_root, output, source_commit):
    torch.set_num_threads(2)
    os.environ["HEPTA_ORIGINAL_EVENT_ARCHIVE"] = str(Path(archive).resolve())
    plan, originals, _ = inputs(archive)
    reader = OriginalSmol(reader_root)
    return analyze(plan, originals, reader, output, source_commit)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("reader", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--source-commit", required=True)
    args = p.parse_args()
    print(json.dumps(run(args.archive, args.reader, args.output, args.source_commit)))
