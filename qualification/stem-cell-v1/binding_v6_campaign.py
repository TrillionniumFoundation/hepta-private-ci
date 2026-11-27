"""P0 Bridge V6: physically fit three equal-parameter Reader arms on V5 frozen features.

This is a diagnostic TRAIN-only comparison, not a V5 release gate or a model
selection.  It never reads official validation, prospective labels, or raw
fresh-domain labels.  The V5 source/feature fingerprint is checked before use.
"""
import argparse
from collections import OrderedDict
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import (checked_design, load_bank, phase_cost, write,
                                   save_model, source_inventory)
from binding_training import BindingTrainingFailure, evaluate_reader
from binding_v6_training import fit_bridge_fixed_budget
from binding_v6_bridge import ARMS, equal_parameter_arms
from group_encoder import file_digest
from token_reader_training import parameter_digest

SEEDS = (41, 47, 53)
PROTOCOL = "hepta.binding.cross-fact-bridge.v6"


def _check_budget(*, updates, diagnostic_interval, batch_size):
    if (type(updates) is not int or not 1 <= updates <= 8000
            or type(diagnostic_interval) is not int or not 1 <= diagnostic_interval <= 1000
            or type(batch_size) is not int or batch_size != 16):
        raise ValueError("registered bounded training schedule required")


