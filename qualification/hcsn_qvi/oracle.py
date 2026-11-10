"""Small discounted impulse-control oracle with an explicit finite model.

The bounded birth/death generator reflects at both endpoints. Continuing
earns g(x)=x; intervention pays -cost, waits a deterministic zero-reward
delay, then resets with linear interpolation on the fixed grid. Uniformized
Bellman equations are equivalent to this *finite* generator's QVI. This is
not a continuum free-boundary certificate or the HCSN neural training task.
"""

from dataclasses import dataclass
import math
import time

import numpy as np


@dataclass(frozen=True)
class Problem:
    nodes: int = 41
    upper: float = 2.0
    mu: float = -0.2
    sigma: float = 0.35
    discount: float = 0.15
    reset: float = 1.37
    delay: float = 0.2
    cost: float = 0.6
    initial: float = 0.8


class FiniteControl:
    """Two-action finite discounted problem; no simulation or reward fitting."""

    def __init__(self, problem=Problem()):
        if (
            isinstance(problem.nodes, bool)
            or not isinstance(problem.nodes, int)
            or not 3 <= problem.nodes <= 128
        ):
            raise ValueError("nodes must be an integer in [3,128]")
        numbers = (
            problem.upper,
            problem.mu,
            problem.sigma,
            problem.discount,
            problem.reset,
            problem.delay,
            problem.cost,
            problem.initial,
        )
        if not all(math.isfinite(v) for v in numbers):
            raise ValueError("finite real problem parameters required")
        if (
            min(problem.upper, problem.sigma, problem.discount, problem.delay) <= 0
            or problem.cost < 0
        ):
            raise ValueError(
                "positive geometry/noise/discount/delay and nonnegative cost required"
            )
        if (
            not 0 <= problem.initial <= problem.upper
            or not 0 <= problem.reset <= problem.upper
        ):
            raise ValueError("initial and reset must be inside the bounded domain")
        self.problem = problem
        self.x = np.linspace(0.0, problem.upper, problem.nodes)
        self.spacing = problem.upper / (problem.nodes - 1)
        upward = (
            problem.sigma**2 / (2 * self.spacing**2) + max(problem.mu, 0) / self.spacing
        )
        downward = (
            problem.sigma**2 / (2 * self.spacing**2)
            + max(-problem.mu, 0) / self.spacing
        )
        generator = np.zeros((problem.nodes, problem.nodes))
        for i in range(problem.nodes):
            if i < problem.nodes - 1:
                generator[i, i + 1] = upward
            if i > 0:
                generator[i, i - 1] = downward
            generator[i, i] = -generator[i].sum()
        self.generator = generator
        self.clock_rate = upward + downward
        transition = np.eye(problem.nodes) + generator / self.clock_rate
        if np.min(transition) < 0 or np.max(np.abs(transition.sum(1) - 1)) > 1e-14:
            raise FloatingPointError("invalid uniformized transition")
        self.wait_kernel = (
            transition * self.clock_rate / (problem.discount + self.clock_rate)
        )
        self.wait_reward = self.x / (problem.discount + self.clock_rate)
        self.reset_weights = self.point_weights(problem.reset)
        self.intervention_kernel = np.broadcast_to(
            math.exp(-problem.discount * problem.delay) * self.reset_weights,
            self.wait_kernel.shape,
        )
        self.intervention_reward = np.full(problem.nodes, -problem.cost)
        self.initial_weights = self.point_weights(problem.initial)
        self.contraction = max(
            self.clock_rate / (problem.discount + self.clock_rate),
            math.exp(-problem.discount * problem.delay),
        )

    def point_weights(self, point):
        weights = np.zeros(self.problem.nodes)
        lower = min(int(point / self.spacing), self.problem.nodes - 2)
        fraction = (point - self.x[lower]) / self.spacing
        weights[lower], weights[lower + 1] = 1 - fraction, fraction
        return weights

    def action_values(self, value):
        return (
            self.wait_reward + self.wait_kernel @ value,
            self.intervention_reward + self.intervention_kernel @ value,
        )

    def evaluate(self, intervention_probability):
        probability = np.asarray(intervention_probability, dtype=float)
        if (
            probability.shape != self.x.shape
            or not np.isfinite(probability).all()
            or np.any((probability < 0) | (probability > 1))
        ):
            raise ValueError("one intervention probability in [0,1] per state required")
        kernel = (1 - probability[:, None]) * self.wait_kernel + probability[
            :, None
        ] * self.intervention_kernel
        reward = (
            1 - probability
        ) * self.wait_reward + probability * self.intervention_reward
        system = np.eye(self.problem.nodes) - kernel
        value = np.linalg.solve(system, reward)
        if not np.isfinite(value).all():
            raise FloatingPointError("policy value is unresolved")
        return value, system

    def policy_iteration(self, maximum=256):
        started = time.perf_counter()
        policy = np.zeros(self.problem.nodes, dtype=bool)
        active_history = []
        for count in range(1, maximum + 1):
            value, system = self.evaluate(policy)
            wait, intervene = self.action_values(value)
            updated = intervene > wait + 1e-13
            active_history.append(int(updated.sum()))
            if np.array_equal(updated, policy):
                residual = float(np.max(np.abs(np.maximum(wait, intervene) - value)))
                if residual > 1e-10:
                    raise FloatingPointError(
                        "QVI Bellman residual exceeded the fixed limit"
                    )
                return dict(
                    value=value,
                    policy=policy,
                    system=system,
                    iterations=count,
                    bellman_residual=residual,
                    active_history=active_history,
                    condition_inf=float(np.linalg.cond(system, np.inf)),
                    wall_seconds=time.perf_counter() - started,
                )
            policy = updated
        raise RuntimeError("policy iteration did not converge within its budget")

    def value_iteration(self, tolerance=1e-9, maximum=200000):
        """Independent contraction iteration with an a posteriori error bound."""
        started = time.perf_counter()
        value = np.zeros_like(self.x)
        for count in range(1, maximum + 1):
            updated = np.maximum(*self.action_values(value))
            change = float(np.max(np.abs(updated - value)))
            bound = self.contraction * change / (1 - self.contraction)
            value = updated
            if bound <= tolerance:
                return dict(
                    value=value,
                    iterations=count,
                    value_error_bound=bound,
                    wall_seconds=time.perf_counter() - started,
                )
        raise RuntimeError("value iteration did not reach its declared error bound")

    def fit_soft_threshold(self, initial=0.4, temperature=0.08, updates=32):
        """Fit one ordinary logistic threshold by implicit policy-value gradients.

        Each line-search candidate is counted. This optimizer never consumes
        the optimal policy or its boundary; it is not a neural-task comparison.
        """
        if temperature <= 0 or not 0 <= initial <= self.problem.upper:
            raise ValueError(
                "positive temperature and in-domain initial threshold required"
            )
        started = time.perf_counter()
        threshold, solves, gradient_solves = initial, 0, 0
        history = []
        for _ in range(updates):
            probability = 0.5 * (1 + np.tanh((threshold - self.x) / (2 * temperature)))
            value, system = self.evaluate(probability)
            solves += 1
            objective = float(self.initial_weights @ value)
            wait, intervene = self.action_values(value)
            derivative = np.linalg.solve(
                system,
                probability * (1 - probability) / temperature * (intervene - wait),
            )
            gradient_solves += 1
            gradient = float(self.initial_weights @ derivative)
            history.append(
                dict(threshold=threshold, objective=objective, gradient=gradient)
            )
            if abs(gradient) < 1e-7:
                break
            accepted = False
            for exponent in range(12):
                step = 0.5**exponent
                candidate = min(
                    self.problem.upper, max(0.0, threshold + step * gradient)
                )
                probability = 0.5 * (
                    1 + np.tanh((candidate - self.x) / (2 * temperature))
                )
                candidate_value, _ = self.evaluate(probability)
                solves += 1
                candidate_objective = float(self.initial_weights @ candidate_value)
                if candidate_objective >= objective + 1e-4 * gradient * (
                    candidate - threshold
                ):
                    threshold, accepted = candidate, True
                    break
            if not accepted or abs(candidate - history[-1]["threshold"]) < 1e-10:
                break
        probability = 0.5 * (1 + np.tanh((threshold - self.x) / (2 * temperature)))
        value, _ = self.evaluate(probability)
        return dict(
            value=value,
            threshold=threshold,
            temperature=temperature,
            history=history,
            policy_evaluations=solves + 1,
            gradient_linear_solves=gradient_solves,
            wall_seconds=time.perf_counter() - started,
        )

    def boundary_bracket(self, policy):
        indices = np.flatnonzero(policy)
        if not len(indices) or len(indices) == len(policy):
            return None
        if not np.array_equal(indices, np.arange(indices[-1] + 1)):
            return None
        return [float(self.x[indices[-1]]), float(self.x[indices[-1] + 1])]


