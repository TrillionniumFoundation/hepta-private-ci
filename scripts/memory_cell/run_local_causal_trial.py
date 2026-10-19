"""Reproducible frozen six-arm test of typed causal answer and verified citations.

No answer-space oracle, no model calls, no learning, no tool-based memory claim.
Existing authored development evidence is NOT independent production evidence.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

from local_causal_reader import answer, digest, SCHEMA, ABSTAIN

ARCHIVE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def file_sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular original evidence archive required")
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def run(archive, output, source_sha):
    archive, output = Path(archive), Path(output)
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("exact source commit required")
    if file_sha(archive) != ARCHIVE_SHA:
        raise ValueError("original archived source identity changed")
    with zipfile.ZipFile(archive) as z:
        plan_bytes = z.read("plan/plan.json")
        plan = json.loads(plan_bytes)
        source_bytes = z.read("plan/source-view.json")
        if hashlib.sha256(source_bytes).hexdigest() != plan["source_view_sha"]:
            raise ValueError("original source-view pin changed")
        originals = {d["identity"]: d for d in json.loads(source_bytes)}
        if len(originals) != len(json.loads(source_bytes)):
            raise ValueError("duplicate original sources")
        if (
            plan.get("schema") != "hepta.event-organization.plan.v1"
            or tuple(plan["arms"]) != ARMS
            or len(plan["cases"]) != 8
        ):
            raise ValueError("original test population changed")
        worker_bytes = z.read("source/event_probe.py")
    output.mkdir(parents=True, exist_ok=False)
    starting = time.perf_counter()
    write(
        output / "preregistered.json",
        dict(
            schema="hepta.memory.local-causal-trial.v1",
            generating_commit=source_sha,
            source_sha256={
                name: file_sha(Path(__file__).with_name(name))
                for name in ("local_causal_reader.py", "run_local_causal_trial.py")
            },
            original_zip_sha256=ARCHIVE_SHA,
            original_plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
            original_source_sha256=plan["source_view_sha"],
            input_profile=SCHEMA,
            frozen_question_ids=[c["query"]["identity"] for c in plan["cases"]],
            arms=list(ARMS),
            no_source_scope_candidate_oracle=True,
            no_label_before_answer_journal=True,
            prior_public_test_exposure=True,
            program_support_arm_is_authored_oracle=True,
            original_worker_sha256=hashlib.sha256(worker_bytes).hexdigest(),
            new_model_calls=0,
            training_steps=0,
            reader_is_structured_program_not_llm=True,
            human_semantic_sufficiency_certified=False,
            production_accepted=False,
        ),
    )
    rows = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in plan["cases"]:
            q = case["query"]
            if digest(case["candidate_ids"]) != case["candidate_digest"]:
                raise ValueError("original candidate pool differs")
            for arm in ARMS:
                selected = case["controls"][arm]["selected"]
                started = time.perf_counter()
                outcome = answer(q, selected, originals)
                row = dict(
                    question_id=q["identity"],
                    task_kind=case["kind"],
                    arm=arm,
                    selected=list(selected),
                    candidate_digest=case["candidate_digest"],
                    query_digest=digest(q),
                    source_view_sha=plan["source_view_sha"],
                    status="succeeded",
                    reader_profile=SCHEMA,
                    output=outcome,
                    query_seconds=time.perf_counter() - started,
                )
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                rows.append(row)
    # Labels are accessed only AFTER complete durable answer census.
    with zipfile.ZipFile(archive) as z:
        truth_bytes = z.read("observations/labels.json")
    if hashlib.sha256(truth_bytes).hexdigest() != plan["labels_sha"]:
        raise ValueError("original labels changed")
    labels = {x["id"]: x for x in json.loads(truth_bytes)}
    if len(labels) != 16 or any(r["question_id"] not in labels for r in rows):
        raise ValueError("original 16-case fixed annotations changed")
    worker = output / "original-event-probe.py"
    with worker.open("xb") as stream:
        stream.write(worker_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    checks = 0
    for r in rows:
        label = labels[r["question_id"]]
        response = r["output"]
        selected_chain = {item["original_id"] for item in response["trace"]}
        expected = label["expected"]
        value = (
            response["answer"].split(" ")[0]
            if response["status"] == "answered"
            else None
        )
        r["parsed_value"] = value
        r["strict_task_success"] = value == expected
        r["complete_declared_chain_cited"] = r["strict_task_success"] and set(
            label["support"]
        ).issubset(selected_chain)
        if label["kind"] == "procedure":
            input_request = dict(
                operation="execute",
                recipe=label["procedure"],
                supplied=value or "invalid_response",
            )
            if len(json.dumps(input_request)) > 16384:
                raise ValueError("original program request exceeds bound")
            started = time.perf_counter()
            p = subprocess.run(
                [sys.executable, "-I", "-S", str(worker)],
                input=json.dumps(input_request),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            checks += 1
            r["original_program_verification"] = dict(
                exit_code=p.returncode,
                stdout=p.stdout,
                stderr=p.stderr,
                seconds=time.perf_counter() - started,
            )
            r["strict_task_success"] = p.returncode == 0
    summary = {}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        summary[arm] = dict(
            planned=len(subset),
            answered=sum(r["output"]["status"] == "answered" for r in subset),
            abstained=sum(r["output"]["status"] == "abstained" for r in subset),
            strict_task_success=sum(r["strict_task_success"] for r in subset),
            complete_declared_chain_cited=sum(
                r["complete_declared_chain_cited"] for r in subset
            ),
            measured_source_read_seconds=sum(r["query_seconds"] for r in subset),
        )
    result = dict(
        schema="hepta.memory.local-causal-trial-result.v1",
        generating_commit=source_sha,
        original_source_archive_sha256=ARCHIVE_SHA,
        raw_journal_sha256=file_sha(output / "raw-answers.jsonl"),
        all_planned=len(rows),
        original_program_verifications=checks,
        actual_reader_type="bounded_symbolic_source_local",
        model_calls=0,
        training_steps=0,
        effective_source_family_count=0,
        independent_future_windows=0,
        strict_task_and_citation_scored=True,
        extraction_index_cost="historical_input_receipt_not_remeasured",
        source_archive_bytes=archive.stat().st_size,
        maintained_revoked_restored_costs=None,
        total_lifecycle_cost=None,
        experimental_wall_seconds=time.perf_counter() - starting,
        result_by_arm=summary,
        comparison_to_llm_is_different_reader_architecture=True,
        independent_human_semantic_review=False,
        production_accepted=False,
        original_questions_previously_exposed=True,
    )
    write(output / "scored-answers.json", rows)
    write(output / "report.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.archive, args.output, args.source_commit), indent=2))
