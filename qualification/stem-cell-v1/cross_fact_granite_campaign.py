"""Actual pinned Granite97 V5 token-bank / equal-parameter Reader training entrypoint.

Reuses the V5 original-byte input, cache, artifact and source guards. Does not
read official validation or evaluate fresh synthetic cohorts unless *all* six
matched arms pass the original train-only full-fit gate. Creates receipts but
never deploys a model or changes an existing Neuron/NDU authority owner.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

SEEDS = (41, 47, 53)
ARMS = ("cross_fact", "local")
TRAIN_STEPS = 8000


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def _write_once(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def full_fit_gate(rows):
    """Require complete registered seed/arm matrix; no failed arm may vanish."""
    if not isinstance(rows, dict) or set(rows) != {str(s) for s in SEEDS}:
        return False
    for seed in SEEDS:
        arms = rows[str(seed)]
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            return False
        for name in ARMS:
            row = arms[name]
            if not isinstance(row, dict) or row.get("train_gate_passed") is not True:
                return False
            if (row.get("status") != "train_gate_passed"
                    or row.get("completed_steps", 0) > TRAIN_STEPS
                    or row.get("completed_steps", 0) < 1
                    or not isinstance(row.get("model_file_sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", row["model_file_sha256"]) is None):
                return False
    return True


def matching_training_budgets(rows):
    """Equal *actual* optimizer updates and examples, separate from planned."""
    if not isinstance(rows, dict) or set(rows) != {str(s) for s in SEEDS}:
        return False
    for seed in SEEDS:
        arms = rows[str(seed)]
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            return False
        a, b = (arms[name] for name in ARMS)
        if not all(isinstance(v, dict) for v in (a, b)):
            return False
        for row in (a, b):
            if (type(row.get("completed_steps")) is not int
                    or not 1 <= row["completed_steps"] <= TRAIN_STEPS
                    or type(row.get("actual_training_exposures")) is not int
                    or row["actual_training_exposures"] != row["completed_steps"] * 16
                    or type(row.get("optimizer_tensor_bytes")) is not int
                    or row["optimizer_tensor_bytes"] <= 0
                    or type(row.get("parameter_count")) is not int
                    or row["parameter_count"] <= 0
                    or not isinstance(row.get("schedule_sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", row["schedule_sha256"]) is None):
                return False
        if any(a.get(key) != b.get(key) for key in
               ("completed_steps", "actual_training_exposures", "schedule_sha256",
                "optimizer_tensor_bytes", "parameter_count")):
            return False
    return True


def matched_fresh_gate(rows):
    """Both real full fits and equal *observed training investment* required.

    This does not assert FLOP parity: masked attention and local MLP have
    different actual arithmetic even with identical parameters and updates.
    """
    return full_fit_gate(rows) and matching_training_budgets(rows)


def campaign(args):
    import torch
    from binding_campaign_utils import checked_design, load_bank, natural_panel, save_model, source_inventory
    from binding_training import fit_binding_reader
    from cross_fact_bridge import matched_reader_pair
    from group_encoder import file_digest
    from token_campaign_utils import infer
    from token_reader_training import parameter_digest

    # Never mutate source or prior V5 outputs. New artifacts belong outside git.
    output = args.output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if output == repository or repository in output.parents:
        raise ValueError("evidence/checkpoint output must remain outside the repository")
    if args.steps != TRAIN_STEPS or args.seed not in ("all", "41", "47", "53"):
        raise ValueError("frozen 8000-update schedule and known seed required")
    output.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    status = {"schema": "hepta.cross-fact.granite-v5.v1", "status": "started",
              "production_authorized": False, "official_validation_accessed": False,
              "fresh_scoring_authorized": False, "independent_real_effectiveness": False}
    try:
        torch.set_num_threads(1)
        # The original complete input checks freeze earlier V4 and V5 decisions.
        original_args = argparse.Namespace(**vars(args))
        original_args.output = args.output_v5
        _original_design, parts, natural = checked_design(original_args)
        source_inventory_bytes = source_inventory()
        bank = load_bank(original_args)
        cases = tuple(parts["reader_train"])
        data = bank.batch(cases)
        data.validate(384)
        seeds = SEEDS if args.seed == "all" else (int(args.seed),)
        source_dir = Path(__file__).parent
        code_hashes = {name: file_digest(source_dir / name) for name in
                       ("cross_fact_bridge.py", "cross_fact_granite_campaign.py",
                        "cross_fact_granite_receipt_oracle.py")}
        plan = {"schema": "hepta.cross-fact.granite-v5.plan.v1", "seeds": list(seeds),
                "registered_complete_seeds": list(SEEDS), "arms": list(ARMS),
                "model_input_width": 384, "hidden_width": 32,
                "extra_parameters_per_arm": 4096,
                "steps": TRAIN_STEPS, "batch_size": 16, "depth": 3,
                "learning_rate": .001, "pair_weight": .5,
                "diagnostic_interval": 250,
                "full_fit_required_for_all_arms_before_fresh": True,
                "normalization_and_encoder_reused_from_original_v5": True,
                "original_design_sha256": file_digest(args.output_v5 / "design.json"),
                "original_runtime_source_sha256": source_inventory_bytes,
                "pretrained_snapshot_sha256": file_digest(args.snapshot / "material.json"),
                "original_token_cache_sha256": file_digest(args.prepared / "features" / "metadata.json"),
                "train_case_ids_sha256": hashlib.sha256(json.dumps(
                    [case.case_id for case in cases], separators=(",", ":")).encode()).hexdigest(),
                "fresh_case_roster_sha256": {
                    role: hashlib.sha256(json.dumps([case.case_id for case in parts[role]],
                        separators=(",", ":")).encode()).hexdigest()
                    for role in ("fresh_combinations", "fresh_vocabulary")},
                "source_groups": len(set(case.source_hash for case in cases)),
                "new_code_sha256": code_hashes,
                "source_disjoint_fresh_evaluation_only_after_global_fit": True,
                "equal_parameter_budget": True,
                "equal_total_compute_predeclared": False,
                "external_result_was_used_for_selection": False,
                "production_authorized": False}
        _write_once(output / "plan.json", plan)
        status["input_checks_passed"] = True
        _write_once(output / "preflight.json", status)
        summaries = {}
        model_map = {}
        for seed in seeds:
            folder = output / f"seed-{seed}"
            folder.mkdir()
            cross, local = matched_reader_pair(384, 32, seed=seed)
            if sum(p.numel() for p in cross.parameters()) != sum(p.numel() for p in local.parameters()):
                raise RuntimeError("unequal model parameter budgets")
            baseline = parameter_digest(cross)
            for arm, original in zip(ARMS, (cross, local)):
                original.eval().requires_grad_(False)
                trained, receipt = fit_binding_reader(original, data, cases,
                    steps=TRAIN_STEPS, seed=seed, batch_size=16, depth=3,
                    learning_rate=.001, pair_weight=.5, diagnostic_interval=250,
                    wall_time_ns=1_800_000_000_000,
                    failure_receipt_fn=lambda failure, a=arm: _write_once(folder / f"{a}-failed.json", failure))
                if receipt["initial_model_sha256"] != baseline:
                    raise RuntimeError("original initialization drift")
                record = save_model(folder, arm, trained, receipt)
                # Same previously exposed TRAIN-source internal-tune questions,
                # never a fresh holdout or selection signal. Meter it anyway.
                natural_metrics = natural_panel(folder, f"{arm}-natural-internal",
                                                trained, natural["tune"], bank)
                natural_file = folder / f"{arm}-natural-internal.json"
                summary = {"status": receipt["status"], "train_gate_passed": receipt["train_gate_passed"],
                           "completed_steps": receipt["completed_steps"],
                           "actual_training_exposures": receipt["actual_training_exposures"],
                           "schedule_sha256": receipt["schedule_sha256"],
                           "original_parameter_digest": receipt["initial_model_sha256"],
                           "trained_parameter_digest": receipt["model_sha256"],
                           "model_file_sha256": record["file_sha256"],
                           "optimizer_tensor_bytes": receipt["optimizer_tensor_bytes"],
                           "parameter_count": receipt["parameter_count"],
                           "training_cpu_ns": receipt["cpu_ns"], "training_wall_ns": receipt["wall_ns"],
                           "training_receipt_file": f"{arm}-training.json",
                           "loss_last": receipt["diagnostics"][-1]["binding"],
                           "natural_internal_tune": natural_metrics,
                           "natural_internal_file_sha256": file_digest(natural_file),
                           "old_task_internal_not_selection": True,
                           "fresh_evaluation_executed": False}
                summaries.setdefault(str(seed), {})[arm] = summary
                model_map[(seed, arm)] = trained
                _write_once(output / f"summary-{seed}-{arm}.json", summary)
                print(json.dumps({"seed": seed, "arm": arm, "train_gate": summary["train_gate_passed"],
                                  "steps": summary["completed_steps"]}), flush=True)
        _write_once(output / "fit-summary.json", summaries)
        fits_passed = full_fit_gate(summaries)
        budgets_equal = matching_training_budgets(summaries)
        allowed = matched_fresh_gate(summaries)
        decision = {"all_model_fit_gates_passed": fits_passed,
                    "all_actual_training_budgets_equal": budgets_equal,
                    "matched_fresh_gate_passed": allowed,
                    "original_v5_source_protocol_sha256": file_digest(args.output_v5 / "design.json"),
                    "training_only_gate": True,
                    "no_pretrained_superiority_claim": True}
        # Explicit no-data path: V5 does not promote a failed fit by reading TEST.
        _write_once(output / "opening-decision.json", decision)
        if not allowed:
            status["status"] = ("train_gate_failed_no_fresh_scoring" if not fits_passed
                                else "unequal_actual_budgets_no_fresh_scoring")
            return status
        # Freeze every model *before* fresh feature generation, then run all arms.
        frozen = {str(seed): {name: summaries[str(seed)][name]["model_file_sha256"]
                              for name in ARMS} for seed in SEEDS}
        _write_once(output / "all-models-frozen.json", frozen)
        fresh = tuple(parts["fresh_combinations"]) + tuple(parts["fresh_vocabulary"])
        bank.register(fresh)
        for role in ("fresh_combinations", "fresh_vocabulary"):
            cohort = parts[role]
            for seed in SEEDS:
                for arm in ARMS:
                    model = model_map[(seed, arm)]
                    probs, batch_receipts = infer(model, cohort, bank, depth=3,
                        batch_size=16, prefix=f"{role}/{seed}/{arm}")
                    prediction_path = output / f"sealed-{role}-{seed}-{arm}.json"
                    _write_once(prediction_path, {"case_ids": [case.case_id for case in cohort],
                        "probabilities": probs, "batches": batch_receipts,
                        "weights_sha256": frozen[str(seed)][arm],
                        "labels_entered_model": False, "scoring_started": False})
        # The separately invoked scorer reconstructs labels from the original
        # protocol only AFTER all 12 raw prediction seals exist on disk.
        status["status"] = "all_frozen_predictions_sealed_pending_independent_scoring"
        status["fresh_prediction_seals_complete"] = True
        status["fresh_scoring_authorized"] = False
        return status
    except Exception as exc:
        status["status"] = "failed"
        status["error_type"] = type(exc).__name__
        status["error"] = str(exc)
        raise
    finally:
        status["cpu_ns"] = time.process_time_ns() - start_cpu
        status["wall_ns"] = time.perf_counter_ns() - start_wall
        _write_once(output / "terminal.json", status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "snapshot", "prepared", "previous_main", "previous_native",
                 "output_v5", "output"):
        parser.add_argument("--" + name.replace("_", "-"), required=True, type=Path, dest=name)
    parser.add_argument("--steps", type=int, default=TRAIN_STEPS)
    parser.add_argument("--seed", default="all", choices=("all", "41", "47", "53"))
    campaign(parser.parse_args())


if __name__ == "__main__":
    main()
