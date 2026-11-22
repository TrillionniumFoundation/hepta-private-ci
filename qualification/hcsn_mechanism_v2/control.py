"""Fixed-review control: hard and stochastic actions share every decision epoch.

At k*interval choose continue or immediate reset, then evolve the same CTMC for
one COMPLETE interval before another decision. This is a discounted review-time
MDP, not the continuous-observation impulse QVI. The reset phase is locked.
"""

from dataclasses import dataclass
import itertools
import math
import time

import numpy as np
import torch


@dataclass(frozen=True)
class ReviewModel:
    discounted_transition: torch.Tensor
    reward_integral: torch.Tensor
    reset_payoff: torch.Tensor
    active_count: int
    reset_entry: int
    discount: float
    interval: float

    @property
    def beta(self):
        return math.exp(-self.discount * self.interval)


def _vector(value, size, reference):
    if (
        value.shape != (size,)
        or value.dtype != reference.dtype
        or value.device != reference.device
        or not bool(torch.isfinite(value).all())
    ):
        raise ValueError("matching finite FP64 vector required")


def review_model(
    generator, reset_payoff, *, discount, interval, active_count, reset_entry
):
    """Freeze exact dense propagation and discounted reward over one review interval."""
    if (
        generator.ndim != 2
        or generator.shape[0] != generator.shape[1]
        or not 2 <= len(generator) <= 64
        or generator.dtype != torch.float64
        or not bool(torch.isfinite(generator).all())
    ):
        raise ValueError("finite FP64 generator required")
    n = len(generator)
    off = generator - torch.diag_embed(generator.diagonal())
    if (
        bool((off < 0).any())
        or bool((generator.diagonal() > 0).any())
        or float(generator.sum(1).abs().max()) > 1e-10
        or type(active_count) is not int
        or not 1 <= active_count < n
        or type(reset_entry) is not int
        or not active_count <= reset_entry < n
        or not math.isfinite(discount)
        or discount <= 0
        or not math.isfinite(interval)
        or interval <= 0
        or not math.isfinite(discount * interval)
        or not 0 < math.exp(-discount * interval) < 1
    ):
        raise ValueError(
            "CTMC, positive clock/discount and locked reset state required"
        )
    _vector(reset_payoff, active_count, generator)
    identity = torch.eye(n, dtype=generator.dtype, device=generator.device)
    resolvent = discount * identity - generator
    transition = torch.matrix_exp(-interval * resolvent)
    integral = torch.linalg.solve(resolvent, identity - transition)
    if not bool(torch.isfinite(transition).all() and torch.isfinite(integral).all()):
        raise FloatingPointError("nonfinite review propagation")
    return ReviewModel(
        transition.detach(),
        integral.detach(),
        reset_payoff.detach().clone(),
        active_count,
        reset_entry,
        float(discount),
        float(interval),
    )


def _policy_system(model, probability):
    transition = model.discounted_transition
    n = len(transition)
    _vector(probability, model.active_count, transition)
    if bool(((probability < 0) | (probability > 1)).any()):
        raise ValueError("reset probabilities must lie in [0,1]")
    chosen = torch.cat((probability, transition.new_zeros(n - model.active_count)))
    payoff = torch.cat(
        (model.reset_payoff, transition.new_zeros(n - model.active_count))
    )
    kernel = transition + chosen[:, None] * (transition[model.reset_entry] - transition)
    rewards = model.reward_integral
    reward_map = rewards + chosen[:, None] * (rewards[model.reset_entry] - rewards)
    identity = torch.eye(n, dtype=transition.dtype, device=transition.device)
    return identity - kernel, reward_map, chosen * payoff


def policy_value(model, running_reward, probability):
    """Exact full continuation; differentiable in the active reset probabilities."""
    _vector(
        running_reward, len(model.discounted_transition), model.discounted_transition
    )
    matrix, reward_map, immediate = _policy_system(model, probability)
    value = torch.linalg.solve(matrix, reward_map @ running_reward + immediate)
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError("nonfinite review-policy value")
    return value


