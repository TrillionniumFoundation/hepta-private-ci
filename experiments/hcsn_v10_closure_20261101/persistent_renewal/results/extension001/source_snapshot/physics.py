from dataclasses import asdict, dataclass
import math
import time
import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr, log_ndtr

@dataclass(frozen=True)
class Physics:
    nu: float
    sigma: float
    reset: float
    refractory: float

    def validate(self):
        if self.sigma <= 0 or self.reset <= 0 or self.refractory <= 0:
            raise ValueError("sigma, reset, and refractory must be positive")


def first_passage_cdf(t, x, nu, sigma):
    """Stable lower first-passage CDF; t<=0 gives zero, x>0 required."""
    t, x = np.broadcast_arrays(np.asarray(t, float), np.asarray(x, float))
    if np.any(x <= 0) or sigma <= 0:
        raise ValueError("positive initial gap and volatility required")
    active = t > 0
    safe_t = np.where(active, t, 1.0)
    scale = sigma * np.sqrt(safe_t)
    a = (-x - nu * safe_t) / scale
    b = (-x + nu * safe_t) / scale
    reflected = np.exp(np.minimum(-2 * nu * x / sigma**2 + log_ndtr(b), 0))
    result = np.where(active, ndtr(a) + reflected, 0)
    if np.any(result > 1 + 1e-10):
        raise ArithmeticError("first-passage probability exceeds one")
    return np.clip(result, 0, 1)


def integrated_cdf(t, x, nu, sigma, tolerance=1e-9):
    """Independent adaptive integral of the first-passage density, with work."""
    if t <= 0:
        return 0.0, 0
    def density(s):
        if s <= 0:
            return 0.0
        log_f = (math.log(x / sigma) - 0.5 * math.log(2 * math.pi)
                 - 1.5 * math.log(s) - (x + nu * s)**2 / (2 * sigma**2 * s))
        return math.exp(log_f) if log_f > -745 else 0.0
    mode = 2 * x*x / (3 * sigma*sigma + math.sqrt(9 * sigma**4 + 4 * nu*nu*x*x))
    points = sorted({v for v in (mode / 10, mode, mode * 10) if 0 < v < t})
    answer = quad(density, 0, t, epsabs=tolerance, epsrel=tolerance,
                  points=points, limit=200, full_output=1)
    value, error, info = answer[:3]
    if len(answer) > 3 or error > max(10 * tolerance, abs(value) * 10 * tolerance):
        raise ArithmeticError(f"first-passage integration failed: {error}")
    return float(value), int(info["neval"])


def renewal_counts(x, horizon, physics, remaining=0.0, cap=32, numerical=False,
                   tolerance=1e-9, reset_enabled=True, refractory_enabled=True):
    """Return P(N=n), n=0..cap-1, and explicit evaluation work.

    cap is a checked support bound, never a last-bin overflow bucket.
    reset_enabled=False is an absorbing, at-most-one-event MODEL ablation.
    refractory_enabled=False is a zero-refractory MODEL ablation; tail checked.
    """
    physics.validate()
    if remaining > 0 and not np.isclose(x, physics.reset):
        raise ValueError("refractory observations must carry the reset gap")
    t = float(horizon) - max(float(remaining), 0.0)
    if t <= 0:
        answer = np.zeros(cap); answer[0] = 1.0
        return answer, {"cdf_terms": 0, "integration_evaluations": 0}
    delay = physics.refractory if refractory_enabled else 0.0
    n = np.arange(1, cap + 1, dtype=float)
    elapsed = t - (n - 1) * delay
    distance = x + (n - 1) * physics.reset
    if numerical:
        values = [integrated_cdf(a, b, physics.nu, physics.sigma, tolerance)
                  for a, b in zip(elapsed, distance)]
        tails = np.array([v[0] for v in values]); work = sum(v[1] for v in values)
    else:
        tails = first_passage_cdf(elapsed, distance, physics.nu, physics.sigma)
        work = 0
    if not reset_enabled:
        tails[1:] = 0
    if tails[-1] > max(1e-10, tolerance * 10):
        raise ValueError(f"event support exceeds cap={cap}; missing mass={tails[-1]}")
    probs = np.r_[1.0, tails[:-1]] - tails
    if probs.min() < -max(1e-10, tolerance * 10):
        raise ArithmeticError("nonmonotone event-count tails")
    probs = np.maximum(probs, 0)
    if abs(probs.sum() - 1) > max(1e-9, tolerance * 20):
        raise ArithmeticError("event-count mass not conserved")
    correction = float(1 - probs.sum())
    probs /= probs.sum()
    return probs, {"cdf_terms": int(np.count_nonzero(elapsed > 0)),
                   "integration_evaluations": int(work), "omitted_tail_mass": float(tails[-1]),
                   "normalization_correction": correction}


