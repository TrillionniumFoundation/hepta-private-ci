"""Full-distribution fixed-boundary CTMC reference with conservative regeneration.

This independent addon does not change or replace the frozen neural study.
Its spatial approximation is a monotone upwind birth-death chain on [L,b),
reflecting at L. Refractory residence is Erlang(k,k/tau), approaching a fixed
delay as k grows. The matrix exponential is exact for that FINITE generator;
it is not an exact unbounded Brownian or moving-boundary network solution.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad
import torch
from torch.nn import functional as F

from .oracle import OracleParams, first_passage_cdf, kappa as scalar_kappa
from .closure_audit import AuditCase, neural_mean_closure


@dataclass(frozen=True)
class Grid:
    nodes: int = 96
    lower: float = -4.0
    refractory_stages: int = 16


def _delta_weights(value, points, spacing):
    if bool((value < points[0]) | (value > points[-1])):
        raise ValueError("Initial/reset state must lie within the active grid nodes")
    weights = (1 - (points - value).abs() / spacing).clamp_min(0)
    return weights / weights.sum()


def generator(mu, sigma, boundary, reset, tau, grid=Grid()):
    """Build a conservative column generator with piecewise-smooth parameters.

    b and all coefficients are fixed for the whole rollout. Differentiating b
    changes the static grid; it does not implement a moving boundary. Linear
    delta interpolation is nondifferentiable at grid knots. tau=0 is a separate
    instantaneous-reset branch; derivatives across that branch are not claimed.
    """
    values = (mu, sigma, boundary, reset, tau)
    anchor = next((value for value in values if isinstance(value, torch.Tensor)),
                  torch.tensor(0.0, dtype=torch.float64))
    mu, sigma, boundary, reset, tau = [torch.as_tensor(value, dtype=anchor.dtype,
                                                      device=anchor.device) for value in values]
    if any(value.ndim != 0 for value in (mu, sigma, boundary, reset, tau)):
        raise ValueError("This reference accepts scalar parameters only")
    if not all(bool(torch.isfinite(value)) for value in (mu, sigma, boundary, reset, tau)):
        raise ValueError("Parameters must be finite")
    if grid.nodes < 4 or grid.refractory_stages < 1 or not math.isfinite(grid.lower):
        raise ValueError("Require >=4 grid nodes, >=1 refractory stage, finite lower bound")
    if bool((sigma < 0) | (tau < 0) | (boundary <= grid.lower) | (reset >= boundary)):
        raise ValueError("Require sigma>=0, tau>=0, L<b and reset<b")
    n, stages = grid.nodes, (grid.refractory_stages if bool(tau > 0) else 0)
    size = n + stages
    spacing = (boundary - grid.lower) / n
    points = grid.lower + torch.arange(n, dtype=anchor.dtype, device=anchor.device) * spacing
    reset_weights = _delta_weights(reset, points, spacing)
    up = sigma.square() / (2 * spacing.square()) + mu.clamp_min(0) / spacing
    down = sigma.square() / (2 * spacing.square()) + (-mu).clamp_min(0) / spacing
    ones = torch.ones(n - 1, dtype=anchor.dtype, device=anchor.device)
    zero = anchor.new_zeros(1)
    active = (up * (torch.diag(ones, -1) - torch.diag(torch.cat((ones, zero))))
              + down * (torch.diag(ones, 1) - torch.diag(torch.cat((zero, ones)))))
    Q = F.pad(active, (0, stages, 0, stages))
    basis = torch.eye(size, dtype=anchor.dtype, device=anchor.device)
    reset_destination = F.pad(reset_weights, (0, stages))
    destination = basis[:, n] if stages else reset_destination
    Q = Q + up * torch.outer(destination - basis[:, n - 1], basis[:, n - 1])
    if stages:
        phase_ones = torch.ones(stages - 1, dtype=anchor.dtype, device=anchor.device)
        phase_chain = torch.diag(phase_ones, -1) - torch.eye(stages, dtype=anchor.dtype,
                                                           device=anchor.device)
        Q = Q + (stages / tau) * (F.pad(phase_chain, (n, 0, n, 0))
                                  + torch.outer(reset_destination, basis[:, -1]))
    event_rate = up * basis[:, n - 1]
    augmented = F.pad(Q, (0, 1, 0, 1))
    augmented = augmented + torch.outer(F.pad(anchor.new_ones(1), (size, 0)),
                                        F.pad(event_rate, (0, 1)))
    return dict(Q=Q, augmented=augmented, points=points, spacing=spacing,
                reset=reset, tau=tau, boundary=boundary, stages=stages,
                event_rate=event_rate, reset_weights=reset_weights,
                grid=grid, lower_boundary="reflecting")


def initial_state(flow, initial):
    initial = torch.as_tensor(initial, dtype=flow["Q"].dtype, device=flow["Q"].device)
    if bool(initial >= flow["boundary"]):
        if flow["stages"]:
            probabilities = flow["Q"].new_zeros(flow["Q"].shape[0])
            probabilities[flow["grid"].nodes] = 1
        else:
            probabilities = flow["reset_weights"]
        count = initial.new_ones(())
    else:
        probabilities = F.pad(_delta_weights(initial, flow["points"], flow["spacing"]),
                               (0, flow["stages"]))
        count = initial.new_zeros(())
    return torch.cat((probabilities, count.reshape(1)))


def propagate(flow, state, horizon, partitions=1):
    if partitions < 1 or horizon < 0:
        raise ValueError("Require positive partitions and nonnegative horizon")
    transition = torch.matrix_exp(flow["augmented"] * (horizon / partitions))
    for _ in range(partitions):
        state = transition @ state
    return state


def moments(flow, state):
    n = flow["grid"].nodes
    probability = state[:-1]
    refractory_mass = probability[n:].sum()
    mean = probability[:n] @ flow["points"] + refractory_mass * flow["reset"]
    second = probability[:n] @ flow["points"].square() + refractory_mass * flow["reset"].square()
    return dict(mean=mean, second_moment=second, variance=second - mean.square(),
                events=state[-1], mass=probability.sum(), minimum_probability=probability.min(),
                refractory_mass=refractory_mass, lower_node_mass=probability[0])


def project_values(flow, state, active_values, refractory_values=None):
    """Project explicit full-state value features against retained probability.

    Arrays are [active_nodes,...] and [refractory_stages,...]. Phase values are
    mandatory when phases exist: silently treating every held state as an
    active state at reset would use an incorrect continuation/action contract.
    Callers separately retain action eligibility during the refractory period.
    """
    active = torch.as_tensor(active_values, dtype=state.dtype, device=state.device)
    if active.ndim < 1 or active.shape[0] != flow["grid"].nodes:
        raise ValueError("active_values must start with the active-grid dimension")
    if flow["stages"]:
        if refractory_values is None:
            raise ValueError("Explicit phase-specific values are required during refractory residence")
        phase = torch.as_tensor(refractory_values, dtype=state.dtype, device=state.device)
        if phase.shape != (flow["stages"], *active.shape[1:]):
            raise ValueError("Refractory value shape is inconsistent with active value features")
        values = torch.cat((active, phase), 0)
    else:
        values = active
    if not bool(torch.isfinite(values).all()):
        raise ValueError("Value features must be finite; carry action eligibility separately")
    return torch.tensordot(state[:-1], values, dims=([0], [0]))


def renewal_count(initial, boundary, params, horizon, tolerance=1e-12):
    """Independent exact FPT series; positive-tau finite, zero-tau bounded tail."""
    if horizon < 0:
        return 0.0
    if initial >= boundary:
        return 1 + renewal_count(params.r, boundary, params, horizon - params.tau, tolerance)
    if horizon == 0:
        return 0.0
    if params.sigma == 0 and params.mu <= 0:
        return 0.0
    distance, gap, total = boundary - initial, boundary - params.r, 0.0
    q = 1 / horizon
    kap = scalar_kappa(params.mu, params.sigma, q)
    for count in range(1, 10001):
        remaining = horizon - (count - 1) * params.tau
        if remaining <= 0:
            return total
        total += float(first_passage_cdf(0, distance + (count - 1) * gap,
                                         remaining, params.mu, params.sigma))
        if params.tau == 0:
            tail_bound = math.exp(q * horizon - kap * (distance + count * gap)) / (-math.expm1(-kap * gap))
            if tail_bound < tolerance:
                return total
    raise RuntimeError("Exact count series exceeded the explicit tail-control cap")


def exact_renewal_moments(initial, boundary, params, horizon):
    """Independent deterministic-delay means/variance from FPT series and Ito.

    For x<b, C(t)=E[N_t]. D=int_(T-tau)+^T C(s)ds is used refractory time.
    B=x*T+mu*T^2/2-mu*int min(tau,T-s)C(s)ds-b*int C+r*int_to_(T-tau)+ C.
    E[X^2]=x^2+2*mu*B+sigma^2*(T-D)+(r^2-b^2)*C(T).
    """
    if initial >= boundary or horizon <= 0:
        raise ValueError("Moment reference here requires x<b and positive horizon")
    count = lambda time: renewal_count(initial, boundary, params, time)
    options = dict(epsabs=2e-9, epsrel=2e-9, limit=100)
    total = count(horizon)
    integrated, error0 = quad(count, 0, horizon, **options)
    previous, error1 = quad(count, 0, max(0, horizon - params.tau), **options)
    weighted, error2 = quad(lambda time: min(params.tau, horizon - time) * count(time),
                            0, horizon, points=[max(0, horizon - params.tau)], **options)
    used = integrated - previous
    mean = initial + params.mu * (horizon - used) + (params.r - boundary) * total
    active_mean_integral = (initial * horizon + params.mu * horizon**2 / 2
                            - params.mu * weighted - boundary * integrated + params.r * previous)
    second = (initial**2 + 2 * params.mu * active_mean_integral
               + params.sigma**2 * (horizon - used) + (params.r**2 - boundary**2) * total)
    return dict(mean=mean, second_moment=second, variance=second - mean**2, events=total,
                refractory_mass=total - count(max(0, horizon - params.tau)),
                quadrature_integral_error_estimates=dict(I0=error0, Iprev=error1, I1=error2),
                quadrature_error_note="Individual unscaled integral estimates; not a bound on moments",
                count_tail_tolerance=1e-12)


def _numeric(values):
    return {key: float(value.detach()) if isinstance(value, torch.Tensor) else value
            for key, value in values.items()}


def _case(name, mu, sigma, boundary, reset, tau, initial, horizon):
    return dict(name=name, mu=mu, sigma=sigma, boundary=boundary, reset=reset,
                tau=tau, initial=initial, horizon=horizon)


def _evaluate(case, grid):
    started = time.process_time()
    with torch.no_grad():
        flow = generator(case["mu"], case["sigma"], case["boundary"], case["reset"], case["tau"], grid)
        result = moments(flow, propagate(flow, initial_state(flow, case["initial"]), case["horizon"]))
    return dict(nodes=grid.nodes, lower=grid.lower, refractory_stages=flow["stages"],
                spacing=float(flow["spacing"]), matrix_size=flow["augmented"].shape[0],
                cpu_seconds=time.process_time() - started, **_numeric(result))


def gradient_audit():
    names = ("mu", "sigma", "boundary", "reset", "tau")
    values = (0.23, 0.67, 1.17, -0.31, 0.37)
    grid = Grid(28, -3.0, 5)
    parameters = [torch.tensor(value, dtype=torch.float64, requires_grad=True) for value in values]
    def objective(arguments):
        flow = generator(*arguments, grid)
        result = moments(flow, propagate(flow, initial_state(flow, 0.13), 0.8))
        return 0.3 * result["mean"] + 0.7 * result["variance"] + 1.1 * result["events"]
    loss = objective(parameters)
    gradients = torch.autograd.grad(loss, parameters)
    records = {}
    for index, name in enumerate(names):
        plus, minus = list(values), list(values)
        plus[index] += 1e-5
        minus[index] -= 1e-5
        finite_difference = float((objective(plus) - objective(minus)) / 2e-5)
        actual = float(gradients[index])
        records[name] = dict(autograd=actual, finite_difference=finite_difference,
                             absolute_error=abs(actual - finite_difference),
                             relative_error=abs(actual - finite_difference) / max(1e-7, abs(finite_difference)))
    return records


def fit_moment_demo(steps=200):
    """Small scalar inverse problem; targets come from independent renewal moments."""
    known = OracleParams(mu=0.25, sigma=0.65, rho=0.4, K=0.4, r=-0.3, tau=0.25)
    boundary, initial, horizons = 1.1, 0.1, (0.4, 1.0, 2.0, 4.0)
    references = [exact_renewal_moments(initial, boundary, known, time) for time in horizons]
    target = torch.tensor([[row[key] for key in ("mean", "variance", "events")] for row in references], dtype=torch.float64)
    mu = torch.nn.Parameter(torch.tensor(-0.1, dtype=torch.float64))
    raw_sigma = torch.nn.Parameter(torch.tensor(math.log(math.expm1(0.8)), dtype=torch.float64))
    reset = torch.nn.Parameter(torch.tensor(-0.05, dtype=torch.float64))
    optimizer = torch.optim.Adam([mu, raw_sigma, reset], lr=0.025)
    grid, history, first_gradients = Grid(64, -4.0, 16), [], None
    started = time.process_time()
    for step in range(steps):
        optimizer.zero_grad(set_to_none=True)
        sigma = 0.1 + F.softplus(raw_sigma)
        flow = generator(mu, sigma, boundary, reset, known.tau, grid)
        state = initial_state(flow, initial)
        rows = [moments(flow, propagate(flow, state, horizon)) for horizon in horizons]
        predictions = torch.stack([torch.stack([row[key] for key in ("mean", "variance", "events")]) for row in rows])
        loss = ((predictions - target) / target.new_tensor([1.0, 1.0, 0.5])).square().mean()
        loss.backward()
        if first_gradients is None:
            first_gradients = dict(mu=float(mu.grad), raw_sigma=float(raw_sigma.grad), reset=float(reset.grad))
        optimizer.step()
        with torch.no_grad():
            reset.clamp_(-3.9, 0.9)
        history.append(dict(step=step + 1, loss=float(loss.detach()), mu=float(mu.detach()),
                             sigma=float((0.1 + F.softplus(raw_sigma)).detach()), reset=float(reset.detach())))
    with torch.no_grad():
        flow = generator(mu, 0.1 + F.softplus(raw_sigma), boundary, reset, known.tau, grid)
        state = initial_state(flow, initial)
        final_moments = [moments(flow, propagate(flow, state, horizon)) for horizon in horizons]
        predictions = torch.stack([torch.stack([row[key] for key in ("mean", "variance", "events")])
                                    for row in final_moments])
        final_loss = float(((predictions - target) / target.new_tensor([1.0, 1.0, 0.5])).square().mean())
    return dict(scope="scalar inverse-moment fit; independent exact targets; no classification",
                known=dict(mu=known.mu, sigma=known.sigma, reset=known.r),
                grid=dict(nodes=64, lower=-4.0, refractory_stages=16),
                horizons=list(horizons), targets=references, first_gradients=first_gradients,
                history=history, final_loss=final_loss,
                final_moments=[_numeric(row) for row in final_moments],
                cpu_seconds=time.process_time() - started,
                approximation_bias_expected=True)


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    cases = [_case("zero_drift", 0, 1, 1, 0, 0.2, 0, 1),
             _case("positive_drift", 0.3, 0.65, 1.1, -0.2, 0.25, 0.2, 2),
             _case("negative_drift", -0.3, 0.7, 0.9, -0.25, 0.15, 0.15, 2),
             _case("instant_reset", 0.2, 0.8, 1, -0.2, 0, 0.1, 2)]
    convergence = []
    for case in cases:
        params = OracleParams(mu=case["mu"], sigma=case["sigma"], rho=0.4,
                              K=0.4, r=case["reset"], tau=case["tau"])
        reference = exact_renewal_moments(case["initial"], case["boundary"], params, case["horizon"])
        records = [_evaluate(case, Grid(nodes, -4.0, 32)) for nodes in (32, 64, 128, 256)]
        convergence.append(dict(case=case, exact=reference, spatial_refinement=records))
    stage_case = _case("delay_refinement", 0.5, 0.8, 1, 0, 0.6, 0.1, 3)
    stage_params = OracleParams(mu=0.5, sigma=0.8, rho=0.4, K=0.4, r=0, tau=0.6)
    stages = dict(case=stage_case, exact=exact_renewal_moments(0.1, 1, stage_params, 3),
                  records=[_evaluate(stage_case, Grid(192, -4, stage)) for stage in (1, 4, 16, 64)])
    domain_case = _case("domain_refinement", 0, 1, 1, 0, 0.2, 0, 3)
    domain_params = OracleParams(mu=0, sigma=1, rho=0.4, K=0.4, r=0, tau=0.2)
    domains = dict(case=domain_case, exact=exact_renewal_moments(0, 1, domain_params, 3),
                   records=[_evaluate(domain_case, Grid(int((1 - lower) / 0.05), lower, 32))
                                             for lower in (-1, -2, -4, -6)])
    flow = generator(0, 1, 1, 0, 0.2, Grid(128, -4, 32))
    initial = initial_state(flow, 0)
    partitions = []
    for count in (1, 4, 16, 64, 256):
        with torch.no_grad():
            result = _numeric(moments(flow, propagate(flow, initial, 1, count)))
        case = AuditCase("dt_comparison", OracleParams(mu=0, sigma=1, rho=0.4,
                         K=0.4, r=0, tau=0.2), 0, 1, ())
        partitions.append(dict(partitions=count, dt=1 / count, distributional=result,
                                mean_closure=neural_mean_closure(case, 1, 1 / count)))
    results = dict(scope="independent scalar static-boundary repair reference, outside frozen study",
                    spatial_convergence=convergence, refractory_convergence=stages,
                    domain_convergence=domains, partition_invariance=partitions,
                    gradients=gradient_audit(), scalar_fit=fit_moment_demo(),
                    total_cpu_seconds=time.process_time() - started,
                    torch=torch.__version__, threads=torch.get_num_threads(),
                    energy_measured=False, main_outcomes_read=False,
                    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    frozen_model_sha256=hashlib.sha256((Path(__file__).parent / "model.py").read_bytes()).hexdigest())
    (output / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(Path(__file__).parent / "results" / "flow_repair001"))
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    run(args.output)
