"""V7.1: old-binding-task gradient preservation for a frozen V6 Bridge Reader.

Original V6 warmup fits the binding paired-world task; subsequent natural
MultiRC training is the NEW task.  V7's earlier stream ordering was reversed.
All arms have the same model, minibatches and two backward passes.  This code
measures the actual old-binding minibatch loss AFTER Adam, and a separately
registered guard arm restores BOTH weights and optimizer moments if that old
loss increases beyond tolerance.  Neither projection nor guard proves
whole-task/future retention, and cost equality is never asserted.
"""
from __future__ import annotations

import copy
import math
import time

import torch
from torch.nn import functional as F

ARMS = ("joint", "protect_old", "protect_old_guarded")
OLD_TASK = "v6_binding_paired_world_warmup"
NEW_TASK = "natural_multirc_continuation"
POST_STEP_TOLERANCE = 1e-6


def combine_gradients(old, new, *, arm):
    """Project only NEW-task gradient away from conflicting OLD-task gradient."""
    if arm not in ARMS or not old or len(old) != len(new):
        raise ValueError("registered arm and aligned nonempty gradient tensors required")
    if any(not isinstance(a, torch.Tensor) or not isinstance(b, torch.Tensor)
           or a.shape != b.shape or a.dtype != b.dtype or a.device != b.device
           or not torch.is_floating_point(a) or not torch.isfinite(a).all()
           or not torch.isfinite(b).all() for a, b in zip(old, new)):
        raise ValueError("finite, compatible floating-point gradients required")
    dot = sum((a.double() * b.double()).sum().item() for a, b in zip(old, new))
    old2 = sum(a.double().square().sum().item() for a in old)
    new2 = sum(b.double().square().sum().item() for b in new)
    projected = arm != "joint" and dot < 0 and old2 > 1e-24
    ratio = dot / old2 if projected else 0.0
    combined = tuple(a + (b - ratio * a if projected else b) for a, b in zip(old, new))
    if any(not torch.isfinite(g).all() for g in combined):
        raise FloatingPointError("nonfinite composed gradient")
    residual = sum((a.double() * (g-a).double()).sum().item()
                   for a, g in zip(old, combined))
    return combined, dict(dot_old_new=dot, old_gradient_squared_l2=old2,
        new_gradient_squared_l2=new2, projected=projected,
        projection_coefficient=ratio, residual_new_dot_old=residual,
        first_order_only=True, actual_retention_verified=False)


def _gradients(loss, params):
    if loss.ndim or not bool(torch.isfinite(loss)):
        raise FloatingPointError("finite scalar training loss required")
    result = torch.autograd.grad(loss, params, allow_unused=False)
    if not result or any(not torch.isfinite(g).all() for g in result):
        raise FloatingPointError("missing or nonfinite trainable gradient")
    return tuple(t.detach() for t in result)


def _old_loss(model, old_batch, pairs, depth, pair_weight):
    logits = model(*old_batch.features(), steps=depth)
    ce = F.cross_entropy(logits, old_batch.targets)
    pair = _paired_margin_loss(logits, old_batch.targets, pairs)
    return ce + pair_weight * pair, ce, pair


def _paired_margin_loss(logits, targets, pairs):
    from binding_training import paired_margin_loss  # exact frozen V6 loss owner
    return paired_margin_loss(logits, targets, pairs)


