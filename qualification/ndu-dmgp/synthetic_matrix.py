"""Deterministic synthetic A0..A5 research comparison; NEVER actual model efficacy.

Provides a stable paired potential-outcome oracle solely to validate routing,
recursive stopping, accounting and train/future isolation. Cannot justify causal
claims on observational trajectories or qualify real image/audio/video decoders.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from random import Random
from statistics import mean
from time import perf_counter_ns

from shadow_reference import (
    EXPERIMENT_MODES, EvidenceError, InsufficientSupport, JointSample,
    choose_portfolio, conditional_covariance,
)

COSTS = {"fast": 1., "high": 4., "verify": 1., "stop": 0.}
COST_RATE = 0.04  # registered synthetic cost/unit, frozen across all modes
QUALITY_MODEL = {  # frozen policy prediction, not fitted on held-out labels
    "easy": {"fast": .70, "high": .84, "verified_fast": .80},
    "hard": {"fast": .33, "high": .58, "verified_fast": .72},
}


@dataclass(frozen=True)
class Episode:
    episode_id: str
    split: str
    context: str
    fast_quality: float
    high_quality: float
    verified_fast_quality: float


def independent_synthetic_episodes(count: int, seed: int, split: str) -> list[Episode]:
    if split not in ("train", "future", "retention") or count <= 0:
        raise EvidenceError("invalid synthetic episode design")
    rng = Random(seed)
    rows = []
    for n in range(count):
        context = "hard" if rng.random() < .45 else "easy"
        target = {"easy": (.70, .85, .80), "hard": (.30, .60, .75)}[context]
        shared_error = rng.gauss(0, .04)
        quality = [max(0., min(1., t + shared_error + rng.gauss(0,.035))) for t in target]
        rows.append(Episode(f"{split}-{seed}-{n}", split, context, *quality))
    return rows


def frozen_expected_ndu(context: str, action: str, verified: bool = False) -> float:
    key = "verified_fast" if action == "fast" and verified else action
    return QUALITY_MODEL[context][key] - COST_RATE*COSTS[action]


def _receding_horizon(context: str, verified: bool, budget: int, depth: int) -> tuple[str, float]:
    choices: list[tuple[str, float]] = [("stop", 0.)]
    if budget >= COSTS["fast"]:
        choices.append(("fast", frozen_expected_ndu(context, "fast", verified)))
    if budget >= COSTS["high"]:
        choices.append(("high", frozen_expected_ndu(context, "high", verified)))
    if not verified and depth > 1 and budget >= COSTS["verify"]:
        _, continuation = _receding_horizon(context, True, budget-1, depth-1)
        choices.append(("verify", -COST_RATE*COSTS["verify"]+continuation))
    return max(choices, key=lambda p: p[1])


def _stable_roll(seed: int, episode_id: str) -> float:
    digest = sha256(f"{seed}:{episode_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")/(1<<64)


def _route_from_portfolio(weights: tuple[float, ...], roll: float) -> str:
    subtotal = 0.
    for idx, weight in enumerate(weights):
        subtotal += weight
        if roll < subtotal:
            return ("fast", "high")[idx]
    return "high"


def _select_actions(mode: str, e: Episode, budget: int,
                    covariances: dict, seed: int) -> tuple[list[str], bool]:
    if mode == "A0":
        return ["fast"], False
    if mode == "A1":
        return ["high"], False
    if mode == "A2":
        return ["high" if e.context == "hard" else "fast"], False
    if mode == "A3":
        return [max(("fast", "high"), key=lambda a: frozen_expected_ndu(e.context, a))], False
    if mode == "A4":
        gains = [frozen_expected_ndu(e.context, a) for a in ("fast", "high")]
        try:
            choice = choose_portfolio(gains, [1.,4.], budget, gamma=3.,
                                      covariance=covariances[e.context], beta=.02, slots=20)
            return [_route_from_portfolio(choice.weights, _stable_roll(seed, e.episode_id))], False
        except InsufficientSupport:
            return [max(("fast", "high"), key=lambda a: frozen_expected_ndu(e.context, a))], True
    if mode == "A5":
        actions = []
        verified = False
        remaining = budget
        for depth in (2, 1):
            action, _ = _receding_horizon(e.context, verified, remaining, depth)
            if action == "stop":
                return actions or ["stop"], False
            actions.append(action)
            remaining -= int(COSTS[action])
            if action == "verify":
                verified = True
                continue
            return actions, False
        return actions or ["stop"], False
    raise EvidenceError("unregistered experimental mode")


def _simulate(e: Episode, actions: list[str], budget: int) -> tuple[float, float, float]:
    if not actions or any(a not in COSTS for a in actions):
        raise EvidenceError("unregistered or empty action trace")
    verified = False
    cost = 0.
    quality = 0.
    terminal = False
    for idx, action in enumerate(actions):
        cost += COSTS[action]
        if cost > budget:
            raise EvidenceError("hard budget overspend")
        if action == "verify":
            if verified or idx == len(actions)-1:
                raise EvidenceError("invalid verification sequence")
            verified = True
        else:
            if idx != len(actions)-1:
                raise EvidenceError("terminal action must be last")
            quality = (e.verified_fast_quality if verified else e.fast_quality) if action == "fast" else (e.high_quality if action == "high" else 0.)
            terminal = True
    if not terminal:
        raise EvidenceError("trajectory did not terminate")
    return quality, cost, quality-COST_RATE*cost


def run_synthetic_matrix(seed: int = 124, n_train: int = 256,
                         n_future: int = 256, budget: int = 5) -> dict:
    if budget < 4 or n_train < 20 or n_future <= 0:
        raise EvidenceError("unsupported synthetic study design")
    train = independent_synthetic_episodes(n_train, seed, "train")
    future = independent_synthetic_episodes(n_future, seed+1, "future")
    # Model/conditional moments from TRAIN only. Future potential outcomes
    # never enter the optimizer or model estimates.
    samples = [JointSample(e.context,
                           (e.fast_quality-COST_RATE, e.high_quality-COST_RATE*4),
                           1., "train") for e in train]
    covariances = {}
    for context in ("easy", "hard"):
        try:
            covariances[context] = conditional_covariance(samples, context, 2, rank=2)
        except InsufficientSupport:
            covariances[context] = None
    results = {}
    for mode in EXPERIMENT_MODES:
        utilities, qualities, costs, controller_ms, total_ms = [], [], [], [], []
        fallbacks, violations = 0, 0
        for e in future:
            tic = perf_counter_ns()
            actions, fallback = _select_actions(mode, e, budget, covariances, seed)
            elapsed_ms = (perf_counter_ns()-tic)/1e6
            fallbacks += int(fallback)
            try:
                q, cost, u = _simulate(e, actions, budget)
            except EvidenceError:
                violations += 1
                raise
            qualities.append(q)
            utilities.append(u)
            costs.append(cost)
            controller_ms.append(elapsed_ms)
            # A toy cost proxy only: this is NOT measured decoder latency.
            total_ms.append(cost + elapsed_ms)
        total_ms.sort()
        results[mode] = {
            "mean_observed_utility": round(mean(utilities), 6),
            "mean_quality": round(mean(qualities), 6),
            "mean_synthetic_cost_units": round(mean(costs), 6),
            "mean_measured_controller_ms": round(mean(controller_ms), 6),
            "p95_proxy_total_ms": round(total_ms[max(0, int(.95*len(total_ms))-1)], 6),
            "hard_budget_violations": violations,
            "covariance_fallbacks": fallbacks,
            "episodes": len(future),
        }
    return {
        "qualification": "SHADOW_SYNTHETIC_ONLY",
        "selected_for_production": False,
        "seed": seed,
        "budget": budget,
        "train_episode_count": len(train),
        "future_episode_count": len(future),
        "covariance_supported_contexts": [k for k,v in covariances.items() if v],
        "experiments": results,
        "limitations": [
            "No real multimodal input, decoder, GPU, memory or energy measurement",
            "Synthetic oracle potential outcomes do not identify real-world causal effects",
            "A5 is finite-horizon deterministic recursive planning, not a solved stochastic FBSDE",
            "No independent human/model quality judgments or production receipts",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run_synthetic_matrix(), indent=2, ensure_ascii=False, sort_keys=True))
