"""Matched natural minibatches and paired replay from one frozen fitting checkpoint."""
from collections import Counter
import random
import time
from types import SimpleNamespace

import torch

from binding_training import (_digest, _failed, _finish, _optimizer_step, _optimizer_storage, _train_copy,
    _validate_data, balanced_group_batches, evaluate_reader, world_pairs)
from token_reader_training import parameter_digest


ARMS = ("natural_only", "replay", "contrastive")


def continuation_plan(natural_cases, binding_cases, *, seed, updates=500, batch_size=16):
    """Freeze case order, labels and both minibatch streams before continuation."""
    natural_cases, binding_cases = tuple(natural_cases), tuple(binding_cases)
    if (type(seed) is not int or type(updates) is not int or not 1 <= updates <= 10000
            or type(batch_size) is not int or not 1 <= batch_size <= len(natural_cases)
            or len({case.case_id for case in natural_cases}) != len(natural_cases)
            or any(case.source_split != "train" for case in natural_cases + binding_cases)
            or set(case.source_hash for case in natural_cases) & set(case.source_hash for case in binding_cases)):
        raise ValueError("bounded, disjoint, complete train-only continuation sources required")
    rng = random.Random(f"hepta-binding-natural-v5/{seed}")
    plan = dict(schema="hepta.binding.continuation-plan.v1", seed=seed, updates=updates,
        batch_size=batch_size, logical_update_order=["natural", "binding"],
        natural_batches=[rng.sample(range(len(natural_cases)), batch_size) for _ in range(updates)],
        binding_batches=balanced_group_batches(binding_cases, updates=updates, batch_size=batch_size, seed=seed))
    for prefix, cases in (("natural", natural_cases), ("binding", binding_cases)):
        plan[prefix + "_case_ids"] = [case.case_id for case in cases]
        plan[prefix + "_targets"] = [case.label for case in cases]
        plan[prefix + "_source_groups"] = [case.source_hash for case in cases]
    plan["plan_sha256"] = _digest(plan)
    return plan


def validate_continuation_plan(plan, natural_data, binding_data, binding_cases, input_dim, *, natural_cases=None):
    """Reject any changed row, label, source binding or sampled sequence."""
    if plan.get("schema") != "hepta.binding.continuation-plan.v1" or plan.get("plan_sha256") != _digest(
            {key: value for key, value in plan.items() if key != "plan_sha256"}):
        raise ValueError("continuation plan digest changed")
    natural_data.validate(input_dim)
    natural_cases = getattr(natural_data, "cases", None) if natural_cases is None else natural_cases
    if natural_cases is not None and [case.case_id for case in natural_cases] != plan["natural_case_ids"]:
        raise ValueError("natural case identity differs from continuation plan")
    _validate_data(binding_data, binding_cases, input_dim)
    for prefix, data in (("natural", natural_data), ("binding", binding_data)):
        if (data.targets.tolist() != plan[prefix + "_targets"]
                or list(data.source_groups) != plan[prefix + "_source_groups"]
                or len(plan[prefix + "_case_ids"]) != len(data.targets)):
            raise ValueError("continuation data differs from frozen plan row bindings")
        batches = plan[prefix + "_batches"]
        if (len(batches) != plan["updates"] or any(len(batch) != plan["batch_size"]
                or len(set(batch)) != len(batch) or any(type(i) is not int or not 0 <= i < len(data.targets)
                for i in batch) for batch in batches)):
            raise ValueError("bounded complete continuation minibatches required")
    if [case.case_id for case in binding_cases] != plan["binding_case_ids"]:
        raise ValueError("binding case identity differs from continuation plan")
    expected_binding = balanced_group_batches(binding_cases, updates=plan["updates"],
        batch_size=plan["batch_size"], seed=plan["seed"])
    rng = random.Random(f"hepta-binding-natural-v5/{plan['seed']}")
    expected_natural = [rng.sample(range(len(natural_data.targets)), plan["batch_size"])
                        for _ in range(plan["updates"])]
    if plan["binding_batches"] != expected_binding or plan["natural_batches"] != expected_natural:
        raise ValueError("continuation sequences differ from their registered deterministic schedules")
    if set(natural_data.source_groups) & set(binding_data.source_groups):
        raise ValueError("continuation sources overlap")


