"""Train/select-only diagnosis of evidence-conditioned answering after collapse.

The original TEST families are excluded. This is a preregistered development
comparison, not independent confirmation. Free generations are sealed BEFORE
teacher forcing or target-based scoring. No adaptive epochs, thresholds, seeds
or checkpoint selection; no candidate or Reader gate is promoted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import gc
from pathlib import Path

import torch
from transformers import AutoTokenizer

import five_causal_experiments as c
import five_reader_response_learning as learning
import five_reader_response_trial as previous
import five_reader_evidence_pairs as pairs
from five_reader_adapter import attach, compose
from five_causal_native import SCHEMA, reader_bindings, public_text, generate_exact, count_forwards
from five_native_historical_smoke import snapshot, READER_INVENTORY, LOCOMO_SHA256, ARCHIVE_SHA256
from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
from native import load

ARMS = ("frozen_reader", "archived_aligned", "paired_ce", "paired_margin", "paired_margin_shuffled", "always_refuse")
OBJECTIVES = {"paired_ce": pairs.CE, "paired_margin": pairs.MARGIN, "paired_margin_shuffled": pairs.MARGIN}
PLAN = {"schema": "hepta.reader.evidence-pair-development.v1", "parent_result_run": 38424588299,
        "archive_sha256": ARCHIVE_SHA256, "benchmark_sha256": LOCOMO_SHA256,
        "data_status": "previously_exposed_public_development", "arms": ARMS,
        "train_per_family": 4, "select_per_family": 2, "train_generation_pairs": 4,
        "selection": "identity_hash_before_eligibility_no_replacement", "test_partition_readout": False,
        "training": learning.TRAINING, "objectives": OBJECTIVES,
        "margin_nats_per_token": pairs.MARGIN_NATS_PER_TOKEN, "contrast_weight": pairs.CONTRAST_WEIGHT,
        "maximum_input_tokens": 2048, "maximum_output_tokens": 64, "per_call_seconds": 120,
        "generation_conditions": {"train": ["support_only", "no_evidence"],
                                  "select": ["support_only", "no_evidence", "oracle_plus_distractors", "support_removed"]},
        "readout_profile": previous.READOUT_PROFILE, "countertarget_backward_equal": False,
        "compute_matched": False, "automatic_selection": False, "production_accepted": False}


def choose(benchmark):
    groups = defaultdict(list)
    forbidden = set()
    for q in benchmark.questions:
        partition, family = benchmark.partition(q), benchmark.families[q.family]
        c.require(partition in ("train", "select", "test"), "unknown source partition")
        if partition == "test":
            forbidden.add(family)
        else:
            groups[(partition, family)].append(q)
    chosen = {p: [q for (part, family), rows in sorted(groups.items()) if part == p
                  for q in sorted(rows, key=lambda x: c.digest(x.identity))[:PLAN[p+"_per_family"]]]
              for p in ("train", "select")}
    families = {p: {benchmark.families[q.family] for q in qs} for p, qs in chosen.items()}
    c.require(all(families.values()) and not families["train"] & families["select"]
              and not (families["train"] | families["select"]) & forbidden, "train/select/test source-family leakage")
    roots = {p: {d.root for q in qs for d in benchmark.history(q)} for p, qs in chosen.items()}
    c.require(not roots["train"] & roots["select"], "train/select source roots overlap")
    return chosen, sorted(forbidden)


def select_pairs(benchmark, queries, tokenizer, position_cap):
    """Validation target-bearing objects are explicitly SELECT, never TRAIN."""
    examples, census = [], []
    for q in queries:
        target = benchmark.targets[q.identity]
        _, supported, usable = previous.cases_for(benchmark, q)
        reason = None
        if not usable or target.answer is None or target.unanswerable:
            reason = "unavailable_or_unresolved_positive_annotation"
        else:
            request = previous.public_request(q, supported)
            answer = str(target.answer).strip() + " " + " ".join("["+e["id"]+"]" for e in request["evidence"])
            rows = [{"id": c.digest([q.identity, k]), "question_id": c.digest(q.identity),
                     "family": benchmark.families[q.family], "split": "select", "request": r,
                     "response": a, "kind": k, "source_sha256": LOCOMO_SHA256}
                    for k, r, a in (("annotated_answer", request, answer),
                                    ("empty_refusal", previous.public_request(q, []), learning.REFUSAL))]
            try:
                pairs.compile_pair(tokenizer, tuple(rows), position_cap=position_cap)
            except c.Invalid as error:
                reason = str(error)
            if reason is None:
                examples.extend(rows)
        census.append({"question_id": q.identity, "family": benchmark.families[q.family],
                       "admitted_for_teacher_forcing": reason is None, "reason": reason, "replacement_selected": False})
    return examples, census


def generation_cases(benchmark, chosen, examples):
    cases = []
    training_pairs = pairs.paired_examples(examples)
    selected = sorted(training_pairs, key=lambda p: c.digest(p[0]["question_id"]))[:PLAN["train_generation_pairs"]]
    original_ids = {c.digest(q.identity): q.identity for q in chosen["train"]}
    for positive, negative in selected:
        for name, row in (("support_only", positive), ("no_evidence", negative)):
            cases.append({"question_id": original_ids[row["question_id"]], "family": row["family"],
                          "split": "train", "condition": name, "request": row["request"]})
    # Every identity-selected validation question remains, even if a target or
    # an annotated-support input is unavailable. It is not replaced or dropped.
    for q in chosen["select"]:
        controls, supported, usable = previous.cases_for(benchmark, q)
        controls["support_only"] = previous.public_request(q, supported) if usable else None
        for name in PLAN["generation_conditions"]["select"]:
            cases.append({"question_id": q.identity, "family": benchmark.families[q.family],
                          "split": "select", "condition": name, "request": controls[name]})
    return cases


def aggregate(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["split"], row["condition"])].append(row)
    return [{"split": split, "condition": condition, "planned": len(items),
             "status_census": dict(Counter(x["status"] for x in items)),
             "refusals": sum(x.get("exact_refusal", False) for x in items),
             "exact_bodies": sum(x.get("benchmark_exact_body") is True for x in items),
             "available_targets": sum(x.get("benchmark_exact_body") is not None for x in items),
             "citation_syntax_valid": sum(x.get("citation_syntax_valid", False) for x in items)}
            for (split, condition), items in sorted(grouped.items())]


def run(staged, prior_study, output):
    staged, prior_study, output = Path(staged), Path(prior_study), Path(output)
    c.require(staged.is_dir() and not any(p.is_symlink() for p in (staged, *staged.parents)), "ordinary staged material required")
    original, reader = staged/"original/memory-inputs", staged/"clean/reader"
    snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    matches = [p for p in original.rglob("*.json") if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact original benchmark missing")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256, allow_unresolved_evidence=True)
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output/"plan.json", PLAN)
    c.write_new(output/"source.json", {name: c.file_sha(Path(__file__).with_name(name)) for name in (
        "five_reader_evidence_pair_trial.py", "five_reader_evidence_pairs.py", "five_reader_response_learning.py",
        "five_reader_response_trial.py", "five_causal_native.py", "five_reader_adapter.py")})
    chosen, test_families = choose(benchmark)
    c.write_new(output/"question-selection.json", {"selected": {p: [q.identity for q in qs] for p, qs in chosen.items()},
                                                "excluded_test_families": test_families})
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    position_cap = c.load(reader/"config.json")["max_position_embeddings"]
    train, census = previous.training_examples(benchmark, chosen["train"], tokenizer, position_cap)
    forbidden = sorted(set(test_families) | {benchmark.families[q.family] for q in chosen["select"]})
    learning.validate_examples(train, forbidden)
    shuffled = learning.permuted_positive_targets(train)
    # All context/response combinations must fit before either treatment runs.
    pairs.prepare(tokenizer, train, position_cap=position_cap)
    pairs.prepare(tokenizer, shuffled, position_cap=position_cap)
    c.write_new(output/"training-census.json", {"rows": census, "examples": len(train),
        "aligned_sha256": c.digest(train), "shuffled_sha256": c.digest(shuffled), "forbidden_families": forbidden})
    cases = generation_cases(benchmark, chosen, train)
    c.write_new(output/"public-inputs.json", cases)
    input_sha = c.file_sha(output/"public-inputs.json")
    prior_plan = c.load(prior_study/"plan.json")
    c.require(prior_plan.get("schema") == previous.PLAN["schema"]
              and prior_plan.get("benchmark_sha256") == LOCOMO_SHA256, "unexpected prior response study")
    raw, summaries, errors = [], {}, []
    initial = None
    previous_event = "0"*64
    with (output/"events.jsonl").open("xb") as journal:
        for arm in ARMS:
            backend, arm_error, training, load_cost = None, None, None, None
            try:
                if arm != "always_refuse":
                    previous_event = c.journal_append(journal, {"event": "arm_started", "arm": arm}, previous_event)
                    with measured() as load_cost:
                        backend = LocalTextGenerator(reader, snap, PLAN["maximum_input_tokens"])
                        if arm == "archived_aligned":
                            base_bindings = {k: c.digest("paired-diagnostic-unused:"+k) for k in c.BINDINGS}
                            base_bindings.update(reader_bindings(snap, tokenizer.chat_template, PLAN["maximum_input_tokens"], 64))
                            base = {"schema": SCHEMA, "kind": "reader", "snapshot": snap, "bindings": base_bindings}
                            manifest = compose(prior_study, base, "aligned_lora/adapter", "aligned_lora/training-receipt.json")
                            attach(backend, prior_study, manifest["response_adapter"], snap)
                    if arm in OBJECTIVES:
                        data = shuffled if arm == "paired_margin_shuffled" else train
                        training = learning.fit_response_adapter(backend, data, output/arm,
                                        forbidden_families=forbidden, loss_profile=OBJECTIVES[arm])
                        c.require(initial is None or initial == training["initial_adapter_sha256"], "paired initialization drift")
                        initial = training["initial_adapter_sha256"]
            except Exception as error:
                arm_error = type(error).__name__+": "+str(error)[:1024]
                errors.append({"arm": arm, "phase": "load_or_train", "error": arm_error})
                previous_event = c.journal_append(journal, {"event": "arm_failed", "arm": arm, "error": arm_error}, previous_event)
            arm_raw = []
            for case in sorted(cases, key=lambda r: c.digest([r["split"], r["question_id"], r["condition"]])):
                row = {k: case[k] for k in ("question_id", "family", "split", "condition")}
                row.update(arm=arm, trial_id=c.digest([arm, row]), status="not_executed", answer=None,
                           evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None:
                    row["status"] = "unavailable_support_annotation"
                elif arm_error is not None:
                    row.update(status="blocked_model_or_training", error=arm_error)
                elif arm == "always_refuse":
                    row.update(status="succeeded", answer=learning.REFUSAL, observed_decoder_forwards=0,
                               execution_kind="nonlearned_control")
                else:
                    previous_event = c.journal_append(journal, {"event": "generation_started", "trial_id": row["trial_id"],
                                         "public_request_sha256": c.digest(case["request"])}, previous_event)
                    owner = backend.loaded.get_base_model() if hasattr(backend.loaded, "get_base_model") else backend.loaded
                    with measured() as cost, count_forwards(owner) as calls:
                        try:
                            answer, details = generate_exact(backend, public_text(case["request"]), 2048, 64)
                            row.update(status="succeeded", answer=answer, **details)
                        except Exception as error:
                            row.update(status="failed", error=type(error).__name__+": "+str(error)[:1024])
                    row.update(cost=cost, observed_decoder_forwards=calls["model_calls"], execution_kind="official_HF")
                    if cost["wall_ns"] > PLAN["per_call_seconds"]*1e9:
                        row["status"] = "timeout_with_observed_output"
                    if row["status"] != "succeeded":
                        errors.append({"arm": arm, "phase": "generation", "trial_id": row["trial_id"]})
                previous_event = c.journal_append(journal, {"event": "generation_recorded", **row}, previous_event)
                raw.append(row); arm_raw.append(row)
            # This arm's unconstrained raw generations seal before targets are
            # used for teacher forcing or scoring. No output gets replaced.
            arm_path = output/(arm+"-raw.json")
            c.write_new(arm_path, arm_raw)
            c.write_new(output/(arm+"-raw-seal.json"), {"sha256": c.file_sha(arm_path), "before_teacher_forcing": True})
            diagnostic, diagnostic_cost, teacher_calls = None, None, None
            if backend is not None and arm_error is None:
                before = learning.state_digest(backend.loaded.state_dict())
                try:
                    validation, val_census = select_pairs(benchmark, chosen["select"], tokenizer, position_cap)
                    decoder = (learning.training_forward_owner(backend.loaded) if hasattr(backend.loaded, "get_base_model")
                               else backend.loaded.base_model)
                    previous_event = c.journal_append(journal, {"event": "teacher_forcing_started", "arm": arm}, previous_event)
                    with measured() as diagnostic_cost, count_forwards(decoder) as teacher:
                        diagnostic = pairs.diagnose(backend.loaded, tokenizer, train + validation, position_cap=position_cap)
                    teacher_calls = teacher["model_calls"]
                    c.require(teacher_calls == 4*len(diagnostic), "teacher-forcing counter mismatch")
                    c.require(learning.state_digest(backend.loaded.state_dict()) == before, "diagnostic mutated frozen model")
                    c.write_new(output/(arm+"-conditional.json"), {"records": diagnostic, "validation_census": val_census,
                                   "observed_decoder_forwards": teacher_calls, "cost": diagnostic_cost})
                    if arm == "archived_aligned":
                        from five_reader_adapter import verify_resident
                        verify_resident(backend)
                except Exception as error:
                    errors.append({"arm": arm, "phase": "teacher_forcing", "error": str(error)[:1024]})
                    previous_event = c.journal_append(journal, {"event": "teacher_forcing_failed_or_unknown", "arm": arm,
                                            "retry_permitted": False}, previous_event)
            if backend is not None:
                try:
                    backend.close()
                except Exception as error:
                    errors.append({"arm": arm, "phase": "close", "error": str(error)[:1024]})
                del backend
                gc.collect()
            scored = previous.score_rows(arm_raw, benchmark)
            for item, original_row in zip(scored, arm_raw):
                item["split"] = original_row["split"]
            c.write_new(output/(arm+"-scores.json"), scored)
            conditional = []
            if diagnostic is not None:
                for split in ("train", "select"):
                    values = [r for r in diagnostic if r["split"] == split]
                    conditional.append({"split": split, "pairs": len(values),
                        "positive_both": sum(r["both_conditional_preferences_positive"] for r in values),
                        "mean_supported_margin": sum(r["supported_answer_margin"] for r in values)/len(values) if values else None,
                        "mean_empty_margin": sum(r["empty_refusal_margin"] for r in values)/len(values) if values else None})
            summaries[arm] = {"generation": aggregate(scored), "conditional": conditional, "training": training,
                              "load_cost": load_cost, "teacher_forcing_calls": teacher_calls, "teacher_forcing_cost": diagnostic_cost}
            print(c.canonical({"completed_arm": arm, "generation": summaries[arm]["generation"], "conditional": conditional}).decode(), flush=True)
    c.require(len(raw) == len(cases)*len(ARMS), "planned denominator incomplete")
    c.write_new(output/"raw-answers.json", raw)
    c.require(c.file_sha(output/"public-inputs.json") == input_sha, "public inputs changed")
    report = {"schema": "hepta.reader.evidence-pair-development-result.v1", "plan_sha256": c.digest(PLAN),
              "raw_sha256": c.file_sha(output/"raw-answers.json"), "planned_rows": len(raw),
              "real_generation_calls": sum(r.get("execution_kind") == "official_HF" for r in raw),
              "generation_forward_lower_bound": sum(r.get("observed_decoder_forwards", 0) for r in raw),
              "arms": summaries, "errors": errors, "excluded_test_families": test_families,
              "training_and_diagnostic_costs_separate": True, "independent_confirmation": False,
              "semantic_sufficiency": None, "compute_matched": False, "production_accepted": False,
              "five_experiments_completed": False}
    c.write_new(output/"report.json", report)
    c.require(not errors, "paired study has retained failures")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--staged", type=Path, required=True)
    p.add_argument("--prior-study", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        run(args.staged, args.prior_study, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output/"failure.json").exists():
            c.write_new(args.output/"failure.json", {"error": str(error)[:2048], "production_accepted": False})
        raise
