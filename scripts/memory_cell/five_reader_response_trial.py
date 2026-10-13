"""Fixed historical source-family Reader learning diagnostic on official HF.

This is DEVELOPMENT on an already exposed public benchmark, NOT the formal
five-experiment confirmation. No human review is manufactured; source labels
are weak supervision, not semantic sufficiency. No threshold/hyperparameter
search or checkpoint selection uses held-out outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import re
from pathlib import Path
import time

import torch
from transformers import AutoTokenizer

import five_causal_experiments as c
from five_causal_native import generate_exact, public_text, count_forwards
from five_native_historical_smoke import (
    ARCHIVE_SHA256, LOCOMO_SHA256, READER_INVENTORY, prepare_materials, snapshot,
)
from five_reader_response_learning import (
    REFUSAL, PROFILE, TRAINING, validate_examples, permuted_positive_targets,
    compile_supervision, fit_response_adapter,
)
from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
from native import load

ARMS = ("frozen_reader", "aligned_lora", "shuffled_positive_lora", "always_refuse")
CONDITIONS = ("no_evidence", "lexical_retrieval", "oracle_plus_distractors", "support_removed")
PLAN = {"schema": "hepta.five-reader.response-learning-diagnostic.v1", "profile": PROFILE,
        "archive_sha256": ARCHIVE_SHA256, "benchmark_sha256": LOCOMO_SHA256,
        "partition": "existing_native_source_family_partition", "train_per_family": 4,
        "test_per_family": 2, "training": TRAINING, "maximum_sources_for_training": 3,
        "arms": ARMS, "conditions": CONDITIONS, "maximum_input_tokens": 2048,
        "maximum_output_tokens": 64, "per_call_seconds": 120,
        "data_status": "historical_public_previously_exposed_not_untouched_confirmation",
        "selection_by": "question_identity_digest_before_target_eligibility_no_replacements",
        "no_hyperparameter_search": True, "production_accepted": False}
CITATION = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")


def choose_questions(benchmark):
    """Uses questions and source-family metadata, never target values."""
    groups = defaultdict(list)
    for q in benchmark.questions:
        groups[(benchmark.partition(q), benchmark.families[q.family])].append(q)
    result = {}
    for partition, count in (("train", PLAN["train_per_family"]), ("test", PLAN["test_per_family"])):
        result[partition] = [q for (part, family), rows in sorted(groups.items()) if part == partition
                             for q in sorted(rows, key=lambda q: c.digest(q.identity))[:count]]
    train_f = {benchmark.families[q.family] for q in result["train"]}
    test_f = {benchmark.families[q.family] for q in result["test"]}
    c.require(train_f and test_f and not train_f & test_f, "source-family split unavailable")
    train_roots = {d.root for q in result["train"] for d in benchmark.history(q)}
    test_roots = {d.root for q in result["test"] for d in benchmark.history(q)}
    c.require(not train_roots & test_roots, "source roots cross train/evaluation")
    return result


def public_request(query, docs):
    return {"question": query.content, "options": [], "evidence": [
        {"id": "E"+c.digest(d.identity)[:12], "modality": "text", "text": d.content,
         "asset_sha256": None, "position": i} for i, d in enumerate(docs)]}


def cases_for(benchmark, query):
    target = benchmark.targets[query.identity]
    history = list(benchmark.history(query))
    known = {d.identity: d for d in history}
    support_ids = tuple(dict.fromkeys(target.evidence))
    supported = [known[i] for i in support_ids if i in known]
    tokens = set(query.content.casefold().split())
    ranked = sorted(history, key=lambda d: (-len(tokens.intersection(d.content.casefold().split())), d.identity))
    distractors = [d for d in ranked if d.identity not in support_ids][:2]
    # Explicitly bound the diagnostic menu. If labels name more than three
    # sources the oracle arm is unavailable, rather than silently truncated.
    usable = bool(support_ids) and not target.unresolved_evidence and len(supported) == len(support_ids) <= 3
    joined = public_request(query, supported + distractors) if usable else None
    support_labels = {"E"+c.digest(d.identity)[:12] for d in supported}
    removed = None if joined is None else joined | {"evidence": [e for e in joined["evidence"] if e["id"] not in support_labels]}
    # Preserve retained IDs, source text, order and original positions exactly.
    return {"no_evidence": public_request(query, []), "lexical_retrieval": public_request(query, ranked[:3]),
            "oracle_plus_distractors": joined, "support_removed": removed}, supported, usable


def training_examples(benchmark, chosen, tokenizer, position_cap):
    examples, census = [], []
    for q in chosen:
        target = benchmark.targets[q.identity]
        _, supported, usable = cases_for(benchmark, q)
        reason = None
        if not usable or target.answer is None or target.unanswerable:
            reason = "unavailable_or_unresolved_positive_annotation"
        else:
            request = public_request(q, supported)
            response = str(target.answer).strip() + " " + " ".join("["+e["id"]+"]" for e in request["evidence"])
            rows = [{"id": c.digest([q.identity, kind]), "question_id": c.digest(q.identity),
                     "family": benchmark.families[q.family], "split": "train", "request": req,
                     "response": text, "kind": kind, "source_sha256": LOCOMO_SHA256}
                    for kind, req, text in (("annotated_answer", request, response),
                                          ("empty_refusal", public_request(q, []), REFUSAL))]
            try:
                for row in rows:
                    compile_supervision(tokenizer, row, input_cap=TRAINING["maximum_input_tokens"],
                                        response_cap=TRAINING["maximum_response_tokens"], position_cap=position_cap)
            except c.Invalid as error:
                reason = str(error)
            if reason is None:
                examples.extend(rows)
        census.append({"question_id": q.identity, "family": benchmark.families[q.family],
                       "admitted": reason is None, "reason": reason, "replacement_selected": False})
    validate_examples(examples)
    c.require(len({r["family"] for r in examples}) >= 2, "training requires multiple source families")
    return examples, census


def score_rows(raw, benchmark):
    """Diagnostic exact body/citation syntax ONLY, never semantic grading."""
    result = []
    for row in raw:
        target = benchmark.targets[row["question_id"]]
        answer = row.get("answer") if row["status"] == "succeeded" else None
        labels = CITATION.findall(answer) if answer is not None else []
        # Preserve case, word order, numbers and negations. Strip ONLY explicit
        # source-label syntax for this separate diagnostic, not the raw answer.
        body = " ".join(CITATION.sub("", answer).split()) if answer is not None else None
        expected = " ".join(str(target.answer).split()) if target.answer is not None else None
        result.append({"trial_id": row["trial_id"], "question_id": row["question_id"],
            "family": row["family"], "arm": row["arm"], "condition": row["condition"], "status": row["status"],
            "exact_refusal": bool(answer is not None and answer.strip() == REFUSAL),
            "benchmark_exact_body": None if expected is None else bool(body is not None and body == expected),
            "citation_syntax_valid": bool(labels) and set(labels) <= set(row.get("evidence_ids", [])),
            "grounded_and_cited_semantics": None, "independent_adjudication": False})
    return result


def summarize(scored):
    out = {}
    for arm in ARMS:
        out[arm] = {}
        for condition in CONDITIONS:
            rows = [r for r in scored if (r["arm"], r["condition"]) == (arm, condition)]
            out[arm][condition] = {"planned": len(rows),
                "succeeded": sum(r["status"] == "succeeded" for r in rows),
                "status_census": dict(Counter(r["status"] for r in rows)),
                "exact_refusals": sum(r["exact_refusal"] for r in rows),
                "exact_bodies": sum(r["benchmark_exact_body"] is True for r in rows),
                "target_available": sum(r["benchmark_exact_body"] is not None for r in rows),
                "syntactically_valid_citations": sum(r["citation_syntax_valid"] for r in rows)}
    return out


def run(archive, work, output):
    output.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "plan.json", PLAN)
    c.write_new(output / "source.json", {"files": {name: c.file_sha(Path(__file__).with_name(name)) for name in
        ("five_reader_response_trial.py", "five_reader_response_learning.py", "five_causal_native.py",
         "five_native_historical_smoke.py", "five_archived_torch_reference.py")},
        "torch": torch.__version__, "scope": "historical_development_not_independent_confirmation"})
    with measured() as staging_cost:
        original, clean, staging = prepare_materials(archive, work / "staged")
    c.write_new(output / "staging.json", staging | {"cost": staging_cost})
    matches = [p for p in original.rglob("*.json") if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact benchmark file unavailable")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256, allow_unresolved_evidence=True)
    chosen = choose_questions(benchmark)
    c.write_new(output / "question-selection.json", {p: [{"id": q.identity, "family": benchmark.families[q.family]}
                 for q in rows] for p, rows in chosen.items()})
    snap = snapshot(clean / "reader", "causal_lm", READER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(clean / "reader", local_files_only=True, trust_remote_code=False)
    # Token-only preparation does not load or discard an unaccounted model.
    config = c.load(clean / "reader" / "config.json")
    examples, census = training_examples(benchmark, chosen["train"], tokenizer, config["max_position_embeddings"])
    forbidden = {benchmark.families[q.family] for q in chosen["test"]}
    validate_examples(examples, forbidden)
    permuted = permuted_positive_targets(examples)
    c.write_new(output / "training-census.json", {"rows": census, "examples": len(examples),
        "aligned_sha256": c.digest(examples), "shuffled_sha256": c.digest(permuted),
        "positive_targets_changed": sum(a["response"] != b["response"] for a, b in zip(examples, permuted)),
        "supervision_is_independent_semantic_review": False})
    requests, unavailable = [], []
    for q in chosen["test"]:
        conditions, _, _ = cases_for(benchmark, q)
        for condition in CONDITIONS:
            requests.append({"question_id": q.identity, "family": benchmark.families[q.family],
                             "condition": condition, "request": conditions[condition]})
            if conditions[condition] is None:
                unavailable.append([q.identity, condition])
    c.write_new(output / "public-evaluation-inputs.json", requests)
    raw, training, loads, errors = [], {}, {}, []
    initial_adapter = None
    previous = "0" * 64
    with (output / "events.jsonl").open("xb") as journal:
        for arm in ARMS:
            backend, arm_error = None, None
            if arm != "always_refuse":
                previous = c.journal_append(journal, {"event": "arm_started", "arm": arm}, previous)
                try:
                    with measured() as load_cost:
                        backend = LocalTextGenerator(clean / "reader", snap, PLAN["maximum_input_tokens"])
                    loads[arm] = load_cost
                    if arm != "frozen_reader":
                        rows = examples if arm == "aligned_lora" else permuted
                        training[arm] = fit_response_adapter(backend, rows, output / arm, forbidden_families=forbidden)
                        digest = training[arm]["initial_adapter_sha256"]
                        c.require(initial_adapter is None or initial_adapter == digest, "control adapter initialization differs")
                        initial_adapter = digest
                except Exception as error:
                    arm_error = type(error).__name__ + ": " + str(error)[:1024]
                    errors.append({"arm": arm, "phase": "load_or_train", "error": arm_error})
                    previous = c.journal_append(journal, {"event": "arm_failed", "arm": arm, "error": arm_error}, previous)
            for case in sorted(requests, key=lambda r: c.digest([r["question_id"], r["condition"]])):
                trial = c.digest([arm, case["question_id"], case["condition"]])
                record = {k: case[k] for k in ("question_id", "family", "condition")}
                record.update(arm=arm, trial_id=trial, status="not_executed", answer=None,
                              evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None:
                    record["status"] = "unavailable_oracle_annotation"
                elif arm_error is not None:
                    record.update(status="blocked_model_or_training", error=arm_error)
                elif arm == "always_refuse":
                    record.update(status="succeeded", answer=REFUSAL, actual_decoder_forwards=0,
                                  execution_kind="nonlearned_control")
                else:
                    previous = c.journal_append(journal, {"event": "reader_started", "trial_id": trial,
                        "public_request_sha256": c.digest(case["request"])}, previous)
                    owner = backend.loaded.get_base_model() if hasattr(backend.loaded, "get_base_model") else backend.loaded
                    with measured() as cost, count_forwards(owner) as forwards:
                        try:
                            answer, details = generate_exact(backend, public_text(case["request"]),
                                                            PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"])
                            record.update(status="succeeded", answer=answer, **details)
                        except Exception as error:
                            record.update(status="failed", error=type(error).__name__+": "+str(error)[:1024])
                    record.update(cost=cost, actual_decoder_forwards=forwards["model_calls"], execution_kind="official_HF")
                    if cost["wall_ns"] > PLAN["per_call_seconds"]*1e9:
                        record["status"] = "timeout_with_observed_output"
                    if record["status"] != "succeeded":
                        errors.append({"trial_id": trial, "phase": "generation", "status": record["status"]})
                previous = c.journal_append(journal, {"event": "trial_recorded", **record}, previous)
                raw.append(record)
            if backend is not None:
                backend.close()
                del backend
                gc.collect()
    c.require(len(raw) == len(ARMS)*len(requests), "incomplete planned denominator")
    c.write_new(output / "raw-answers.json", raw)
    seal = c.file_sha(output / "raw-answers.json")
    c.write_new(output / "raw-seal.json", {"sha256": seal, "event_tail_sha256": previous,
                                           "rows": len(raw), "scoring_has_not_started": True})
    scored = score_rows(raw, benchmark)
    c.write_new(output / "diagnostic-scores.json", {"raw_sha256": seal, "rows": scored})
    report = {"schema": "hepta.five-reader.response-learning-result.v1", "raw_sha256": seal,
        "plan_sha256": c.digest(PLAN), "task_families": sorted(forbidden), "distinct_questions": len(chosen["test"]),
        "planned_rows": len(raw), "training": training, "load_costs": loads, "arms": summarize(scored),
        "errors": errors, "unavailable_oracle_controls": unavailable,
        "actual_decoder_forwards": sum(r.get("actual_decoder_forwards", 0) for r in raw),
        "arm_order": list(ARMS), "order_counterbalanced": False, "compute_matched": False,
        "old_task_retention_established": False, "independent_confirmation": False,
        "reader_adequacy_established": False, "production_accepted": False,
        "disposition": "historical_development_result_not_formal_admission"}
    c.write_new(output / "report.json", report)
    c.require(not errors, "execution errors retained in report; no successful experiment claim")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.archive, args.work, args.output)
    except Exception as error:
        failure = args.output / "failure.json"
        if not failure.exists():
            c.write_new(failure, {"error": type(error).__name__+": "+str(error)[:2048],
                                  "completed": False, "production_accepted": False})
        raise
