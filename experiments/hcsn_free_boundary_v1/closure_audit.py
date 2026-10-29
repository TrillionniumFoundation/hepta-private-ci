"""Audit the declared neural mean closure against a fixed-parameter renewal law.

No training data, learned weights, or benchmark outcomes are inspected. Exact
first-passage event-time simulation avoids Euler crossing bias. Independent
renewal moments provide the primary reference; Monte Carlo supplies a check
with pointwise 95% normal intervals, not a claim of benchmark superiority.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad
from scipy.special import log_ndtr, ndtri_exp
import torch

from .model import RegenerativeContentCell, simulate_event_interval
from .oracle import OracleParams, first_passage_cdf, solve_boundary
from .oracle_torch import first_passage_terms


@dataclass(frozen=True)
class AuditCase:
    name: str
    params: OracleParams
    initial: float
    horizon: float
    steps: tuple


def expected_count(initial, boundary, params, horizon):
    """Exact finite sum for tau > 0, including an initial-hit atom for T > 0."""
    if horizon <= 0:
        return 0.0
    if params.tau <= 0:
        raise ValueError("This independent audit reference uses strictly positive refractory time.")
    if initial >= boundary:
        return 1 + expected_count(params.r, boundary, params, horizon - params.tau)
    total = 0.0
    for n in range(1, int(math.floor(horizon / params.tau)) + 2):
        remaining = horizon - (n - 1) * params.tau
        if remaining <= 0:
            break
        distance = boundary - initial + (n - 1) * (boundary - params.r)
        total += float(first_passage_cdf(0.0, distance, remaining, params.mu, params.sigma))
    return total


def exact_moments(initial, boundary, params, horizon):
    """Renewal count plus an independent scalar integral of refractory usage.

    X_T=x+mu*A_T+sigma*W_(A_T)+(r-b)*N_T and bounded active time A_T <= T
    give its mean. Used refractory time has expectation integral_0^tau C(T-u)du.
    The reported quadrature error excludes floating-point/CDF evaluation error.
    """
    if initial >= boundary and horizon > 0:
        if horizon <= params.tau:
            return dict(voltage=params.r, refractory=params.tau - horizon,
                        events=1.0, active_time=0.0, quadrature_error_estimate=0.0)
        rest = exact_moments(params.r, boundary, params, horizon - params.tau)
        return dict(rest, events=1 + rest["events"])
    count = expected_count(initial, boundary, params, horizon)
    used, error = quad(lambda u: expected_count(initial, boundary, params, horizon - u),
                       0.0, min(params.tau, horizon), epsabs=2e-11, epsrel=2e-11, limit=200)
    active = horizon - used
    return dict(voltage=initial + params.mu * active + (params.r - boundary) * count,
                refractory=params.tau * count - used, events=count, active_time=active,
                quadrature_error_estimate=error)


def _sample_hit(distance, mu, sigma, rng):
    """Exact inverse-Gaussian/Levy hit times, with negative-drift defect mass."""
    if mu == 0:
        normal = rng.standard_normal(distance.shape)
        return (distance / (sigma * normal))**2
    times = rng.wald(distance / abs(mu), (distance / sigma)**2)
    if mu < 0:
        hit_eventually = rng.random(distance.shape) < np.exp(2 * mu * distance / sigma**2)
        times = np.where(hit_eventually, times, np.inf)
    return times


def _sample_killed_endpoint(initial, boundary, elapsed, mu, sigma, rng):
    """Sample the endpoint conditional on no crossing via bridge rejection.

    A truncated Gaussian proposal y<b is accepted with probability
    1-exp(-2*(b-x)*(b-y)/(sigma^2*t)); drift cancels in this bridge probability.
    """
    answer = np.empty_like(initial)
    pending = np.arange(initial.size)
    for _ in range(10000):
        if pending.size == 0:
            return answer
        x, t = initial[pending], elapsed[pending]
        scale = sigma * np.sqrt(t)
        mean = x + mu * t
        z = (boundary - mean) / scale
        uniforms = np.maximum(rng.random(pending.size), np.finfo(float).tiny)
        proposal = mean + scale * ndtri_exp(log_ndtr(z) + np.log(uniforms))
        accept_probability = -np.expm1(-2 * (boundary - x) * (boundary - proposal) / (sigma**2 * t))
        accept = rng.random(pending.size) < np.clip(accept_probability, 0, 1)
        answer[pending[accept]] = proposal[accept]
        pending = pending[~accept]
    raise RuntimeError("Killed-endpoint rejection sampler did not terminate.")


def exact_event_monte_carlo(initial, boundary, params, horizon, samples, seed):
    """Actual reset/refractory sample paths using exact first-hit clocks."""
    rng = np.random.default_rng(seed)
    voltage = np.full(samples, initial, dtype=float)
    remaining = np.full(samples, horizon, dtype=float)
    cooldown = np.zeros(samples)
    counts = np.zeros(samples)
    active_time = np.zeros(samples)
    if initial >= boundary:
        counts += 1
        voltage[:] = params.r
        held = np.minimum(remaining, params.tau)
        remaining -= held
        cooldown[:] = params.tau - held
    max_iterations = int(math.floor(horizon / params.tau)) + 3
    for _ in range(max_iterations):
        active = np.flatnonzero(remaining > 0)
        if active.size == 0:
            break
        start = voltage[active]
        available = remaining[active]
        hitting = _sample_hit(boundary - start, params.mu, params.sigma, rng)
        fires = hitting <= available
        nohit = active[~fires]
        if nohit.size:
            voltage[nohit] = _sample_killed_endpoint(start[~fires], boundary, available[~fires],
                                                    params.mu, params.sigma, rng)
            active_time[nohit] += available[~fires]
            remaining[nohit] = 0
            cooldown[nohit] = 0
        hit = active[fires]
        if hit.size:
            counts[hit] += 1
            active_time[hit] += hitting[fires]
            remaining[hit] -= hitting[fires]
            voltage[hit] = params.r
            held = np.minimum(remaining[hit], params.tau)
            remaining[hit] -= held
            cooldown[hit] = params.tau - held
    if np.any(remaining > 0):
        raise RuntimeError("Exact event sampler exceeded the refractory-implied count bound.")
    result = {}
    for name, values in (("voltage", voltage), ("refractory", cooldown),
                         ("events", counts), ("active_time", active_time)):
        average = float(values.mean())
        standard_error = float(values.std(ddof=1) / math.sqrt(samples))
        result[name] = dict(mean=average, standard_error=standard_error,
                            pointwise_normal_95_ci=[average - 1.96 * standard_error,
                                                   average + 1.96 * standard_error])
    return result


def neural_mean_closure(case, boundary, dt):
    """Exercise frozen model.advance directly, without training or altered source."""
    with torch.random.fork_rng():
        torch.manual_seed(401)
        cell = RegenerativeContentCell(1, boundary_mode="free", channels="dual").double()
    anchor = torch.zeros(1, 1, dtype=torch.float64)
    state = cell.initial_state(1, anchor)
    state["voltage"][:] = case.initial
    local = {name: torch.full_like(anchor, getattr(case.params, name)) for name in ("mu", "sigma", "rho", "K", "r", "tau")}
    local["boundary"] = torch.full_like(anchor, boundary)
    count = 0.0
    elapsed = 0.0
    with torch.no_grad():
        while elapsed < case.horizon - 1e-12:
            interval = min(dt, case.horizon - elapsed)
            _, state, aux = cell.advance(anchor, anchor, torch.full_like(anchor, interval), state, local)
            count += float(aux["activity"].item())
            elapsed += interval
    return dict(dt=dt, voltage=float(state["voltage"].item()),
                refractory=float(state["refractory"].item()), events=count,
                cost_proxy=case.params.K * count)


def floating_point_audit():
    grid = list(itertools.product((1e-4, 0.01, 0.1, 1.0, 10.0),
                                  (-0.35, 0.0, 0.65), (0.15, 0.6, 2.0),
                                  (0.01, 0.1, 0.3, 1.0, 5.0, 32.0)))
    values = torch.tensor(grid, dtype=torch.float64)
    args64 = tuple(values[:, i].clone().requires_grad_() for i in range(4))
    args32 = tuple(t.detach().float().requires_grad_() for t in args64)
    outputs64 = first_passage_terms(*args64)
    outputs32 = first_passage_terms(*args32)
    grads64 = torch.autograd.grad(sum(x.sum() for x in outputs64), args64)
    grads32 = torch.autograd.grad(sum(x.sum() for x in outputs32), args32)
    if not all(torch.isfinite(t).all() for t in (*outputs64, *outputs32, *grads64, *grads32)):
        raise AssertionError("Nonfinite output/gradient inside the audited moderate numerical grid.")
    return dict(cases=len(grid), maximum_cdf_float32_vs_float64_error=float((outputs32[0].double() - outputs64[0]).detach().abs().max()),
                maximum_survival_float32_vs_float64_error=float((outputs32[1].double() - outputs64[1]).detach().abs().max()),
                maximum_float32_mass_defect=float((outputs32[0] + outputs32[1] - 1).detach().abs().max()),
                maximum_scaled_gradient_difference=max(float(((a.double() - b).abs() / (1 + b.abs())).max()) for a, b in zip(grads32, grads64)),
                finite_outputs_and_first_gradients=True,
                scope="moderate model-relevant grid, not all finite float inputs")


def audit(samples=60000):
    torch.set_num_threads(1)
    started = time.perf_counter()
    base = Path(__file__).parent
    files = [base / name for name in ("closure_audit.py", "model.py", "oracle.py", "oracle_torch.py")]
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    default = OracleParams()
    negative = OracleParams(mu=-0.35, sigma=0.7, rho=0.4, K=0.8, r=-0.2, tau=0.3)
    rapid = OracleParams(mu=0.65, sigma=0.6, rho=0.4, K=0.6, r=0.0, tau=0.2)
    cases = [AuditCase("positive_drift_distribution_collapse", default, default.r, 4.0, (1, 0.5, 0.25, 0.125, 0.0625, 0.03125)),
             AuditCase("negative_drift_near_boundary", negative, solve_boundary(negative).boundary - 0.2, 2.0, (1, 0.5, 0.25, 0.125, 0.0625, 0.03125)),
             AuditCase("large_interval_multiple_firings", rapid, rapid.r, 12.0, (4, 2, 1, 0.5, 0.25, 0.125)),
             AuditCase("initial_state_above_boundary", default, solve_boundary(default).boundary + 0.1, 1.0, (1, 0.5, 0.25, 0.125, 0.0625, 0.03125))]
    rows = []
    for index, case in enumerate(cases):
        boundary = solve_boundary(case.params).boundary
        reference = exact_moments(case.initial, boundary, case.params, case.horizon)
        mc = exact_event_monte_carlo(case.initial, boundary, case.params, case.horizon, samples, 20261029 + index)
        for name in ("voltage", "refractory", "events", "active_time"):
            standard_error = mc[name]["standard_error"]
            z = (mc[name]["mean"] - reference[name]) / standard_error if standard_error else 0.0
            mc[name]["reference_z_score"] = z
            if abs(z) > 5:
                raise AssertionError((case.name, name, "independent Monte Carlo/reference inconsistency", z))
        approximations = []
        for dt in case.steps:
            approximate = neural_mean_closure(case, boundary, dt)
            approximate["signed_bias_vs_exact"] = {name: approximate[name] - reference[name]
                                                    for name in ("voltage", "refractory", "events")}
            approximate["event_cost_bias"] = case.params.K * (approximate["events"] - reference["events"])
            approximations.append(approximate)
        rows.append(dict(name=case.name, parameters=asdict(case.params), initial=case.initial,
                         boundary=boundary, horizon=case.horizon, exact_renewal_moments=reference,
                         exact_event_monte_carlo=mc, mean_closure=approximations))

    # For one initially active interval no longer than tau, voltage and count
    # are exact, but interval-end cooldown exceeds the true remaining cooldown.
    boundary = solve_boundary(default).boundary
    local_rows = []
    for dt in (0.05, 0.1, 0.2, 0.3):
        initial = boundary - 0.2
        case = AuditCase("single_interval", default, initial, dt, (dt,))
        reference = exact_moments(initial, boundary, default, dt)
        approximation = neural_mean_closure(case, boundary, dt)
        bias = approximation["refractory"] - reference["refractory"]
        integral, err = quad(lambda t: float(first_passage_cdf(initial, boundary, t, default.mu, default.sigma)),
                             0, dt, epsabs=1e-12)
        assert abs(approximation["voltage"] - reference["voltage"]) < 1e-10
        assert abs(approximation["events"] - reference["events"]) < 1e-10
        assert abs(bias - integral) < 1e-10
        local_rows.append(dict(dt=dt, cooldown_bias=bias, integral_first_hit_cdf=integral,
                               cooldown_bias_upper_bound=dt * reference["events"],
                               quadrature_error_estimate=err))

    # Regression for the initial-hit edge identified during this audit. Later
    # within-interval crossings remain explicitly discretized at grid endpoints.
    initial = torch.tensor([1.01], dtype=torch.float64)
    zeros = torch.zeros_like(initial)
    grid_edge = simulate_event_interval(initial, zeros, torch.full_like(initial, -1.0), zeros,
                                        torch.ones_like(initial), zeros, torch.full_like(initial, 0.3),
                                        torch.full_like(initial, 0.1), torch.zeros(1, 1, dtype=torch.float64))
    simulator_edge = dict(initial=1.01, boundary=1.0, drift=-1.0, sigma=0.0, dt=0.1, substeps=1,
                          simulator_events=float(grid_edge["events"].item()),
                          continuous_contract_initial_events=1,
                          initial_atom_regression_passed=float(grid_edge["events"].item()) == 1,
                          interpretation="initial atom handled before substeps; later crossings remain a grid approximation")
    assert simulator_edge["initial_atom_regression_passed"], "Initial-hit simulator regression returned."
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == source_hashes, "Audited source changed during execution. Rerun before binding evidence."
    return dict(schema="hcsn.mean-closure-audit.v1", status="passed_with_measured_approximation_bias",
                samples_per_scenario=samples, monte_carlo_seed_base=20261029,
                monte_carlo_time_discretization="none: exact inverse-Gaussian first hits and killed endpoint sampling",
                monte_carlo_intervals="pointwise 95% normal approximations; z<5 is a diagnostic gate, not a superiority test",
                scenarios=rows, one_interval_cooldown_bias=local_rows,
                deterministic_refractory_mixture_counterexample=dict(dt=0.1, refractory_probability=0.5, refractory_duration=1.0,
                                                                      exact_expected_active_time=0.05, closure_active_time=0.0),
                numerical=floating_point_audit(), hard_event_simulator_edge=simulator_edge,
                neural_closure_exact_regenerative_claim=False, timestep_refinement_guarantees_convergence=False,
                source_sha256=source_hashes, wall_seconds=time.perf_counter() - started)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=60000)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "closure001.json")
    args = parser.parse_args()
    report = audit(args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(status=report["status"], output=str(args.output), wall_seconds=report["wall_seconds"],
                         max_float32_cdf_error=report["numerical"]["maximum_cdf_float32_vs_float64_error"])))
