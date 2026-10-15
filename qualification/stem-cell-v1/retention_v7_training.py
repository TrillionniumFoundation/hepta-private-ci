"""V7 fixed-budget transfer, replay and centered-logit retention controls.

Teacher preparation happens once outside this call. Only six public feature
tensors enter the Reader; targets, pairing and teacher logits select losses.
"""
from collections import Counter
import math
import time
from types import SimpleNamespace

import torch
from torch.nn import functional as F

from binding_continuation import continuation_plan, validate_continuation_plan
from binding_training import (_digest, _failed, _finish, _optimizer_storage, _train_copy,
    _validate_data, balanced_group_batches, evaluate_reader, paired_margin_loss, world_pairs)
from reader_features import tensor_digest
from token_reader_training import parameter_digest


ARMS = ("repeat", "diverse", "anchored", "low_lr")
STREAMS = ("natural", "transfer", "retention")


def make_retention_plan(natural_cases, binding_cases, augmentation_cases, *, seed,
                        updates=500, batch_size=16):
    """Extend the V6 natural/old schedule with independently shuffled train groups."""
    natural_cases, binding_cases, augmentation_cases = map(tuple,
        (natural_cases, binding_cases, augmentation_cases))
    plan = continuation_plan(natural_cases, binding_cases, seed=seed,
                             updates=updates, batch_size=batch_size)
    if (not augmentation_cases or any(c.source_split != "train" for c in augmentation_cases)
            or len({c.case_id for c in augmentation_cases}) != len(augmentation_cases)
            or {c.source_hash for c in augmentation_cases}
            & {c.source_hash for c in natural_cases + binding_cases}
            or {c.case_id for c in augmentation_cases}
            & {c.case_id for c in natural_cases + binding_cases}
            or {c.case_id for c in natural_cases} & {c.case_id for c in binding_cases}):
        raise ValueError("augmentation must contain unique, disjoint training cases")
    plan.update(retention_schema="hepta.retention.plan.v7", stream_order=list(STREAMS),
        logical_update_order=list(STREAMS),
        arms=list(ARMS), augmentation_seed=seed ^ 0x713,
        augmentation_case_ids=[c.case_id for c in augmentation_cases],
        augmentation_targets=[c.label for c in augmentation_cases],
        augmentation_source_groups=[c.source_hash for c in augmentation_cases],
        augmentation_batches=balanced_group_batches(augmentation_cases, updates=updates,
            batch_size=batch_size, seed=seed ^ 0x713),
        synthetic_pair_weight=.5, anchored_retention_weight=1.,
        learning_rates={arm: .0001 if arm == "low_lr" else .001 for arm in ARMS})
    plan["plan_sha256"] = _digest({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def _validate(plan, natural_data, binding_data, augmentation_data, binding_cases,
              augmentation_cases, natural_cases, input_dim):
    validate_continuation_plan(plan, natural_data, binding_data, binding_cases,
                               input_dim, natural_cases=natural_cases)
    _validate_data(augmentation_data, augmentation_cases, input_dim)
    expected = make_retention_plan(natural_cases, binding_cases, augmentation_cases,
        seed=plan["seed"], updates=plan["updates"], batch_size=plan["batch_size"])
    if plan != expected:
        raise ValueError("retention plan differs from its complete deterministic row bindings")


def centered_logit_mse(logits, teacher_logits):
    """Preserve a two-class margin without penalizing a shared logit offset."""
    if logits.shape != teacher_logits.shape or logits.ndim != 2 or logits.shape[1] != 2:
        raise ValueError("aligned binary student and frozen teacher logits required")
    return F.mse_loss(logits - logits.mean(-1, keepdim=True),
                      teacher_logits - teacher_logits.mean(-1, keepdim=True))


def _step(model, optimizer, data, indices, cases, *, depth, teacher, anchor_weight):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    batch = data.take(indices)
    optimizer.zero_grad(set_to_none=True)
    trace = model(*batch.features(), steps=depth, return_attention=True)
    logits = trace["logits"]
    ce = F.cross_entropy(logits, batch.targets)
    pair = paired_margin_loss(logits, batch.targets, world_pairs(cases)) if cases else ce * 0
    pair_weight = .5 if cases else 0.
    anchor = centered_logit_mse(logits, teacher[indices]) if anchor_weight else ce * 0
    loss = ce + pair_weight * pair + anchor_weight * anchor
    if not torch.isfinite(loss):
        raise FloatingPointError("nonfinite retention loss")
    for state in trace["states"]:
        state.retain_grad()
    loss.backward()
    gradients = [p.grad for p in model.parameters() if p.grad is not None]
    if not gradients or any(not torch.isfinite(g).all() for g in gradients):
        raise FloatingPointError("nonfinite or absent retention parameter gradient")
    states = [state.detach() for state in trace["states"]]
    if (any(not torch.isfinite(s).all() or s.abs().max().item() > 1.000001 for s in states)
            or any(s.grad is not None and not torch.isfinite(s.grad).all() for s in trace["states"])):
        raise FloatingPointError("nonfinite or unbounded retention recurrent state")
    record = dict(indices=list(indices), exposures=len(indices), logits=logits.detach().tolist(),
        binary_cross_entropy=ce.item(), pair_loss=pair.item(), pair_weight=pair_weight,
        anchor_mse=anchor.item(), anchor_weight=anchor_weight, total_loss=loss.item(),
        parameter_gradient_l2=math.sqrt(sum(g.double().square().sum().item() for g in gradients)),
        hop_state_gradient_l2=[None if s.grad is None else s.grad.norm().item() for s in trace["states"]],
        hop_state_saturation_fraction=[s.abs().ge(.99).float().mean().item() for s in states],
        hop_state_max_abs=[s.abs().max().item() for s in states], depth=depth,
        finite_gradients=True, inference_feature_arguments=6)
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in model.parameters()):
        raise FloatingPointError("nonfinite retention parameters after update")
    record.update(finite_parameters_after_update=True,
        cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall)
    return record


def continue_retention(model, natural_data, binding_data, augmentation_data, binding_cases,
                       augmentation_cases, *, arm, plan, teacher_logits,
                       teacher_logits_sha256, natural_cases, depth=3, diagnostic_interval=100,
                       wall_time_ns=3_600_000_000_000, failure_receipt_fn=None):
    """Run every natural→transfer→retention update; diagnostics never select a model."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    receipt = dict(schema="hepta.retention.continuation.v7", status="started", arm=arm,
        plan_sha256=plan.get("plan_sha256"), requested_logical_updates=plan.get("updates"),
        completed_steps=0, updates=[], diagnostics=[], optimizer="Adam_foreach_false",
        stopping_rule="fixed_budget_diagnostics_do_not_select", stream_order=list(STREAMS),
        teacher_preparation_scope="external_once_per_seed_shared_all_arms_not_recharged_here",
        teacher_logits_sha256=teacher_logits_sha256, final_evaluation_authorized=False)
    for stream in STREAMS:
        receipt["completed_" + stream + "_updates"] = 0
        receipt["actual_" + stream + "_exposures"] = 0
    try:
        natural_cases, binding_cases, augmentation_cases = map(tuple,
            (natural_cases, binding_cases, augmentation_cases))
        _validate(plan, natural_data, binding_data, augmentation_data, binding_cases,
                  augmentation_cases, natural_cases, model.input_dim)
        if (arm not in ARMS or type(depth) is not int or not 1 <= depth <= model.max_hops
                or type(diagnostic_interval) is not int or diagnostic_interval < 1
                or type(wall_time_ns) is not int or wall_time_ns <= 0):
            raise ValueError("known retention arm and bounded training schedule required")
        if (not isinstance(teacher_logits, torch.Tensor) or teacher_logits.device.type != "cpu"
                or teacher_logits.dtype != torch.float32 or teacher_logits.requires_grad
                or tuple(teacher_logits.shape) != (len(binding_cases), 2)
                or not torch.isfinite(teacher_logits).all()
                or tensor_digest(teacher_logits) != teacher_logits_sha256):
            raise ValueError("bound finite frozen CPU FP32 old-case teacher logits required")
        # All row/source/teacher/schedule validation precedes copying or optimizer creation.
        initial = parameter_digest(model)
        trained = _train_copy(model)
        learning_rate, anchor_weight = plan["learning_rates"][arm], float(arm == "anchored")
        optimizer = torch.optim.Adam(trained.parameters(), lr=learning_rate, foreach=False)
        receipt.update(seed=plan["seed"], initial_model_sha256=initial, learning_rate=learning_rate,
            anchor_weight=anchor_weight, pair_weight=.5, depth=depth, batch_size=plan["batch_size"],
            teacher_logits_shape=list(teacher_logits.shape), teacher_logits_dtype=str(teacher_logits.dtype),
            teacher_digest_scope="raw_contiguous_FP32_bytes_shape_dtype_validated_separately",
            teacher_logits_model_binding_scope="external_campaign_provenance", teacher_calls_inside_fit=0,
            anchor_applies_only_to="retention", training_case_identity_verified=True,
            transfer_data_role="old_binding" if arm == "repeat" else "augmentation",
            natural_sequence_sha256=_digest(plan["natural_batches"]),
            binding_sequence_sha256=_digest(plan["binding_batches"]),
            augmentation_sequence_sha256=_digest(plan["augmentation_batches"]),
            transfer_sequence_sha256=_digest(plan["binding_batches"] if arm == "repeat"
                                            else plan["augmentation_batches"]),
            wall_time_budget_ns=wall_time_ns)

        def diagnose(step):
            receipt["diagnostics"].append(dict(logical_step=step, optimizer_steps=len(receipt["updates"]),
                binding=evaluate_reader(trained, binding_data, cases=binding_cases,
                    depth=depth, batch_size=plan["batch_size"]),
                augmentation=evaluate_reader(trained, augmentation_data, cases=augmentation_cases,
                    depth=depth, batch_size=plan["batch_size"])))

        diagnose(0)
        status = "completed"
        for logical_step in range(1, plan["updates"] + 1):
            for stream in STREAMS:
                if time.perf_counter_ns() - wall >= wall_time_ns:
                    status = "budget_stopped"
                    break
                old = stream == "retention" or stream == "transfer" and arm == "repeat"
                prefix = "natural" if stream == "natural" else "binding" if old else "augmentation"
                indices = plan[prefix + "_batches"][logical_step - 1]
                data = natural_data if stream == "natural" else binding_data if old else augmentation_data
                cases = None if stream == "natural" else [
                    (binding_cases if old else augmentation_cases)[i] for i in indices]
                receipt["attempted_step"] = len(receipt["updates"]) + 1
                record = _step(trained, optimizer, data, indices, cases, depth=depth,
                    teacher=teacher_logits, anchor_weight=anchor_weight if stream == "retention" else 0.)
                identifiers = [plan[prefix + "_case_ids"][i] for i in indices]
                record.update(step=len(receipt["updates"]) + 1, logical_step=logical_step,
                    stream=stream, data_role=prefix, case_ids=identifiers, sample_sha256=_digest(identifiers))
                receipt["updates"].append(record)
                receipt["completed_" + stream + "_updates"] += 1
                receipt["actual_" + stream + "_exposures"] += len(indices)
            if status == "budget_stopped":
                break
            receipt["completed_steps"] = logical_step
            if logical_step % diagnostic_interval == 0 or logical_step == plan["updates"]:
                diagnose(logical_step)
        if tensor_digest(teacher_logits) != teacher_logits_sha256 or teacher_logits.requires_grad:
            raise RuntimeError("frozen shared teacher logits changed during fitting")
        receipt.update(status=status, case_exposures={stream: dict(Counter(
            case_id for row in receipt["updates"] if row["stream"] == stream for case_id in row["case_ids"]))
            for stream in STREAMS}, actual_total_exposures=sum(receipt["actual_" + s + "_exposures"] for s in STREAMS),
            teacher_logits_unchanged=True, raw_step_logits_recorded=True,
            planned_stream_update_budgets_equal=True,
            actual_stream_update_counts_equal=len({receipt["completed_" + s + "_updates"] for s in STREAMS}) == 1,
            strict_equal_compute=False)
        sources = set(getattr(model, "training_source_groups", ())) | set(natural_data.source_groups)
        sources.update(binding_data.source_groups)
        if arm != "repeat":
            sources.update(augmentation_data.source_groups)
        receipt.update(_optimizer_storage(optimizer, trained))
        trained, receipt = _finish(model, trained, SimpleNamespace(source_groups=sources), initial, receipt)
        receipt.update(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
            timing_scope="validation_copy_optimizer_updates_raw_logits_diagnostics_freeze_receipt")
        return trained, receipt
    except Exception as error:
        _failed(error, receipt, wall, cpu, failure_receipt_fn)
