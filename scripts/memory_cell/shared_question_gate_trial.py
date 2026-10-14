"""Fixed small-Head development trial using one real archived Encoder.

Reuse only pinned, already registered pairs. No Reader is loaded, no LoRA fit,
no new donor selection, and no answer or reviewer label becomes an Encoder input.
This tests a representation/Head hypothesis, not final-answer correctness.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import five_causal_experiments as c
import shared_question_gate as gate

SELECT_SHA = "aeb4113b6d2baace0a042f960876861c78b5449b6d9dac404dee2e5c041e46fa"
SELECT_SOURCE = "1672d4b3debb65bf0d7198464d9dc0c55811f08e"
PLAN = {"schema": gate.PROFILE + ".study", "arms": gate.ARMS, "seeds": gate.SEEDS,
        "steps": gate.STEPS, "rank": gate.RANK, "learning_rate": gate.LEARNING_RATE,
        "representation": gate.REPRESENTATION, "maximum_input_tokens": gate.MAXIMUM_TOKENS,
        "labels": "previously_registered_weak_question_swap", "fixed_logit_threshold": 0.0,
        "source_pairing": "unchanged_644799a3_TRAIN_and_1672d4b3_SELECT",
        "no_reference_answer_encoder_input": True, "new_reader_calls": 0,
        "new_pretrained_optimizer_updates": 0, "new_donor_selection": False,
        "test_partition_access": False, "independent_confirmation": False,
        "comparison_with_Reader_TCO": False, "production_accepted": False}


def run(original_archive, cancelled_archive, select_archive, work, output):
    import torch
    from safetensors.torch import save_file, load_file
    from transformers import AutoTokenizer
    import relevance_recovery as recovery
    import select_question_relevance as select_protocol
    from reader_content_swap_trial import extract_verified
    from five_native_historical_smoke import prepare_materials, snapshot, ENCODER_INVENTORY
    from five_causal_native import count_forwards
    from experiments.shared_stem_cell.execution import LocalEncoder, measured, parameters, tensor_digest

    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    c.write_new(output / "plan.json", PLAN)
    with measured() as material_cost:
        old, old_receipt = extract_verified(Path(cancelled_archive), work / "cancelled", recovery.CANCELLED_SHA)
        sel, sel_receipt = extract_verified(Path(select_archive), work / "select", SELECT_SHA)
        c.require((old / "source/tested-commit.txt").read_text().strip() == recovery.CANCELLED_SOURCE,
                  "wrong fixed TRAIN source")
        c.require((sel / "source/tested-commit.txt").read_text().strip() == SELECT_SOURCE, "wrong fixed SELECT source")
        train = c.load(old / "study/train-plan.json")
        selected = c.load(sel / "study/inventory-plan.json")
        select_report = c.load(sel / "study/report.json")
        c.require(select_report["inventory_sha256"] == c.file_sha(sel / "study/inventory-plan.json"), "SELECT seal changed")
        select_pairs = select_protocol.build_plan(selected, c.load(old / "study/public-inputs.json"))
        public = gate.public_plan(train, select_pairs)
        c.require(len(train["units"]) == 14 and sum(x["status"] == "available" for x in train["units"]) == 13,
                  "original TRAIN pair census changed")
        c.require(len(select_pairs["units"]) == 4 and select_pairs["available_pairs"] == 3,
                  "original SELECT pair census changed")
        _, clean, staging = prepare_materials(Path(original_archive), work / "original")
    c.write_new(output / "materials.json", {"cancelled": old_receipt, "select": sel_receipt,
                                            "original": staging, "cost": material_cost})
    c.write_new(output / "public-feature-plan.json", public)
    public_sha = c.file_sha(output / "public-feature-plan.json")
    encoder_dir = clean / "encoder"
    snap = snapshot(encoder_dir, "encoder", ENCODER_INVENTORY)
    tokenizer = AutoTokenizer.from_pretrained(encoder_dir, local_files_only=True, trust_remote_code=False)
    capacity = min(gate.MAXIMUM_TOKENS, c.load(encoder_dir / "config.json")["max_position_embeddings"])
    preflight = gate.token_preflight(tokenizer, public, capacity)
    c.write_new(output / "token-preflight.json", preflight)
    print("SHARED_GATE_PREFLIGHT", c.canonical({"features": len(preflight["rows"]), "ready": preflight["all_within_cap"]}).decode(), flush=True)
    c.require(preflight["all_within_cap"], "full source exceeds Encoder capacity; no truncation or replacement")
    tail, backend = "0" * 64, None
    with (output / "events.jsonl").open("xb") as journal:
        tail = c.journal_append(journal, {"event": "encoder_load_started", "snapshot_sha256": c.digest(snap)}, tail)
        with measured() as load_cost:
            backend = LocalEncoder(encoder_dir, snap, capacity)
        try:
            tail = c.journal_append(journal, {"event": "encoder_features_started"}, tail)
            with measured() as feature_cost, count_forwards(backend.model) as counter:
                try:
                    features, feature_receipt = gate.encode_once(backend, public, preflight)
                except Exception as error:
                    tail = c.journal_append(journal, {"event": "encoder_features_failed",
                        "error": str(error)[:1024], "observed_encoder_dispatches": counter["model_calls"],
                        "unobserved_tail_unknown": True, "retry_permitted": False}, tail)
                    raise
            c.require(counter["model_calls"] == feature_receipt["completed_encoder_batches"], "actual Encoder dispatch mismatch")
            feature_receipt.update(load_cost=load_cost, feature_cost=feature_cost, actual_encoder_forwards=counter["model_calls"])
            tail = c.journal_append(journal, {"event": "encoder_features_completed", "actual_forwards": counter["model_calls"]}, tail)
            c.write_new(output / "features-receipt.json", feature_receipt)
            # Learned model weights are never needed again by the gate fits.
            backend.close()
            del backend
            backend = None
        finally:
            if backend is not None:
                backend.close()
        feature_before = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
        fit_rows = [v for u in public["units"] if u["split"] == "train" for v in u["variants"]]
        train_q = torch.stack([features[v["question_key"]] for v in fit_rows])
        train_e = torch.stack([features[v["evidence_key"]] for v in fit_rows])
        labels = torch.tensor([1.0 if v["role"] == "matched" else 0.0 for v in fit_rows])
        raw, receipts = {}, {}
        for seed in gate.SEEDS:
            for arm in gate.ARMS:
                name = arm + "-" + str(seed)
                tail = c.journal_append(journal, {"event": "head_fit_started", "name": name}, tail)
                model, fit_receipt = gate.fit(train_q, train_e, labels, arm=arm, seed=seed)
                folder = output / "heads" / name
                folder.mkdir(parents=True)
                weights = {k: v.detach().clone().contiguous() for k, v in model.state_dict().items()}
                save_file(weights, str(folder / "head.safetensors"))
                reloaded = deepcopy(model)
                reloaded.load_state_dict(load_file(str(folder / "head.safetensors")), strict=True)
                c.require(parameters(reloaded) == parameters(model), "Head reload mismatch")
                model = reloaded.eval().requires_grad_(False)
                immutable = parameters(model)
                predictions = []
                with torch.no_grad(), measured() as inference_cost:
                    for unit in public["units"]:
                        row = {"pair_id": unit["pair_id"], "status": "unavailable", "logits": None}
                        if unit["status"] == "available":
                            q = torch.stack([features[v["question_key"]] for v in unit["variants"]])
                            e = torch.stack([features[v["evidence_key"]] for v in unit["variants"]])
                            scores = model(q, e)
                            c.require(bool(torch.isfinite(scores).all()), "nonfinite Head output")
                            row.update(status="succeeded", logits=scores.tolist())
                        predictions.append(row)
                c.require(parameters(model) == immutable, "Head inference changed parameters")
                # Seal logits without computing SELECT-label metrics yet.
                c.write_new(folder / "raw-logits.json", predictions)
                fit_receipt.update(checkpoint_reload_equal=True, inference_cost=inference_cost,
                    checkpoint_file_sha256=c.file_sha(folder / "head.safetensors"),
                    raw_prediction_sha256=c.file_sha(folder / "raw-logits.json"))
                c.write_new(folder / "training-receipt.json", fit_receipt)
                raw[name], receipts[name] = predictions, fit_receipt
                tail = c.journal_append(journal, {"event": "head_predictions_sealed", "name": name,
                    "raw_sha256": fit_receipt["raw_prediction_sha256"], "optimizer_steps": fit_receipt["optimizer_steps"]}, tail)
        c.write_new(output / "raw-logits.json", raw)
        c.write_new(output / "prediction-seal.json", {"sha256": c.file_sha(output / "raw-logits.json"), "before_summary": True})
        c.require(public_sha == c.file_sha(output / "public-feature-plan.json") and
                  feature_before == c.digest({k: tensor_digest(v) for k, v in sorted(features.items())}), "inputs/features changed during Head learning")
        summaries = {name: gate.summarize(public["units"], rows) for name, rows in raw.items()}
    result = {"schema": gate.PROFILE + ".result", "plan_sha256": c.digest(PLAN),
        "public_plan_sha256": public_sha, "raw_sha256": c.file_sha(output / "raw-logits.json"),
        "encoder": feature_receipt, "head_parameters": {k: v["saved_model"] for k, v in receipts.items()},
        "optimizer_updates": sum(v["optimizer_steps"] for v in receipts.values()), "summaries": summaries,
        "errors": [], "new_reader_calls": 0, "new_pretrained_optimizer_updates": 0,
        "sample_independence": "donor_reuse_and_three_seeds_are_not_new_tasks",
        "baseline_semantics": "frozen_zero_logit_and_evidence_only_cannot_distinguish_identical_source_pairs",
        "source_status": "already_exposed_weak_development_not_independent_semantic_review",
        "feature_cache_is_per_run": True, "persistent_service_benchmark": False,
        "compute_matched": False, "semantic_accuracy": None, "Reader_call_skipping_authorized": False,
        "reader_adequacy_established": False, "production_accepted": False, "five_experiments_completed": False}
    c.write_new(output / "report.json", result)
    print("SHARED_QUESTION_GATE_RESULT", c.canonical(result).decode(), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("original-archive", "cancelled-archive", "select-archive", "work", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.original_archive, args.cancelled_archive, args.select_archive, args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048], "completed": False,
                "reader_adequacy_established": False, "production_accepted": False})
        raise
