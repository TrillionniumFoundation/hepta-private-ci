"""Matched renewal content kernels; event generation never calls their CDF.

X=x+nu*t+sigma*W hits zero, waits refractory, then restarts at reset.
The n-th event CDF is F(t-(n-1)*refractory; x+(n-1)*reset).
Content is a column-stochastic Markov transition per event, not a nonlinear
function applied to a mean-reset state. All kernels consume the same estimates.
"""

from dataclasses import asdict, dataclass
import math
import time

import numpy as np
import torch
from scipy.integrate import quad
from scipy.special import log_ndtr, ndtr


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


class RenewalCore:
    """Analytic evaluation or matched independent numerical integration."""
    def __init__(self, numerical=False, tolerance=1e-9, cap=32,
                 reset_enabled=True, refractory_enabled=True):
        self.name = "matched_numerical" if numerical else "analytic"
        self.numerical, self.tolerance, self.cap = numerical, tolerance, cap
        self.reset_enabled, self.refractory_enabled = reset_enabled, refractory_enabled
        self.calls = self.work = self.cdf_terms = 0
        self.max_tail_mass = self.max_normalization_correction = 0.0

    def counts(self, x, horizon, physics, remaining=0):
        result, work = renewal_counts(x, horizon, physics, remaining, self.cap,
                                     self.numerical, self.tolerance,
                                     self.reset_enabled, self.refractory_enabled)
        self.calls += 1; self.work += work["integration_evaluations"]
        self.cdf_terms += work["cdf_terms"]
        self.max_tail_mass = max(self.max_tail_mass, work.get("omitted_tail_mass", 0.0))
        self.max_normalization_correction = max(self.max_normalization_correction,
                                               abs(work.get("normalization_correction", 0.0)))
        return result


def sample_counts(rng, physics, x, horizon, size, remaining=0.0):
    """Independent exact IG event sampling; no CDF or time-step detection."""
    if physics.nu >= 0:
        raise ValueError("IG simulator contract requires negative drift")
    hitting = rng.wald(x / -physics.nu, x*x / physics.sigma**2, size=size)
    hitting += remaining
    counts = np.zeros(size, dtype=int)
    while np.any(hitting <= horizon):
        active = hitting <= horizon
        counts[active] += 1
        hitting[active] += physics.refractory + rng.wald(
            physics.reset / -physics.nu, physics.reset**2 / physics.sigma**2,
            size=int(active.sum()))
    return counts


def shared_calibration(rng, truth, samples=512, dt=0.25):
    """Sufficient-statistic simulation of common independent Gaussian increments."""
    estimated_nu = truth.nu + truth.sigma / math.sqrt(samples * dt) * rng.normal()
    estimated_sigma = truth.sigma * math.sqrt(rng.chisquare(samples - 1) / (samples - 1))
    estimate = Physics(min(float(estimated_nu), -0.02), float(estimated_sigma),
                       truth.reset, truth.refractory)
    return estimate, {"samples": samples, "dt": dt, "true": asdict(truth),
                      "estimated": asdict(estimate), "shared_by_all_arms": True}


def features(x, horizon, physics, remaining=0):
    return np.array([x, horizon, physics.nu, physics.sigma, physics.reset,
                     physics.refractory, remaining], dtype=np.float32)


class GatedPropagator(torch.nn.Module):
    """Ordinary feed-forward gated residual propagator; it is not an SSM."""
    def __init__(self, width=128, cap=32):
        super().__init__()
        self.base = torch.nn.Linear(7, width)
        self.update = torch.nn.Linear(7, width)
        self.gate = torch.nn.Linear(7, width)
        self.output = torch.nn.Sequential(torch.nn.Linear(width, width), torch.nn.SiLU(),
                                          torch.nn.Linear(width, cap))

    def forward(self, packet):
        gate = self.gate(packet).sigmoid()
        hidden = (1 - gate) * self.base(packet) + gate * self.update(packet).tanh()
        logits = self.output(hidden)
        n = torch.arange(logits.shape[-1], device=packet.device)[None]
        possible = (n == 0) | ((n - 1) * packet[:, 5:6] < packet[:, 1:2] - packet[:, 6:7])
        return logits.masked_fill(~possible, -1e9)