def return_affine(model, probability, initial):
    """One adjoint solve represents full policy return for any reward observation."""
    _vector(initial, len(model.discounted_transition), model.discounted_transition)
    if bool((initial < 0).any()) or abs(float(initial.sum()) - 1) > 1e-12:
        raise ValueError("normalized initial distribution required")
    matrix, reward_map, immediate = _policy_system(model, probability)
    occupation = torch.linalg.solve(matrix.T, initial)
    return occupation @ reward_map, occupation @ immediate


def _bellman(model, running_reward, value, probability_floor):
    if not math.isfinite(probability_floor) or not 0 <= probability_floor < 0.5:
        raise ValueError("probability floor must lie in [0,.5)")
    _vector(value, len(model.discounted_transition), model.discounted_transition)
    _vector(running_reward, len(value), model.discounted_transition)
    continuing = (
        model.reward_integral @ running_reward + model.discounted_transition @ value
    )
    advantage = (
        model.reset_payoff
        + continuing[model.reset_entry]
        - continuing[: model.active_count]
    )
    best = probability_floor + (1 - 2 * probability_floor) * (advantage > 0).to(value)
    target = torch.cat(
        (
            continuing[: model.active_count] + best * advantage,
            continuing[model.active_count :],
        )
    )
    residual = float((target - value).abs().max().detach())
    return advantage, residual, residual / (1 - model.beta)


def residual_bound(model, running_reward, value, *, probability_floor=0.0):
    """Sup-norm Bellman residual and residual/(1-beta) value-error bound."""
    _, residual, bound = _bellman(model, running_reward, value, probability_floor)
    return {"bellman_residual": residual, "residual_bound": bound}


@torch.no_grad()
def solve_review_control(
    model,
    running_reward,
    *,
    probability_floor=0.0,
    value_tolerance=1e-8,
    max_evaluations=8193,
    wall_seconds=120.0,
):
    """Howard iteration for the common clock, optionally with bounded probabilities."""
    if (
        not math.isfinite(value_tolerance)
        or value_tolerance <= 0
        or type(max_evaluations) is not int
        or max_evaluations < 1
        or not math.isfinite(wall_seconds)
        or wall_seconds <= 0
    ):
        raise ValueError("positive tolerance and finite work limits required")
    started = time.perf_counter()
    policy = torch.zeros(
        model.active_count, dtype=torch.bool, device=model.discounted_transition.device
    )
    status = "budget_exhausted"
    for evaluations in range(1, max_evaluations + 1):
        probability = probability_floor + (1 - 2 * probability_floor) * policy.to(
            model.reset_payoff
        )
        value = policy_value(model, running_reward, probability)
        advantage, residual, bound = _bellman(
            model, running_reward, value, probability_floor
        )
        if bound <= value_tolerance:
            status = "converged"
            break
        if (
            evaluations == max_evaluations
            or time.perf_counter() - started >= wall_seconds
        ):
            break
        policy = advantage > 0
    return {
        "value": value,
        "probability": probability,
        "status": status,
        "linear_solves": evaluations,
        "backward_passes": 0,
        "bellman_residual": residual,
        "residual_bound": bound,
        "wall_seconds": time.perf_counter() - started,
    }


@torch.no_grad()
def enumerate_review_policies(model, running_reward, initial, *, probability_floor=0.0):
    """Independent NumPy row assembly and exhaustive corner-policy evaluation.

    An affine two-action Bellman map attains its maximum at a corner of either
    [0,1]^active or [floor,1-floor]^active. No oracle values train the BP gate.
    """
    if not 0 <= probability_floor < 0.5 or model.active_count > 12:
        raise ValueError(
            "bounded floor and at most 12 binary control dimensions required"
        )
    _vector(running_reward, len(initial), model.discounted_transition)
    _vector(initial, len(model.discounted_transition), model.discounted_transition)
    if bool((initial <= 0).any()) or abs(float(initial.sum()) - 1) > 1e-12:
        raise ValueError("strictly positive normalized initial distribution required")
    started = time.perf_counter()
    transition = model.discounted_transition.detach().cpu().numpy()
    base = (
        model.reward_integral.detach().cpu().numpy()
        @ running_reward.detach().cpu().numpy()
    )
    payoffs = model.reset_payoff.detach().cpu().numpy()
    values, probabilities = [], []
    for bits in itertools.product((0.0, 1.0), repeat=model.active_count):
        probability = probability_floor + (1 - 2 * probability_floor) * np.array(bits)
        matrix, rhs = np.eye(len(base)) - transition, base.copy()
        for i, p in enumerate(probability):
            matrix[i] = (
                np.eye(len(base))[i]
                - (1 - p) * transition[i]
                - p * transition[model.reset_entry]
            )
            rhs[i] = (1 - p) * base[i] + p * (payoffs[i] + base[model.reset_entry])
        values.append(np.linalg.solve(matrix, rhs))
        probabilities.append(probability)
    values = torch.as_tensor(
        np.stack(values), dtype=initial.dtype, device=initial.device
    )
    probabilities = torch.as_tensor(
        np.stack(probabilities), dtype=initial.dtype, device=initial.device
    )
    best = int((values @ initial).argmax())
    return {
        "value": values[best],
        "probability": probabilities[best],
        "all_values": values,
        "all_probabilities": probabilities,
        "linear_solves": len(values),
        "wall_seconds": time.perf_counter() - started,
    }


