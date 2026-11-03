#!/usr/bin/env python3
"""Small, dependency-free NDU–Merton portfolio prototype.

This is a qualification simulator, not an LLM trainer. It models three resource
accounts (per-request inference, world-model rollout, and slow training) and
allocates a finite budget over action/thinking/tool/branch assets with a
risk-sensitive, KL-regularized portfolio objective.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
import random
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class Asset:
    name: str
    kind: str
    quality: float       # estimated marginal utility before cost/risk
    cost: float          # token/FLOP/rollout cost
    prior: float = 1.0


@dataclass
class LayerResult:
    name: str
    budget: float
    reserve: float
    weights: Dict[str, float]
    active_mass: float
    unallocated_mass: float
    expected_cost: float
    objective: float
    stop: bool
    chosen: str


def _normalize(xs: Sequence[float]) -> List[float]:
    total = sum(xs)
    if total <= 0.0:
        return [1.0 / len(xs)] * len(xs)
    return [x / total for x in xs]


def _softmax(xs: Sequence[float]) -> List[float]:
    m = max(xs)
    exps = [math.exp(max(-60.0, min(60.0, x - m))) for x in xs]
    return _normalize(exps)


def _kl(weights: Sequence[float], prior: Sequence[float]) -> float:
    value = 0.0
    for p, q in zip(weights, prior):
        if p > 0.0 and q > 0.0:
            value += p * math.log(p / q)
    return value


def _quad(weights: Sequence[float], covariance: Sequence[Sequence[float]]) -> float:
    return sum(
        weights[i] * weights[j] * covariance[i][j]
        for i in range(len(weights))
        for j in range(len(weights))
    )


def portfolio_objective(
    weights: Sequence[float],
    assets: Sequence[Asset],
    covariance: Sequence[Sequence[float]],
    gamma: float,
    temperature: float,
    cost_shadow: float,
) -> float:
    qualities = sum(p * a.quality for p, a in zip(weights, assets))
    costs = sum(p * a.cost for p, a in zip(weights, assets))
    # KL penalty is the discrete analogue of recursive entropy regularization.
    prior = _normalize([a.prior for a in assets])
    return (
        qualities
        - cost_shadow * costs
        - 0.5 * gamma * _quad(weights, covariance)
        - temperature * _kl(weights, prior)
    )


def gibbs_portfolio(
    assets: Sequence[Asset],
    covariance: Sequence[Sequence[float]],
    budget: float,
    reserve: float,
    gamma: float,
    temperature: float,
    cost_shadow: float,
    stop_utility: float,
) -> Tuple[List[float], bool, float]:
    """Return (weights, stopped, objective) under a finite budget.

    The Gibbs score is a first-order router; covariance and budget are then
    enforced explicitly. This keeps the prototype transparent and deterministic
    while preserving the Merton analogy (marginal return, risk, shadow price).
    """
    if budget <= reserve or not assets:
        return [0.0] * len(assets), True, stop_utility

    # A diagonal risk proxy gives a stable Gibbs proposal; the full covariance
    # is evaluated and reported in the objective below.
    scores = [
        a.quality - cost_shadow * a.cost - 0.5 * gamma * covariance[i][i]
        for i, a in enumerate(assets)
    ]
    prior = _normalize([a.prior for a in assets])
    logits = [math.log(max(1e-12, q)) + s / max(temperature, 1e-9)
              for q, s in zip(prior, scores)]
    raw = _softmax(logits)

    # Reserve is a hard uncommitted wealth fraction. Scale the active portfolio
    # to satisfy the expected cost constraint rather than allowing the router to
    # spend away solvency.
    active_budget = max(0.0, budget - reserve)
    expected_cost = sum(p * a.cost for p, a in zip(raw, assets))
    scale = min(1.0, active_budget / expected_cost) if expected_cost > 0 else 1.0
    weights = [scale * p for p in raw]
    expected_cost = sum(p * a.cost for p, a in zip(weights, assets))
    objective = portfolio_objective(
        weights, assets, covariance, gamma, temperature, cost_shadow
    )
    if objective <= stop_utility:
        return [0.0] * len(assets), True, stop_utility
    return weights, False, objective


def _covariance(stds: Sequence[float], common: float = 0.15) -> List[List[float]]:
    """Positive semidefinite common-factor covariance."""
    return [
        [stds[i] * stds[j] * (common + (1.0 - common if i == j else 0.0))
         for j in range(len(stds))]
        for i in range(len(stds))
    ]


def default_accounts() -> Dict[str, Tuple[float, float, List[Asset], List[List[float]]]]:
    """Return (budget, reserve, assets, covariance) for the three accounts."""
    inference = [
        Asset("direct_action", "action", 0.92, 1.0, 1.5),
        Asset("think_token", "thinking", 0.35, 0.55, 1.0),
        Asset("retrieve", "thinking", 0.70, 2.5, 0.8),
        Asset("verify", "thinking", 0.64, 2.0, 0.8),
        Asset("branch", "thinking", 0.50, 3.0, 0.6),
    ]
    rollout = [
        Asset("latent_dynamics_0", "world_model", 0.68, 4.0, 1.0),
        Asset("latent_dynamics_1", "world_model", 0.63, 4.5, 1.0),
        Asset("observation", "world_model", 0.74, 3.0, 0.9),
        Asset("planning_branch", "world_model", 0.58, 6.0, 0.7),
    ]
    training = [
        Asset("text_batch", "training", 0.70, 12.0, 1.0),
        Asset("vision_batch", "training", 0.58, 14.0, 0.8),
        Asset("cell_adapter", "training", 0.66, 5.0, 1.2),
        Asset("shared_encoder", "training", 0.44, 35.0, 0.6),
    ]
    return {
        "inference": (12.0, 1.5, inference, _covariance([0.26, 0.35, 0.42, 0.30, 0.50], 0.20)),
        "rollout": (20.0, 3.0, rollout, _covariance([0.34, 0.37, 0.29, 0.52], 0.25)),
        "training": (100.0, 10.0, training, _covariance([0.33, 0.39, 0.31, 0.55], 0.30)),
    }


def run(seed: int = 17, gamma: float = 1.2, temperature: float = 0.18,
        cost_shadow: float = 0.06) -> Dict[str, object]:
    rng = random.Random(seed)
    results: List[LayerResult] = []
    for name, (budget, reserve, assets, covariance) in default_accounts().items():
        # Independent held-out outcome proxy. It is deliberately not used to
        # choose the policy; it only checks that the router has a measurable
        # external quantity to compare in later experiments.
        held_out = {a.name: a.quality + rng.gauss(0.0, 0.03) for a in assets}
        weights, stopped, objective = gibbs_portfolio(
            assets, covariance, budget, reserve, gamma, temperature,
            cost_shadow, stop_utility=0.05,
        )
        expected_cost = sum(p * a.cost for p, a in zip(weights, assets))
        chosen = "STOP" if stopped else max(
            ((p, a.name) for p, a in zip(weights, assets)), default=(0.0, "STOP")
        )[1]
        results.append(LayerResult(
            name=name,
            budget=budget,
            reserve=reserve,
            weights={a.name: round(p, 8) for p, a in zip(weights, assets)},
            active_mass=sum(weights),
            unallocated_mass=max(0.0, 1.0 - sum(weights)),
            expected_cost=expected_cost,
            objective=objective,
            stop=stopped,
            chosen=chosen,
        ))
    return {
        "seed": seed,
        "gamma": gamma,
        "temperature": temperature,
        "cost_shadow": cost_shadow,
        "accounts": [r.__dict__ for r in results],
        "protocol": {
            "selected_weights_are_advisory": True,
            "production_authority": "DENY_ALL",
            "outcome_proxy_is_held_out": True,
            "note": "qualification simulator; no model weights or provider dispatch",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--gamma", type=float, default=1.2)
    parser.add_argument("--temperature", type=float, default=0.18)
    parser.add_argument("--cost-shadow", type=float, default=0.06)
    args = parser.parse_args()
    print(json.dumps(run(args.seed, args.gamma, args.temperature, args.cost_shadow), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
