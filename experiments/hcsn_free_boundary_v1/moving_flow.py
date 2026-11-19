"""Conservative cell-average flow with instantaneous boundary-jump events.

Independent reference only: no frozen neural-study files or outcomes are used.
The physical lower bound, reset, refractory mean/stages and affine event reward
remain fixed within an episode. Drift, volatility and boundary are piecewise
constant. Matrix exponentials are exact for each finite generator; spatial,
domain, remapping and Erlang approximations remain explicit.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch
from torch.nn import functional as F

from .closure_audit import _sample_hit, _sample_killed_endpoint


@dataclass(frozen=True)
class Grid:
    cells: int = 96
    lower: float = -5.0
    refractory_stages: int = 16


def _weights(value, centers, spacing):
    if bool((value < centers[0]) | (value > centers[-1])):
        raise ValueError("Initial/reset location must be represented by grid centers")
    weights = (1 - (centers - value).abs() / spacing).clamp_min(0)
    return weights / weights.sum()


def generator(mu, sigma, boundary, reset, tau, grid=Grid(),
              reward_slope=1.0, reward_intercept=-0.4):
    """Cell-centered finite-volume generator; p holds cell-integrated mass.

    Internal diffusion jumps have rate D/h**2. The absorbing upper face is
    h/2 from its last center, giving outgoing diffusion rate 2D/h**2.
    Incoming upwind advection from outside has zero density when mu<0.
    Reconstructing a uniform density inside cells is the remapping convention;
    this is deliberately distinct from distributional_flow's nodal grid.
    """
    values = (mu, sigma, boundary, reset, tau, reward_slope, reward_intercept)
    anchor = next((value for value in values if isinstance(value, torch.Tensor)),
                  torch.tensor(0.0, dtype=torch.float64))
    mu, sigma, boundary, reset, tau, slope, intercept = [
        torch.as_tensor(value, dtype=anchor.dtype, device=anchor.device) for value in values]
    if any(value.ndim != 0 or not bool(torch.isfinite(value))
           for value in (mu, sigma, boundary, reset, tau, slope, intercept)):
        raise ValueError("Finite scalar parameters required")
    if (grid.cells < 4 or grid.refractory_stages < 1 or not math.isfinite(grid.lower)
            or bool((sigma < 0) | (tau < 0) | (boundary <= grid.lower) | (reset >= boundary))):
        raise ValueError("Require >=4 cells, >=1 phase, sigma/tau>=0, finite L<r<b")
    n, stages = grid.cells, grid.refractory_stages if bool(tau > 0) else 0
    spacing = (boundary - grid.lower) / n
    edges = grid.lower + torch.arange(n + 1, dtype=anchor.dtype, device=anchor.device) * spacing
    centers = (edges[:-1] + edges[1:]) / 2
    reset_weights = _weights(reset, centers, spacing)
    diffusion = sigma.square() / (2 * spacing.square())
    up = diffusion + mu.clamp_min(0) / spacing
    down = diffusion + (-mu).clamp_min(0) / spacing
    exit_rate = 2 * diffusion + mu.clamp_min(0) / spacing
    ones = anchor.new_ones(n - 1)
    zero = anchor.new_zeros(1)
    active = (up * (torch.diag(ones, -1) - torch.diag(torch.cat((ones, zero))))
              + down * (torch.diag(ones, 1) - torch.diag(torch.cat((zero, ones)))))
    Q = F.pad(active, (0, stages, 0, stages))
    size = n + stages
    basis = torch.eye(size, dtype=anchor.dtype, device=anchor.device)
    reset_destination = F.pad(reset_weights, (0, stages))
    destination = basis[:, n] if stages else reset_destination
    Q = Q + exit_rate * torch.outer(destination - basis[:, n - 1], basis[:, n - 1])
    if stages:
        chain = (torch.diag(anchor.new_ones(stages - 1), -1)
                 - torch.eye(stages, dtype=anchor.dtype, device=anchor.device))
        Q = Q + (stages / tau) * (F.pad(chain, (n, 0, n, 0))
                                  + torch.outer(reset_destination, basis[:, -1]))
    event_rate = exit_rate * basis[:, n - 1]
    reward_rate = (slope * boundary + intercept) * event_rate
    augmented = F.pad(Q, (0, 2, 0, 2))
    augmented = augmented + torch.outer(F.pad(anchor.new_ones(1), (size, 1)),
                                        F.pad(event_rate, (0, 2)))
    augmented = augmented + torch.outer(F.pad(anchor.new_ones(1), (size + 1, 0)),
                                        F.pad(reward_rate, (0, 2)))
    return dict(Q=Q, augmented=augmented, centers=centers, edges=edges,
                spacing=spacing, reset=reset, tau=tau, boundary=boundary,
                stages=stages, reset_weights=reset_weights, event_rate=event_rate,
                reward_rate=reward_rate, reward_slope=slope, reward_intercept=intercept,
                mu=mu, sigma=sigma, grid=grid)


def initial_state(flow, initial):
    x = torch.as_tensor(initial, dtype=flow["Q"].dtype, device=flow["Q"].device)
    if x.ndim != 0 or not bool(torch.isfinite(x)):
        raise ValueError("Finite scalar initial pressure required")
    if bool(x >= flow["boundary"]):
        if flow["stages"]:
            probability = flow["Q"].new_zeros(flow["Q"].shape[0])
            probability[flow["grid"].cells] = 1
        else:
            probability = flow["reset_weights"]
        count = x.new_ones(())
        reward = flow["reward_slope"] * x + flow["reward_intercept"]
    else:
        probability = F.pad(_weights(x, flow["centers"], flow["spacing"]), (0, flow["stages"]))
        count, reward = x.new_zeros(()), x.new_zeros(())
    return torch.cat((probability, count.reshape(1), reward.reshape(1)))


def propagate(flow, state, horizon, partitions=1):
    if horizon < 0 or partitions < 1:
        raise ValueError("Nonnegative horizon and positive partitions required")
    transition = torch.matrix_exp(flow["augmented"] * (horizon / partitions))
    for _ in range(partitions):
        state = transition @ state
    return state


def remap(old, new, state):
    """Conservative overlap projection, with covered active mass firing at once.

    Old cell mass represents a piecewise-constant density on physical cells.
    The integral over each old/new overlap is transferred. Above-new-boundary
    active mass enters reset/phase0 and adds an immediate event and the exact
    affine-reward integral of that reconstructed density. Existing phase mass
    is copied unchanged: its remaining Erlang-phase law is never restarted.
    """
    if old["grid"].lower != new["grid"].lower or old["stages"] != new["stages"]:
        raise ValueError("Physical lower bound and refractory phase count must remain fixed")
    for field in ("reset", "tau", "reward_slope", "reward_intercept"):
        if not bool(old[field] == new[field]):
            raise ValueError(f"{field} must remain fixed throughout the episode")
    old_n, new_n = old["grid"].cells, new["grid"].cells
    if state.shape != (old["Q"].shape[0] + 2,):
        raise ValueError("State shape does not match the old flow")
    left = torch.maximum(new["edges"][:-1, None], old["edges"][None, :-1])
    right = torch.minimum(new["edges"][1:, None], old["edges"][None, 1:])
    overlaps = (right - left).clamp_min(0)
    old_widths = old["edges"][1:] - old["edges"][:-1]
    transfer = overlaps / old_widths
    hit_left = torch.maximum(old["edges"][:-1], new["boundary"])
    hit_width = (old["edges"][1:] - hit_left).clamp_min(0)
    hit_fraction = hit_width / old_widths
    hit_first_moment = hit_fraction * (hit_left + old["edges"][1:]) / 2
    active = state[:old_n]
    immediate_count = hit_fraction @ active
    immediate_first_moment = hit_first_moment @ active
    immediate_reward = (new["reward_slope"] * immediate_first_moment
                        + new["reward_intercept"] * immediate_count)
    probabilities = transfer @ active
    if new["stages"]:
        phase = state[old_n:old_n + old["stages"]]
        phase = phase + F.pad(immediate_count.reshape(1), (0, new["stages"] - 1))
        probabilities = torch.cat((probabilities, phase))
    else:
        probabilities = probabilities + immediate_count * new["reset_weights"]
    result = torch.cat((probabilities, (state[-2] + immediate_count).reshape(1),
                        (state[-1] + immediate_reward).reshape(1)))
    physical_mean = (state[:old_n] @ old["centers"]
                     + state[old_n:-2].sum() * old["reset"]
                     - immediate_first_moment + new["reset"] * immediate_count)
    projected_mean = (result[:new_n] @ new["centers"]
                      + result[new_n:-2].sum() * new["reset"])
    # Replacing overlap-supported density by a uniform new cell can move its
    # centroid by at most half the new width; reset interpolation preserves r.
    first_moment_error_bound = new["spacing"] * (active.sum() - immediate_count) / 2
    return result, dict(immediate_events=immediate_count, immediate_reward=immediate_reward,
                        removed_active_first_moment=immediate_first_moment,
                        physical_post_jump_mean=physical_mean,
                        projected_post_jump_mean=projected_mean,
                        projection_mean_error=projected_mean-physical_mean,
                        projection_mean_error_bound=first_moment_error_bound,
                        transfer_column_mass=transfer.sum(0) + hit_fraction,
                        transfer=transfer, hit_fraction=hit_fraction)


def moments(flow, state):
    n = flow["grid"].cells
    probability, active = state[:-2], state[:n]
    phase = probability[n:]
    mean = active @ flow["centers"] + phase.sum() * flow["reset"]
    # Uniform-cell reconstruction: E[X^2 | cell i] = center_i^2+h^2/12.
    second = (active @ (flow["centers"].square() + flow["spacing"].square() / 12)
              + phase.sum() * flow["reset"].square())
    if flow["stages"]:
        phase_remaining = (torch.arange(flow["stages"], 0, -1,
                                       dtype=state.dtype, device=state.device)
                           * flow["tau"] / flow["stages"])
        refractory_remaining = phase @ phase_remaining
    else:
        refractory_remaining = state.new_zeros(())
    return dict(mean=mean, second_moment=second, variance=second - mean.square(),
                events=state[-2], reward=state[-1], mass=probability.sum(),
                minimum_probability=probability.min(), refractory_mass=phase.sum(),
                refractory_remaining=refractory_remaining, lower_cell_mass=active[0])


def projected_policy_values(flow, state, rho=0.4):
    """Finite-generator fixed-threshold values, with an explicit eligible obstacle.

    This solves the discounted policy-evaluation linear system for this local
    finite generator. It does not optimize the threshold or anticipate later
    input changes. Refractory intervention is disallowed and excluded explicitly.
    """
    rho = torch.as_tensor(rho, dtype=state.dtype, device=state.device)
    if not bool(rho > 0):
        raise ValueError("Positive discount required")
    size = flow["Q"].shape[0]
    operator = rho * torch.eye(size, dtype=state.dtype, device=state.device) - flow["Q"].T
    value = torch.linalg.solve(operator, flow["reward_rate"])
    n = flow["grid"].cells
    after_reset = value[n] if flow["stages"] else flow["reset_weights"] @ value[:n]
    obstacle = flow["reward_slope"] * flow["centers"] + flow["reward_intercept"] + after_reset
    return dict(continuation=state[:-2] @ value,
                eligible_continuation=state[:n] @ value[:n],
                eligible_intervention=state[:n] @ obstacle,
                eligible_continuation_gap=state[:n] @ (value[:n] - obstacle),
                eligible_mass=state[:n].sum(), active_J=value[:n], active_G=obstacle,
                phase_J=value[n:], bellman_residual=(operator @ value - flow["reward_rate"]).abs().max())


def rollout(segments, reset, tau, initial, grid=Grid(), reward_slope=1.0, reward_intercept=-0.4,
            partitions=1):
    flow, state, records = None, None, []
    for segment in segments:
        new_flow = generator(segment["mu"], segment["sigma"], segment["boundary"],
                             reset, tau, grid, reward_slope, reward_intercept)
        if flow is None:
            state = initial_state(new_flow, initial)
            jump = dict(immediate_events=state[-2], immediate_reward=state[-1],
                         projection_mean_error=state.new_zeros(()),
                         projection_mean_error_bound=state.new_zeros(()))
        else:
            state, jump = remap(flow, new_flow, state)
        after_jump = moments(new_flow, state)
        state = propagate(new_flow, state, segment["duration"], partitions)
        records.append(dict(after_jump=after_jump, after_segment=moments(new_flow, state),
                            jump={key: jump[key] for key in ("immediate_events", "immediate_reward",
                                  "projection_mean_error", "projection_mean_error_bound")}))
        flow = new_flow
    if flow is None:
        raise ValueError("At least one segment required")
    return flow, state, records


def exact_segment_monte_carlo(segments, reset, tau, initial, samples=50000, seed=601701,
                              refractory_stages=16, reward_slope=1.0, reward_intercept=-0.4):
    """Independent unbounded Brownian sample paths, with exact segment hitting.

    Hit clocks and killed endpoints are imported read-only from closure_audit.
    Each event samples Gamma(k,tau/k) residence, or exactly tau when k=None;
    remaining residence is carried across every boundary/parameter jump.
    No Euler time grid, Brownian bridge omission, or endpoint-only event test.
    """
    if samples < 2 or tau < 0 or any(s["boundary"] <= reset for s in segments):
        raise ValueError("Require >=2 paths, nonnegative tau and reset below every boundary")
    rng = np.random.default_rng(seed)
    x = np.full(samples, initial, dtype=float)
    cooldown = np.zeros(samples)
    count = np.zeros(samples)
    rewards = np.zeros(samples)
    records = []
    started = time.process_time()

    def residence(size):
        if tau == 0:
            return np.zeros(size)
        if refractory_stages is None:
            return np.full(size, tau)
        return rng.gamma(refractory_stages, tau / refractory_stages, size)

    def statistic(values):
        mean = float(values.mean())
        standard_error = float(values.std(ddof=1) / math.sqrt(samples))
        return dict(mean=mean, standard_error=standard_error,
                    pointwise_normal_95_ci=[mean - 1.96 * standard_error, mean + 1.96 * standard_error])

    def summarize():
        mean = x.mean()
        variance_samples = (x - mean)**2
        return dict(mean=statistic(x), second_moment=statistic(x*x),
                    variance=statistic(variance_samples), events=statistic(count),
                    reward=statistic(rewards), refractory_mass=statistic((cooldown > 0).astype(float)),
                    refractory_remaining=statistic(cooldown))

    for segment in segments:
        mu, sigma, boundary, duration = [float(segment[name]) for name in
                                        ("mu", "sigma", "boundary", "duration")]
        if sigma < 0 or duration < 0:
            raise ValueError("Nonnegative volatility and duration required")
        immediate = np.flatnonzero((cooldown <= 0) & (x >= boundary))
        jump_counts = np.zeros(samples)
        jump_rewards = np.zeros(samples)
        if immediate.size:
            jump_counts[immediate] = 1
            jump_rewards[immediate] = reward_slope * x[immediate] + reward_intercept
            count[immediate] += 1
            rewards[immediate] += jump_rewards[immediate]
            x[immediate] = reset
            cooldown[immediate] = residence(immediate.size)
        after_jump = summarize()
        remaining = np.full(samples, duration)
        for _ in range(10000):
            held = np.minimum(cooldown, remaining)
            cooldown -= held
            remaining -= held
            active = np.flatnonzero(remaining > 0)
            if active.size == 0:
                break
            available = remaining[active]
            start = x[active]
            if sigma == 0:
                hitting = ((boundary - start) / mu if mu > 0 else np.full(active.size, np.inf))
            else:
                hitting = _sample_hit(boundary - start, mu, sigma, rng)
            fires = hitting <= available
            nonhit = active[~fires]
            if nonhit.size:
                if sigma == 0:
                    x[nonhit] = start[~fires] + mu * available[~fires]
                else:
                    x[nonhit] = _sample_killed_endpoint(start[~fires], boundary, available[~fires],
                                                        mu, sigma, rng)
                remaining[nonhit] = 0
            hit = active[fires]
            if hit.size:
                count[hit] += 1
                rewards[hit] += reward_slope * boundary + reward_intercept
                x[hit] = reset
                remaining[hit] -= hitting[fires]
                cooldown[hit] = residence(hit.size)
        else:
            raise RuntimeError("Exact event sampler exceeded explicit per-segment event-loop cap")
        records.append(dict(after_jump=after_jump, after_segment=summarize(),
                            immediate_events=statistic(jump_counts), immediate_reward=statistic(jump_rewards)))
    return dict(samples=samples, seed=seed, refractory_stages=refractory_stages,
                refractory_law="deterministic" if refractory_stages is None else "Erlang",
                time_discretization="none: exact first-hit clocks and killed endpoint samples",
                lower_boundary="unbounded below", records=records,
                cpu_seconds=time.process_time() - started,
                confidence_interval_note="Pointwise normal Monte Carlo intervals; not discretization error bounds")


def _numeric(value):
    if isinstance(value, torch.Tensor):
        return float(value.detach()) if value.ndim == 0 else value.detach().tolist()
    if isinstance(value, dict):
        return {key: _numeric(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_numeric(item) for item in value]
    return value


def gradient_audit():
    """Differentiate a shrinking interior boundary, including its instantaneous atom."""
    grid = Grid(29, -3.0, 7)
    old = generator(0.21, 0.72, 1.13, -0.23, 0.31, grid)
    state = propagate(old, initial_state(old, 0.17), 0.71).detach()

    def objective(boundary):
        new = generator(-0.19, 0.61, boundary, -0.23, 0.31, grid)
        remapped, jump = remap(old, new, state)
        final = propagate(new, remapped, 0.43)
        values = moments(new, final)
        return 0.3*values["mean"] + 0.7*values["variance"] + 1.1*values["events"] + 0.2*values["reward"], jump

    boundary = torch.tensor(0.637, dtype=torch.float64, requires_grad=True)
    value, jump = objective(boundary)
    gradient = float(torch.autograd.grad(value, boundary, retain_graph=True)[0])
    jump_gradient = float(torch.autograd.grad(jump["immediate_events"], boundary)[0])
    epsilon = 1e-5
    plus, plus_jump = objective(0.637 + epsilon)
    minus, minus_jump = objective(0.637 - epsilon)
    finite = float((plus - minus)/(2*epsilon))
    jump_finite = float((plus_jump["immediate_events"]-minus_jump["immediate_events"])/(2*epsilon))
    return dict(boundary=0.637, finite_difference_step=epsilon,
                objective=dict(autograd=gradient, finite_difference=finite,
                               absolute_error=abs(gradient-finite),
                               relative_error=abs(gradient-finite)/max(1e-9, abs(finite))),
                immediate_count=dict(autograd=jump_gradient, finite_difference=jump_finite,
                                     absolute_error=abs(jump_gradient-jump_finite),
                                     relative_error=abs(jump_gradient-jump_finite)/max(1e-9, abs(jump_finite))),
                scope="Interior fixed-topology derivative, not a derivative through overlap knots")


def _scenario(name, segments, reset=-0.3, tau=0.3, initial=0.15):
    return dict(name=name, segments=segments, reset=reset, tau=tau, initial=initial)


def run(output, samples=50000):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    wall_started = time.perf_counter()
    cases = [
        _scenario("shrink_expand_drift_change", [
            dict(mu=0.35, sigma=0.8, boundary=1.15, duration=0.8),
            dict(mu=-0.25, sigma=0.65, boundary=0.48, duration=0.6),
            dict(mu=0.15, sigma=0.75, boundary=1.05, duration=0.8)]),
        _scenario("negative_drift_then_shrink", [
            dict(mu=-0.4, sigma=0.75, boundary=1.0, duration=0.9),
            dict(mu=0.45, sigma=0.65, boundary=0.35, duration=0.9),
            dict(mu=-0.15, sigma=0.6, boundary=0.85, duration=0.6)],
                  reset=-0.25, tau=0.45, initial=0.2),
    ]
    records = []
    for case_index, case in enumerate(cases):
        arguments = {key: value for key, value in case.items() if key != "name"}
        mc = exact_segment_monte_carlo(**arguments, samples=samples,
                                       seed=603001 + case_index, refractory_stages=16)
        spatial = []
        for cells in (32, 64, 128, 256, 512):
            begin = time.process_time()
            with torch.no_grad():
                flow, state, history = rollout(**arguments, grid=Grid(cells, -5, 16))
            spatial.append(dict(cells=cells, lower=-5, stages=16,
                                 records=_numeric(history), final=_numeric(moments(flow, state)),
                                 cpu_seconds=time.process_time()-begin))
        delay = []
        for stages in (1, 4, 16, 64):
            matched = mc if stages == 16 else exact_segment_monte_carlo(
                **arguments, samples=samples, seed=603011 + 10*case_index + stages,
                refractory_stages=stages)
            with torch.no_grad():
                flow, state, history = rollout(**arguments, grid=Grid(256, -5, stages))
            delay.append(dict(stages=stages, finite_final=_numeric(moments(flow, state)),
                              matched_erlang_monte_carlo=matched))
        deterministic = exact_segment_monte_carlo(**arguments, samples=samples,
                        seed=603101+case_index, refractory_stages=None)
        with torch.no_grad():
            flow, state, _ = rollout(**arguments, grid=Grid(128, -5, 16))
            projection = projected_policy_values(flow, state)
            projection = {key: value for key, value in projection.items()
                          if key not in ("active_J", "active_G", "phase_J")}
        records.append(dict(case=case, spatial=spatial, matched_erlang_monte_carlo=mc,
                             phase_refinement=delay, deterministic_delay_monte_carlo=deterministic,
                             local_policy_projection=_numeric(projection)))
    with torch.no_grad():
        arguments = {key: value for key, value in cases[0].items() if key != "name"}
        base_flow, base_state, _ = rollout(**arguments, grid=Grid(64, -5, 8))
        composition = []
        for parts in (1, 4, 16, 64):
            flow, state, _ = rollout(**arguments, grid=Grid(64, -5, 8), partitions=parts)
            composition.append(dict(partitions=parts, max_state_difference=float((state-base_state).abs().max()),
                                    final=_numeric(moments(flow, state))))
    directory = Path(__file__).parent
    source_files = ("moving_flow.py", "moving_flow_tests.py", "closure_audit.py", "distributional_flow.py", "model.py")
    results = dict(scope="Independent piecewise-constant scalar moving-boundary reference; outside main study",
                   scenarios=records, composition=composition, gradients=gradient_audit(),
                   total_cpu_seconds=time.process_time()-started,
                   wall_seconds=time.perf_counter()-wall_started,
                   peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   torch=torch.__version__, python=platform.python_version(),
                   threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
                   source_sha256={name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                                  for name in source_files},
                   energy_measured=False, main_outcomes_read=False,
                   state_semantics="active cell masses; Erlang phase masses; cumulative event count and undiscounted affine firing reward",
                   fixed_episode_parameters=["lower", "reset", "tau", "refractory_stages", "reward_slope", "reward_intercept"])
    (output/"results.json").write_text(json.dumps(results, indent=2, sort_keys=True, allow_nan=False)+"\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=50000)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    run(args.output, args.samples)
