"""Prospectively fixed expanded SELECT-donor audit of three saved Readers.

This NEW development protocol preserves the old missing-donor result. It keeps
all four old SELECT generation recipients, expands only the SELECT donor pool,
and uses no optimizer or target-conditioned generation. Qualified pair coverage
must be known before model loading. A green job is not Reader admission.
"""
from __future__ import annotations

import argparse
import gc
from pathlib import Path

import five_causal_experiments as c
import reader_content_swap as control
import reader_content_swap_trial as saved
import select_content_inventory as inventory

ARMS = ("frozen_reader", "aligned_8", "shuffled_8")
PLAN = {"schema": "hepta.reader.select-content-validation.v1", "inventory_profile": inventory.PROFILE,
        "parent": "051c21c6dd0abe9a610bf0a2c6666727fd727e4e", "arms": ARMS,
        "budget_artifact_id": 11838105827, "budget_artifact_sha256": saved.BUDGET_SHA,
        "budget_source": saved.BUDGET_SOURCE,
        "old_content_run": 38493158981, "old_content_missingness_retained": True,
        "recipients": "exact_saved_SELECT_generation_questions_no_replacements",
        "donors": "all_eligible_SELECT_questions_fixed_before_model_execution",
        "pairing": saved.PLAN["donor_rule"], "pairing_function": "reader_content_swap.build_comparisons",
        "source_representation": "source-session-time-v1_with_neutral_local_citations",
        "maximum_input_tokens": 2048, "maximum_output_tokens": 64, "per_call_seconds": 120,
        "vocabulary_projection": "full-logits-v1", "new_optimizer_updates": 0,
        "required_coverage": "every_reference_bearing_fixed_recipient_paired_and_compiled",
        "missing_reference_recipient_retained": True,
        "target_semantics": "weak_annotations_not_proven_donor_incompatibility",
        "data_status": "previously_exposed_public_development",
        "independent_confirmation": False, "test_target_access": False,
        "automatic_selection": False, "production_accepted": False}


