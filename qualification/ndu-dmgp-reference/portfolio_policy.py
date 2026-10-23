#!/usr/bin/env python3
"""Qualification-only, non-authorizing A0-A5 portfolio policy reference.

A4/A5 produce probabilities over *mutually exclusive* authorized actions;
never mix incompatible decoder latents or grant an execution permission.
"""

from __future__ import annotations

import math
from typing import Any

from ndu_dmgp import EvidenceError, finite, nonempty, require, digest


ARMS = ("A0", "A1", "A2", "A3", "A4", "A5")


def _softmax(x: list[float]) -> list[float]:
    origin = max(x)
    exps = [math.exp(max(-80, v - origin)) for v in x]
    total = sum(exps)
    return [v / total for v in exps]


def _risk(covariance: dict[str, Any], width: int) -> list[list[float]]:
    diagonal = covariance.get("diagonal")
    factors = covariance.get("factors")
    require(isinstance(diagonal, list) and len(diagonal) == width, "risk: mismatched diagonal width")
    require(isinstance(factors, list) and all(isinstance(f, list) and len(f) == width for f in factors),
            "risk: mismatched factor width")
    d = [finite(v, "risk.diagonal", 1e-12, 100) for v in diagonal]
    f = [[finite(v, "risk.factor", -10, 10) for v in row] for row in factors]
    return [[(d[i] if i == j else 0.0) + sum(v[i] * v[j] for v in f)
             for j in range(width)] for i in range(width)]


def _portfolio_weights(values: list[float], cov: list[list[float]], gamma: float, beta: float) -> list[float]:
    """Mirror-ascent surrogate; no global FBSDE/HJB optimality claim."""
    n = len(values)
    require(1 <= n <= 8, "portfolio: expected 1..8 admitted actions")
    w = [1.0 / n] * n
    base = [1.0 / n] * n
    for _ in range(128):
        gradient = [values[i] - gamma * sum(cov[i][j] * w[j] for j in range(n))
                    - beta * math.log(max(w[i], 1e-15) / base[i]) for i in range(n)]
        next_w = _softmax([math.log(max(w[i], 1e-15)) + 0.2 * gradient[i] for i in range(n)])
        if max(abs(a - b) for a, b in zip(w, next_w)) < 1e-8:
            w = next_w
            break
        w = next_w
    require(abs(sum(w) - 1.0) < 1e-9 and all(0 <= v <= 1 for v in w), "portfolio: simplex failure")
    return w


def choose(arm: str, context: dict[str, Any], actions: list[dict[str, Any]],
           covariance: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return purely advisory selection probabilities / explicit abstention.

    Future input state and snapshots must be bound before calling. Current
    state/authority is immutable. Action legality is decided upstream; unknown
    or non-authorized actions are never included in the scored set.
    """
    require(arm in ARMS, "policy: unknown arm")
    objective = nonempty(context.get("objective_digest"), "policy.objective_digest")
    selected_snapshot = nonempty(context.get("selected_snapshot_digest"), "policy.selected_snapshot_digest")
    state = nonempty(context.get("state_digest"), "policy.state_digest")
    budget = finite(context.get("remaining_compute_units"), "policy.remaining_compute_units", 0, 1e12)
    min_quality = finite(context.get("minimum_predicted_quality"), "policy.minimum_predicted_quality", 0, 1)
    require(context.get("terminal_requirements_satisfied") in (True, False),
            "policy: terminal state unsupported")
    require(isinstance(actions, list) and len(actions) <= 16, "policy: too many action candidates")
    seen: set[str] = set()
    admitted: list[dict[str, Any]] = []
    abstain = False
    for row in actions:
        action = nonempty(row.get("id"), "policy.action.id")
        require(action not in seen, "policy: duplicate action identity")
        seen.add(action)
        require(row.get("objective_digest") == objective and row.get("snapshot_digest") == selected_snapshot,
                "policy: mixed objective or generation")
        if action == "abstain":
            require(row.get("authorized") is True and row.get("hard_constraints_ok") is True,
                    "policy: abstain must be feasible")
            abstain = True
            continue
        cost = finite(row.get("compute_units"), "policy.action.compute_units", 0, 1e12)
        quality = finite(row.get("predicted_quality"), "policy.action.predicted_quality", 0, 1)
        instant = finite(row.get("instant_ndu"), "policy.action.instant_ndu", -1, 1)
        recursive = finite(row.get("recursive_ndu"), "policy.action.recursive_ndu", -1, 1)
        if action == "stop" and not context["terminal_requirements_satisfied"]:
            continue
        if row.get("authorized") is not True or row.get("hard_constraints_ok") is not True:
            continue
        if cost > budget or quality < min_quality:
            continue
        admitted.append({"id": action, "compute_units": cost, "predicted_quality": quality,
                         "instant_ndu": instant, "recursive_ndu": recursive})
    require(abstain, "policy: missing feasible abstain")
    if not admitted:
        return {"requested_arm": arm, "evaluated_arm": "abstain", "route": "abstain",
                "probabilities": {"abstain": 1.0}, "reason": "no_feasible_actions",
                "objective_digest": objective, "state_digest": state,
                "selected_snapshot_digest": selected_snapshot, "advisory_only": True}
    admitted.sort(key=lambda r: r["id"])
    effective_arm = arm
    reason = "admitted"
    if arm in ("A4", "A5"):
        matched = (isinstance(covariance, dict) and
                   covariance.get("action_ids") == [r["id"] for r in admitted] and
                   covariance.get("state_digest") == state and
                   covariance.get("qualified") is True)
        if matched:
            try:
                risk = _risk(covariance, len(admitted))
            except EvidenceError:
                matched = False
        if not matched:
            # Fail closed to deterministic one-step NDU, never invent covariance.
            effective_arm = "A3"
            reason = "unsupported_conditional_covariance_deterministic_ndu_fallback"
    if effective_arm in ("A4", "A5"):
        values = [row["instant_ndu" if effective_arm == "A4" else "recursive_ndu"] for row in admitted]
        gamma = finite(context.get("risk_aversion"), "policy.risk_aversion", 0, 100)
        beta = finite(context.get("kl_penalty"), "policy.kl_penalty", 0.0001, 10)
        probs = _portfolio_weights(values, risk, gamma, beta)
        weights = {row["id"]: p for row, p in zip(admitted, probs)}
        route = "stochastic_policy_proposal"
    else:
        if effective_arm == "A0":
            matched = [row for row in admitted if row["id"] == context.get("default_action_id")]
            chosen = matched[0] if matched else None
        elif effective_arm == "A1":
            chosen = min(admitted, key=lambda r: (r["compute_units"], r["id"]))
        elif effective_arm == "A2":
            chosen = max(admitted, key=lambda r: (r["predicted_quality"] / max(r["compute_units"], 1e-9), r["id"]))
        else:
            chosen = max(admitted, key=lambda r: (r["instant_ndu"], r["id"]))
        if chosen is None:
            weights, route = {"abstain": 1.0}, "abstain"
            reason = "default_action_not_admitted"
        else:
            weights, route = {chosen["id"]: 1.0}, "deterministic_action_proposal"
    result = {"requested_arm": arm, "evaluated_arm": effective_arm,
              "route": route, "probabilities": weights, "reason": reason,
              "objective_digest": objective, "state_digest": state,
              "selected_snapshot_digest": selected_snapshot, "advisory_only": True}
    result["proposal_digest"] = digest(result)
    return result