def content_from_counts(probabilities, initial, transition):
    z = np.asarray(initial, float)
    transition = np.asarray(transition, float)
    if np.any(transition < 0) or not np.allclose(transition.sum(axis=0), 1):
        raise ValueError("transition must be column-stochastic")
    result = np.zeros_like(z)
    for weight in probabilities:
        result += weight * z
        z = transition @ z
    return result


def shared_calibration(rng, truth, samples=512, dt=0.25):
    """Sufficient-statistic simulation of common independent Gaussian increments."""
    estimated_nu = truth.nu + truth.sigma / math.sqrt(samples * dt) * rng.normal()
    estimated_sigma = truth.sigma * math.sqrt(rng.chisquare(samples - 1) / (samples - 1))
    estimate = Physics(min(float(estimated_nu), -0.02), float(estimated_sigma),
                       truth.reset, truth.refractory)
    return estimate, {"samples": samples, "dt": dt, "true": asdict(truth),
                      "estimated": asdict(estimate), "shared_by_all_arms": True}


@dataclass
class Observation:
    time: float
    x: float
    refractory_remaining: float
    content_probs: list
    has_read: bool


@dataclass(frozen=True)
class Config:
    dt: float = .15
    ticks: int = 20
    deadlines: tuple = (5, 10, 15, 20)
    budget: int = 3
    classes: int = 5
    read_cost: float = .04
    light_threshold: float = .28
    particles: int = 4
    condition: str = "matched"


def transition_matrix(k):
    matrix = np.zeros((k, k))
    for i in range(k):
        matrix[i, i] = .15
        matrix[(i + 1) % k, i] = .55
        matrix[(i - 1) % k, i] = .30
    return matrix


def generate_path(rng, physics, grid, x, content, transition, remaining=0.0):
    """Jointly consistent IG event times and 3-D Bessel-bridge observations.

    Conditional on a first hitting time, the radial Brownian bridge is the
    first-passage bridge; the constant drift cancels under that conditioning.
    All arm READ schedules index this same pre-generated joint trajectory.
    """
    if physics.nu >= 0:
        raise ValueError("independent simulator requires negative drift")
    if remaining > 0 and not np.isclose(x, physics.reset):
        raise ValueError("invalid refractory initial state")
    start = float(grid[0]) + remaining
    hit = start + rng.wald(x / -physics.nu, x*x / physics.sigma**2)
    vector, previous = np.array([x, 0., 0.]), start
    xs, rests, contents, events = [], [], [], []
    for now in grid:
        while now >= hit:
            old = content
            content = int(rng.choice(len(transition), p=transition[:, content]))
            events.append({"time": float(hit), "before": old, "after": content})
            start = hit + physics.refractory
            hit = start + rng.wald(physics.reset / -physics.nu,
                                   physics.reset**2 / physics.sigma**2)
            vector, previous = np.array([physics.reset, 0., 0.]), start
        if now < start:
            gap, rest = physics.reset, start - now
        else:
            delta = max(float(now - previous), 0.)
            ratio = (hit - now) / (hit - previous)
            vector = ratio * vector + physics.sigma * np.sqrt(delta * ratio) * rng.normal(size=3)
            previous = float(now)
            gap, rest = float(np.linalg.norm(vector)), 0.0
        xs.append(gap); rests.append(rest); contents.append(content)
    return {"x": xs, "refractory_remaining": rests, "content": contents, "events": events}