class LearnedCore:
    """Ordinary nonlinear propagator consuming exactly the analytic input packet."""
    name = "ordinary_gated"

    def __init__(self, model, cap):
        self.model, self.cap = model, cap
        self.calls = self.work = self.cdf_terms = 0

    def counts(self, x, horizon, physics, remaining=0):
        import torch
        self.calls += 1
        if horizon <= remaining:
            result = np.zeros(self.cap); result[0] = 1
            return result
        with torch.no_grad():
            packet = torch.from_numpy(features(x, horizon, physics, remaining))[None]
            probabilities = self.model(packet).softmax(dim=-1)[0].numpy().astype(float)
        # A shared physical support constraint, not an analytic probability label.
        n = np.arange(self.cap)
        possible = (n == 0) | ((n - 1) * physics.refractory < horizon - remaining)
        probabilities *= possible
        probabilities /= probabilities.sum()
        return probabilities


def propagation_dataset(seed, size):
    rng = np.random.default_rng(seed)
    data = np.empty((size, 7), np.float32); labels = np.empty(size, np.int64)
    truth_rows = np.empty((size, 4), float)
    calibration_seconds = 0.
    for i in range(size):
        truth = Physics(-rng.uniform(.2, 1.2), rng.uniform(.15, .75),
                        rng.uniform(.35, 1.25), rng.uniform(.12, .32))
        started = time.perf_counter()
        estimate, _ = shared_calibration(rng, truth)
        calibration_seconds += time.perf_counter() - started
        x, horizon = rng.uniform(.08, 2.8), rng.uniform(.015, 3.2)
        remaining = rng.uniform(0, truth.refractory) if rng.random() < .3 else 0.0
        if remaining > 0:
            x = truth.reset
        data[i] = features(x, horizon, estimate, remaining)
        labels[i] = sample_counts(rng, truth, x, horizon, 1, remaining)[0]
        truth_rows[i] = list(asdict(truth).values())
    return data, labels, truth_rows, calibration_seconds


def fit_ordinary(seed=1701, train_size=8192, epochs=80, width=128, cap=32):
    """Fit using independent sampled event counts, not analytic probability labels.

    The returned dataset is common training evidence. The analytic core uses its
    common physical calibration, while the ordinary core additionally fits the
    sampled count labels. No held-out mechanism trajectories are used here.
    """
    import torch
    torch.set_num_threads(1); torch.manual_seed(seed)
    start = time.perf_counter()
    data, labels, truth_rows, calibration_seconds = propagation_dataset(seed, train_size)
    generation_seconds = time.perf_counter() - start
    if labels.max() >= cap:
        raise ValueError("training event support exceeds output cap")
    model = GatedPropagator(width, cap)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    tx, ty = torch.from_numpy(data), torch.from_numpy(labels)
    for _ in range(epochs):
        for batch in torch.randperm(train_size).split(256):
            optimizer.zero_grad(set_to_none=True)
            loss = torch.nn.functional.cross_entropy(model(tx[batch]), ty[batch])
            loss.backward(); optimizer.step()
    model.eval()
    fit_seconds = time.perf_counter() - start - generation_seconds
    dev_x, dev_y, _, _ = propagation_dataset(991238, 512)
    with torch.no_grad():
        dev_nll = float(torch.nn.functional.cross_entropy(model(torch.from_numpy(dev_x)), torch.from_numpy(dev_y)))
    analytic_nll = []
    for row, label in zip(dev_x, dev_y):
        x, horizon, nu, sigma, reset, refractory, remaining = map(float, row)
        prob, _ = renewal_counts(x, horizon, Physics(nu, sigma, reset, refractory), remaining, cap)
        analytic_nll.append(-math.log(max(float(prob[label]), 1e-12)))
    report = {"seed": seed, "train_size": train_size, "epochs": epochs, "width": width,
              "cap": cap, "train_seconds": time.perf_counter() - start,
              "architecture": "feedforward_gated_residual_propagator_not_SSM",
              "parameters": sum(p.numel() for p in model.parameters()),
              "label_source": "independent_IG_samples", "calibration_samples": 512,
              "data_generation_seconds": generation_seconds, "fit_seconds": fit_seconds,
              "shared_calibration_seconds_in_data": calibration_seconds,
              "development_validation_seed": 991238, "development_validation_size": 512,
              "development_validation_nll": dev_nll,
              "development_analytic_estimated_parameter_nll": float(np.mean(analytic_nll)),
              "training_nll": float(torch.nn.functional.cross_entropy(model(tx), ty).detach())}
    return LearnedCore(model, cap), report, {"features": data, "labels": labels,
                                           "training_true_physics": truth_rows}
