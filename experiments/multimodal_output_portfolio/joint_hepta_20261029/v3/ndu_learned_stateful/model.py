"""Finite learned-kernel control; no experiment truth or calibration labels in Policy."""
from dataclasses import dataclass
from functools import lru_cache
import numpy as np

ACTIONS = ("inspect", "repair")
OUTCOMES = tuple((y, d, z) for y in (-1, 0, 1) for d in (1, 3) for z in (0, 1))
METRICS = ("utility", "quality", "fees", "simulated_clock", "launches", "failures", "timeouts")


@dataclass(frozen=True)
class Task:
    deadline: int = 4
    fee: float = .025
    time_price: float = .02
    max_steps: int = 2

    def __post_init__(self):
        if not (0 <= self.deadline <= 8 and 0 <= self.max_steps <= 3):
            raise ValueError("finite deadline/step limit")
        if not np.isfinite([self.fee, self.time_price]).all() or min(self.fee, self.time_price) < 0:
            raise ValueError("nonnegative finite prices")

    @property
    def span(self):
        return 1 + self.max_steps * self.fee + self.deadline * self.time_price


def quality(z):
    return .55 + .45 * z


class Kernel:
    def __init__(self, probabilities):
        p = np.array(probabilities, dtype=float, copy=True)
        if p.shape != (2, 2, 2, 12) or not np.isfinite(p).all() or (p < 0).any():
            raise ValueError("eight finite nonnegative twelve-outcome rows required")
        if not np.allclose(p.sum(axis=-1), 1, rtol=0, atol=1e-12):
            raise ValueError("rows must be probability distributions")
        p.flags.writeable = False
        self.p = p

    @lru_cache(None)
    def events(self, z, action, cap):
        grouped = {}
        for i, (y, duration, next_z) in enumerate(OUTCOMES):
            event = (y, duration, next_z) if duration <= cap else (-2, cap, z)
            grouped.setdefault(event, np.zeros(2))[:] += self.p[:, z, action, i]
        return tuple((event, float(v[0]), float(v[1])) for event, v in grouped.items())

    def posterior(self, belief, z, action, cap, observed, no_duration=False):
        p0 = p1 = 0.
        for event, a, b in self.events(z, action, cap):
            match = event == observed
            if no_duration:
                match = (event[0], event[2]) == (observed[0], observed[2])
            if match:
                p0 += a
                p1 += b
        denominator = (1 - belief) * p0 + belief * p1
        if denominator <= 0:
            raise ValueError("observed event outside fitted support")
        return belief * p1 / denominator


def estimate(draws, pseudocount=.5):
    """Only purchased outcome indices and known row/support indexing enter this estimator."""
    if draws.shape[:3] != (2, 2, 2) or draws.ndim != 4 or draws.shape[-1] == 0:
        raise ValueError("labeled reset row bank required")
    if pseudocount <= 0 or (draws < 0).any() or (draws >= 12).any():
        raise ValueError("positive smoothing and supported outcome indices required")
    counts = np.stack([np.bincount(row, minlength=12) for row in draws.reshape(8, -1)])
    return Kernel(((counts + pseudocount) / (draws.shape[-1] + 12 * pseudocount)).reshape(2, 2, 2, 12))


class Policy:
    def __init__(self, kernel, task, mode="plugin_dp"):
        if mode not in ("prior_stop", "myopic", "plugin_dp", "no_duration", "no_state", "known_oracle"):
            raise ValueError("unknown policy")
        self.kernel, self.task, self.mode = kernel, task, mode

        @lru_cache(None)
        def solve(belief, z, remaining, steps):
            best, choice = quality(z) * max(belief, 1 - belief), (-1, int(belief > .5))
            if self.mode == "prior_stop" or min(remaining, steps) <= 0:
                return best, choice
            for action in range(2):
                for cap in range(1, remaining + 1):
                    value = -task.fee
                    for event, p0, p1 in kernel.events(z, action, cap):
                        mass = (1 - belief) * p0 + belief * p1
                        if not mass:
                            continue
                        after = self.update(belief, z, action, cap, event)
                        next_z = z if mode == "no_state" else event[2]
                        continuation = solve(after, next_z, remaining - event[1], steps - 1)[0]
                        value += mass * (continuation - task.time_price * event[1])
                    if value > best + 1e-12:
                        best, choice = value, (action, cap)
            return best, choice
        self.solve = solve

    def update(self, belief, z, action, cap, event):
        return self.kernel.posterior(belief, z, action, cap, event, self.mode == "no_duration")

    def __call__(self, belief, z, remaining, steps):
        depth = min(steps, 1) if self.mode == "myopic" else steps
        return self.solve(belief, z, remaining, depth)[1]


def evaluate(true_kernel, task, policy):
    """Exact finite trajectory sum; H is evaluator-only, never a Policy argument."""
    @lru_cache(None)
    def walk(h, belief, z, remaining, steps):
        action, argument = policy(belief, z, remaining, steps)
        if action == -1:
            q = quality(z) * (argument == h)
            return np.array([q, q, 0, 0, 0, 0, 0], dtype=float)
        result = np.array([-task.fee, 0, task.fee, 0, 1, 0, 0], dtype=float)
        for event, p0, p1 in true_kernel.events(z, action, argument):
            mass = (p0, p1)[h]
            if not mass:
                continue
            y, duration, next_z = event
            after = policy.update(belief, z, action, argument, event)
            continuation = walk(h, after, next_z, remaining - duration, steps - 1).copy()
            continuation += [-task.time_price * duration, 0, 0, duration, 0, y == -1, y == -2]
            result += mass * continuation
        return result
    return .5 * (walk(0, .5, 0, task.deadline, task.max_steps) + walk(1, .5, 0, task.deadline, task.max_steps))


def rollouts(true_kernel, task, policy, hidden, uniforms):
    """Paired simulator tasks; each launch consumes only its selected random slot."""
    cdf = np.cumsum(true_kernel.p, axis=-1)
    records = np.zeros((len(hidden), len(METRICS)))
    for i, h in enumerate(hidden):
        belief, z, remaining, steps = .5, 0, task.deadline, task.max_steps
        fees = clock = launches = failures = timeouts = 0
        while True:
            action, cap = policy(belief, z, remaining, steps)
            if action == -1:
                q = quality(z) * (cap == h)
                records[i] = [q - fees - task.time_price * clock, q, fees, clock, launches, failures, timeouts]
                break
            slot = uniforms[i, launches, z, action]
            index = min(int(np.searchsorted(cdf[h, z, action], slot, side="right")), 11)
            y, duration, next_z = OUTCOMES[index]
            event = (y, duration, next_z) if duration <= cap else (-2, cap, z)
            belief = policy.update(belief, z, action, cap, event)
            z, remaining, steps = event[2], remaining - event[1], steps - 1
            fees, clock, launches = fees + task.fee, clock + event[1], launches + 1
            failures, timeouts = failures + (event[0] == -1), timeouts + (event[0] == -2)
    return records


def tv_error(a, b):
    return float(np.max(.5 * np.abs(a.p - b.p).sum(axis=-1)))


def tv_radius(n, alpha=.025, families=24, pseudocount=.5):
    raw = np.sqrt(np.log((2 ** 12 - 2) * 8 * families / alpha) / (2 * n))
    smoothing = 12 * pseudocount / (n + 12 * pseudocount)
    return min(1., float(raw + smoothing))


def value_radius(task, epsilon):
    return task.span * min(1., task.max_steps * epsilon)
