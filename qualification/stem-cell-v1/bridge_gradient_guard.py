"""V7 candidate-only old-task-preserving gradients for the V6 cross-fact Reader.

This is actual PyTorch backward/Adam, not a surrogate receipt or an NDU/FBSDE
solver.  Both arms evaluate exactly the same two train-only minibatches with
identical frozen Stem features, trainable Reader tensors and optimizer updates.
The projected arm guarantees only first-order *unpreconditioned* old-gradient
alignment, not actual Adam retention or downstream quality.
"""
from __future__ import annotations

import copy
import math
import time

import torch
from torch.nn import functional as F

ARMS = ("joint", "protect_old")


def combine_gradients(old, new, *, arm):
    """Project a conflicting new gradient off the old gradient, globally.

    The control performs the same dot/norm census.  Projected updates still
    include the complete old gradient.  This is not a projection onto the
    entire old-task feasible set, and it is not a guarantee after Adam.
    """
    if arm not in ARMS or not old or len(old) != len(new):
        raise ValueError("known arm and aligned nonempty gradient tensors required")
    if any(not isinstance(a, torch.Tensor) or not isinstance(b, torch.Tensor)
           or a.shape != b.shape or a.dtype != b.dtype or a.device != b.device
           or not torch.is_floating_point(a) or not torch.isfinite(a).all()
           or not torch.isfinite(b).all() for a, b in zip(old, new)):
        raise ValueError("finite, compatible floating-point gradients required")
    dot = sum((a.double() * b.double()).sum().item() for a, b in zip(old, new))
    old2 = sum(a.double().square().sum().item() for a in old)
    new2 = sum(b.double().square().sum().item() for b in new)
    projected = arm == "protect_old" and dot < 0 and old2 > 1e-24
    ratio = dot / old2 if projected else 0.0
    combined = tuple(a + (b - ratio * a if projected else b) for a, b in zip(old, new))
    if any(not torch.isfinite(g).all() for g in combined):
        raise FloatingPointError("nonfinite composed gradient")
    after_dot = sum((a.double() * (g - a).double()).sum().item()
                    for a, g in zip(old, combined))
    return combined, dict(dot_old_new=dot, old_gradient_squared_l2=old2,
                          new_gradient_squared_l2=new2, projected=projected,
                          projection_coefficient=ratio,
                          residual_new_dot_old=after_dot,
                          first_order_only=True, actual_retention_verified=False)


def _gradients(loss, params):
    if loss.ndim or not torch.isfinite(loss):
        raise FloatingPointError("finite scalar training loss required")
    result = torch.autograd.grad(loss, params, allow_unused=False)
    if not result or any(not torch.isfinite(g).all() for g in result):
        raise FloatingPointError("missing or nonfinite trainable gradient")
    return tuple(t.detach() for t in result)


def gradient_step(model, optimizer, natural_batch, binding_batch, world_pairs, *, arm, depth=3,
                  pair_weight=0.5, max_gradient_norm=1.0):
    """Two real forwards/backwards and one Adam step; never sees heldout data."""
    if arm not in ARMS or type(depth) is not int or not 1 <= depth <= model.max_hops or (
            type(pair_weight) not in (float, int) or pair_weight != 0.5 or
            type(max_gradient_norm) not in (float, int) or not 0 < max_gradient_norm <= 100):
        raise ValueError("registered arm, depth, pair weight and gradient cap required")
    if not model.training or not all(p.requires_grad for p in model.parameters()):
        raise ValueError("only a fresh trainable candidate Reader may be updated")
    if natural_batch.targets.numel() == 0 or binding_batch.targets.numel() == 0:
        raise ValueError("nonempty train-only minibatches required")
    from binding_training import paired_margin_loss  # existing exact V6 loss owner

    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    params = tuple(model.parameters())
    optimizer.zero_grad(set_to_none=True)
    old_logits = model(*natural_batch.features(), steps=depth)
    old_loss = F.cross_entropy(old_logits, natural_batch.targets)
    old_grad = _gradients(old_loss, params)
    new_logits = model(*binding_batch.features(), steps=depth)
    new_ce = F.cross_entropy(new_logits, binding_batch.targets)
    new_pair = paired_margin_loss(new_logits, binding_batch.targets, world_pairs)
    new_loss = new_ce + pair_weight * new_pair
    new_grad = _gradients(new_loss, params)
    combined, projection = combine_gradients(old_grad, new_grad, arm=arm)
    for param, gradient in zip(params, combined):
        param.grad = gradient.detach().clone()
    observed_norm = torch.nn.utils.clip_grad_norm_(params, max_gradient_norm, error_if_nonfinite=True)
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in params):
        raise FloatingPointError("nonfinite parameters following optimizer step")
    return dict(arm=arm, old_ce=float(old_loss.detach()), new_ce=float(new_ce.detach()),
                binding_pair_loss=float(new_pair.detach()), pair_weight=pair_weight,
                optimizer_steps=1, actual_reader_forwards=2, actual_backward_calls=2,
                old_train_rows=int(natural_batch.targets.numel()),
                new_train_rows=int(binding_batch.targets.numel()),
                preclip_combined_l2=float(observed_norm.detach()),
                clip_limit=max_gradient_norm, **projection,
                cpu_ns=time.process_time_ns() - start_cpu,
                wall_ns=time.perf_counter_ns() - start_wall)


