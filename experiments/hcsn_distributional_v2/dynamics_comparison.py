"""Four reset semantics under the same finite-grid drive, with raw evidence.

This diagnostic changes no trained model or frozen protocol. A passive recovery
trace sums exponentially decaying event impulses; it has no feedback into the
driver and is not represented as an independently validated adaptation model.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import numpy as np
from scipy.linalg import expm
from scipy.stats import poisson
import torch

from .distribution_kernel import Grid, prepare_operator
from .kernel_tests import independent_generator


PARAMETERS = [.45, .6, .55, .05, .3]
MODELS = ["absorbing_no_reset", "end_window_probability_reset", "instant_reset_ctmc", "erlang2_refractory_ctmc"]
DURATIONS = [.0625, .25, 1.]
HORIZONS = [1., 4., 16.]
MC_SAMPLES = 12000
MC_TRACE_SAMPLES = 128
SEED = 103041
RECOVERY_TAU = .8
COUNT_CAP = 128
UNIFORMIZATION_RATE = 8.1
UNIFORMIZATION_TERMS = 512
LIMITS = dict(dense_semigroup=5e-12, source_kernel_state_l1=2e-10,
              source_kernel_events=2e-10, distribution_mass=2e-12,
              histogram_tail=1e-12, count_moment=2e-10,
              monte_carlo_family_alpha=1e-4, monte_carlo_mean_standard_errors=6.,
              monte_carlo_mean_absolute_slack=2e-3)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def specification(name):
    phases = 2 if name == "erlang2_refractory_ctmc" else 0
    grid = Grid(8, -2., phases, fixed_rate=8.1, fixed_terms=21, max_duration=.36, per_token_chunks=True)
    full, event, centers, reset = independent_generator(*PARAMETERS, grid)
    destination = np.zeros(len(full))
    if phases:
        destination[8] = 1
    else:
        destination[:8] = reset
    mark = np.outer(destination, event)
    killed = full - mark
    if name == "absorbing_no_reset":
        generator = np.zeros((9, 9)); generator[:8, :8] = killed
        generator[8, :8] = event
        mark = np.zeros_like(generator); mark[8, :8] = event
        event = np.r_[event, 0.]
        initial = np.r_[reset, 0.]
    elif name == "end_window_probability_reset":
        generator, initial = None, reset.copy()
    else:
        generator, initial = full, np.r_[reset, np.zeros(phases)]
    return dict(name=name, grid=grid, generator=generator, mark_matrix=mark,
                killed_active=killed[:8, :8], event=event, reset=reset,
                initial=initial, phases=phases, centers=centers)


def moment_operator(spec, dt):
    """Column operator on [state probabilities, E count, E recovery trace]."""
    n = len(spec["initial"])
    if spec["name"] == "end_window_probability_reset":
        survival = expm(spec["killed_active"].T * dt)
        event = 1 - survival.sum(-1)
        transition = survival + np.outer(event, spec["reset"])
        operator = np.zeros((n + 2, n + 2))
        operator[:n, :n] = transition.T
        operator[n, :n] = event; operator[n, n] = 1
        operator[n + 1, :n] = event; operator[n + 1, n + 1] = np.exp(-dt / RECOVERY_TAU)
        return operator
    augmented = np.zeros((n + 2, n + 2))
    augmented[:n, :n] = spec["generator"]
    augmented[n, :n] = spec["event"]
    augmented[n + 1, :n] = spec["event"]
    augmented[n + 1, n + 1] = -1 / RECOVERY_TAU
    return expm(augmented * dt)


def count_distribution(spec, dt, horizon):
    """Independent marked-uniformization count law, or discrete end-window law."""
    states = len(spec["initial"])
    joint = np.zeros((COUNT_CAP + 1, states)); joint[0] = spec["initial"]
    if spec["name"] == "end_window_probability_reset":
        zero = expm(spec["killed_active"] * dt)
        one = np.outer(spec["reset"], 1 - zero.sum(0))
        overflow = 0.
        for _ in range(round(horizon / dt)):
            overflow += float(joint[-1] @ one.sum(0))
            new = joint @ zero.T
            new[1:] += joint[:-1] @ one.T
            joint = new
        return joint.sum(-1), dict(count_tail_discarded=overflow, poisson_tail=0.)
    zero = np.eye(states) + (spec["generator"] - spec["mark_matrix"]) / UNIFORMIZATION_RATE
    one = spec["mark_matrix"] / UNIFORMIZATION_RATE
    mean = UNIFORMIZATION_RATE * horizon
    weight = np.exp(-mean)
    mixture = weight * joint
    overflow_power, weighted_overflow = 0., 0.
    for order in range(1, UNIFORMIZATION_TERMS + 1):
        overflow_power += float(joint[-1] @ one.sum(0))
        new = joint @ zero.T; new[1:] += joint[:-1] @ one.T
        joint = new
        weight *= mean / order
        mixture += weight * joint
        weighted_overflow += weight * overflow_power
    return mixture.sum(-1), dict(count_tail_discarded=weighted_overflow,
                                poisson_tail=float(poisson.sf(UNIFORMIZATION_TERMS, mean)))


def deterministic(spec, dt, horizon):
    operator = moment_operator(spec, dt)
    state = np.r_[spec["initial"], 0., 0.]
    records = [[0., *state]]
    for step in range(1, round(horizon / dt) + 1):
        state = operator @ state
        records.append([step * dt, *state])
    one = moment_operator(spec, dt) @ np.r_[spec["initial"], 0., 0.]
    half = moment_operator(spec, dt / 2)
    divided = half @ half @ np.r_[spec["initial"], 0., 0.]
    semigroup = dict(state_l1=float(np.abs(one[:-2] - divided[:-2]).sum()),
                     expected_count=abs(float(one[-2] - divided[-2])),
                     passive_recovery=abs(float(one[-1] - divided[-1])))
    law, certificate = count_distribution(spec, dt, horizon)
    count_mean = float(law @ np.arange(len(law)))
    count_variance = float(law @ (np.arange(len(law)) - count_mean) ** 2)
    assert abs(law.sum() - 1) < LIMITS["distribution_mass"]
    assert certificate["count_tail_discarded"] < LIMITS["histogram_tail"]
    assert abs(count_mean - state[-2]) < LIMITS["count_moment"]
    if spec["name"] != "end_window_probability_reset":
        assert max(semigroup.values()) < LIMITS["dense_semigroup"]
    source_check = None
    if spec["name"] in ("instant_reset_ctmc", "erlang2_refractory_ctmc"):
        xs = [torch.tensor(v, dtype=torch.float64) for v in PARAMETERS]
        prepared = prepare_operator(*xs, horizon, spec["grid"])
        p = torch.tensor(spec["initial"], dtype=torch.float64)
        result = p @ prepared["transition"]
        source_check = dict(state_l1_error=float(np.abs(result.numpy() - state[:-2]).sum()),
                            event_error=abs(float(p @ prepared["event_vector"]) - state[-2]),
                            probability_bound=float(prepared["solver"]["probability_l1_error_bound"]),
                            event_bound=float(prepared["solver"]["event_error_bound"]))
        assert source_check["state_l1_error"] < LIMITS["source_kernel_state_l1"]
        assert source_check["event_error"] < LIMITS["source_kernel_events"]
    return np.asarray(records), law, dict(expected_events=float(state[-2]), event_count_mean_from_law=count_mean,
        event_count_variance_from_law=count_variance, passive_recovery_mean=float(state[-1]),
        final_active_mass=float(state[:8].sum()),
        final_refractory_phase_mass=state[8:10].tolist() if spec["phases"] else [],
        final_absorbed_mass=float(state[8]) if spec["name"] == "absorbing_no_reset" else 0.,
        half_step_semigroup_error=semigroup, count_law_certificate=certificate,
        original_source_kernel_comparison=source_check)


def monte_carlo(spec, dt, horizon, seed):
    """Event-driven jump paths; probability reset is delayed until window end."""
    rng = np.random.default_rng(seed)
    name, phases = spec["name"], spec["phases"]
    state = rng.choice(len(spec["initial"]), MC_SAMPLES, p=spec["initial"])
    counts = np.zeros(MC_SAMPLES, dtype=np.int32)
    recovery = np.zeros(MC_SAMPLES)
    time_now = np.zeros(MC_SAMPLES)
    n = 8
    mu, sigma, boundary, reset, tau = PARAMETERS
    h = (boundary + 2) / n; D = sigma * sigma / 2
    up, down, exit_rate = D / h ** 2 + max(mu, 0) / h, D / h ** 2 + max(-mu, 0) / h, 2 * D / h ** 2 + max(mu, 0) / h
    number_states = 10 if phases else 9
    rate = np.full(number_states, up + down)
    rate[0] = up; rate[n - 1] = down + exit_rate
    rate[n:] = phases / tau if phases else 0.
    sample_records, aggregate = [], []
    physical_jumps = 0
    for step in range(1, round(horizon / dt) + 1):
        end = step * dt
        live = rate[state] > 0
        while live.any():
            indices = np.flatnonzero(live)
            current = state[indices]
            waiting = rng.exponential(1 / rate[current])
            occurred = time_now[indices] + waiting <= end
            no = indices[~occurred]
            recovery[no] *= np.exp(-(end - time_now[no]) / RECOVERY_TAU)
            time_now[no] = end; live[no] = False
            indices, current, waiting = indices[occurred], current[occurred], waiting[occurred]
            if not len(indices):
                continue
            physical_jumps += len(indices)
            recovery[indices] *= np.exp(-waiting / RECOVERY_TAU)
            time_now[indices] += waiting
            uniform = rng.random(len(indices))
            active = current < n
            left = active & (uniform < np.where(current > 0, down, 0.) / rate[current])
            state[indices[left]] -= 1
            right_or_mark = active & ~left
            marked = right_or_mark & (current == n - 1)
            ordinary_right = right_or_mark & ~marked
            state[indices[ordinary_right]] += 1
            if marked.any():
                marked_indices = indices[marked]
                if name in ("absorbing_no_reset", "end_window_probability_reset"):
                    state[marked_indices] = n; live[marked_indices] = False
                elif phases:
                    state[marked_indices] = n
                else:
                    state[marked_indices] = rng.choice(n, len(marked_indices), p=spec["reset"])
                if name != "end_window_probability_reset":
                    counts[marked_indices] += 1; recovery[marked_indices] += 1
            refractory = ~active
            release = refractory & (current == n + phases - 1)
            if release.any():
                state[indices[release]] = rng.choice(n, int(release.sum()), p=spec["reset"])
            progress = refractory & ~release
            state[indices[progress]] += 1
        # Absorbed/pending paths have no further physical jumps this window.
        remaining = time_now < end
        recovery[remaining] *= np.exp(-(end - time_now[remaining]) / RECOVERY_TAU)
        time_now[remaining] = end
        if name == "end_window_probability_reset":
            pending = state == n
            counts[pending] += 1; recovery[pending] += 1
            state[pending] = rng.choice(n, int(pending.sum()), p=spec["reset"])
        probability = np.bincount(state, minlength=len(spec["initial"])) / MC_SAMPLES
        aggregate.append([end, float(counts.mean()), float(counts.var(ddof=1)), float(recovery.mean()), *probability])
        sample_records.append(np.stack((state[:MC_TRACE_SAMPLES], counts[:MC_TRACE_SAMPLES], recovery[:MC_TRACE_SAMPLES]), -1))
    return dict(final_state=state, final_count=counts, final_recovery=recovery,
                aggregate_trace=np.asarray(aggregate), sample_trace=np.asarray(sample_records),
                physical_jumps=physical_jumps)


def run_case(name, dt, horizon, index, output):
    spec = specification(name)
    trace, law, evidence = deterministic(spec, dt, horizon)
    seed = SEED + index
    mc = monte_carlo(spec, dt, horizon, seed)
    histogram = np.bincount(mc["final_count"], minlength=COUNT_CAP + 1) / MC_SAMPLES
    if len(histogram) != len(law):
        raise ValueError("Observed count exceeded registered count cap")
    cdf_distance = float(np.abs(histogram.cumsum() - law.cumsum()).max())
    number_comparisons = len(MODELS) * len(DURATIONS) * len(HORIZONS)
    dkw_guard = float(np.sqrt(np.log(2 * number_comparisons / LIMITS["monte_carlo_family_alpha"]) / (2 * MC_SAMPLES)))
    mean_count = float(mc["final_count"].mean())
    standard_error = float(mc["final_count"].std(ddof=1) / np.sqrt(MC_SAMPLES))
    mean_guard = LIMITS["monte_carlo_mean_standard_errors"] * standard_error + LIMITS["monte_carlo_mean_absolute_slack"]
    recovery_mean = float(mc["final_recovery"].mean())
    recovery_se = float(mc["final_recovery"].std(ddof=1) / np.sqrt(MC_SAMPLES))
    recovery_guard = LIMITS["monte_carlo_mean_standard_errors"] * recovery_se + LIMITS["monte_carlo_mean_absolute_slack"]
    assert cdf_distance <= dkw_guard
    assert abs(mean_count - evidence["expected_events"]) <= mean_guard
    assert abs(recovery_mean - evidence["passive_recovery_mean"]) <= recovery_guard
    file_name = f"{name}_dt{str(dt).replace('.', 'p')}_T{int(horizon)}.npz"
    data = dict(deterministic_trace=trace, count_law=law, mc_count_histogram=histogram,
                mc_final_count=mc["final_count"], mc_final_state=mc["final_state"],
                mc_final_passive_recovery=mc["final_recovery"],
                mc_aggregate_trace=mc["aggregate_trace"], mc_first128_sample_trace=mc["sample_trace"],
                initial=spec["initial"], marked_event_intensity=spec["event"],
                killed_active_generator=spec["killed_active"], reset_distribution=spec["reset"])
    if spec["generator"] is not None:
        data.update(column_generator=spec["generator"], mark_matrix=spec["mark_matrix"])
    np.savez_compressed(output / file_name, **data)
    return dict(model=name, observation_dt=dt, horizon=horizon, seed=seed, **evidence,
        monte_carlo=dict(samples=MC_SAMPLES, count_sum=int(mc["final_count"].sum()),
            count_mean=mean_count, count_standard_error=standard_error, count_mean_registered_guard=mean_guard,
            passive_recovery_mean=recovery_mean, passive_recovery_standard_error=recovery_se,
            passive_recovery_registered_guard=recovery_guard, count_cdf_max_error=cdf_distance,
            simultaneous_dkw_guard=dkw_guard, physical_jumps=mc["physical_jumps"],
            raw_final_count_saved=True, raw_first128_trajectories_saved=True),
        raw_path=file_name, raw_sha256=digest(output / file_name))


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    directory = Path(__file__).parent
    paths = [Path(__file__), directory / "distribution_kernel.py", directory / "kernel_tests.py"]
    sources = {str(p): digest(p) for p in paths}
    registration = dict(schema="hcsn-four-reset-dynamics-registration.v1", parameters=PARAMETERS,
        parameter_order=["mu", "sigma", "boundary", "reset", "mean_refractory_duration"],
        driver="Same constant mu, sigma, boundary and reset across all variants; initial state at reset interpolation",
        models=MODELS, observation_durations=DURATIONS, horizons=HORIZONS,
        cells=8, lower_wall=-2., initial_at_reset=True, monte_carlo_samples=MC_SAMPLES,
        monte_carlo_seed_start=SEED, raw_trajectory_samples=MC_TRACE_SAMPLES,
        count_cap=COUNT_CAP, reference_uniformization_rate=UNIFORMIZATION_RATE,
        reference_uniformization_terms=UNIFORMIZATION_TERMS, limits=LIMITS,
        passive_recovery=dict(tau=RECOVERY_TAU, definition="sum exp(-(t-event_time)/tau)",
            feedback_into_driver=False, probability_reset_event_time="observation-window endpoint"),
        no_reset="Killed active process plus absorbing fired state; at most one event total",
        probability_reset="First event in each window freezes path; reset deposited at endpoint, at most one event per window",
        instantaneous_reset="Marked CTMC with immediate reinjection, allowing repeated events including self-reset",
        refractory="Marked CTMC reinjects after two Erlang phases, with mean tau and variance tau^2/2",
        source_sha256=sources, task_labels_read=False, frozen_sources_changed=False,
        limitations=["Finite reflecting grid, not Brownian spatial convergence evidence",
                     "Passive recovery is a diagnostic readout, not new adaptive feedback",
                     "No-reset has no reset or refractory parameter to train",
                     "These dynamical checks do not test content quality"])
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    rows, failures = [], []
    jobs = [(name, dt, horizon) for name in MODELS for dt in DURATIONS for horizon in HORIZONS]
    for i, (name, dt, horizon) in enumerate(jobs):
        try:
            rows.append(run_case(name, dt, horizon, i, output))
        except Exception:
            failures.append(dict(model=name, observation_dt=dt, horizon=horizon, traceback=traceback.format_exc()))
    changed = [str(p) for p in paths if digest(p) != sources[str(p)]]
    summary = dict(schema="hcsn-four-reset-dynamics-audit.v1", passed=not failures and not changed,
                   records=rows, failures=failures, source_sha256=sources, source_changed_during_audit=changed,
                   self_cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall,
                   peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   gpu_measured=False, energy_measured=False)
    (output / "RESULTS.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    lines = ["# Same-drive reset and refractory comparison", "",
        "All four processes use the same finite-grid drift, diffusion, boundary, reset location and initial state. "
        "Absorption permits one event in the entire episode. Endpoint probability reset permits one event "
        "per observation window and deliberately delays reinjection. Immediate reset and Erlang refractory "
        "variants are continuous-time marked chains and permit repeated events within one window.", "",
        "| Process | Observation dt | T | Expected count | Active mass | Refractory phase mass | Passive recovery |",
        "|---|---:|---:|---:|---:|---|---:|"]
    for row in rows:
        if row["horizon"] == HORIZONS[-1]:
            lines.append(f"| {row['model']} | {row['observation_dt']} | {row['horizon']} | {row['expected_events']:.9g} | "
                         f"{row['final_active_mass']:.9g} | {row['final_refractory_phase_mass']} | {row['passive_recovery_mean']:.9g} |")
    lines.extend(["", "The continuous chains satisfy time-subdivision consistency, including expected counts and "
        "a passive exponentially decaying event trace. The endpoint reset approximation generally does not; "
        "its discrepancy and convergence with smaller observation steps are reported rather than hidden.", "",
        "Count distributions use a separately assembled marked-uniformization recursion. Each of the 36 scenarios "
        "has 12000 independent event-driven Monte Carlo paths, final per-path count/state/recovery records, "
        "and 128 complete sampled trajectories. Count CDF comparisons use a predeclared simultaneous DKW bound.", "",
        "The passive recovery trace has no feedback into the drive. Refractory recovery is the Erlang phase exit; "
        "neither is presented as a newly verified biophysical adaptation law. Trainable parameters are evaluated "
        "by the separate content experiments, not by inventing reset gradients for an absorbing process.", "",
        f"Passed: {summary['passed']}. Self CPU {summary['self_cpu_seconds']:.6f}s; wall {summary['wall_seconds']:.6f}s.", ""])
    if failures:
        lines.extend(["## Failures", "", *[item["traceback"] for item in failures]])
    (output / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({key: summary[key] for key in ("passed", "self_cpu_seconds", "wall_seconds")}))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    main(args.output)