def cost_sensitivity(problem, step=1e-4):
    """Implicit derivative applies only while the optimal active set is fixed."""
    from dataclasses import replace

    if not 0 < step < problem.cost:
        raise ValueError("finite-difference step must lie in (0,cost)")
    control = FiniteControl(problem)
    current = control.policy_iteration()
    plus = FiniteControl(replace(problem, cost=problem.cost + step)).policy_iteration()
    minus = FiniteControl(replace(problem, cost=problem.cost - step)).policy_iteration()
    implicit = np.linalg.solve(current["system"], -current["policy"].astype(float))
    finite_difference = (plus["value"] - minus["value"]) / (2 * step)
    stable = np.array_equal(current["policy"], plus["policy"]) and np.array_equal(
        current["policy"], minus["policy"]
    )
    difference = float(np.max(np.abs(implicit - finite_difference)))
    return dict(
        step=step,
        active_set_unchanged=bool(stable),
        implicit_gradient=implicit.tolist(),
        finite_difference=finite_difference.tolist(),
        maximum_absolute_difference=difference,
        gradient_comparison_qualified=bool(stable and difference <= 1e-7),
        active_changes_plus=int(np.count_nonzero(current["policy"] != plus["policy"])),
        active_changes_minus=int(
            np.count_nonzero(current["policy"] != minus["policy"])
        ),
    )