def gradient_step(model, optimizer, binding_old_batch, natural_new_batch, old_world_pairs,
                  *, arm, depth=3, pair_weight=.5, max_gradient_norm=1.,
                  post_step_tolerance=POST_STEP_TOLERANCE):
    """One old-binding + one new-natural backward and one actual Adam proposal.

    All three arms pay exactly one additional old-binding forward to observe the
    post-Adam loss.  Guarded arm alone additionally snapshots/restores Adam
    state if its actual sampled old-task loss rises beyond tolerance.
    """
    if (arm not in ARMS or type(depth) is not int or not 1 <= depth <= model.max_hops
            or type(pair_weight) not in (float, int) or pair_weight != .5
            or type(max_gradient_norm) not in (float, int) or not 0 < max_gradient_norm <= 100
            or type(post_step_tolerance) not in (float, int)
            or not math.isfinite(post_step_tolerance)
            or not 0 <= post_step_tolerance <= .01):
        raise ValueError("registered arm, depth, pair weight and tolerance required")
    if not model.training or not all(p.requires_grad for p in model.parameters()):
        raise ValueError("only a fresh trainable Reader candidate may be updated")
    if binding_old_batch.targets.numel() == 0 or natural_new_batch.targets.numel() == 0:
        raise ValueError("nonempty old-binding and new-natural train minibatches required")
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    params = tuple(model.parameters())
    optimizer.zero_grad(set_to_none=True)
    old_loss, old_ce, old_pair = _old_loss(
        model, binding_old_batch, old_world_pairs, depth, pair_weight)
    old_grad = _gradients(old_loss, params)
    new_logits = model(*natural_new_batch.features(), steps=depth)
    new_ce = F.cross_entropy(new_logits, natural_new_batch.targets)
    new_grad = _gradients(new_ce, params)
    combined, projection = combine_gradients(old_grad, new_grad, arm=arm)
    for param, gradient in zip(params, combined):
        param.grad = gradient.detach().clone()
    norm = torch.nn.utils.clip_grad_norm_(
        params, max_gradient_norm, error_if_nonfinite=True)
    # Observe the ACTUAL Adam direction, not the preconditioner-free gradient.
    prior = [p.detach().clone() for p in params]
    state_before = copy.deepcopy(optimizer.state_dict()) if arm == "protect_old_guarded" else None
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in params):
        raise FloatingPointError("nonfinite parameters following optimizer step")
    direction_dot = sum((g.double() * (p.detach().double() - before.double())).sum().item()
                        for g, p, before in zip(old_grad, params, prior))
    with torch.no_grad():
        post_loss, _, _ = _old_loss(
            model, binding_old_batch, old_world_pairs, depth, pair_weight)
    if not bool(torch.isfinite(post_loss)):
        raise FloatingPointError("nonfinite post-Adam old-binding loss")
    observed_old_delta = float(post_loss - old_loss.detach())
    rejected = arm == "protect_old_guarded" and observed_old_delta > post_step_tolerance
    if rejected:
        # Revert *both* tensors and Adam's moments / step counter.  Reverting
        # weights alone silently biases all subsequent candidate training.
        with torch.no_grad():
            for param, before in zip(params, prior):
                param.copy_(before)
        optimizer.load_state_dict(state_before)
        if any(not torch.equal(p.detach(), before) for p, before in zip(params, prior)):
            raise RuntimeError("guarded model rollback failed")
    return dict(arm=arm, old_task=OLD_TASK, new_task=NEW_TASK,
        old_ce=float(old_ce.detach()), old_pair_loss=float(old_pair.detach()),
        old_loss_before=float(old_loss.detach()),
        old_loss_after_proposal=float(post_loss.detach()), old_loss_proposal_delta=observed_old_delta,
        new_ce=float(new_ce.detach()), pair_weight=pair_weight,
        attempted_optimizer_steps=1, accepted_optimizer_steps=0 if rejected else 1,
        rejected_optimizer_steps=int(rejected),
        actual_reader_forwards=3, actual_backward_calls=2,
        old_train_rows=int(binding_old_batch.targets.numel()),
        new_train_rows=int(natural_new_batch.targets.numel()),
        post_step_forward_observed=True, old_loss_guard_tolerance=post_step_tolerance,
        old_loss_guard_reverted=bool(rejected),
        adam_old_direction_dot=direction_dot,
        optimizer_state_restored_if_rejected=bool(rejected),
        preclip_combined_l2=float(norm.detach()), clip_limit=max_gradient_norm,
        **projection, cpu_ns=time.process_time_ns()-started_cpu,
        wall_ns=time.perf_counter_ns()-started_wall)


