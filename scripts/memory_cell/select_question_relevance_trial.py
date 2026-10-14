"""Finish SELECT same-source/different-question measurement using saved Readers.

No training, new donor search or outcome-conditioned replacement. The supplied
training artifact MUST be the completed exact 644799a3 run with an externally
provided SHA256. If unavailable, stop before model loading. Old mismatched
answers are reused, not counted as new calls. This remains exposed development.
"""
from __future__ import annotations

import argparse
import gc
from pathlib import Path

import five_causal_experiments as c
import reader_content_swap_trial as saved
import select_question_relevance as protocol

TRAIN_SOURCE = "644799a3ec45e18e77ce4ad772029f67fee55db7"
TRAIN_RUN = 38512395172
SELECT_SOURCE = "1672d4b3debb65bf0d7198464d9dc0c55811f08e"
SELECT_SHA = "aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa"
PLAN = {"schema": "hepta.reader.select-question-followthrough.v1", "profile": protocol.PROFILE,
        "arms": protocol.ARMS, "training_source": TRAIN_SOURCE, "training_run": TRAIN_RUN,
        "select_source": SELECT_SOURCE, "select_archive_sha256": SELECT_SHA,
        "generation": "only_missing_matched_donor_question_once_per_unique_input_per_arm",
        "mismatched_answers": "exact_saved_training_study_SELECT_outputs",
        "maximum_input_tokens": 2048, "maximum_output_tokens": 64, "per_call_seconds": 120,
        "vocabulary_projection": "full-logits-v1", "new_optimizer_updates": 0,
        "new_independent_tasks": 0, "automatic_selection": False, "production_accepted": False}


def validate_training(root):
    root = Path(root)
    c.require((root / "source/tested-commit.txt").read_text().strip() == TRAIN_SOURCE, "wrong completed training source")
    study = root / "study"
    plan, report = c.load(study / "plan.json"), c.load(study / "report.json")
    c.require(report.get("schema") == "hepta.reader.question-relevance-result.v1"
              and report.get("errors") == [] and report["plan_sha256"] == c.digest(plan), "incomplete training result")
    c.require(plan["schema"] == "hepta.reader.question-relevance-study.v1"
              and plan["epochs"] == 8 and plan["vocabulary_projection"] == "full-logits-v1"
              and tuple(x[0] for x in plan["arms"]) == protocol.ARMS
              and set(report["arms"]) == set(protocol.ARMS), "old training design changed")
    raw = c.load(study / "raw-answers.json")
    cases = c.load(study / "public-inputs.json")
    c.require(report["raw_sha256"] == c.file_sha(study / "raw-answers.json"), "training raw seal mismatch")
    joined = protocol.join_previous(cases, raw)
    for arm in protocol.ARMS:
        own = c.load(study / (arm + "-raw.json"))
        seal = c.load(study / (arm + "-raw-seal.json"))
        c.require(seal["before_target_scoring"] is True and seal["sha256"] == c.file_sha(study / (arm + "-raw.json"))
                  and own == [r for r in raw if r["arm"] == arm], "saved arm raw bytes changed")
        c.require(report["arms"][arm]["model_integrity_verified"] is True, "old model integrity failed")
        c.require(all(r["arm"] == arm for r in joined[arm].values()), "old answer arm changed")
        if arm != "frozen_reader":
            receipt = c.load(study / arm / "training-receipt.json")
            c.require(receipt == report["arms"][arm]["training"] and receipt["base_unchanged"] is True
                      and receipt["checkpoint_reload_equal"] is True, "saved training receipt differs")
    return study, report, cases, joined


