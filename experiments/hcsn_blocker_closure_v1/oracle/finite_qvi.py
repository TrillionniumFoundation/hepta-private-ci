"""Finite-state discounted impulse control, including post-firing value.

The state grid is fixed. KEEP observes a continuous-time Markov chain; FIRE
receives a declared reward, waits an Erlang refractory time, and resets.
Policy iteration is exact up to floating-point linear solves for this finite
problem. It does not certify an underlying continuous-space approximation.
"""

from dataclasses import dataclass

import numpy as np
from scipy.linalg import solve


@dataclass(frozen=True)
class Problem:
    grid: np.ndarray
    generator: np.ndarray
    running: np.ndarray
    rewards: np.ndarray
    reset: np.ndarray
    rho: float
    tau: float
    phases: int
    name: str

    def __post_init__(self):
        n = len(self.grid)
        if (n < 3 or self.generator.shape != (n, n)
                or self.running.shape != (n,) or self.reset.shape != (n,)
                or self.rewards.ndim != 2 or self.rewards.shape[1] != n):
            raise ValueError("Invalid finite-state shapes")
        arrays = [self.grid, self.generator, self.running, self.rewards, self.reset]
        if not all(np.isfinite(a).all() for a in arrays):
            raise ValueError("Finite arrays required")
        off = self.generator.copy()
        np.fill_diagonal(off, 0)
        if (np.min(off) < 0 or np.max(np.abs(self.generator.sum(1))) > 1e-10
                or np.min(self.reset) < 0 or abs(self.reset.sum()-1) > 1e-12):
            raise ValueError("Invalid generator or reset distribution")
        if not (np.isfinite(self.rho) and np.isfinite(self.tau)
                and self.rho > 0 and self.tau > 0
                and isinstance(self.phases, int) and self.phases >= 1):
            raise ValueError("Positive discount/refractory duration required")

    @property
    def delay_discount(self):
        return (1 + self.rho*self.tau/self.phases)**(-self.phases)

    @property
    def rate(self):
        return max(float(-np.diag(self.generator).min()), 1e-12)


def interpolation(grid, point):
    """Linear reset weights and derivative; reject out-of-grid resets.

    At an interior grid knot the derivative is the right derivative. A unique
    two-sided classical derivative is not claimed at such a knot.
    """
    if not grid[0] <= point <= grid[-1]:
        raise ValueError("Reset outside the fixed grid")
    j = min(max(int(np.searchsorted(grid, point, side="right"))-1, 0), len(grid)-2)
    h = grid[j+1]-grid[j]
    weights, derivative = np.zeros(len(grid)), np.zeros(len(grid))
    weights[j:j+2] = [(grid[j+1]-point)/h, (point-grid[j])/h]
    derivative[j:j+2] = [-1/h, 1/h]
    return weights, derivative


def action_values(problem, value):
    """Rows are KEEP then each FIRE action; values include future reset cycles."""
    rate, rho = problem.rate, problem.rho
    keep = (problem.running + rate*value + problem.generator@value)/(rho+rate)
    fire = problem.rewards + problem.delay_discount*(problem.reset@value)
    return np.vstack([keep, fire])


def policy_system(problem, action):
    n = len(problem.grid)
    matrix = problem.rho*np.eye(n)-problem.generator
    rhs = problem.running.copy()
    fired = np.flatnonzero(action)
    matrix[fired] = np.eye(n)[fired]-problem.delay_discount*problem.reset
    rhs[fired] = problem.rewards[action[fired]-1, fired]
    return matrix, rhs


def evaluate_policy(problem, action):
    action = np.asarray(action, dtype=np.int64)
    if action.shape != (len(problem.grid),) or np.any(action < 0) or np.any(action > len(problem.rewards)):
        raise ValueError("Invalid action vector")
    matrix, rhs = policy_system(problem, action)
    return solve(matrix, rhs, assume_a="gen", check_finite=False)