def run(args):
    """Write first a frozen protocol; never rank/select a model using TEST."""
    _check_budget(updates=args.updates, diagnostic_interval=args.diagnostic_interval,
                  batch_size=args.batch_size)
    if args.seeds not in (SEEDS, (41,), (47,), (53,)):
        raise ValueError("only predeclared three seeds or one-seed diagnostics allowed")
    if args.output.exists():
        raise ValueError("no overwrite: immutable V6 result directory required")
    # V5 own directory is read-only, and its exact source inventory is checked.
    original_output = args.output
    args = argparse.Namespace(**{**vars(args), "output": args.v5_output})
    v5_design, parts, _ = checked_design(args)
    if tuple(v5_design["seeds"]) != SEEDS or v5_design["warmup"]["depth"] != 3:
        raise ValueError("wrong V5 pinned model/training protocol")
    bank = load_bank(args)
    train_cases = tuple(parts["reader_train"])
    train = bank.batch(train_cases)
    train.validate(384)
    if len(train_cases) != 128 or len({c.case_id for c in train_cases}) != 128:
        raise ValueError("expected genuine V5 complete 32-group training set")
    started = time.perf_counter_ns(), time.process_time_ns()
    protocol = dict(schema=PROTOCOL, experiment_scope="train_only_diagnostic",
        ancestor_v5_design_sha256=file_digest(args.v5_output / "design.json"),
        source_inventory=source_inventory(),
        initial_architecture="TokenReader(384,32)+four_32x32_no_bias_matrices",
        arms=list(ARMS), seeds=list(args.seeds), updates=args.updates,
        diagnostic_interval=args.diagnostic_interval, batch_size=args.batch_size,
        depth=3, learning_rate=0.001, paired_world_loss_weight=0.5,
        full_profile=args.updates == 8000 and args.diagnostic_interval == 250 and args.seeds == SEEDS,
        feature_source="frozen_Granite97_V5_original_cached_tokens",
        training_control="identical_initial_weights_and_complete_group_schedule",
        model_selection_authorized=False, native_ndu_integrated=False,
        official_validation_scored=False, fresh_source_scored=False,
        production_authorized=False)
    output = original_output
    output.mkdir(parents=True, exist_ok=False)
    write(output, "protocol.json", protocol)
    outcomes = OrderedDict()
    for seed in args.seeds:
        models = equal_parameter_arms(seed=seed)
        initial = {arm: parameter_digest(model) for arm, model in models.items()}
        if len(set(initial.values())) != 1:
            raise ValueError("initial model weights differ across registered arms")
        summary = {}
        seed_dir = output / f"seed-{seed}"
        seed_dir.mkdir()
        for arm, model in models.items():
            try:
                trained, receipt = fit_bridge_fixed_budget(model, train, train_cases,
                    steps=args.updates, seed=seed,
                    diagnostic_interval=args.diagnostic_interval,
                    wall_time_ns=1_800_000_000_000,
                    failure_receipt_fn=lambda rec, a=arm: write(seed_dir, f"{a}-failure.json", rec))
                if receipt["initial_model_sha256"] != initial[arm]:
                    raise RuntimeError("trained arm does not bind original initialization")
                metrics = evaluate_reader(trained, train, cases=train_cases, depth=3)
                receipt.update(arm=arm, training_only_bridge_v6=True,
                    full128_fit_gate_passed=bool(receipt["train_gate_passed"]),
                    future_scoring_authorized=False)
                save_model(seed_dir, arm, trained, receipt)
                write(seed_dir, f"{arm}-train.json", dict(
                    metrics=metrics, case_ids=[c.case_id for c in train_cases],
                    targets=train.targets.tolist(), source_groups=list(train.source_groups),
                    model_sha256=parameter_digest(trained),
                    labels_entered_inference=False,
                    feature_tensors_per_forward=6, scope="train_only_no_fresh_selection"))
                summary[arm] = dict(status=receipt["status"],
                    model_sha256=parameter_digest(trained),
                    initial_sha256=initial[arm],
                    gate_passed=bool(receipt["train_gate_passed"]),
                    full_budget_completed=bool(receipt["full_budget_completed"]),
                    correct=int(round(metrics["accuracy"] * len(train_cases))),
                    accuracy=metrics["accuracy"],
                    paired_both=metrics["both_worlds_correct"],
                    cpu_ns=receipt["cpu_ns"], wall_ns=receipt["wall_ns"],
                    completed_updates=receipt["completed_steps"],
                    schedule_sha256=receipt["schedule_sha256"],
                    actual_training_exposures=receipt["actual_training_exposures"],
                    parameter_count=receipt["parameter_count"],
                    optimizer_tensor_bytes=receipt["optimizer_tensor_bytes"],
                    initial_parameter_bytes=receipt["parameter_bytes"],
                    training_receipt_sha256=file_digest(seed_dir / f"{arm}-training.json"),
                    score_file_sha256=file_digest(seed_dir / f"{arm}-train.json"))
            except BindingTrainingFailure as error:
                summary[arm] = dict(status="failed", gate_passed=False,
                    failure_receipt_sha256=file_digest(seed_dir / f"{arm}-failure.json")
                    if (seed_dir / f"{arm}-failure.json").exists() else None,
                    completed_updates=error.receipt.get("completed_steps", 0),
                    cpu_ns=error.receipt.get("cpu_ns"),
                    wall_ns=error.receipt.get("wall_ns"))
            # Do not automatically restart a failed arm with new hyperparameters.
        outcomes[str(seed)] = summary
        write(output, f"seed-{seed}-result.json", summary)
    write(output, "result.json", dict(schema=PROTOCOL, protocol_sha256=file_digest(output / "protocol.json"),
        source_inventory=source_inventory(), ancestors_unchanged=True,
        outcomes=outcomes, cost=phase_cost(started),
        model_selection_authorized=False, fresh_scoring_authorized=False,
        complete_full_profile=protocol["full_profile"] and all(
            arm in arms and arms[arm].get("status") == "fixed_budget_completed"
            and arms[arm].get("full_budget_completed") is True
            and arms[arm].get("completed_updates") == args.updates
            for arms in outcomes.values() for arm in ARMS),
        production_authorized=False))
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "snapshot", "prepared", "previous-main", "previous-native", "v5-output", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--updates", type=int, default=8000)
    parser.add_argument("--diagnostic-interval", type=int, default=250)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    args = parser.parse_args()
    args.seeds = tuple(args.seeds)
    torch.set_num_threads(1)
    run(args)


if __name__ == "__main__":
    main()
