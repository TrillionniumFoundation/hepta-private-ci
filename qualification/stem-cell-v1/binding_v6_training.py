"""Exactly matched fixed-budget training of V6 arms; V5 trainer remains byte-identical.

Unlike V5's earliest-train-fit schedule, an arm cannot save work by passing a
training-only checkpoint. This permits a fixed-update comparison while metering
actual unequal arithmetic/CPU. Validation/fresh labels are never loaded.
"""
from collections import Counter
import time

import torch

from binding_training import (_digest, _validate_data, _train_copy, _optimizer_step,
                              _optimizer_storage, _finish, _failed, balanced_group_batches,
                              evaluate_reader, world_pairs)
from token_reader_training import parameter_digest


def fit_bridge_fixed_budget(model, data, cases, *, seed, steps, diagnostic_interval=250,
                            wall_time_ns=1_800_000_000_000, failure_receipt_fn=None):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = dict(schema="hepta.binding.bridge-fixed-budget.v6", status="started", seed=seed,
        requested_steps=steps, completed_steps=0, actual_training_exposures=0,
        updates=[], diagnostics=[], optimizer="Adam_foreach_false", learning_rate=.001,
        batch_size=16, depth=3, pair_weight=.5,
        selection_rule="none_fixed_budget", final_evaluation_authorized=False,
        official_validation_evaluated=False, future_scoring_authorized=False)
    try:
        if (type(seed) is not int or not 0 <= seed < 2**32 or type(steps) is not int
                or not 1 <= steps <= 8000 or type(diagnostic_interval) is not int
                or not 1 <= diagnostic_interval <= 1000 or type(wall_time_ns) is not int
                or wall_time_ns <= 0):
            raise ValueError("bounded fixed training schedule required")
        cases = tuple(cases)
        _validate_data(data, cases, model.input_dim)
        batches = balanced_group_batches(cases, updates=steps, batch_size=16, seed=seed)
        receipt.update(case_ids_sha256=_digest([c.case_id for c in cases]),
                       schedule_sha256=_digest(batches),
                       training_targets_sha256=_digest(data.targets.tolist()))
        initial_digest = parameter_digest(model)
        receipt["initial_model_sha256"] = initial_digest
        trained = _train_copy(model)
        optimizer = torch.optim.Adam(trained.parameters(), lr=.001, foreach=False)
        receipt["diagnostics"].append(dict(optimizer_step=0,
            binding=evaluate_reader(trained, data, cases=cases, depth=3)))
        for step, indices in enumerate(batches, 1):
            if time.perf_counter_ns() - wall >= wall_time_ns:
                receipt["status"] = "budget_stopped"
                break
            receipt["attempted_step"] = step
            record = _optimizer_step(trained, optimizer, data, indices, depth=3,
                pair_weight=.5, pairs=world_pairs([cases[i] for i in indices]),
                case_ids=[cases[i].case_id for i in indices])
            record["step"] = step
            receipt["updates"].append(record)
            receipt.update(completed_steps=step, actual_training_exposures=step * 16)
            if step % diagnostic_interval == 0 or step == steps:
                receipt["diagnostics"].append(dict(optimizer_step=step,
                    binding=evaluate_reader(trained, data, cases=cases, depth=3)))
        completed = receipt["completed_steps"]
        if completed == steps:
            receipt["status"] = "fixed_budget_completed"
        receipt["case_exposures"] = dict(Counter(
            cid for row in receipt["updates"] for cid in row["case_ids"]))
        receipt.update(_optimizer_storage(optimizer, trained))
        trained, receipt = _finish(model, trained, data, initial_digest, receipt)
        final = receipt["diagnostics"][-1]["binding"]
        receipt.update(train_gate_passed=(completed == steps and
            final["accuracy"] == 1. and final["both_worlds_correct"] == 1.
            and final["binary_cross_entropy"] <= .1),
            full_budget_completed=completed == steps,
            equal_arithmetic_not_claimed=True, reproducible_schedule=True,
            cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            timing_scope="validation_copy_optimizer_updates_diagnostics_freeze_receipt",
            full_lifecycle_cost_claimed=False)
        return trained, receipt
    except Exception as error:
        _failed(error, receipt, wall, cpu, failure_receipt_fn)