def continue_binding_reader(model, natural_data, binding_data, binding_cases, *, arm, plan,
                            natural_diagnostic=None, natural_cases=None, depth=3, learning_rate=.001,
                            diagnostic_interval=100, wall_time_ns=3_600_000_000_000,
                            failure_receipt_fn=None):
    """Execute every fixed-budget update; diagnostics never stop or select a model."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = dict(schema="hepta.binding.continuation.v1", status="started", arm=arm,
        plan_sha256=plan.get("plan_sha256"), requested_natural_updates=plan.get("updates"),
        completed_steps=0, completed_natural_updates=0, completed_binding_updates=0,
        actual_natural_exposures=0, actual_binding_exposures=0, updates=[], diagnostics=[],
        optimizer="Adam_foreach_false", learning_rate=learning_rate, depth=depth,
        stopping_rule="fixed_budget_diagnostics_do_not_select", same_initial_checkpoint_required=True)
    try:
        binding_cases = tuple(binding_cases)
        validate_continuation_plan(plan, natural_data, binding_data, binding_cases, model.input_dim,
                                   natural_cases=natural_cases)
        receipt["natural_case_identity_verified"] = natural_cases is not None or hasattr(natural_data, "cases")
        if (arm not in ARMS or not 0 < learning_rate <= 1 or type(depth) is not int
                or not 1 <= depth <= model.max_hops or type(diagnostic_interval) is not int
                or diagnostic_interval < 1 or type(wall_time_ns) is not int or wall_time_ns <= 0):
            raise ValueError("known arm and bounded continuation schedule required")
        if natural_diagnostic is not None:
            natural_diagnostic.validate(model.input_dim)
            if not set(natural_diagnostic.source_groups) <= set(natural_data.source_groups):
                raise ValueError("natural diagnostics must be a subset of training sources")
        initial_digest = parameter_digest(model)
        trained = _train_copy(model)
        optimizer = torch.optim.Adam(trained.parameters(), lr=learning_rate, foreach=False)
        pair_weight = .5 if arm == "contrastive" else 0.
        receipt.update(pair_weight=pair_weight, requested_binding_updates=0 if arm == "natural_only" else plan["updates"],
                       initial_model_sha256=initial_digest, batch_size=plan["batch_size"])

        def diagnose(logical_step):
            diagnostic = dict(logical_step=logical_step, optimizer_steps=len(receipt["updates"]),
                binding=evaluate_reader(trained, binding_data, cases=binding_cases,
                                        depth=depth, batch_size=plan["batch_size"]))
            if natural_diagnostic is not None:
                diagnostic["natural"] = evaluate_reader(trained, natural_diagnostic,
                    depth=depth, batch_size=plan["batch_size"])
            receipt["diagnostics"].append(diagnostic)

        diagnose(0)
        status = "completed"
        for logical_step in range(1, plan["updates"] + 1):
            if time.perf_counter_ns() - wall >= wall_time_ns:
                status = "budget_stopped"
                break
            streams = ("natural",) if arm == "natural_only" else ("natural", "binding")
            for stream in streams:
                if time.perf_counter_ns() - wall >= wall_time_ns:
                    status = "budget_stopped"
                    break
                indices = plan[stream + "_batches"][logical_step - 1]
                selected = [binding_cases[i] for i in indices] if stream == "binding" else None
                receipt["attempted_step"] = len(receipt["updates"]) + 1
                record = _optimizer_step(trained, optimizer, binding_data if selected else natural_data,
                    indices, depth=depth, pair_weight=pair_weight if selected else 0.,
                    pairs=world_pairs(selected) if selected else (),
                    case_ids=[plan[stream + "_case_ids"][i] for i in indices])
                record.update(step=len(receipt["updates"]) + 1, logical_step=logical_step, stream=stream)
                receipt["updates"].append(record)
                receipt["completed_" + stream + "_updates"] += 1
                receipt["actual_" + stream + "_exposures"] += len(indices)
            if status == "budget_stopped":
                break
            receipt["completed_steps"] = logical_step
            if logical_step % diagnostic_interval == 0 or logical_step == plan["updates"]:
                diagnose(logical_step)
        receipt["case_exposures"] = {stream: dict(Counter(case_id for row in receipt["updates"]
            if row["stream"] == stream for case_id in row["case_ids"])) for stream in ("natural", "binding")}
        receipt.update(status=status, final_evaluation_authorized=False,
            actual_total_exposures=receipt["actual_natural_exposures"] + receipt["actual_binding_exposures"],
            wall_time_budget_ns=wall_time_ns, natural_sequence_sha256=_digest(plan["natural_batches"]),
            binding_sequence_sha256=_digest(plan["binding_batches"]) if arm != "natural_only" else None)
        sources = set(getattr(model, "training_source_groups", ())) | set(natural_data.source_groups)
        if arm != "natural_only":
            sources.update(binding_data.source_groups)
        receipt.update(_optimizer_storage(optimizer, trained))
        trained, receipt = _finish(model, trained, SimpleNamespace(source_groups=sources), initial_digest, receipt)
        receipt.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            timing_scope="complete_call_validation_copy_optimizer_materialization_updates_diagnostics_freeze_receipt")
        return trained, receipt
    except Exception as error:
        _failed(error, receipt, wall, cpu, failure_receipt_fn)
