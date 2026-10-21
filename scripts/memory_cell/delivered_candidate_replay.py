"""Independent-process source recheck of the original model's sealed local scores.

No neural model re-execution, original tensor parity, independent human oracle,
independent fresh sources or MemoryCell promotion. Re-executes each original
bounded procedure and recomputes the typed causal closure from source bytes.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from delivered_candidate_reader import SCHEMA, sha_file, validate_raw_rows
from local_causal_reader import ABSTAIN, answer as source_chain
from offline_event_reader_trial import ARMS, inputs, write
from offline_smol_reader import PINS


def read_json(path, max_size):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 1 <= path.stat().st_size <= max_size
    ):
        raise ValueError("bounded regular original record required")

    def duplicate(fields):
        out = {}
        for k, value in fields:
            if k in out:
                raise ValueError("duplicate original journal JSON key")
            out[k] = value
        return out

    def invalid(value):
        raise ValueError("nonfinite original record " + value)

    return json.loads(
        path.read_text(), object_pairs_hook=duplicate, parse_constant=invalid
    )


def audit(archive, execution, expected_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("exact sealed original generating commit required")
    execution = Path(execution)
    plan, sources, worker_bytes = inputs(archive)
    registration = read_json(execution / "preregistered.json", 262144)
    summary = read_json(execution / "summary.json", 262144)
    raw_path = execution / "raw-answers.jsonl"
    if (
        raw_path.is_symlink()
        or not raw_path.is_file()
        or raw_path.stat().st_size > 4 * 1024 * 1024
        or sha_file(raw_path) != summary.get("original_raw_journal_sha256")
    ):
        raise ValueError("original model journal missing or digest changed")
    raw = [json.loads(line) for line in raw_path.read_text().splitlines()]
    source_replay = validate_raw_rows(plan, sources, raw)
    if (
        registration.get("schema") != SCHEMA
        or summary.get("schema") != SCHEMA
        or summary.get("source_commit") != expected_commit
        or registration.get("source_commit") != expected_commit
        or registration.get("no_hindsight_target_or_label_inference") is not True
        or registration.get("global_scope_answer_space_oracle") is not False
        or registration.get("worker_sha256") != hashlib.sha256(worker_bytes).hexdigest()
        or summary.get("original_model_identity") != raw[0]["reader_identity"]
        or any(r["reader_identity"] != summary["original_model_identity"] for r in raw)
        or summary.get("original_weights_sha256") != PINS["model.safetensors"]
        or summary.get("production_accepted") is not False
        or summary.get("only_delivered_values_and_fixed_refusal") is not True
        or summary.get("knowledge_module_training_calls") != 0
        or summary.get("independently_admitted_future_families") != 0
        or summary.get("reference_reader_executed") is not False
        or summary.get("complete_tco_usd") is not None
        or summary.get("actual_original_reader_forward_attempts")
        != sum(r["status"] == "succeeded" for r in raw)
        or summary.get("original_attempts") != 48
    ):
        raise ValueError("original source/model/disposition binding mismatch")
    scores = read_json(execution / "postsealed-scored.json", 4 * 1024 * 1024)
    if sha_file(execution / "postsealed-scored.json") != summary.get(
        "original_scored_journal_sha256"
    ):
        raise ValueError("postsealed score journal digest mismatch")
    if not isinstance(scores, list) or len(scores) != 48:
        raise ValueError("original scored task census incomplete")
    scored = {(row["question_id"], row["arm"]): row for row in scores}
    if len(scored) != 48:
        raise ValueError("duplicate scored task/arm pair")
    with zipfile.ZipFile(archive) as z:
        target_bytes = z.read("observations/labels.json")
    if hashlib.sha256(target_bytes).hexdigest() != plan["labels_sha"]:
        raise ValueError("original postsealed labels changed")
    gold = {r["id"]: r for r in json.loads(target_bytes)}
    worker = execution / "original-event-probe.py"
    if (
        worker.is_symlink()
        or not worker.is_file()
        or sha_file(worker) != hashlib.sha256(worker_bytes).hexdigest()
    ):
        raise ValueError("original authored worker executable changed")
    totals = {arm: Counter() for arm in ARMS}
    tool_replays = 0
    for case in plan["cases"]:
        qid = case["query"]["identity"]
        for arm in ARMS:
            result = scored[(qid, arm)]
            raw_row = next(
                x for x in raw if x["question_id"] == qid and x["arm"] == arm
            )
            if (
                result.get("question_id") != qid
                or result.get("arm") != arm
                or result.get("chosen") != raw_row.get("chosen")
                or result.get("status") != raw_row["status"]
                or result.get("input_tokens") != raw_row.get("input_tokens")
                or result.get("evaluated_hypotheses")
                != raw_row.get("evaluated_hypotheses")
                or result.get("model_seconds") != raw_row["model_seconds"]
            ):
                raise ValueError(
                    "postsealed row not paired to original reader response"
                )
            truth = gold[qid]
            closure = source_chain(case["query"], raw_row["selected"], sources)
            complete = closure["status"] == "answered"
            chain_value = closure["answer"].split(" ", 1)[0] if complete else None
            chosen = raw_row["chosen"]
            correct = raw_row["status"] == "succeeded" and chosen == truth["expected"]
            supported = bool(correct and complete and chain_value == chosen)
            procedure = None
            if case["kind"] == "procedure":
                request = dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=chosen
                    if chosen != ABSTAIN and chosen is not None
                    else "invalid_response",
                )
                if len(json.dumps(request)) > 16384:
                    raise ValueError("original procedure byte bound exceeded")
                attempt = subprocess.run(
                    [sys.executable, "-I", "-S", str(worker)],
                    input=json.dumps(request),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                procedure = dict(
                    exit_code=attempt.returncode,
                    stdout_sha256=hashlib.sha256(attempt.stdout.encode()).hexdigest(),
                    stderr_sha256=hashlib.sha256(attempt.stderr.encode()).hexdigest(),
                )
                supported = supported and attempt.returncode == 0
                tool_replays += 1
            if (
                result["strict_candidate_correct"] is not bool(correct)
                or result["typed_source_chain_complete"] is not complete
                or result["typed_chain_matched_chosen"]
                is not bool(chain_value == chosen)
                or result["supported_task_success"] is not bool(supported)
                or result["verified_original_constrained_program"] != procedure
            ):
                raise ValueError(
                    "independent source/program replay disagrees with scored row"
                )
            c = totals[arm]
            c["planned"] += 1
            c["actual_model_forwards"] += raw_row["status"] == "succeeded"
            c["failed"] += raw_row["status"] == "failed"
            c["strict_candidate_correct"] += correct
            c["typed_source_chain_complete"] += complete
            c["supported_task_success"] += supported
            c["original_worker_calls"] += procedure is not None
            c["original_worker_success"] += (
                procedure is not None and procedure["exit_code"] == 0
            )
            c["evaluated_hypotheses"] += raw_row.get("evaluated_hypotheses", 0)
            c["prompt_tokens"] += raw_row.get("input_tokens", 0)
            c["refusals"] += chosen == ABSTAIN
    for arm in ARMS:
        for name, count in totals[arm].items():
            if summary["by_arm"][arm][name] != count:
                raise ValueError(
                    "original per-arm published metric drift: " + arm + "/" + name
                )
    if tool_replays != 12:
        raise ValueError("missing original bounded program reexecutions")
    return dict(
        schema="hepta.memory.source-delivered-independent-local-replay.v1",
        generating_source=expected_commit,
        original_source_archive_sha256=registration["source_archive_sha256"],
        original_raw_journal_sha256=summary["original_raw_journal_sha256"],
        original_scored_journal_sha256=summary["original_scored_journal_sha256"],
        original_model_attempts=source_replay["original_model_attempts"],
        separately_executed_original_program_checks=tool_replays,
        independent_process_source_and_program_recompute=True,
        new_neural_model_calls=0,
        independent_human_entailment=False,
        candidate_space_original_scope_oracle=False,
        new_independent_source_families=0,
        production_accepted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original_archive", type=Path)
    p.add_argument("private_execution", type=Path)
    p.add_argument("published_receipt", type=Path)
    p.add_argument("--source-commit", required=True)
    args = p.parse_args()
    result = audit(args.original_archive, args.private_execution, args.source_commit)
    if args.published_receipt.exists() or args.published_receipt.is_symlink():
        raise ValueError("do not overwrite existing independent replay receipt")
    write(args.published_receipt, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
