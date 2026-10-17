"""Real original Smol135 source-delivered candidate study (no answer-space oracle).

Source-controlled, old authored development population. Every scored option
comes exclusively from this arm's delivered original event bytes or from the
public fixed refusal string. Never call this task success, neural generation,
a trained MemoryCell, a human evidence review, or an independent future cohort.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

from local_causal_reader import (
    ABSTAIN,
    answer as source_chain,
    interpret_query,
    parse_event,
    timestamp,
)
from offline_event_reader_trial import ARCHIVE_SHA, ARMS, inputs, messages, write
from offline_smol_reader import OriginalSmol, PROFILE, PINS, digest
from reader_candidate_capacity import candidate_score, CHOICE

SCHEMA = "hepta.memory.source-delivered-original-smol-candidates.v1"
MAX_OPTIONS = 12
MAX_INPUT_TOKENS = 2048
MAX_CHOICE_TOKENS = 32


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def frozen_selection(case, arm, sources):
    """Bound candidate values only to the evidence actually delivered to arm.

    Does not scan or hash withheld source content, read gold, or use an
    answer-conditioned candidate list. A complete public causal chain is
    evaluated separately, after the original model scores are journaled.
    """
    if arm not in ARMS:
        raise ValueError("unknown frozen arm")
    query = case["query"]
    selected = case["controls"][arm]["selected"]
    if (
        not isinstance(selected, list)
        or len(selected) > 8
        or len(selected) != len(set(selected))
        or not isinstance(query["identity"], str)
    ):
        raise ValueError("invalid or duplicate delivered original IDs")
    public = interpret_query(query["content"])
    revision = public[1] if public is not None else None
    cutoff = timestamp(query["observed_at"])
    values = set()
    source_sha = []
    for source_id in selected:
        if source_id not in sources:
            raise ValueError("delivered source not in original index")
        source = sources[source_id]
        event = parse_event(
            source, query_scope=query["scope"], query_time=cutoff, revoked=()
        )
        source_sha.append(
            dict(
                id=source_id,
                sha256=hashlib.sha256(source["content"].encode()).hexdigest(),
            )
        )
        if revision is not None and event["revision"] <= revision:
            value = event["value"]
            if CHOICE.fullmatch(value):
                values.add(value)
    if len(values) > MAX_OPTIONS:
        raise ValueError("oversized evidence-local answer-space")
    choices = sorted(
        values, key=lambda value: digest((ARCHIVE_SHA, query["identity"], arm, value))
    )
    # An abstention option is always provided; the no-evidence control cannot
    # choose an answer by inventing a global-scope candidate vocabulary.
    return dict(
        selected=list(selected),
        original_source_hashes=source_sha,
        evidence_only_candidates=choices,
        forced_choices=[*choices, ABSTAIN],
        selection_digest=digest(selected),
        no_global_answer_space_oracle=True,
    )


def strict_rank(scores, choices):
    if len(scores) != len(choices) or not choices or len(set(choices)) != len(choices):
        raise ValueError("incomplete or duplicate forced scoring")
    seen = set()
    for score in scores:
        if score["value"] in seen or score["value"] not in choices:
            raise ValueError("unregistered choice returned by model")
        seen.add(score["value"])
        x = score["mean_log_likelihood"]
        if type(x) not in (float, int) or not math.isfinite(x) or x > 0:
            raise ValueError("invalid original conditional log likelihood")
        if not 1 <= score["token_count"] <= MAX_CHOICE_TOKENS:
            raise ValueError("invalid forced-choice token count")
    return sorted(
        choices,
        key=lambda v: (
            -next(s["mean_log_likelihood"] for s in scores if s["value"] == v),
            choices.index(v),
        ),
    )


def validate_raw_rows(plan, sources, raw):
    """Second-process provenance/option ranking check; no neural re-execution."""
    if (
        len(plan["cases"]) != 8
        or tuple(plan["arms"]) != ARMS
        or len(raw) != 8 * len(ARMS)
    ):
        raise ValueError("original source-delivered task matrix incomplete")
    observed = set()
    for case in plan["cases"]:
        for arm in ARMS:
            qid = case["query"]["identity"]
            matching = [
                r for r in raw if r.get("question_id") == qid and r.get("arm") == arm
            ]
            if len(matching) != 1 or (qid, arm) in observed:
                raise ValueError("missing/duplicate actual reader attempt")
            observed.add((qid, arm))
            row = matching[0]
            control = frozen_selection(case, arm, sources)
            for name in (
                "selected",
                "original_source_hashes",
                "evidence_only_candidates",
                "forced_choices",
                "selection_digest",
            ):
                if row.get(name) != control[name]:
                    raise ValueError(
                        "actual delivered evidence/answer-space tampered: " + name
                    )
            if row.get("status") not in ("succeeded", "failed"):
                raise ValueError("unknown reader attempt status")
            if row.get("reader_profile") != PROFILE:
                raise ValueError("changed original model profile")
            if row["status"] == "succeeded":
                chosen = strict_rank(row["scores"], control["forced_choices"])[0]
                if row.get("chosen") != chosen:
                    raise ValueError("forced score/ranking tampering")
                if (
                    type(row.get("input_tokens")) is not int
                    or not 1 <= row["input_tokens"] <= MAX_INPUT_TOKENS
                    or len(row["scores"]) != len(control["forced_choices"])
                ):
                    raise ValueError("unbounded or missing model scoring")
            else:
                if row.get("chosen") is not None or row.get("scores"):
                    raise ValueError("failed attempt carried successful model scores")
            if any(
                field in row
                for field in (
                    "expected",
                    "target",
                    "gold",
                    "label_answer",
                    "complete_source_chain",
                    "program_success",
                    "strict_success",
                )
            ):
                raise ValueError(
                    "postscore annotation leaked into original answer journal"
                )
    if len(observed) != 48:
        raise ValueError("source-local reader census incomplete")
    return {
        "original_model_attempts": 48,
        "paired_questions": 8,
        "source_only_rank_replayed": True,
        "new_model_calls": 0,
        "independent_source_families": 0,
        "production_accepted": False,
    }


def run(archive, reader_root, output, source_commit):
    import torch

    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact generating source commit required")
    torch.set_num_threads(2)
    started = time.perf_counter()
    plan, sources, worker_bytes = inputs(archive)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "preregistered.json",
        dict(
            schema=SCHEMA,
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_commit=source_commit,
            source_archive_sha256=ARCHIVE_SHA,
            original_model_artifact_id=11586991191,
            model_files=PINS,
            model_numeric_profile=PROFILE,
            method="conditional mean token log-likelihood of delivered candidates and fixed refusal",
            candidate_source="each_arm_delivered_original_event_values_only",
            global_scope_answer_space_oracle=False,
            no_hindsight_target_or_label_inference=True,
            absent_and_lesioned_evidence_may_force_abstention=True,
            original_48_matched_evidence_conditions=list(ARMS),
            source_question_set_already_public=True,
            human_sufficient_witnesses_certified=False,
            real_project_program_experiments=False,
            training_steps=0,
            independent_future_roots=0,
            production_accepted=False,
            code_sha256={
                path: sha_file(Path(__file__).with_name(path))
                for path in (
                    "delivered_candidate_reader.py",
                    "reader_candidate_capacity.py",
                    "local_causal_reader.py",
                    "offline_event_reader_trial.py",
                    "offline_smol_reader.py",
                )
            },
            worker_sha256=hashlib.sha256(worker_bytes).hexdigest(),
        ),
    )
    model = OriginalSmol(reader_root)
    started_model = time.perf_counter()
    raw = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in plan["cases"]:
            for arm in ARMS:
                control = frozen_selection(case, arm, sources)
                row = dict(
                    question_id=case["query"]["identity"],
                    kind=case["kind"],
                    arm=arm,
                    reader_identity=model.identity,
                    reader_profile=PROFILE,
                    **{
                        k: control[k]
                        for k in (
                            "selected",
                            "original_source_hashes",
                            "evidence_only_candidates",
                            "forced_choices",
                            "selection_digest",
                        )
                    },
                )
                step = time.perf_counter()
                try:
                    request = messages(case, arm, sources)
                    prompt = model.tokenizer.render(request)
                    ids = model.tokenizer.encode(prompt)
                    if not 1 <= len(ids) <= MAX_INPUT_TOKENS:
                        raise ValueError(
                            "original prompt budget exceeded, no truncation"
                        )
                    with torch.inference_mode():
                        logits, cache = model.forward(ids)
                        scores = [
                            {
                                "value": value,
                                **candidate_score(model, logits, cache, value),
                            }
                            for value in control["forced_choices"]
                        ]
                    chosen = strict_rank(scores, control["forced_choices"])[0]
                    row.update(
                        status="succeeded",
                        input_digest=digest(ids),
                        input_tokens=len(ids),
                        evaluated_hypotheses=len(scores),
                        scores=scores,
                        chosen=chosen,
                    )
                except Exception as error:
                    row.update(
                        status="failed",
                        chosen=None,
                        scores=[],
                        error_type=type(error).__name__,
                        error=str(error)[:512],
                    )
                row["model_seconds"] = time.perf_counter() - step
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                raw.append(row)
                print(
                    json.dumps(
                        {
                            "attempt": len(raw),
                            "planned": 48,
                            "arm": arm,
                            "status": row["status"],
                        }
                    ),
                    flush=True,
                )
    model.verify_frozen()
    original_inference_seconds = time.perf_counter() - started_model
    validated = validate_raw_rows(plan, sources, raw)
    # Open the original target only AFTER the full raw-answer journal is fsynced.
    with zipfile.ZipFile(archive) as z:
        label_bytes = z.read("observations/labels.json")
    if hashlib.sha256(label_bytes).hexdigest() != plan["labels_sha"]:
        raise ValueError("answer annotations do not match the sealed source plan")
    labels = {r["id"]: r for r in json.loads(label_bytes)}
    worker = output / "original-event-probe.py"
    with worker.open("xb") as f:
        f.write(worker_bytes)
        f.flush()
        os.fsync(f.fileno())
    by_arm = {}
    private = []
    for case in plan["cases"]:
        qid = case["query"]["identity"]
        truth = labels[qid]
        for arm in ARMS:
            row = next(r for r in raw if r["question_id"] == qid and r["arm"] == arm)
            closure = source_chain(case["query"], row["selected"], sources)
            chain_value = (
                closure["answer"].split(" ", 1)[0]
                if closure["status"] == "answered"
                else None
            )
            choice = row["chosen"]
            source_complete = closure["status"] == "answered"
            score_correct = row["status"] == "succeeded" and choice == truth["expected"]
            # This is a typed source-closure check, NOT a human citation judgment,
            # generated explanation, or learned model contribution.
            supported = bool(
                score_correct and source_complete and chain_value == choice
            )
            procedure = None
            if case["kind"] == "procedure":
                request = {
                    "operation": "execute",
                    "recipe": truth["procedure"],
                    "supplied": choice
                    if choice != ABSTAIN and choice is not None
                    else "invalid_response",
                }
                if len(json.dumps(request)) > 16384:
                    raise ValueError("registered original procedure request too large")
                p = subprocess.run(
                    [sys.executable, "-I", "-S", str(worker)],
                    input=json.dumps(request),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                procedure = dict(
                    exit_code=p.returncode,
                    stdout_sha256=hashlib.sha256(p.stdout.encode()).hexdigest(),
                    stderr_sha256=hashlib.sha256(p.stderr.encode()).hexdigest(),
                )
                supported = supported and p.returncode == 0
            private.append(
                dict(
                    question_id=qid,
                    arm=arm,
                    chosen=choice,
                    strict_candidate_correct=bool(score_correct),
                    typed_source_chain_complete=source_complete,
                    typed_chain_matched_chosen=bool(chain_value == choice),
                    supported_task_success=bool(supported),
                    verified_original_constrained_program=procedure,
                    **{
                        k: v
                        for k, v in row.items()
                        if k
                        in (
                            "status",
                            "model_seconds",
                            "input_tokens",
                            "evaluated_hypotheses",
                        )
                    },
                )
            )
    write(output / "postsealed-scored.json", private)
    for arm in ARMS:
        rows = [r for r in private if r["arm"] == arm]
        original_rows = [r for r in raw if r["arm"] == arm]
        by_arm[arm] = dict(
            planned=8,
            actual_model_forwards=sum(r["status"] == "succeeded" for r in rows),
            failed=sum(r["status"] == "failed" for r in rows),
            strict_candidate_correct=sum(r["strict_candidate_correct"] for r in rows),
            typed_source_chain_complete=sum(
                r["typed_source_chain_complete"] for r in rows
            ),
            supported_task_success=sum(r["supported_task_success"] for r in rows),
            original_worker_calls=sum(
                r["verified_original_constrained_program"] is not None for r in rows
            ),
            original_worker_success=sum(
                r["verified_original_constrained_program"] is not None
                and r["verified_original_constrained_program"]["exit_code"] == 0
                for r in rows
            ),
            evaluated_hypotheses=sum(
                r.get("evaluated_hypotheses", 0) for r in original_rows
            ),
            prompt_tokens=sum(r.get("input_tokens", 0) for r in original_rows),
            model_seconds=sum(r["model_seconds"] for r in original_rows),
            refusals=sum(r["chosen"] == ABSTAIN for r in original_rows),
        )
    result = dict(
        schema=SCHEMA,
        source_commit=source_commit,
        original_attempts=validated["original_model_attempts"],
        actual_original_reader_forward_attempts=sum(
            row["status"] == "succeeded" for row in raw
        ),
        tested_source_archive_sha256=ARCHIVE_SHA,
        original_weights_sha256=PINS["model.safetensors"],
        original_model_identity=model.identity,
        original_raw_journal_sha256=sha_file(output / "raw-answers.jsonl"),
        original_scored_journal_sha256=sha_file(output / "postsealed-scored.json"),
        reader_inference_seconds=original_inference_seconds,
        total_wall_seconds=time.perf_counter() - started,
        by_arm=by_arm,
        original_source_archive_bytes=Path(archive).stat().st_size,
        model_retained_bytes=sum(
            (Path(reader_root) / file).stat().st_size for file in PINS
        ),
        unmeasured_lifecycle_costs=[
            "paid CPU/GPU",
            "source indexing",
            "source retention",
            "maintenance",
            "revocation",
            "production recovery",
        ],
        complete_tco_usd=None,
        full_gold_candidate_pool_used=False,
        only_delivered_values_and_fixed_refusal=True,
        typed_source_chain_is_model_generated_citation=False,
        independent_human_sufficient_context_certified=False,
        independently_admitted_future_families=0,
        knowledge_module_training_calls=0,
        reference_reader_executed=False,
        model_choice_is_not_free_generation=True,
        real_program_repair_succeeded=None,
        production_accepted=False,
    )
    write(output / "summary.json", result)
    if any(row["status"] != "succeeded" for row in raw):
        raise ValueError(
            "original failed reader attempts retained; cannot promote census"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("archive", "model", "output"):
        parser.add_argument(arg, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.archive, args.model, args.output, args.source_commit)))


if __name__ == "__main__":
    main()
