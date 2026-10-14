"""Execute cosine-preserving residual gates on exact frozen development inputs.

Only missing TRAIN own-evidence vectors may invoke the fixed archived Encoder.
All old question/donor features and every SELECT vector come from authenticated
saved outputs. No Reader, SELECT fit, donor reselection or pretrained update.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import shared_gate_cosine_residual as residual

ORIGINAL_ARTIFACT_SHA = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
CANCELLED_ARTIFACT_SHA = "601cd09ae82cc6915121aaf8bb0eac5c1fe7c8b370c9d4a832bc6e5d54b91bac"


def validate_similarity(root, dependency_receipt, select_inputs):
    import shared_gate_similarity as similarity
    import shared_gate_crossed_evidence as crossed
    root = Path(root); study = root / "study"
    c.require((root / "source/tested-commit.txt").read_text().strip() == residual.ORIGINS["similarity"]["source"]
              and not (study / "failure.json").exists(), "wrong or failed similarity source")
    disposition = c.load(root / "execution-disposition.json")
    report, plan, threshold, raw = [c.load(study / name) for name in
        ("report.json", "plan.json", "train-threshold.json", "raw-logits.json")]
    expected_origins = {k: dependency_receipt["origins"][k] for k in ("heads", "crossed")}
    c.require(disposition.get("analysis_completed") is True
              and report["schema"] == similarity.PROFILE + ".result"
              and report["analysis_completed"] is True and report["errors"] == []
              and report["new_pretrained_model_loads"] == report["new_encoder_forwards"] == 0
              and report["new_reader_calls"] == report["new_optimizer_updates"] == 0
              and report["new_scalar_parameters_fitted"] == 1
              and report["plan_sha256"] == c.digest(plan)
              and report["raw_sha256"] == c.file_sha(study / "raw-logits.json")
              and report["threshold_sha256"] == c.file_sha(study / "train-threshold.json")
              and report["train_calibration"] == threshold
              and c.load(study / "prediction-seal.json") == {"sha256": report["raw_sha256"], "before_summary": True},
              "similarity result/threshold binding failed")
    c.require(plan["schema"] == similarity.PROFILE + ".plan"
              and plan["origins"] == expected_origins
              and set(raw) == {"cosine_zero", "cosine_train_threshold"}
              and threshold["schema"] == similarity.PROFILE + ".train-threshold"
              and threshold["select_access"] is False and threshold["scalar_parameters_fitted"] == 1
              and c.finite(threshold["threshold"], -2.0, 2.0), "unregistered fixed cosine baseline")
    for name, rows in raw.items():
        c.require(crossed.summarize(select_inputs["units"], rows) == report["summaries"][name],
                  "saved cosine readout changed")
    return threshold


def rebuild_train_material(original, clean, cancelled_root):
    """Rebuild all admitted dated TRAIN questions, not the four free-generation rows."""
    from transformers import AutoTokenizer
    import five_reader_evidence_pair_trial as parent
    import five_reader_response_learning as learning
    import five_reader_response_trial as response
    import question_evidence_relevance as relevance
    import source_time_evidence as metadata
    from source_time_evidence_trial import project_examples
    from five_native_historical_smoke import LOCOMO_SHA256
    from native import load

    matches = [p for p in Path(original).rglob("*.json")
               if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact original benchmark missing")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256,
                     allow_unresolved_evidence=True)
    chosen, excluded = parent.choose(benchmark)
    reader = Path(clean) / "reader"
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True, trust_remote_code=False)
    position_cap = c.load(reader / "config.json")["max_position_embeddings"]
    original_train, census = response.training_examples(
        benchmark, chosen["train"], tokenizer, position_cap)
    train, projection = project_examples(
        original_train, chosen["train"], benchmark.history, metadata.SOURCE_TIME)
    forbidden = sorted(set(excluded) | {benchmark.families[q.family] for q in chosen["select"]})
    learning.validate_examples(train, forbidden)
    rebuilt = relevance.build_plan(train, forbidden)
    saved = c.load(Path(cancelled_root) / "study" / "train-plan.json")
    c.require(all(saved.get(k) == v for k, v in rebuilt.items())
              and saved.get("forbidden_families") == forbidden,
              "saved TRAIN relevance plan cannot be reproduced")
    identities = {c.digest(q.identity): q.identity for q in chosen["train"]}
    annotated = {row["question_id"]: row for row in train if row["kind"] == "annotated_answer"}
    c.require(len(annotated) == len(rebuilt["units"]) and set(annotated) == set(identities),
              "complete admitted TRAIN own-source census required")
    own_inputs = [{"question_id": identities[qid], "family": row["family"],
                   "split": "train", "condition": "own_sources",
                   "request": deepcopy(row["request"])}
                  for qid, row in sorted(annotated.items())]
    return saved, own_inputs, {"training_census": census, "projection": projection,
        "chosen_train": [q.identity for q in chosen["train"]],
        "chosen_select": [q.identity for q in chosen["select"]],
        "forbidden_families": forbidden, "train_examples_sha256": c.digest(train),
        "own_inputs_sha256": c.digest(own_inputs)}


def encode_additional(folder, snapshot, specs, expected_encoder, maximum_tokens):
    """Encode only new TRAIN own-evidence components, with explicit paid cost."""
    import torch
    from torch.nn import functional as F
    from transformers import AutoTokenizer
    import shared_question_gate as gate
    from five_causal_native import count_forwards
    from experiments.shared_stem_cell.execution import LocalEncoder, measured, parameters

    c.require(isinstance(specs, list), "additional feature list required")
    if not specs:
        return {}, {"actual_encoder_forwards": 0, "unique_features": 0,
                    "pretrained_model_loaded": False, "cost": None}, None
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True, trust_remote_code=False)
    preflight = gate.token_preflight(tokenizer, {"features": specs}, maximum_tokens)
    c.require(preflight["all_within_cap"], "TRAIN own evidence exceeds Encoder capacity; no truncation")
    backend = None
    values, batches = {}, []
    try:
        with measured() as total_cost:
            backend = LocalEncoder(folder, snapshot, maximum_tokens)
            before = parameters(backend.loaded)
            c.require(before == expected_encoder, "different Encoder supplied missing TRAIN features")
            groups = defaultdict(list)
            tokens = {row["key"]: row for row in preflight["rows"]}
            for spec in specs:
                c.require(set(spec) == {"key", "scope", "text"}
                          and spec["key"] == c.digest([gate.REPRESENTATION, spec["scope"], spec["text"]])
                          and spec["key"] in tokens, "additional feature identity changed")
                ids = backend.tokenizer(spec["text"], truncation=False,
                                        add_special_tokens=True)["input_ids"]
                c.require(c.digest(ids) == tokens[spec["key"]]["token_sha256"],
                          "additional tokenizer drift")
                groups[tuple(spec["scope"])].append(spec)
            with count_forwards(backend.model) as counter:
                for scope in sorted(groups):
                    rows = groups[scope]
                    batch_size = min(32, 32768 // maximum_tokens)
                    for start in range(0, len(rows), batch_size):
                        selected = rows[start:start + batch_size]
                        with measured() as cost:
                            encoded = backend.encode([x["text"] for x in selected])
                        c.require(encoded.ndim == 2 and encoded.shape[0] == len(selected)
                                  and encoded.dtype == torch.float32 and encoded.device.type == "cpu"
                                  and bool(torch.isfinite(encoded).all())
                                  and bool((encoded.norm(dim=1) > 0).all()),
                                  "invalid additional Encoder result")
                        with torch.inference_mode(False):
                            normalized = F.normalize(encoded.detach().clone(), p=2, dim=1)
                        for spec, value in zip(selected, normalized):
                            values[spec["key"]] = value.clone().contiguous()
                        batches.append({"scope": list(scope), "keys": [x["key"] for x in selected],
                                        "returned_tensor_bytes": encoded.numel() * encoded.element_size(),
                                        "cost": cost})
            c.require(before == parameters(backend.loaded), "additional encoding changed Encoder")
            backend.close(); backend = None
            return values, {"actual_encoder_forwards": counter["model_calls"],
                            "unique_features": len(values), "pretrained_model_loaded": True,
                            "batches": batches, "encoder": before, "cost": total_cost}, preflight
    finally:
        if backend is not None:
            backend.close()


def run(head_archive, cross_archive, similarity_archive, original_archive, cancelled_archive,
        dependency_receipt, work, output):
    import torch
    from safetensors.torch import load_file, save_file
    import relevance_recovery as recovery
    import shared_gate_similarity as similarity
    import shared_gate_similarity_trial as similarity_trial
    import shared_question_gate as gate
    from shared_gate_crossed_trial import validate_saved
    from reader_content_swap_trial import extract_verified
    from five_native_historical_smoke import prepare_materials, snapshot, ENCODER_INVENTORY
    from experiments.shared_stem_cell.execution import measured, parameters, tensor_digest

    c.require(dependency_receipt.get("schema") == residual.PROFILE + ".dependency"
              and dependency_receipt.get("ready") is True
              and set(dependency_receipt.get("origins", {})) == set(residual.ORIGINS),
              "three exact successful residual origins required")
    origins = dependency_receipt["origins"]
    for role, expected in residual.ORIGINS.items():
        c.require(all(origins[role].get(k) == v for k, v in expected.items())
                  and origins[role].get("ready") is True
                  and origins[role].get("observed_status") == "completed"
                  and origins[role].get("observed_conclusion") == "success"
                  and c.sha(origins[role].get("artifact_sha256")),
                  "wrong residual artifact pin")
    work, output = Path(work), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    config = {"schema": residual.PROFILE + ".plan", "origins": origins,
              "arms": list(residual.ARMS), "seeds": list(residual.SEEDS),
              "steps": residual.STEPS, "learning_rate": residual.LEARNING_RATE,
              "rank": residual.RANK, "base": "saved_fp64_cosine_minus_saved_TRAIN_threshold",
              "residual": "zero_initialized_pure_question_evidence_interaction",
              "training_profiles": {"one_way_residual": "repeat_BB_AB_to_four_rows",
                                    "rectangle_residual": "AA1_AB0_BA0_BB1",
                                    "rectangle_reversed": "AA0_AB1_BA1_BB0"},
              "select_fit": False, "new_donor_selection": False,
              "semantic_accuracy": None, "production_accepted": False}
    c.write_new(output / "plan.json", config)
    with measured() as acquisition:
        hr, hv = extract_verified(Path(head_archive), work / "heads",
                                  origins["heads"]["artifact_sha256"])
        xr, xv = extract_verified(Path(cross_archive), work / "crossed",
                                  origins["crossed"]["artifact_sha256"])
        sr, sv = extract_verified(Path(similarity_archive), work / "similarity",
                                  origins["similarity"]["artifact_sha256"])
        cr, cv = extract_verified(Path(cancelled_archive), work / "cancelled",
                                  CANCELLED_ARTIFACT_SHA)
        c.require((cr / "source/tested-commit.txt").read_text().strip() == recovery.CANCELLED_SOURCE,
                  "wrong fixed cancelled TRAIN source")
        original, clean, staging = prepare_materials(Path(original_archive), work / "original")
    names = {a + "-" + str(seed) for a in gate.ARMS for seed in gate.SEEDS}
    _, _, public, _ = validate_saved(hr)
    crossed_study, select_inputs, _, encoder_receipt = similarity_trial.validate_crossed(
        xr, public, origins["heads"]["artifact_sha256"], names)
    threshold_receipt = validate_similarity(sr, dependency_receipt, select_inputs)
    threshold = threshold_receipt["threshold"]
    saved_train, own_inputs, rebuild_receipt = rebuild_train_material(original, clean, cr)
    train_inputs = residual.build_train_rectangles(public, saved_train, own_inputs)
    c.write_new(output / "train-rectangles.json", train_inputs)
    c.write_new(output / "train-rebuild.json", rebuild_receipt)
    features = load_file(str(crossed_study / "frozen-features.safetensors"), device="cpu")
    existing_specs = list(public["features"]) + list(select_inputs["additional_features"])
    c.require(set(features) == {x["key"] for x in existing_specs}, "crossed cache census changed")
    old_identity = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
    c.require(old_identity == encoder_receipt["feature_tensor_sha256"],
              "crossed cache tensor digest changed")
    encoder_folder = clean / "encoder"
    snap = snapshot(encoder_folder, "encoder", ENCODER_INVENTORY)
    capacity = min(gate.MAXIMUM_TOKENS,
                   c.load(encoder_folder / "config.json")["max_position_embeddings"])
    expected_encoder = encoder_receipt["original_recomputation"]["encoder"]
    additional, additional_receipt, preflight = encode_additional(
        encoder_folder, snap, train_inputs["additional_features"], expected_encoder, capacity)
    c.require(not set(additional) & set(features), "additional TRAIN feature overwrites crossed cache")
    features.update(additional)
    feature_identity = c.digest({k: tensor_digest(v) for k, v in sorted(features.items())})
    save_file(features, str(output / "frozen-features.safetensors"))
    c.write_new(output / "feature-receipt.json", {"old_crossed_tensor_sha256": old_identity,
        "combined_tensor_sha256": feature_identity,
        "combined_file_sha256": c.file_sha(output / "frozen-features.safetensors"),
        "old_feature_count": len(existing_specs), "additional": additional_receipt,
        "preflight": preflight, "acquisition_cost": acquisition,
        "original": staging, "heads": hv, "crossed": xv, "similarity": sv, "cancelled": cv})
    raw, receipts, summaries = {}, {}, {}
    tail = "0" * 64
    with (output / "events.jsonl").open("xb") as journal:
        baseline_train = residual.predict(train_inputs["units"], features, threshold)
        baseline_select = residual.predict(select_inputs["units"], features, threshold)
        raw["cosine_frozen"] = {"train": baseline_train, "select": baseline_select}
        summaries["cosine_frozen"] = {
            "train": residual.summarize(train_inputs["units"], baseline_train),
            "select": residual.summarize(select_inputs["units"], baseline_select)}
        tail = c.journal_append(journal, {"event": "baseline_predictions_sealed",
            "train_sha256": c.digest(baseline_train), "select_sha256": c.digest(baseline_select)}, tail)
        for seed in residual.SEEDS:
            for arm in residual.TRAINABLE_ARMS:
                name = arm + "-" + str(seed)
                tail = c.journal_append(journal, {"event": "residual_fit_started", "name": name}, tail)
                model, receipt = residual.fit(train_inputs["units"], features, threshold,
                                              arm=arm, seed=seed)
                folder_out = output / "heads" / name
                folder_out.mkdir(parents=True)
                save_file({k: v.detach().clone().contiguous()
                           for k, v in model.state_dict().items()},
                          str(folder_out / "head.safetensors"))
                reloaded = residual.ResidualGate(next(iter(features.values())).numel())
                reloaded.load_state_dict(load_file(str(folder_out / "head.safetensors")), strict=True)
                reloaded.eval().requires_grad_(False)
                c.require(parameters(reloaded) == parameters(model), "residual checkpoint reload mismatch")
                train_raw = residual.predict(train_inputs["units"], features, threshold, reloaded)
                select_raw = residual.predict(select_inputs["units"], features, threshold, reloaded)
                raw[name] = {"train": train_raw, "select": select_raw}
                summaries[name] = {
                    "train": residual.summarize(train_inputs["units"], train_raw),
                    "select": residual.summarize(select_inputs["units"], select_raw)}
                c.write_new(folder_out / "raw.json", raw[name])
                receipt.update(checkpoint_reload_equal=True,
                               checkpoint_file_sha256=c.file_sha(folder_out / "head.safetensors"),
                               raw_prediction_sha256=c.file_sha(folder_out / "raw.json"))
                c.write_new(folder_out / "training-receipt.json", receipt)
                receipts[name] = receipt
                tail = c.journal_append(journal, {"event": "residual_predictions_sealed",
                    "name": name, "raw_sha256": receipt["raw_prediction_sha256"],
                    "optimizer_steps": receipt["optimizer_steps"]}, tail)
    c.write_new(output / "raw-logits.json", raw)
    c.write_new(output / "prediction-seal.json",
                {"sha256": c.file_sha(output / "raw-logits.json"), "before_summary": True})
    baseline_flags = similarity_trial.flags(select_inputs["units"], baseline_select)
    comparisons = {name: similarity.compare_flags(
                    select_inputs["units"],
                    similarity_trial.flags(select_inputs["units"], rows["select"]),
                    baseline_flags)
                   for name, rows in raw.items() if name != "cosine_frozen"}
    c.require(feature_identity == c.digest({k: tensor_digest(v) for k, v in sorted(features.items())}),
              "residual study modified frozen features")
    report = {"schema": residual.PROFILE + ".result", "errors": [],
              "plan_sha256": c.digest(config), "raw_sha256": c.file_sha(output / "raw-logits.json"),
              "fixed_threshold": threshold,
              "fixed_threshold_receipt_sha256": c.digest(threshold_receipt),
              "summaries": summaries, "paired_against_cosine_frozen": comparisons,
              "head_parameters": {k: v["saved_model"] for k, v in receipts.items()},
              "new_head_optimizer_updates": sum(v["optimizer_steps"] for v in receipts.values()),
              "new_pretrained_model_loads": int(additional_receipt["pretrained_model_loaded"]),
              "new_encoder_forwards": additional_receipt["actual_encoder_forwards"],
              "new_reader_calls": 0, "new_donor_selection": False, "select_fit": False,
              "sample_independence": "same_exposed_pairs_and_three_seeds_are_not_new_tasks",
              "compute_matched": False, "semantic_accuracy": None,
              "reader_call_skipping_authorized": False, "reader_adequacy_established": False,
              "production_accepted": False, "five_experiments_completed": False}
    c.write_new(output / "report.json", report)
    print("COSINE_RESIDUAL_GATE_RESULT", c.canonical(report).decode(), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dependency", "run"))
    for name in ("head-run-json", "head-artifacts-json", "cross-run-json", "cross-artifacts-json",
                 "similarity-run-json", "similarity-artifacts-json", "head-archive", "cross-archive",
                 "similarity-archive", "original-archive", "cancelled-archive", "dependency-json", "work"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "dependency":
        paths = (args.head_run_json, args.head_artifacts_json, args.cross_run_json,
                 args.cross_artifacts_json, args.similarity_run_json, args.similarity_artifacts_json)
        c.require(all(p is not None for p in paths), "six authenticated metadata files required")
        result = residual.dependency(*(c.load(p) for p in paths))
        c.write_new(args.output, result)
        print(c.canonical(result).decode(), flush=True)
        return 0 if result["ready"] else 3
    required = (args.head_archive, args.cross_archive, args.similarity_archive,
                args.original_archive, args.cancelled_archive, args.dependency_json, args.work)
    c.require(all(p is not None for p in required), "residual artifacts/dependency/work required")
    try:
        run(args.head_archive, args.cross_archive, args.similarity_archive,
            args.original_archive, args.cancelled_archive,
            c.load(args.dependency_json), args.work, args.output)
    except Exception as error:
        if args.output.is_dir() and not (args.output / "failure.json").exists():
            c.write_new(args.output / "failure.json", {"error": str(error)[:2048],
                "model_execution_completed": False, "production_accepted": False})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
