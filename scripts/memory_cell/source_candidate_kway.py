"""Source-only K-way value readout, with an explicitly nonparametric lexicon.

Candidate strings are obtained from the ORIGINAL source corpus, not a model's
parameters. The reader receives the same empty-evidence question for every
candidate. Teacher-forced likelihood cannot be called standalone parametric
recall, generated answer accuracy, semantic correctness or production quality.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re

MAX_SCOPES = 1
MAX_QUESTIONS = 2
MAX_CANDIDATES = 16
ARMS = ("base", "memory")


def roster(examples, *, maximum_scopes=MAX_SCOPES, maximum_questions=MAX_QUESTIONS):
    if (
        type(maximum_scopes) is not int
        or not 1 <= maximum_scopes <= MAX_SCOPES
        or type(maximum_questions) is not int
        or not 1 <= maximum_questions <= MAX_QUESTIONS
        or not 1 <= len(examples) <= 2048
    ):
        raise ValueError("bounded source-only candidate plan required")
    groups, identities = {}, set()
    for item in examples:
        if not isinstance(item, dict) or not isinstance(item.get("query"), dict):
            raise ValueError("complete source question required")
        query, value = item["query"], item.get("target")
        scope, identity = query.get("scope"), query.get("identity")
        if (
            not isinstance(scope, str)
            or not scope
            or not isinstance(identity, str)
            or not identity
            or identity in identities
            or not isinstance(value, str)
            or not 0 < len(value.encode()) <= 256
            or not isinstance(query.get("content"), str)
            or not query["content"]
        ):
            raise ValueError("unique bounded original source question required")
        identities.add(identity)
        groups.setdefault(scope, []).append(item)
    eligible, excluded = [], []
    accepted_scopes = 0
    for scope, entries in sorted(groups.items()):
        candidates = tuple(sorted({entry["target"] for entry in entries}))
        # Never construct a target-conditioned top-K, whose membership could
        # trivially leak the correct candidate. Admit the WHOLE scope or none.
        if not 2 <= len(candidates) <= MAX_CANDIDATES:
            excluded.append(dict(scope=scope, candidate_count=len(candidates)))
            continue
        if accepted_scopes >= maximum_scopes:
            excluded.append(dict(scope=scope, candidate_count=len(candidates)))
            continue
        accepted_scopes += 1
        for entry in sorted(entries, key=lambda e: e["query"]["identity"])[
            :maximum_questions
        ]:
            eligible.append(
                dict(
                    scope=scope,
                    query=entry["query"],
                    target=entry["target"],
                    candidates=candidates,
                )
            )
    return tuple(eligible), tuple(excluded)


def summarize(rows, cases):
    """Score only after raw likelihoods have been durably recorded."""
    from native import digest

    expected = {
        (c["query"]["identity"], arm, digest(value))
        for c in cases
        for arm in ARMS
        for value in c["candidates"]
    }
    keys = [(r["question_id"], r["arm"], r["candidate_digest"]) for r in rows]
    if (
        not cases
        or len(keys) != len(expected)
        or len(set(keys)) != len(keys)
        or set(keys) != expected
    ):
        raise ValueError("missing/duplicate/changed source candidate or arm")
    indexed = {(r["question_id"], r["arm"], r["candidate_digest"]): r for r in rows}
    complete = base_correct = memory_correct = wins = losses = changed = 0
    for case in cases:
        qid = case["query"]["identity"]
        candidates = case["candidates"]
        profiles = set()
        prompt_ids = set()
        reader_questions = set()
        per_arm = {}
        for arm in ARMS:
            subset = [indexed[(qid, arm, digest(c))] for c in candidates]
            for r in subset:
                if r["status"] not in ("succeeded", "failed"):
                    raise ValueError("invalid recorded model call status")
                if r["scope"] != case["scope"] or r["delivered_evidence"] != []:
                    raise ValueError("source content entered model input")
                prompt_ids.add(r["prompt_digest"])
                profiles.add(r["reader_profile"])
                reader_questions.add(r["actual_reader_question_id"])
                if r["status"] == "succeeded":
                    for number in ("mean_nll", "seconds"):
                        x = r[number]
                        if type(x) not in (float, int) or not math.isfinite(x) or x < 0:
                            raise ValueError("invalid actual model observation")
                    if (
                        type(r["input_tokens"]) is not int
                        or type(r["supervised_tokens"]) is not int
                        or r["input_tokens"] <= r["supervised_tokens"]
                        or r["supervised_tokens"] <= 0
                    ):
                        raise ValueError("invalid model token accounting")
            if all(r["status"] == "succeeded" for r in subset):
                per_arm[arm] = min(
                    candidates,
                    key=lambda c: (
                        indexed[(qid, arm, digest(c))]["mean_nll"],
                        digest(c),
                    ),
                )
        if len(prompt_ids) != 1 or len(profiles) != 1 or len(reader_questions) != 1:
            raise ValueError("Qwen prompt/reader drift across candidate ranking")
        if len(per_arm) != 2:
            continue
        complete += 1
        base = per_arm["base"] == case["target"]
        memory = per_arm["memory"] == case["target"]
        base_correct += base
        memory_correct += memory
        wins += int(memory and not base)
        losses += int(base and not memory)
        changed += int(per_arm["base"] != per_arm["memory"])
    missing = len(cases) - complete
    report = dict(
        schema="hepta.source-lexicon.kway.v1",
        planned_questions=len(cases),
        planned_model_calls=len(expected),
        completed_model_calls=sum(r["status"] == "succeeded" for r in rows),
        complete_base_adapter_questions=complete,
        missing_question_pairs=missing,
        base_closed_set_correct=base_correct,
        memory_closed_set_correct=memory_correct,
        memory_wins=wins,
        memory_losses=losses,
        changed_top_candidates=changed,
        all_planned_effect_bounds=[
            (wins - losses - missing) / len(cases),
            (wins - losses + missing) / len(cases),
        ],
        lexicon_from_source_not_parameters=True,
        teacher_forced_not_unconstrained_generation=True,
        source_only_training_questions_not_independent_holdout=True,
        new_independent_source_families=0,
        downstream_task_success=None,
        independent_semantic_precision=None,
        significance_established=False,
        production_accepted=False,
    )
    from source_binding_specificity import question_binding

    report["question_value_binding"] = question_binding(rows, cases)
    return report


def probe(
    reader,
    documents,
    out,
    *,
    ready_sha,
    writer_source,
    source_commit,
    scorer=None,
    maximum_questions=MAX_QUESTIONS,
):
    from experience_memory import render, source_examples
    from native import digest
    from source_paraphrase_probe import paraphrase_writer_question
    from source_recall_likelihood import _valid_score, conditional_nll

    if (
        out.exists()
        or not re.fullmatch(r"[0-9a-f]{64}", ready_sha)
        or not re.fullmatch(r"[0-9a-f]{40}", writer_source)
        or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
        or {d.root for d in documents} != reader.roots
        or {d.scope for d in documents} != reader.scopes
    ):
        raise ValueError("source readout cannot open unbound source snapshot")
    examples, dispositions = source_examples(
        documents, revision=2, allowed_roots=reader.roots, revoked=set()
    )
    cases, excluded = roster(examples, maximum_questions=maximum_questions)
    if not cases:
        raise ValueError("no complete eligible source-value lexicon")
    # Source-only questions are preregistered without seeing any generated
    # answer. The target is held internally for AFTER-journal scoring only.
    plan = []
    prepared = []
    for case in cases:
        q = paraphrase_writer_question(dict(query=case["query"]))
        ids = render(reader.tokenizer, q, [], [])
        plan.append(
            dict(
                source_question_id=case["query"]["identity"],
                actual_reader_question_id=q.identity,
                source_scope=case["scope"],
                prompt_digest=digest(ids),
                lexicon_digests=[digest(v) for v in case["candidates"]],
            )
        )
        prepared.append((case, q, ids))
    out.mkdir()
    plan_path = out / "plan.json"
    with plan_path.open("x", encoding="utf-8") as stream:
        json.dump(
            dict(
                schema="hepta.source-lexicon.plan.v1",
                ready_sha256=ready_sha,
                generating_source=source_commit,
                writer_source=writer_source,
                comparisons=plan,
                skipped_source_scopes=excluded,
                unresolved_source_relations=len(dispositions),
                no_downstream_task_labels_consumed=True,
                lexicon_is_external_source_content=True,
                production_accepted=False,
            ),
            stream,
            allow_nan=False,
            indent=2,
        )
        stream.write("\n")
    rows = []
    raw_path = out / "raw-likelihoods.jsonl"
    with raw_path.open("x", encoding="utf-8") as stream:
        for case, q, ids in prepared:
            for arm in ARMS:
                for value in case["candidates"]:
                    row = dict(
                        question_id=case["query"]["identity"],
                        actual_reader_question_id=q.identity,
                        scope=case["scope"],
                        arm=arm,
                        candidate_digest=digest(value),
                        prompt_digest=digest(ids),
                        reader_profile=reader.profile,
                        delivered_evidence=[],
                    )
                    try:
                        observed = (scorer or conditional_nll)(reader, ids, value, arm)
                        _valid_score(observed, len(ids))
                        row.update(status="succeeded", **observed)
                    except Exception as error:
                        row.update(
                            status="failed",
                            error_type=type(error).__name__,
                            error=str(error)[:256],
                        )
                    stream.write(
                        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                    rows.append(row)
    reader.verify_frozen()
    report = summarize(rows, cases)
    report.update(
        ready_sha256=ready_sha,
        source_commit=source_commit,
        plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        source_lexicon_value_count=sum(len(c["candidates"]) for c in cases),
        candidate_score_attempts_logged=len(rows),
        source_lexicon_storage_bytes=sum(
            len(value.encode("utf-8")) for value in cases[0]["candidates"]
        ),
        candidate_input_tokens=sum(
            row["input_tokens"] for row in rows if row["status"] == "succeeded"
        ),
        candidate_supervised_tokens=sum(
            row["supervised_tokens"] for row in rows if row["status"] == "succeeded"
        ),
        measured_candidate_seconds=sum(
            row["seconds"] for row in rows if row["status"] == "succeeded"
        ),
    )
    with (out / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, allow_nan=False, indent=2)
        stream.write("\n")
    if report["completed_model_calls"] != report["planned_model_calls"]:
        raise ValueError("incomplete original K-way reader calls; failures retained")
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
    parser.add_argument("--maximum-questions", type=int, default=MAX_QUESTIONS)
    args = parser.parse_args()
    ready = read(args.snapshot / "READY.json", args.ready_sha)
    if (
        ready["schema"] != "hepta.source-knowledge.snapshot.v1"
        or ready["task_payload_consumed"] is not False
        or ready["production_accepted"] is not False
    ):
        raise ValueError("uncommitted or post-task memory snapshot")
    documents = original_documents(args.sources, args.source_sha)
    if digest([asdict(d) for d in documents]) != ready["source_documents_digest"]:
        raise ValueError("source bytes changed after writing")
    _, inventory = model_inputs(args.model, args.stage_sha)
    if inventory["inventory_digest"] != ready["base_identity"]:
        raise ValueError("different shared pretrained reader")
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
        raise ValueError("source writer/reader profile differs")
    return probe(
        reader,
        documents,
        args.output,
        ready_sha=args.ready_sha,
        writer_source=ready["writer_source"],
        source_commit=args.source_commit,
        maximum_questions=args.maximum_questions,
    )


if __name__ == "__main__":
    main()