def continue_candidate(parent, natural_data, binding_data, binding_cases, *, plan, arm,
                       depth=3, learning_rate=0.001, max_gradient_norm=1.,
                       deadline_ns=1_800_000_000_000, original_natural_cases=None):
    """Run a fully pinned V6 train plan; return a frozen candidate and receipt.

    This function has no holdout access, selector, runtime mutator or effect
    permissions. Any error propagates; caller must seal a failure receipt.
    """
    from binding_continuation import validate_continuation_plan
    from binding_training import world_pairs
    from token_reader_training import parameter_digest

    began_cpu, began_wall = time.process_time_ns(), time.perf_counter_ns()
    if arm not in ARMS or type(deadline_ns) is not int or deadline_ns <= 0 or (
            type(learning_rate) not in (float, int) or not 0 < learning_rate <= 1):
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
    old_ids, new_ids = plan["natural_case_ids"], plan["binding_case_ids"]
    for number in range(plan["updates"]):
        if time.perf_counter_ns() - began_wall >= deadline_ns:
            raise TimeoutError("candidate train wall deadline exceeded; no partial promotion")
        old_indices = plan["natural_batches"][number]
        new_indices = plan["binding_batches"][number]
        batch_cases = [binding_cases[i] for i in new_indices]
        step = gradient_step(candidate, optimizer, natural_data.take(old_indices),
            binding_data.take(new_indices), world_pairs(batch_cases), arm=arm,
            depth=depth, max_gradient_norm=max_gradient_norm)
        step.update(logical_step=number+1,
                    old_case_ids=[old_ids[i] for i in old_indices],
                    new_case_ids=[new_ids[i] for i in new_indices])
        steps.append(step)
    state_bytes = sum(value.numel() * value.element_size()
                      for state in optimizer.state.values() for value in state.values()
                      if isinstance(value, torch.Tensor))
    optimizer.zero_grad(set_to_none=True)
    candidate.eval().requires_grad_(False)
    candidate.training_source_groups = tuple(sorted(
        set(getattr(parent, "training_source_groups", ())) |
        set(natural_data.source_groups) | set(binding_data.source_groups)))
    if parameter_digest(parent) != initial_sha:
        raise RuntimeError("frozen V6 parent was mutated")
    return candidate, dict(schema="hepta.bridge.gradient-continuation.v7",
        arm=arm, status="completed", plan_sha256=plan["plan_sha256"],
        source_scope="original_train_only", initial_model_sha256=initial_sha,
        final_model_sha256=parameter_digest(candidate), old_train_batches=plan["updates"],
        new_train_batches=plan["updates"], optimizer_steps=plan["updates"],
        actual_reader_forwards=2*plan["updates"], actual_backward_calls=2*plan["updates"],
        old_train_rows=sum(s["old_train_rows"] for s in steps),
        new_train_rows=sum(s["new_train_rows"] for s in steps),
        optimizer_tensor_bytes=state_bytes, trainable_parameter_count=sum(p.numel() for p in candidate.parameters()),
        old_task_retention_verified=False, natural_task_generalization_verified=False,
        equal_backward_calls=True, equal_optimizer_updates=True,
        full_backward_flops_matched=False, actual_compute_equal=False,
        real_ndu_improvement_verified=False, production_authorized=False,
        updates=steps, cpu_ns=time.process_time_ns()-began_cpu,
        wall_ns=time.perf_counter_ns()-began_wall,
        formula_flops=None, nested_costs_additive=False)