def run(original_archive, budget_archive, work, output):
    import torch
    from transformers import AutoTokenizer
    import five_reader_response_learning as learning
    import five_reader_response_trial as response
    import five_reader_evidence_pair_trial as parent
    from five_native_historical_smoke import prepare_materials, snapshot, READER_INVENTORY, LOCOMO_SHA256, ARCHIVE_SHA256
    from five_causal_native import SCHEMA, reader_bindings, public_text, generate_exact, count_forwards
    from five_reader_adapter import compose, attach, verify_resident
    from experiments.shared_stem_cell.execution import LocalTextGenerator, measured
    from native import load

    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    config = PLAN | {"original_archive_sha256": ARCHIVE_SHA256, "benchmark_sha256": LOCOMO_SHA256}
    c.write_new(output / "plan.json", config)
    with measured() as acquisition:
        root, receipt = saved.extract_verified(budget_archive, work / "saved-budget", saved.BUDGET_SHA)
        study, previous = saved.validate_budget(root)
        original, clean, staging = prepare_materials(Path(original_archive), work / "original-material")
    c.write_new(output / "materials.json", {"budget": receipt, "original": staging, "cost": acquisition})
    matches = [p for p in original.rglob("*.json") if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact original benchmark missing")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256, allow_unresolved_evidence=True)
    prior_cases = c.load(study / "public-inputs.json")
    planned = inventory.build_plan(benchmark, prior_cases)
    c.write_new(output / "inventory-plan.json", planned)
    cases = planned["public_cases"]
    c.write_new(output / "public-inputs.json", cases)
    input_seal = c.file_sha(output / "public-inputs.json")
    inventory_seal = c.file_sha(output / "inventory-plan.json")
    reader = clean / "reader"
    snap = snapshot(reader, "causal_lm", READER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    capacity = c.load(reader / "config.json")["max_position_embeddings"]
    compiled, census = {}, []
    for item in planned["comparisons"]:
        error = None
        if item["status"] == "available":
            try:
                compiled[item["question_id"]] = control.compile_comparison(tokenizer, item, position_cap=capacity)
            except c.Invalid as failure:
                error = str(failure)[:512]
        census.append({"question_id": item["question_id"], "donor_question_id": item["donor_question_id"],
                       "compiled": item["question_id"] in compiled, "reason": error,
                       "replacement_selected": False})
    c.write_new(output / "compilation-census.json", census)
    coverage = inventory.readiness(planned, compiled)
    c.write_new(output / "coverage.json", coverage)
    print("SELECT_INVENTORY_COVERAGE", c.canonical(coverage).decode(), flush=True)
    if not coverage["all_reference_bearing_ready"]:
        c.write_new(output / "report.json", {"schema": "hepta.reader.select-content-validation-result.v1",
            "plan_sha256": c.digest(config), "status": "blocked_pair_coverage_before_model_load",
            "coverage": coverage, "new_model_calls": 0, "new_optimizer_updates": 0,
            "reader_adequacy_established": False, "production_accepted": False})
        raise c.Invalid("new SELECT inventory still lacks required pair coverage; no model loaded")

    tail, all_raw, by_arm, summaries, errors = "0" * 64, [], {}, {}, []
    with (output / "events.jsonl").open("xb") as journal:
        for arm in ARMS:
            backend, arm_error, load_cost, composition = None, None, None, None
            tail = c.journal_append(journal, {"event": "arm_started", "arm": arm}, tail)
            try:
                with measured() as load_cost:
                    backend = LocalTextGenerator(reader, snap, PLAN["maximum_input_tokens"])
                    if arm != "frozen_reader":
                        bindings = {k: c.digest("select-audit-unused:" + k) for k in c.BINDINGS}
                        bindings.update(reader_bindings(snap, tokenizer.chat_template,
                                                       PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"]))
                        base = {"schema": SCHEMA, "kind": "reader", "snapshot": snap, "bindings": bindings}
                        description = compose(study, base, arm + "/adapter", arm + "/training-receipt.json")
                        c.require(description["response_adapter"]["adapter_tensor_sha256"] ==
                                  previous["arms"][arm]["training"]["adapter_tensor_sha256"], "saved adapter identity differs")
                        composition = attach(backend, study, description["response_adapter"], snap)
                c.require(not backend.loaded.training and all(not p.requires_grad for p in backend.loaded.parameters()),
                          "read-only candidate is not frozen")
                frozen = learning.state_digest(backend.loaded.state_dict())
            except Exception as error:
                arm_error = type(error).__name__ + ": " + str(error)[:1024]
                errors.append({"arm": arm, "phase": "load", "error": arm_error})
                tail = c.journal_append(journal, {"event": "load_failed", "arm": arm,
                    "error": arm_error, "cost": load_cost, "retry_permitted": False}, tail)
            raw = []
            for case in cases:
                row = {k: case[k] for k in ("question_id", "family", "split", "condition")}
                row.update(arm=arm, trial_id=c.digest([PLAN["schema"], arm, row]), status="not_executed", answer=None,
                           evidence_ids=[] if case["request"] is None else [e["id"] for e in case["request"]["evidence"]])
                if case["request"] is None:
                    row["status"] = "unavailable_recipient_annotation_or_source"
                elif arm_error is not None:
                    row.update(status="blocked_model", error=arm_error)
                else:
                    row["public_request_sha256"] = c.digest(case["request"])
                    tail = c.journal_append(journal, {"event": "generation_started", **row}, tail)
                    decoder = (learning.training_forward_owner(backend.loaded)
                               if arm != "frozen_reader" else backend.loaded.base_model)
                    with measured() as cost, count_forwards(decoder) as calls:
                        try:
                            answer, details = generate_exact(backend, public_text(case["request"]),
                                PLAN["maximum_input_tokens"], PLAN["maximum_output_tokens"])
                            row.update(status="succeeded", answer=answer, **details)
                        except Exception as error:
                            row.update(status="failed", error=type(error).__name__ + ": " + str(error)[:1024])
                    row.update(cost=cost, observed_decoder_forwards=calls["model_calls"], model_attempted=True)
                    if cost["wall_ns"] > PLAN["per_call_seconds"] * 1e9:
                        row["status"] = "timeout_with_observed_output"
                    if row["status"] != "succeeded":
                        errors.append({"arm": arm, "phase": "generation", "trial_id": row["trial_id"]})
                tail = c.journal_append(journal, {"event": "generation_recorded", **row}, tail)
                raw.append(row)
                all_raw.append(row)
            # Unconstrained answers seal before targets can enter likelihood calls.
            c.write_new(output / (arm + "-raw.json"), raw)
            c.write_new(output / (arm + "-raw-seal.json"), {
                "sha256": c.file_sha(output / (arm + "-raw.json")), "before_teacher_forcing": True})
            audits = []
            for recipient in planned["recipients"]:
                item = {k: recipient[k] for k in ("question_id", "family", "split", "donor_question_id")}
                item.update(status="unavailable_recipient_annotation", audit=None, observed_decoder_forwards=0)
                if arm_error is not None:
                    item["status"] = "blocked_model"
                elif recipient["question_id"] in compiled:
                    tail = c.journal_append(journal, {"event": "audit_started", "arm": arm, **item}, tail)
                    decoder = (learning.training_forward_owner(backend.loaded)
                               if arm != "frozen_reader" else backend.loaded.base_model)
                    with measured() as cost, count_forwards(decoder) as calls:
                        try:
                            result = control.score_comparison(backend.loaded, compiled[recipient["question_id"]])
                            c.require(calls["model_calls"] == 4, "four actual scored sequences required")
                            item.update(status="succeeded", audit=result)
                        except Exception as error:
                            item.update(status="failed", error=type(error).__name__ + ": " + str(error)[:1024])
                    item.update(cost=cost, observed_decoder_forwards=calls["model_calls"], retry_permitted=False)
                    if item["status"] != "succeeded":
                        errors.append({"arm": arm, "phase": "audit", "question_id": item["question_id"]})
                tail = c.journal_append(journal, {"event": "audit_recorded", "arm": arm, **item}, tail)
                audits.append(item)
            integrity = False
            if backend is not None:
                if arm_error is None:
                    try:
                        c.require(learning.state_digest(backend.loaded.state_dict()) == frozen, "audit changed weights")
                        if arm != "frozen_reader":
                            verify_resident(backend)
                        integrity = True
                    except Exception as error:
                        errors.append({"arm": arm, "phase": "integrity", "error": str(error)[:1024]})
                try:
                    backend.close()
                except Exception as error:
                    errors.append({"arm": arm, "phase": "close", "error": str(error)[:1024]})
                del backend
                gc.collect()
            scored = response.score_rows(raw, benchmark)
            for result, original_row in zip(scored, raw):
                result["split"] = original_row["split"]
            c.write_new(output / (arm + "-scores.json"), scored)
            c.write_new(output / (arm + "-content-audit.json"), audits)
            by_arm[arm] = audits
            summaries[arm] = {"generation": parent.aggregate(scored), "content": control.summarize(audits),
                "load_cost": load_cost, "composition": composition, "model_integrity_verified": integrity,
                "audit_forwards": sum(x["observed_decoder_forwards"] for x in audits), "optimizer_updates": 0}
            print(c.canonical({"completed_arm": arm, **summaries[arm]}).decode(), flush=True)
    c.require(len(all_raw) == len(cases) * len(ARMS), "planned generation denominator changed")
    c.require(c.file_sha(output / "public-inputs.json") == input_seal and
              c.file_sha(output / "inventory-plan.json") == inventory_seal and
              c.file_sha(matches[0]) == LOCOMO_SHA256, "frozen input bytes changed")
    c.write_new(output / "raw-answers.json", all_raw)
    report = {"schema": "hepta.reader.select-content-validation-result.v1", "plan_sha256": c.digest(config),
        "inventory_sha256": inventory_seal, "raw_sha256": c.file_sha(output / "raw-answers.json"),
        "planned_generation_rows": len(all_raw), "successful_model_calls": sum(x["status"] == "succeeded" for x in all_raw),
        "generation_forward_lower_bound": sum(x.get("observed_decoder_forwards", 0) for x in all_raw),
        "arms": summaries, "coverage": coverage, "errors": errors,
        "paired_vs_frozen": inventory.paired_readout(by_arm),
        "aligned_vs_shuffled": inventory.paired_readout({k: by_arm[k] for k in ("aligned_8", "shuffled_8")}, "shuffled_8"),
        "new_optimizer_updates": 0, "new_independent_tasks": 0,
        "old_missing_validation_result_reinterpreted": False, "reader_adequacy_established": False,
        "independent_confirmation": False, "compute_matched": False,
        "production_accepted": False, "five_experiments_completed": False}
    c.write_new(output / "report.json", report)
    print("SELECT_CONTENT_RESULT", c.canonical(report).decode(), flush=True)
    c.require(not errors, "SELECT content study has retained failures")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-archive", type=Path, required=True)
    parser.add_argument("--budget-archive", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.original_archive, args.budget_archive, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048], "completed": False,
                                                      "production_accepted": False})
        raise