def solve_policy(problem, tolerance=2e-12, max_iterations=200):
    action = np.zeros(len(problem.grid), dtype=np.int64)
    for iteration in range(max_iterations):
        value = evaluate_policy(problem, action)
        values = action_values(problem, value)
        best = values.argmax(0)
        advantage = values[best, np.arange(len(action))]-value
        change = advantage > tolerance
        if not np.any(change):
            residual = float(np.max(np.abs(values.max(0)-value)))
            return dict(value=value, action=action, iterations=iteration+1,
                        residual=residual, values=values)
        action = np.where(change, best, action)
    raise RuntimeError("Policy iteration did not converge")


def residual_certificate(problem, value):
    """Contraction residual bound, in value units; not interval arithmetic."""
    gamma = max(problem.rate/(problem.rho+problem.rate), problem.delay_discount)
    residual = float(np.max(np.abs(action_values(problem, value).max(0)-value)))
    return dict(residual=residual, contraction=gamma,
                value_error_bound=residual/(1-gamma))


def implicit_gradient(problem, solution, derivative):
    """Differentiate the policy equations on a fixed strict active set.

    derivative keys: generator, running, rewards, reset, rho, tau.
    Selection is not differentiated through argmax. The caller must verify that
    the policy is stable in the finite-difference neighborhood.
    """
    n, value, action = len(problem.grid), solution["value"], solution["action"]
    get = lambda key, shape: np.asarray(derivative.get(key, np.zeros(shape)))
    drho, dtau = derivative.get("rho", 0.), derivative.get("tau", 0.)
    base = 1 + problem.rho*problem.tau/problem.phases
    discount_derivative = -problem.delay_discount*(problem.tau*drho+problem.rho*dtau)/base
    dmatrix = drho*np.eye(n)-get("generator", (n, n))
    drhs = get("running", (n,)).copy()
    fired = np.flatnonzero(action)
    dmatrix[fired] = -discount_derivative*problem.reset-problem.delay_discount*get("reset", (n,))
    drewards = get("rewards", problem.rewards.shape)
    drhs[fired] = drewards[action[fired]-1, fired]
    matrix, _ = policy_system(problem, action)
    return solve(matrix, drhs-dmatrix@value, assume_a="gen", check_finite=False)


def birth_death_generator(up, down):
    n = len(up)
    matrix = np.zeros((n, n))
    for i in range(n):
        if i+1 < n:
            matrix[i, i+1] = up[i]
        if i:
            matrix[i, i-1] = down[i]
    np.fill_diagonal(matrix, -matrix.sum(1))
    return matrix


def build_affine(grid, mu=.1, sigma=.45, rho=.45, K=.525, reset=-.13,
                 tau=.75, phases=2):
    grid = np.asarray(grid, dtype=np.float64)
    h = grid[1]-grid[0]
    if sigma <= 0 or not np.allclose(np.diff(grid), h):
        raise ValueError("Positive diffusion and a uniform fixed grid required")
    n = len(grid)
    up = np.full(n, sigma*sigma/(2*h*h)+max(mu, 0)/h)
    down = np.full(n, sigma*sigma/(2*h*h)+max(-mu, 0)/h)
    weights, dw = interpolation(grid, reset)
    problem = Problem(grid, birth_death_generator(up, down), np.zeros(n),
                      (grid-K)[None, :], weights, rho, tau, phases, "affine")
    deriv = {"rho": {"rho": 1.}, "tau": {"tau": 1.}, "reset": {"reset": dw},
             "K": {"rewards": -np.ones((1, n))}}
    if mu != 0:
        deriv["mu"] = {"generator": birth_death_generator(
            np.full(n, float(mu > 0)/h), np.full(n, -float(mu < 0)/h))}
    deriv["sigma"] = {"generator": birth_death_generator(
        np.full(n, sigma/(h*h)), np.full(n, sigma/(h*h)))}
    return problem, deriv
