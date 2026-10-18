"""Independent analytic/Monte Carlo reference for the NDU FBSDE TREE shadow.

Qualification-only. This deliberately solves dX=dW, f=0, g(x)=x^2, T=1.
It does not claim a learned neural FBSDE solver or a general coupled FBSDE.
The binomial tree matches Brownian first and second moments for this payoff,
and held-out Gaussian paths independently estimate E[g(X_T)|X_0=0].
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random


@dataclass(frozen=True)
class AnalyticReceipt:
    schema: str
    driver: str
    steps: int
    node_count: int
    root_value: float
    exact_global_value: float
    maximum_value_field_error: float
    maximum_z_covariance_error: float
    terminal_residual: float
    single_branch_terminal_value: float
    single_branch_global_gap: float
    train_estimate: float
    train_standard_error: float
    heldout_estimate: float
    heldout_standard_error: float
    heldout_pass: bool
    authority: str = "DENY_ALL"
    production_activated: bool = False
    learned_model_efficacy_measured: bool = False

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    def evidence_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_json().encode()).hexdigest()


def _grid(steps: int) -> tuple[dict[tuple[int, ...], float], float]:
    if type(steps) is not int or not 1 <= steps <= 10:
        raise ValueError("steps must be 1..10")
    dt = 1.0 / steps
    states = {(): 0.0}
    for depth in range(steps):
        for path, x in tuple(states.items()):
            if len(path) != depth:
                continue
            states[path + (0,)] = x - math.sqrt(dt)
            states[path + (1,)] = x + math.sqrt(dt)
    return states, dt


def _gaussian_paths(seed: int, samples: int, steps: int) -> tuple[float, float]:
    if type(seed) is not int or type(samples) is not int or samples < 2:
        raise ValueError("need seed and at least two independent samples")
    generator = random.Random(seed)
    sigma = math.sqrt(1.0 / steps)
    terminal_payoffs = [
        sum(generator.gauss(0.0, sigma) for _ in range(steps)) ** 2
        for _ in range(samples)
    ]
    mean = sum(terminal_payoffs) / samples
    variance = sum((payoff - mean) ** 2 for payoff in terminal_payoffs) / (samples - 1)
    return mean, math.sqrt(variance / samples)


def evaluate_analytic_reference(
    *,
    steps: int = 4,
    samples: int = 8192,
    train_seed: int = 1729,
    heldout_seed: int = 1931,
) -> AnalyticReceipt:
    if train_seed == heldout_seed:
        raise ValueError("train and held-out path seeds must be independent")
    states, dt = _grid(steps)
    values = {
        path: x * x for path, x in states.items() if len(path) == steps
    }
    maximum_z_error = 0.0
    maximum_value_error = 0.0
    terminal_residual = max(
        abs(values[path] - x * x)
        for path, x in states.items() if len(path) == steps
    )

    for depth in range(steps - 1, -1, -1):
        for path, x in states.items():
            if len(path) != depth:
                continue
            left = values[path + (0,)]
            right = values[path + (1,)]
            parent = (left + right) / 2.0
            values[path] = parent
            # Cov(Y_next, DeltaW | F_k) / Var(DeltaW | F_k)
            # for symmetric increments ±sqrt(dt). Exact Z(t,x)=2x.
            covariance = ((left - parent) * -math.sqrt(dt)
                          + (right - parent) * math.sqrt(dt)) / 2.0
            z = covariance / dt
            maximum_z_error = max(maximum_z_error, abs(z - 2.0 * x))
            exact_local = x * x + (1.0 - depth * dt)
            maximum_value_error = max(
                maximum_value_error, abs(parent - exact_local)
            )

    train_mean, train_se = _gaussian_paths(train_seed, samples, steps)
    heldout_mean, heldout_se = _gaussian_paths(heldout_seed, samples, steps)
    exact_root = 1.0
    # Four standard errors is a conservative, reproducible diagnostic, not
    # a confidence guarantee for other data/model/selection procedures.
    heldout_pass = (
        abs(train_mean - exact_root) <= 4.0 * train_se
        and abs(heldout_mean - exact_root) <= 4.0 * heldout_se
        and abs(train_mean - heldout_mean)
        <= 4.0 * math.hypot(train_se, heldout_se)
    )
    single_branch = values[(1,) * steps]
    return AnalyticReceipt(
        schema="hepta.ndu.fbsde.analytic-reference.v1",
        driver="dX=dW; f=0; g(X_T)=X_T^2; T=1",
        steps=steps,
        node_count=len(states),
        root_value=values[()],
        exact_global_value=exact_root,
        maximum_value_field_error=maximum_value_error,
        maximum_z_covariance_error=maximum_z_error,
        terminal_residual=terminal_residual,
        single_branch_terminal_value=single_branch,
        single_branch_global_gap=abs(single_branch - exact_root),
        train_estimate=train_mean,
        train_standard_error=train_se,
        heldout_estimate=heldout_mean,
        heldout_standard_error=heldout_se,
        heldout_pass=heldout_pass,
    )


if __name__ == "__main__":
    result = evaluate_analytic_reference()
    print(result.canonical_json())
    print(result.evidence_digest())
