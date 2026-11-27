"""Qualification-only NDU-DMGP portfolio primitives. No execution authority.

This is a deterministic research reference, not a replacement for the
versioned Rust NDU owner or an FBSDE implementation.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class Candidate:
    identity: str
    expected_ndu: float
    cost: float
    duration_ms: float
    hard_feasible: bool
    evidence_digest: str
    objective_digest: str
    generation: int
    observer_id: str


def select_deterministic(candidates: Sequence[Candidate], *,
                         objective_digest: str, generation: int,
                         max_cost: float, max_duration_ms: float) -> Candidate:
    """Admissibility before utility. Includes explicit abstention."""
    if not candidates or not objective_digest:
        raise ValueError("missing objective or candidates")
    if len({c.identity for c in candidates}) != len(candidates):
        raise ValueError("duplicate candidate")
    abstain = [c for c in candidates if c.identity == "abstain"]
    if len(abstain) != 1 or not abstain[0].hard_feasible:
        raise ValueError("feasible abstain required")
    valid = []
    for c in candidates:
        if not c.evidence_digest or not c.observer_id:
            raise ValueError("unverifiable candidate")
        if c.objective_digest != objective_digest or c.generation != generation:
            raise ValueError("mixed objective/generation")
        if not all(isfinite(x) for x in (c.expected_ndu, c.cost, c.duration_ms)):
            raise ValueError("nonfinite values")
        if c.cost < 0 or c.duration_ms < 0:
            raise ValueError("negative resources")
        if c.hard_feasible and c.cost <= max_cost and c.duration_ms <= max_duration_ms:
            valid.append(c)
    if not valid:
        raise ValueError("no feasible candidate")
    best_value = max(x.expected_ndu for x in valid)
    ties = [c for c in valid if c.expected_ndu == best_value]
    if len(ties) != 1:
        raise ValueError("utility tie: slow path required")
    return ties[0]


def shrink_covariance(samples: Sequence[Sequence[float]], *, alpha: float = 0.25,
                      min_samples: int = 8, ridge: float = 1e-8):
    """Conservative full-matrix covariance with diagonal shrinkage.

    Samples are JOINT same-episode candidate returns, not independent
    per-expert marginals. Caller must validate independent observer lineage,
    time/episode grouping and conditional support; this helper cannot.
    """
    if not 0 <= alpha <= 1 or ridge <= 0:
        raise ValueError("invalid covariance profile")
    n = len(samples)
    if n < min_samples or n < 2:
        return None
    d = len(samples[0])
    if not 1 <= d <= 32 or any(len(row) != d for row in samples):
        raise ValueError("ragged/unsupported joint samples")
    if any(not isfinite(v) for row in samples for v in row):
        raise ValueError("nonfinite joint samples")
    means = [sum(row[j] for row in samples) / n for j in range(d)]
    raw = [[sum((row[i] - means[i]) * (row[j] - means[j])
                for row in samples) / (n - 1) for j in range(d)]
           for i in range(d)]
    return [[(1 - alpha) * raw[i][j] +
             (alpha * raw[i][i] if i == j else 0.0) +
             (ridge if i == j else 0.0)
             for j in range(d)] for i in range(d)]


def portfolio_objective(weights, advantages, covariance, gamma, costs,
                        max_cost):
    """Local quadratic surrogate, NOT a global NDU-FBSDE optimum."""
    n = len(weights)
    if n == 0 or any(len(x) != n for x in (advantages, costs, covariance)):
        raise ValueError("dimension mismatch")
    if any(len(row) != n for row in covariance):
        raise ValueError("dimension mismatch")
    flat = list(weights) + list(advantages) + list(costs)
    flat += [x for row in covariance for x in row]
    if not all(isfinite(x) for x in flat + [gamma, max_cost]):
        raise ValueError("nonfinite inputs")
    if gamma < 0 or any(x < 0 for x in costs):
        raise ValueError("invalid risk/resource values")
    if any(w < 0 for w in weights) or abs(sum(weights) - 1) > 1e-9:
        raise ValueError("weights must be on simplex")
    if sum(w * c for w, c in zip(weights, costs)) > max_cost:
        raise ValueError("budget violated")
    variance = sum(weights[i] * covariance[i][j] * weights[j]
                   for i in range(n) for j in range(n))
    if variance < -1e-9:
        raise ValueError("invalid covariance")
    return sum(w * a for w, a in zip(weights, advantages)) - 0.5 * gamma * max(variance, 0)


def state_closure_delta(baseline_errors, history_errors):
    """Positive delta means omitted history improves held-out prediction."""
    if not baseline_errors or len(baseline_errors) != len(history_errors):
        raise ValueError("paired held-out errors required")
    if any(not isfinite(x) or x < 0 for x in list(baseline_errors) + list(history_errors)):
        raise ValueError("invalid errors")
    return (sum(baseline_errors) - sum(history_errors)) / len(baseline_errors)