def run(original_archive, training_archive, training_sha256, select_archive, work, output):
    import torch
    from transformers import AutoTokenizer
    import five_reader_response_learning as learning
    from five_reader_evidence_pairs import sequence_score
    from five_native_historical_smoke import prepare_materials, snapshot, READER_INVENTORY, ARCHIVE_SHA256
    from five_causal_native import SCHEMA, reader_bindings, public_text, generate_exact, count_forwards
    from five_reader_adapter import compose, attach, verify_resident
    from experiments.shared_stem_cell.execution import LocalTextGenerator, measured

    work, output = Path(work), Path(output)
    c.require(c.sha(training_sha256), "external training artifact SHA required")
    output.mkdir(parents=True, exist_ok=False)
    config = PLAN | {"training_archive_sha256": training_sha256, "original_archive_sha256": ARCHIVE_SHA256}
    c.write_new(output / "plan.json", config)
    with measured() as acquisition:
        root, training_verification = saved.extract_verified(training_archive, work / "completed-training", training_sha256)
        study, prior, prior_cases, previous = validate_training(root)
        select_root, select_verification = saved.extract_verified(select_archive, work / "select-result", SELECT_SHA)
        c.require((select_root / "source/tested-commit.txt").read_text().strip() == SELECT_SOURCE, "wrong SELECT source")
        selected = select_root / "study"
        inventory = c.load(selected / "inventory-plan.json")
        select_report = c.load(selected / "report.json")
        c.require(select_report["errors"] == [] and select_report["inventory_sha256"] == c.file_sha(selected / "inventory-plan.json"), "SELECT inventory seal changed")
        plan = protocol.build_plan(inventory, prior_cases)
        c.write_new(output / "comparison-plan.json", plan)
        c.write_new(output / "new-public-inputs.json", plan["public_requests"])
        original, clean, staging = prepare_materials(Path(original_archive), work / "original")
    c.write_new(output / "materials.json", {"training": training_verification, "select": select_verification,
                                            "original": staging, "cost": acquisition})
    reader = clean / "reader"
    snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    capacity = c.load(reader / "config.json")["max_position_embeddings"]
    compiled, census = {}, []
    for unit in plan["units"]:
        error = None
        if unit["status"] == "available":
            try:
                compiled[unit["question_id"]] = protocol.compile_unit(tokenizer, unit, position_cap=capacity)
            except Exception as failure:
                error = type(failure).__name__ + ": " + str(failure)[:512]
        census.append({"question_id": unit["question_id"], "compiled": unit["question_id"] in compiled,
                       "status": unit["status"], "error": error, "replacement_selected": False})
    c.write_new(output / "compilation-census.json", census)
    ready = {u["question_id"] for u in plan["units"] if u["status"] == "available"}
    c.require(ready and set(compiled) == ready, "blocked coverage before Reader load; no alternative donor")
    input_seal = c.file_sha(output / "new-public-inputs.json")
    comparison_seal = c.file_sha(output / "comparison-plan.json")
    all_raw, summaries, errors, tail = [], {}, [], "0" * 64
    with (output / "events.jsonl").open("xb") as journal:
        for arm in protocol.ARMS:
            backend, arm_error, load_cost, composition = None, None, None, None
            tail = c.journal_append(journal, {"event": "arm_started", "arm": arm}, tail)
            try:
                with measured() as load_cost:
                    backend = LocalTextGenerator(reader, snap, PLAN["maximum_input_tokens"])
                    if arm != "frozen_reader":
                        bindings = {k: c.digest("select-question-unused:" + k) for k in c.BINDINGS}
                        bindings.update(reader_bindings(snap, tokenizer.chat_template, PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"]))
                        base = {"schema": SCHEMA, "kind": "reader", "snapshot": snap, "bindings": bindings}
                        description = compose(study, base, arm + "/adapter", arm + "/training-receipt.json")
                        c.require(description["response_adapter"]["adapter_tensor_sha256"] == prior["arms"][arm]["training"]["adapter_tensor_sha256"], "different saved candidate")
                        composition = attach(backend, study, description["response_adapter"], snap)
                c.require(not backend.loaded.training and all(not p.requires_grad for p in backend.loaded.parameters()), "frozen candidate required")
                before = learning.state_digest(backend.loaded.state_dict())
            except Exception as failure:
                arm_error = type(failure).__name__ + ": " + str(failure)[:1024]
                errors.append({"arm": arm, "phase": "load", "error": arm_error})
                tail = c.journal_append(journal, {"event": "load_failed", "arm": arm, "error": arm_error, "cost": load_cost}, tail)
            generated, arm_raw = {}, []
            for case in plan["public_requests"]:
                key = case["request_id"]
                row = {"arm": arm, "request_id": key, "trial_id": c.digest([PLAN["schema"], arm, key]),
                       "status": "blocked_model" if arm_error else "not_executed", "answer": None,
                       "public_request_sha256": c.digest(case["request"]), "model_attempted": False}
                if arm_error is None:
                    tail = c.journal_append(journal, {"event": "generation_started", **row}, tail)
                    decoder = learning.training_forward_owner(backend.loaded) if arm != "frozen_reader" else backend.loaded.base_model
                    with measured() as cost, count_forwards(decoder) as calls:
                        try:
                            answer, details = generate_exact(backend, public_text(case["request"]), PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"])
                            row.update(status="succeeded", answer=answer, **details)
                        except Exception as failure:
                            row.update(status="failed", error=type(failure).__name__ + ": " + str(failure)[:1024])
                    row.update(cost=cost, observed_decoder_forwards=calls["model_calls"], model_attempted=True)
                    if cost["wall_ns"] > PLAN["per_call_seconds"] * 1e9:
                        row["status"] = "timeout_with_observed_output"
                    if row["status"] != "succeeded": errors.append({"arm": arm, "phase": "generate", "request_id": key})
                tail = c.journal_append(journal, {"event": "generation_recorded", **row}, tail)
                generated[key] = row; arm_raw.append(row); all_raw.append(row)
            c.write_new(output / (arm + "-new-raw.json"), arm_raw)
            c.write_new(output / (arm + "-new-raw-seal.json"), {"sha256": c.file_sha(output / (arm + "-new-raw.json")), "before_teacher_forcing": True})
            audits = []
            for unit in plan["units"]:
                row = {k: unit[k] for k in ("question_id", "original_question_id", "family", "split", "donor_question_id")}
                row.update(status="unavailable_reference_or_donor", preference=None, observed_decoder_forwards=0)
                old = previous[arm][(unit["question_id"], "donor_sources")]
                new = generated.get(unit["matched_request_id"], {"status": "unavailable", "answer": None})
                row.update(behavior=protocol.behavior(new, old), reused_mismatched_trial_id=old["trial_id"],
                           reused_mismatched_answer=old["answer"], matched_request_id=unit["matched_request_id"],
                           matched_answer=new["answer"], reused_answer_is_new_model_call=False)
                if arm_error is not None:
                    row["status"] = "blocked_model"
                elif unit["question_id"] in compiled:
                    tail = c.journal_append(journal, {"event": "audit_started", "arm": arm, **row}, tail)
                    decoder = learning.training_forward_owner(backend.loaded) if arm != "frozen_reader" else backend.loaded.base_model
                    with measured() as cost, count_forwards(decoder) as calls, torch.no_grad():
                        try:
                            values = [float(sequence_score(backend.loaded, b)) for b, _ in compiled[unit["question_id"]]]
                            c.require(calls["model_calls"] == 4, "four actual same-source scores required")
                            row.update(status="succeeded", preference=protocol.preference(values),
                                       compiled=[m for _, m in compiled[unit["question_id"]]])
                        except Exception as failure:
                            row.update(status="failed", error=type(failure).__name__ + ": " + str(failure)[:1024])
                    row.update(cost=cost, observed_decoder_forwards=calls["model_calls"])
                    if cost["wall_ns"] > PLAN["per_call_seconds"] * 1e9: row["status"] = "timeout_with_observed_scores"
                    if row["status"] != "succeeded": errors.append({"arm": arm, "phase": "audit", "question_id": unit["question_id"]})
                tail = c.journal_append(journal, {"event": "audit_recorded", "arm": arm, **row}, tail)
                audits.append(row)
            integrity = False
            if backend is not None:
                try:
                    if arm_error is None:
                        c.require(learning.state_digest(backend.loaded.state_dict()) == before, "scoring changed weights")
                        if arm != "frozen_reader": verify_resident(backend)
                        integrity = True
                    backend.close()
                except Exception as failure:
                    errors.append({"arm": arm, "phase": "integrity_or_close", "error": str(failure)[:1024]})
                del backend
                gc.collect()
            c.write_new(output / (arm + "-audit.json"), audits)
            summaries[arm] = protocol.summarize(audits) | {"load_cost": load_cost, "composition": composition,
                "model_integrity_verified": integrity, "new_likelihood_forwards": sum(x["observed_decoder_forwards"] for x in audits)}
            print(c.canonical({"completed_arm": arm, **summaries[arm]}).decode(), flush=True)
    c.require(c.file_sha(output / "new-public-inputs.json") == input_seal and c.file_sha(output / "comparison-plan.json") == comparison_seal, "frozen inputs changed")
    c.require(len(all_raw) == len(protocol.ARMS) * len(plan["public_requests"]), "new call census changed")
    c.write_new(output / "new-raw-answers.json", all_raw)
    report = {"schema": PLAN["schema"] + ".result", "plan_sha256": c.digest(config),
        "new_raw_sha256": c.file_sha(output / "new-raw-answers.json"), "arms": summaries, "errors": errors,
        "planned_new_generation_calls": len(all_raw), "successful_new_generation_calls": sum(x["status"] == "succeeded" for x in all_raw),
        "new_generation_forward_lower_bound": sum(x.get("observed_decoder_forwards", 0) for x in all_raw),
        "new_optimizer_updates": 0, "new_independent_tasks": 0, "old_mismatched_outputs_regenerated": False,
        "independent_semantic_reviews": 0, "reader_adequacy_established": False, "production_accepted": False,
        "compute_matched": False, "five_experiments_completed": False}
    c.write_new(output / "report.json", report)
    print("SELECT_QUESTION_RESULT", c.canonical(report).decode(), flush=True)
    c.require(not errors, "saved SELECT question audit retains execution failures")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("original-archive", "training-archive", "select-archive", "work", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--training-sha256", required=True)
    args = parser.parse_args()
    try:
        run(args.original_archive, args.training_archive, args.training_sha256, args.select_archive, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048], "completed": False, "production_accepted": False})
        raise