def continue_candidate(parent, natural_data, binding_data, binding_cases, *, plan, arm,
                       depth=3, learning_rate=.001, max_gradient_norm=1.,
                       deadline_ns=1_800_000_000_000, original_natural_cases=None):
    """Original frozen V6 checkpoint + exact source-bound 500-step candidate.

    The *binding* dataset is old (warmup); *natural* is new (continuation).
    Failures remain candidate-only and are sealed by the enclosing campaign.
    """
    from binding_continuation import validate_continuation_plan
    from binding_training import world_pairs
    from token_reader_training import parameter_digest
    began_cpu, began_wall = time.process_time_ns(), time.perf_counter_ns()
    if (arm not in ARMS or type(deadline_ns) is not int or deadline_ns <= 0
            or type(learning_rate) not in (float, int) or not 0 < learning_rate <= 1):
        raise ValueError("bounded candidate schedule required")
    binding_cases = tuple(binding_cases)
    validate_continuation_plan(plan, natural_data, binding_data, binding_cases,
                               parent.input_dim, natural_cases=original_natural_cases)
    if parent.training or any(p.requires_grad for p in parent.parameters()):
        raise ValueError("starting V6 checkpoint must be frozen")
    initial_sha = parameter_digest(parent)
    candidate = copy.deepcopy(parent).train().requires_grad_(True)
    optimizer = torch.optim.Adam(candidate.parameters(), lr=learning_rate, foreach=False)
    steps = []
    old_ids, new_ids = plan["binding_case_ids"], plan["natural_case_ids"]
    for number in range(plan["updates"]):
        if time.perf_counter_ns() - began_wall >= deadline_ns:
            raise TimeoutError("candidate wall deadline exceeded; no partial promotion")
        old_indices, new_indices = (plan["binding_batches"][number],
                                     plan["natural_batches"][number])
        old_cases = [binding_cases[i] for i in old_indices]
        step = gradient_step(candidate, optimizer, binding_data.take(old_indices),
            natural_data.take(new_indices), world_pairs(old_cases), arm=arm,
            depth=depth, max_gradient_norm=max_gradient_norm)
        step.update(logical_step=number+1,
            old_case_ids=[old_ids[i] for i in old_indices],
            new_case_ids=[new_ids[i] for i in new_indices])
        steps.append(step)
    optimizer_bytes = sum(value.numel() * value.element_size()
                          for state in optimizer.state.values() for value in state.values()
                          if isinstance(value, torch.Tensor))
    optimizer.zero_grad(set_to_none=True)
    candidate.eval().requires_grad_(False)
    candidate.training_source_groups = tuple(sorted(
        set(getattr(parent, "training_source_groups", ())) |
        set(natural_data.source_groups) | set(binding_data.source_groups)))
    if parameter_digest(parent) != initial_sha:
        raise RuntimeError("frozen V6 parent was mutated")
    accepted = sum(s["accepted_optimizer_steps"] for s in steps)
    rejected = sum(s["rejected_optimizer_steps"] for s in steps)
    return candidate, dict(schema="hepta.bridge.gradient-continuation.v7.1",
        arm=arm, status="completed", plan_sha256=plan["plan_sha256"],
        old_task=OLD_TASK, new_task=NEW_TASK,
        source_scope="original_train_only", initial_model_sha256=initial_sha,
        final_model_sha256=parameter_digest(candidate),
        old_train_batches=plan["updates"], new_train_batches=plan["updates"],
        attempted_optimizer_steps=plan["updates"], accepted_optimizer_steps=accepted,
        rejected_optimizer_steps=rejected,
        actual_reader_forwards=3*plan["updates"],
        actual_backward_calls=2*plan["updates"],
        old_train_rows=sum(s["old_train_rows"] for s in steps),
        new_train_rows=sum(s["new_train_rows"] for s in steps),
        optimizer_tensor_bytes=optimizer_bytes,
        trainable_parameter_count=sum(p.numel() for p in candidate.parameters()),
        old_task_retention_verified=False, natural_task_generalization_verified=False,
        equal_backward_calls=True, equal_attempted_optimizer_steps=True,
        full_backward_flops_matched=False, actual_compute_equal=False,
        real_ndu_improvement_verified=False, production_authorized=False,
        updates=steps, cpu_ns=time.process_time_ns()-began_cpu,
        wall_ns=time.perf_counter_ns()-began_wall,
        formula_flops=None, nested_costs_additive=False)