def fit_lookup_gate(
    model,
    running_reward,
    initial,
    *,
    logit_limit,
    max_steps=8192,
    learning_rate=0.1,
    value_tolerance=1e-8,
    wall_seconds=120.0,
    checkpoints=(0, 32, 128, 512, 2048, 4096, 8192),
):
    """Projected Adam on the SAME exact policy value; stopping uses a residual bound.

    Logits are constrained to [-L,L]. Their precise policy class has endpoints
    sigmoid(-L) and sigmoid(L), so its optimum is separately enumeratable.
    Traces count completed parameter updates; each returned policy is evaluated.
    """
    _vector(initial, len(model.discounted_transition), model.discounted_transition)
    if (
        bool((initial <= 0).any())
        or abs(float(initial.sum()) - 1) > 1e-12
        or not math.isfinite(logit_limit)
        or not 0 < logit_limit <= 30
        or type(max_steps) is not int
        or max_steps < 0
        or not math.isfinite(learning_rate)
        or learning_rate <= 0
        or not math.isfinite(value_tolerance)
        or value_tolerance <= 0
        or not math.isfinite(wall_seconds)
        or wall_seconds <= 0
        or any(type(c) is not int or c < 0 for c in checkpoints)
    ):
        raise ValueError(
            "valid initial distribution, finite logit box and work limits required"
        )
    started = time.perf_counter()
    logits = torch.zeros(
        model.active_count,
        dtype=initial.dtype,
        device=initial.device,
        requires_grad=True,
    )
    optimizer = torch.optim.Adam([logits], lr=learning_rate)
    floor = torch.sigmoid(initial.new_tensor(-logit_limit)).item()
    trace, gradient_norm = [], None
    status = "budget_exhausted"
    for steps in range(max_steps + 1):
        probability = logits.sigmoid()
        value = policy_value(model, running_reward, probability)
        objective = initial @ value
        _, residual, bound = _bellman(model, running_reward, value, floor)
        stopped = (
            bound <= value_tolerance
            or steps == max_steps
            or time.perf_counter() - started >= wall_seconds
        )
        if steps in checkpoints or stopped:
            trace.append(
                {
                    "steps": steps,
                    "forward_linear_solves": steps + 1,
                    "backward_passes": steps,
                    "training_return": float(objective.detach()),
                    "bellman_residual": residual,
                    "residual_bound": bound,
                    "probability": probability.detach().tolist(),
                    "wall_seconds": time.perf_counter() - started,
                }
            )
        if stopped:
            status = "converged" if bound <= value_tolerance else "budget_exhausted"
            break
        optimizer.zero_grad(set_to_none=True)
        (-objective).backward()
        if logits.grad is None or not bool(torch.isfinite(logits.grad).all()):
            raise FloatingPointError("nonfinite full-return gradient")
        gradient_norm = float(logits.grad.abs().max())
        optimizer.step()
        with torch.no_grad():
            logits.clamp_(-logit_limit, logit_limit)
    return {
        "value": value.detach(),
        "probability": probability.detach(),
        "logits": logits.detach(),
        "status": status,
        "steps": steps,
        "linear_solves": steps + 1,
        "backward_passes": steps,
        "last_update_gradient_norm": gradient_norm,
        "bellman_residual": residual,
        "residual_bound": bound,
        "trace": trace,
        "wall_seconds": time.perf_counter() - started,
    }
