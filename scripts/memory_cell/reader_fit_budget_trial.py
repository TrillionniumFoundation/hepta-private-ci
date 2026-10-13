"""Fixed training-dose experiment plus read-only target/decoding audit.

TRAIN/SELECT only, same source-date projection for every arm, two prespecified
budgets and correct/shuffled supervision. No extra model, optimizer, dynamic
stopping, best-checkpoint selection, target-free-generation substitution or
production admission. This driver calls the EXISTING fit_response_adapter.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gc
from pathlib import Path

import torch
from transformers import AutoTokenizer

import five_causal_experiments as c
import five_reader_response_learning as learning
import five_reader_response_trial as response
import five_reader_evidence_pair_trial as parent
import five_reader_evidence_pairs as pairs
import source_time_evidence as metadata
from source_time_evidence_trial import project_examples, project_cases
import reader_fit_audit as audit
from five_causal_native import public_text, generate_exact, count_forwards
from five_native_historical_smoke import (
    prepare_materials, snapshot, ARCHIVE_SHA256, LOCOMO_SHA256, READER_INVENTORY)
from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
from native import load

# Fixed order, not a claim of randomized host-cost counterbalancing.
ARMS = (("frozen_reader", 0, False), ("aligned_2", 2, False),
        ("shuffled_8", 8, True), ("shuffled_2", 2, True), ("aligned_8", 8, False))
PLAN = {"schema": "hepta.reader.fixed-fit-budget.v1", "arms": ARMS,
    "parent_source": "5fdb607484785e8ce78781808dda18866ef35709",
    "epochs_fixed_before_results": [2, 8], "model_representation": metadata.SOURCE_TIME,
    "training_objective": pairs.MARGIN, "loss_config": {
        "margin_nats_per_token": pairs.MARGIN_NATS_PER_TOKEN, "contrast_weight": pairs.CONTRAST_WEIGHT},
    "training": deepcopy(learning.TRAINING), "audit_profile": audit.PROFILE,
    "readout_profile": response.READOUT_PROFILE, "selection_plan_sha256": c.digest(parent.PLAN),
    "maximum_input_tokens": 2048, "maximum_output_tokens": 64, "per_call_seconds": 120,
    "archive_sha256": ARCHIVE_SHA256, "benchmark_sha256": LOCOMO_SHA256,
    "test_readout": False, "automatic_selection": False, "adaptive_budget": False,
    "data_status": "previously_exposed_public_train_select_development",
    "uncited_targets_only_in_post_generation_diagnostic": True,
    "cost_design": "optimization_dose_not_equal_compute", "production_accepted": False}


def assert_training_pair_identity(train, shuffled, forbidden):
    learning.validate_examples(train, forbidden)
    learning.validate_examples(shuffled, forbidden)
    c.require(len(train) == len(shuffled), "shuffle changed cohort")
    for a, b in zip(train, shuffled):
        c.require({k:v for k,v in a.items() if k != "response"}
                  == {k:v for k,v in b.items() if k != "response"}, "shuffle changed input or identity")
        if a["kind"] == "empty_refusal":
            c.require(a == b, "shuffle changed empty supervision")
    c.require(sorted(x["response"] for x in train) == sorted(x["response"] for x in shuffled),
              "shuffle changed target multiset")
    c.require(any(a["response"] != b["response"] for a,b in zip(train, shuffled)), "degenerate shuffle")


def compare_schedules(short, long):
    """Compare actual registered unit order, NOT timing, scores or best epochs."""
    def starts(path):
        import json
        rows = [json.loads(line)["record"] for line in path.read_text().splitlines()]
        return [(r["epoch"], r["index"], r["example_id"])
                for r in rows if r["event"] == "optimizer_started"]
    a, b = starts(short), starts(long)
    c.require(a and len(b) == 4 * len(a) and a == b[:len(a)], "dose example-order prefix mismatch")
    return {"short_started_units": len(a), "long_started_units": len(b),
            "example_order_prefix_equal": True, "intermediate_tensor_equality_proved": False}


def run(archive, work, output):
    archive, work, output = Path(archive), Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    c.write_new(output / "plan.json", PLAN)
    c.write_new(output / "source.json", {name:c.file_sha(Path(__file__).with_name(name)) for name in (
        "reader_fit_budget_trial.py", "reader_fit_audit.py", "source_time_evidence.py",
        "source_time_evidence_trial.py", "five_reader_evidence_pairs.py", "five_reader_response_learning.py",
        "five_reader_evidence_pair_trial.py", "five_reader_response_trial.py", "five_causal_native.py",
        "five_native_historical_smoke.py", "native.py")})
    with measured() as staging_cost:
        original, clean, staging = prepare_materials(archive, work / "staged")
    c.write_new(output / "staging.json", staging | {"cost": staging_cost})
    matches = [p for p in original.rglob("*.json")
               if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact original benchmark unavailable")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256, allow_unresolved_evidence=True)
    chosen, excluded = parent.choose(benchmark)
    forbidden = sorted(set(excluded) | {benchmark.families[q.family] for q in chosen["select"]})
    reader = clean / "reader"
    snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    capacity = c.load(reader / "config.json")["max_position_embeddings"]
    original_train, census = response.training_examples(benchmark, chosen["train"], tokenizer, capacity)
    train, projection = project_examples(original_train, chosen["train"], benchmark.history, metadata.SOURCE_TIME)
    shuffled = learning.permuted_positive_targets(train)
    assert_training_pair_identity(train, shuffled, forbidden)
    pairs.prepare(tokenizer, train, position_cap=capacity)
    pairs.prepare(tokenizer, shuffled, position_cap=capacity)
    train_pairs = pairs.paired_examples(train)
    for pair in train_pairs:
        audit.compile_audit(tokenizer, pair, position_cap=capacity)
    cases, input_projection = project_cases(parent.generation_cases(benchmark, chosen, original_train),
        chosen["train"] + chosen["select"], benchmark.history, metadata.SOURCE_TIME)
    c.write_new(output / "cohort.json", {"chosen": {s:[q.identity for q in qs] for s,qs in chosen.items()},
        "excluded_test_families": excluded, "training_census": census, "train_pairs": len(train_pairs),
        "train_sha256": c.digest(train), "shuffled_sha256": c.digest(shuffled)})
    c.write_new(output / "projection.json", {"training": projection, "generation": input_projection})
    c.write_new(output / "public-inputs.json", cases)
    input_seal = c.file_sha(output / "public-inputs.json")
    previous, raw, summaries, errors, initial = "0"*64, [], {}, [], None
    with (output / "events.jsonl").open("xb") as journal:
        for arm, epochs, permuted in ARMS:
            backend, training, arm_error, load_cost = None, None, None, None
            previous = c.journal_append(journal, {"event": "arm_started", "arm": arm,
                "epochs": epochs, "shuffled": permuted}, previous)
            try:
                with measured() as load_cost:
                    backend = LocalTextGenerator(reader, snap, PLAN["maximum_input_tokens"])
                if epochs:
                    training = learning.fit_response_adapter(backend, shuffled if permuted else train,
                        output / arm, forbidden_families=forbidden, epochs=epochs, loss_profile=pairs.MARGIN)
                    c.require(training["optimizer_steps"] == epochs * len(train_pairs), "unexpected update count")
                    c.require(initial is None or training["initial_adapter_sha256"] == initial, "initialization drift")
                    initial = training["initial_adapter_sha256"]
                c.require(all(not p.requires_grad for p in backend.loaded.parameters()), "evaluation model trainable")
                frozen = learning.state_digest(backend.loaded.state_dict())
            except Exception as error:
                arm_error = type(error).__name__ + ": " + str(error)[:1024]
                errors.append({"arm": arm, "phase": "load_or_train", "error": arm_error})
                previous = c.journal_append(journal, {"event": "arm_failed", "arm": arm,
                    "error": arm_error, "retry_permitted": False, "load_cost": load_cost}, previous)
            arm_raw = []
            for case in sorted(cases, key=lambda r:c.digest([r["split"],r["question_id"],r["condition"]])):
                row = {k:case[k] for k in ("question_id","family","split","condition")}
                row.update(arm=arm, trial_id=c.digest([arm,row]), status="not_executed", answer=None,
                    evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None:
                    row["status"] = "unavailable_support_annotation"
                elif arm_error is not None:
                    row.update(status="blocked_model_or_training", error=arm_error)
                else:
                    row["public_request_sha256"] = c.digest(case["request"])
                    previous = c.journal_append(journal, {"event":"generation_started", **row}, previous)
                    decoder = learning.training_forward_owner(backend.loaded) if epochs else backend.loaded.base_model
                    with measured() as cost, count_forwards(decoder) as calls:
                        try:
                            answer, details = generate_exact(backend, public_text(case["request"]),
                                PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"])
                            row.update(status="succeeded", answer=answer, **details)
                        except Exception as error:
                            row.update(status="failed", error=type(error).__name__+": "+str(error)[:1024])
                    row.update(cost=cost, observed_decoder_forwards=calls["model_calls"], model_attempted=True)
                    if cost["wall_ns"] > PLAN["per_call_seconds"] * 1e9:
                        row["status"] = "timeout_with_observed_output"
                    if row["status"] != "succeeded":
                        errors.append({"arm":arm,"phase":"generation","trial_id":row["trial_id"]})
                previous = c.journal_append(journal, {"event":"generation_recorded",**row}, previous)
                raw.append(row); arm_raw.append(row)
            # All free outputs for this model are immutable before target audits.
            c.write_new(output / (arm+"-raw.json"), arm_raw)
            c.write_new(output / (arm+"-raw-seal.json"), {"sha256":c.file_sha(output/(arm+"-raw.json")),
                "before_teacher_forcing":True})
            records, validation_census = [], None
            if backend is not None and arm_error is None:
                try:
                    selection, validation_census = parent.select_pairs(benchmark, chosen["select"], tokenizer, capacity)
                    validation, _ = project_examples(selection, chosen["select"], benchmark.history, metadata.SOURCE_TIME)
                    evaluation_pairs = pairs.paired_examples(train+validation, training=False)
                    decoder = learning.training_forward_owner(backend.loaded) if epochs else backend.loaded.base_model
                    for pair in evaluation_pairs:
                        item = {"question_id":pair[0]["question_id"],"family":pair[0]["family"],
                                "split":pair[0]["split"],"status":"not_executed","audit":None}
                        previous = c.journal_append(journal, {"event":"audit_started","arm":arm,**item},previous)
                        with measured() as cost, count_forwards(decoder) as calls:
                            try:
                                result = audit.audit_one(backend.loaded, tokenizer, pair, position_cap=capacity)
                                c.require(calls["model_calls"] == 6, "six actual scored sequences required")
                                item.update(status="succeeded",audit=result)
                            except Exception as error:
                                item.update(status="failed",error=type(error).__name__+": "+str(error)[:1024])
                        item.update(cost=cost,observed_decoder_forwards=calls["model_calls"],retry_permitted=False)
                        if item["status"] != "succeeded":
                            errors.append({"arm":arm,"phase":"audit","question_id":item["question_id"]})
                        previous = c.journal_append(journal,{"event":"audit_recorded","arm":arm,**item},previous)
                        records.append(item)
                    c.require(learning.state_digest(backend.loaded.state_dict()) == frozen,
                              "inference or target audit changed frozen model")
                except Exception as error:
                    errors.append({"arm":arm,"phase":"audit_setup_or_integrity","error":str(error)[:1024]})
                    previous = c.journal_append(journal,{"event":"audit_failed_or_unknown","arm":arm,
                        "error":str(error)[:1024],"retry_permitted":False},previous)
            c.write_new(output/(arm+"-audit.json"),{"records":records,"validation_census":validation_census})
            if backend is not None:
                try: backend.close()
                except Exception as error: errors.append({"arm":arm,"phase":"close","error":str(error)[:1024]})
                del backend
                gc.collect()
            scored = response.score_rows(arm_raw, benchmark)
            for score, row in zip(scored, arm_raw): score["split"] = row["split"]
            c.write_new(output/(arm+"-scores.json"),scored)
            summaries[arm] = {"epochs":epochs,"shuffled":permuted,"training":training,"load_cost":load_cost,
                "generation":parent.aggregate(scored),"audit":audit.summarize(records),
                "audit_forward_lower_bound":sum(r["observed_decoder_forwards"] for r in records)}
            print(c.canonical({"completed_arm":arm, "generation":summaries[arm]["generation"],
                               "audit":summaries[arm]["audit"]}).decode(),flush=True)
    schedules = {}
    for kind in ("aligned", "shuffled"):
        if all(summaries[kind+"_"+str(n)]["training"] is not None for n in (2,8)):
            try:
                schedules[kind] = compare_schedules(output/(kind+"_2")/"optimizer-journal.jsonl",
                                                    output/(kind+"_8")/"optimizer-journal.jsonl")
            except Exception as error: errors.append({"phase":"schedule_comparison","kind":kind,"error":str(error)})
    c.require(len(raw) == len(cases)*len(ARMS), "planned generation census incomplete")
    c.require(c.file_sha(output/"public-inputs.json") == input_seal
              and c.file_sha(matches[0]) == LOCOMO_SHA256, "frozen input drift")
    c.write_new(output/"raw-answers.json",raw)
    report = {"schema":"hepta.reader.fixed-fit-budget-result.v1", "plan_sha256":c.digest(PLAN),
        "raw_sha256":c.file_sha(output/"raw-answers.json"),"planned_rows":len(raw),
        "succeeded":sum(r["status"]=="succeeded" for r in raw),"arms":summaries,
        "generation_forward_lower_bound":sum(r.get("observed_decoder_forwards",0) for r in raw),
        "actual_schedule_prefix_comparisons":schedules,"errors":errors,
        "excluded_test_families":excluded,"training_and_audit_costs_are_additional":True,
        "compute_matched":False,"independent_confirmation":False,"reader_adequacy_established":False,
        "automatic_selection":False,"production_accepted":False,"five_experiments_completed":False}
    c.write_new(output/"report.json",report)
    print("FIT_BUDGET_RESULT",c.canonical(report).decode(),flush=True)
    c.require(not errors,"fit-budget study has retained failures")
    return report


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",type=Path);p.add_argument("--work",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    try: run(args.archive,args.work,args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output/"failure.json").exists():
            c.write_new(args.output/"failure.json",{"error":str(error)[:2048],"production_accepted":False})
        raise