def predict(core, observation, now, physics, transition):
    before = time.perf_counter()
    counts = core.counts(observation.x, max(now - observation.time, 0), physics,
                         observation.refractory_remaining)
    probabilities = content_from_counts(counts, observation.content_probs, transition)
    core.evaluation_seconds = getattr(core, "evaluation_seconds", 0.) + time.perf_counter() - before
    return probabilities, {"event_probability": float(1 - counts[0]),
                            "expected_events": float(counts @ np.arange(len(counts))),
                            "count_probabilities": counts.tolist()}


def policy_prediction(core, obs, now, physics, matrix, suppress_events):
    if suppress_events and obs.has_read:
        return np.asarray(obs.content_probs)
    return predict(core, obs, now, physics, matrix)[0]


def choose_action(core, controller, obs, tick, budget, physics, matrix, config,
                  simulation_seed, suppress_events=False):
    """No actual world/path object is accepted by this policy interface."""
    future = [d for d in config.deadlines if d > tick]
    if not future or budget <= 0:
        return "STOP", {"reason": "no_future_output_or_budget", "simulations": 0}
    prior = {d: policy_prediction(core, obs, d * config.dt, physics, matrix,
                                  suppress_events) for d in future}
    if controller == "lightweight":
        error = float(1 - prior[future[0]].max())
        request = "READ" if error > config.light_threshold and future[0] - tick <= 2 else "WAIT"
        return request, {"forecast_error": error, "simulations": 0}
    # Shared estimated model, sampled without consulting the actual future.
    candidates = sorted(set([tick + 1] + future))
    start_tick = round(obs.time / config.dt)
    grid = np.arange(start_tick, config.ticks + 1) * config.dt
    rng = np.random.default_rng(simulation_seed)
    samples = [generate_path(rng, physics, grid, obs.x,
                            int(rng.choice(config.classes, p=obs.content_probs)), matrix,
                            obs.refractory_remaining) for _ in range(config.particles)]
    baseline = sum(1 - p.max() for p in prior.values()) / len(config.deadlines)
    values = []
    for arrival in candidates:
        loss = 0.
        for sample in samples:
            index = arrival - start_tick
            fake_obs = Observation(arrival * config.dt, sample["x"][index],
                                   sample["refractory_remaining"][index],
                                   np.eye(config.classes)[sample["content"][index]].tolist(), True)
            for deadline in future:
                predicted = (prior[deadline] if deadline < arrival else
                             policy_prediction(core, fake_obs, deadline * config.dt,
                                               physics, matrix, suppress_events))
                loss += 1 - predicted.max()
        loss /= config.particles * len(config.deadlines)
        values.append({"arrival_tick": arrival, "net_value": float(baseline - loss - config.read_cost)})
    best = max(values, key=lambda row: (row["net_value"], -row["arrival_tick"]))
    action = "STOP" if best["net_value"] <= 0 else ("READ" if best["arrival_tick"] == tick + 1 else "WAIT")
    return action, {"candidate_values": values, "selected_arrival": best["arrival_tick"],
                    "simulations": config.particles, "value_scope": "one_planned_read_heuristic"}


def make_episode(seed, config):
    rng = np.random.default_rng(seed)
    nominal_refractory = rng.uniform(.16, .28)
    sampled_factor = rng.choice([.65, 1.45])
    factor = sampled_factor if config.condition == "hidden_refractory_mismatch" else 1.
    truth = Physics(-rng.uniform(.3, 1.0), rng.uniform(.2, .65),
                    rng.uniform(.4, 1.0), nominal_refractory * factor)
    calibration_start = time.perf_counter()
    estimates, record = shared_calibration(rng, truth)
    estimates = Physics(estimates.nu, estimates.sigma, estimates.reset, nominal_refractory)
    record["estimated"] = asdict(estimates)
    record["refractory_estimate_source"] = "public_nominal_not_hidden_true_duration"
    record["wall_seconds"] = time.perf_counter() - calibration_start
    x = rng.uniform(.3, 1.3)
    grid = np.arange(config.ticks + 1) * config.dt
    path = generate_path(rng, truth, grid, x, int(rng.integers(config.classes)),
                         transition_matrix(config.classes))
    return {"seed": seed, "initial_x": x, "calibration": record, "path": path,
            "condition": config.condition, "initial_content_hidden_until_READ": True}
