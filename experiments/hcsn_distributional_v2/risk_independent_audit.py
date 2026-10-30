"""Independent audit of the new first-marked-event risk kernel.

References use physical jump enumeration, dense matrix exponentials, scalar
overlap loops, and an event-driven Monte Carlo simulation. The new risk kernel
is imported only after its hash and the fixed experiment have been registered.
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
import torch

from .distribution_kernel import Grid, make_flow, prepare_operator
from .kernel_tests import independent_generator
from .stable_probability_tests import independent_remap


CASES = [
    dict(name="phase_mixture", phases=2, parameters=[.237, .513, .8431, -.173, .417], old_boundary=1.137, duration=.495755147934),
    dict(name="repeated_event_window", phases=2, parameters=[.48, .6, .55, .05, .3], old_boundary=.55, duration=7.31),
    dict(name="self_reset", phases=0, parameters=[.2, .45, .85, .65, .75], old_boundary=.85, duration=3.2),
    dict(name="zero_duration_shrink", phases=2, parameters=[.237, .513, .431, -.173, .417], old_boundary=1.17, duration=0.),
    dict(name="zero_duration_expand", phases=2, parameters=[.237, .513, 1.17, -.173, .417], old_boundary=.431, duration=0.),
]
MC_SAMPLES = 30000
MC_SEED = 103011
GRADIENT_PARAMETERS = [.237, .513, .8431, -.173, .417, .495755147934]
LIMITS = dict(generator_max=3e-14, survival_l1_extra_roundoff=2e-12,
              remap_max=3e-15, finite_difference_step=1e-5, gradient_scaled=2e-5,
              monte_carlo_standard_errors=5., monte_carlo_absolute_slack=2e-4,
              phase_and_reset_independence_gradient=1e-13)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_grid(phases):
    return Grid(8, -2., phases, fixed_rate=8.1, fixed_terms=21, max_duration=.36, per_token_chunks=True)


def independent_killed(parameters, grid):
    generator, event, _, weights = independent_generator(*parameters, grid)
    destination = np.zeros(len(generator))
    if grid.refractory_stages:
        destination[grid.cells] = 1
    else:
        destination[:grid.cells] = weights
    killed = generator - np.outer(destination, event)
    return killed, generator, event, destination


def independent_survival_remap(old_boundary, parameters, grid):
    regenerative, immediate, _ = independent_remap(old_boundary, parameters, grid, 0.)
    _, _, _, destination = independent_killed(parameters, grid)
    return regenerative - np.outer(immediate, destination)


def dense_operator(parameters, grid, old_boundary, duration):
    killed, _, _, _ = independent_killed(parameters, grid)
    remap = independent_survival_remap(old_boundary, parameters, grid)
    return remap @ expm(killed.T * duration)


def monte_carlo_first_event(parameters, grid, old_boundary, duration, p, seed):
    """Simulate physical marks directly; same-state marked resets still count."""
    rng = np.random.default_rng(seed)
    n, m = grid.cells, grid.refractory_stages
    mu, sigma, boundary, reset, tau = parameters
    state = rng.choice(n + m, MC_SAMPLES, p=p / p.sum())
    first = np.zeros(MC_SAMPLES, dtype=bool)
    active = state < n
    old_spacing = (old_boundary - grid.lower) / n
    coordinate = grid.lower + (state[active] + rng.random(active.sum())) * old_spacing
    old_active_indices = np.flatnonzero(active)
    jump = coordinate >= boundary
    first[old_active_indices[jump]] = True
    h = (boundary - grid.lower) / n
    state[old_active_indices[~jump]] = np.minimum(n - 1, ((coordinate[~jump] - grid.lower) / h).astype(int))
    D = sigma * sigma / 2
    up, down, exit_rate = D / h ** 2 + max(mu, 0) / h, D / h ** 2 + max(-mu, 0) / h, 2 * D / h ** 2 + max(mu, 0) / h
    total = np.full(n + m, up + down)
    total[0] = up; total[n - 1] = down + exit_rate
    if m:
        total[n:] = m / tau
    _, _, _, reset_weights = independent_generator(*parameters, grid)
    times = np.zeros(MC_SAMPLES)
    live = ~first
    transitions = 0
    while live.any():
        indices = np.flatnonzero(live)
        current = state[indices]
        times[indices] += rng.exponential(1 / total[current])
        occurred = times[indices] <= duration
        live[indices[~occurred]] = False
        indices, current = indices[occurred], current[occurred]
        if not len(indices):
            continue
        transitions += len(indices)
        random = rng.random(len(indices))
        is_active = current < n
        left_rate = np.where(current > 0, down, 0.)
        left_jump = is_active & (random < left_rate / total[current])
        state[indices[left_jump]] -= 1
        right_or_event = is_active & ~left_jump
        event = right_or_event & (current == n - 1)
        first[indices[event]] = True; live[indices[event]] = False
        right = right_or_event & ~event
        state[indices[right]] += 1
        phase = ~is_active
        release = phase & (current == n + m - 1)
        if release.any():
            state[indices[release]] = rng.choice(n, int(release.sum()), p=reset_weights)
        progress = phase & ~release
        state[indices[progress]] += 1
    probability = float(first.mean())
    return dict(samples=MC_SAMPLES, seed=seed, risk=probability,
                binomial_standard_error=float(np.sqrt(probability * (1 - probability) / MC_SAMPLES)),
                simulated_physical_transitions=transitions)


def audit_cases(risk_module):
    rows = []
    for i, case in enumerate(CASES):
        for dtype in (torch.float32, torch.float64):
            grid = make_grid(case["phases"])
            xs = [torch.tensor(v, dtype=dtype) for v in case["parameters"]]
            parameters = [float(v) for v in xs]
            old = torch.tensor(case["old_boundary"], dtype=dtype)
            dt = torch.tensor(case["duration"], dtype=dtype)
            flow = make_flow(*xs, grid)
            operator = risk_module.first_event_operator(flow, old, dt)
            reference = dense_operator(parameters, grid, float(old), float(dt))
            dtype64_flow = make_flow(*(x.double() for x in xs), grid)
            generator, full, event, destination = independent_killed(parameters, grid)
            actual_generator = risk_module.killed_generator(dtype64_flow).numpy()
            generator_error = float(np.max(np.abs(actual_generator - generator)))
            remap = independent_survival_remap(float(old), parameters, grid)
            actual_remap = risk_module.survival_remap(old, dtype64_flow).numpy()
            remap_error = float(np.max(np.abs(actual_remap - remap)))
            transition = operator["survival_transition"].numpy()
            operator_error = float(np.max(np.abs(transition - reference).sum(-1)))
            bound = float(operator["probability_error_bound"])
            assert generator_error < LIMITS["generator_max"]
            assert remap_error < LIMITS["remap_max"]
            assert operator_error <= bound + LIMITS["survival_l1_extra_roundoff"]
            p = np.random.default_rng(MC_SEED + i).dirichlet(np.ones(len(generator)))
            if case["name"] == "self_reset":
                p = np.eye(len(generator))[-1]
            probability = torch.tensor(p, dtype=dtype)
            incoming = probability.double().numpy()
            first = risk_module.first_event_probability(probability, operator)
            reference_risk = float(incoming @ (1 - reference.sum(-1)))
            actual_risk = float(first["risk"])
            identity_error = abs(float(first["risk"] + first["surviving_mass"] - first["incoming_mass"]))
            ordinary = prepare_operator(*xs, dt, grid, old_boundary=old)
            expected_count = float((probability * ordinary["event_vector"]).sum())
            assert actual_risk >= -2e-12 and actual_risk <= float(first["incoming_mass"]) + 2e-12
            assert actual_risk <= expected_count + (3e-6 if dtype == torch.float32 else 3e-11)
            assert identity_error < 2e-15
            row = dict(case=case["name"], input_dtype=str(dtype), arithmetic_dtype=operator["arithmetic_dtype"],
                       phases=case["phases"], generator_max_error=generator_error,
                       remap_max_error=remap_error, survival_operator_max_row_l1_error=operator_error,
                       truncation_probability_bound=bound, roundoff_included=False,
                       risk=actual_risk, reference_risk=reference_risk, expected_event_count=expected_count,
                       risk_absolute_error=abs(actual_risk - reference_risk),
                       incoming_mass=float(first["incoming_mass"]), risk_plus_survival_mass_identity_error=identity_error,
                       minimum_risk_vector=float(operator["risk_vector"].min()),
                       maximum_risk_vector=float(operator["risk_vector"].max()), survival_normalized=False)
            if dtype == torch.float64:
                mc = monte_carlo_first_event(parameters, grid, float(old), float(dt), p, MC_SEED + 10 + i)
                error = abs(mc["risk"] - reference_risk)
                guard = LIMITS["monte_carlo_standard_errors"] * mc["binomial_standard_error"] + LIMITS["monte_carlo_absolute_slack"]
                assert error <= guard
                row["monte_carlo"] = dict(**mc, error=error, registered_guard=guard)
            if case["name"] == "self_reset":
                naive = full.copy(); naive[:grid.cells - 1, -1] -= destination[:grid.cells - 1] * event[-1]
                wrong_survival = remap @ expm(naive.T * float(dt))
                wrong_risk = float(incoming @ (1 - wrong_survival.sum(-1)))
                row.update(self_reset_mark_intensity=float(destination[-1] * event[-1]),
                           risk_if_self_reset_mark_is_wrongly_kept=wrong_risk,
                           self_reset_semantics_gap=abs(wrong_risk - reference_risk))
                assert row["self_reset_semantics_gap"] > .1
            rows.append(row)
    return rows


def gradients(risk_module):
    grid = make_grid(2)
    p = torch.tensor(np.random.default_rng(MC_SEED + 99).dirichlet(np.ones(10)), dtype=torch.float64)
    xs = [torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in GRADIENT_PARAMETERS]
    op = risk_module.first_event_operator(make_flow(*xs[:5], grid), 1.137, xs[-1])
    objective = risk_module.first_event_probability(p, op)["risk"]
    grad = torch.autograd.grad(objective, xs)
    rows = []
    for i, name in enumerate(["mu", "sigma", "boundary", "reset", "tau", "duration"]):
        plus, minus = list(GRADIENT_PARAMETERS), list(GRADIENT_PARAMETERS)
        h = LIMITS["finite_difference_step"]; plus[i] += h; minus[i] -= h
        p_np = p.numpy()
        pos = p_np @ (1 - dense_operator(plus[:5], grid, 1.137, plus[-1]).sum(-1))
        neg = p_np @ (1 - dense_operator(minus[:5], grid, 1.137, minus[-1]).sum(-1))
        fd = float((pos - neg) / (2 * h))
        scaled = abs(float(grad[i]) - fd) / max(1e-8, abs(fd))
        assert scaled < LIMITS["gradient_scaled"], (name, scaled)
        rows.append(dict(parameter=name, autograd=float(grad[i]), independent_dense_finite_difference=fd,
                         scaled_error=scaled))
    for phases in (0, 2):
        current_grid = make_grid(phases)
        ys = [torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in GRADIENT_PARAMETERS]
        active_p = torch.zeros(8 + phases, dtype=torch.float64); active_p[4] = 1
        out = risk_module.first_event_operator(make_flow(*ys[:5], current_grid), 1.137, ys[-1])
        value = risk_module.first_event_probability(active_p, out)["risk"]
        reset_tau_gradients = torch.autograd.grad(value, ys[3:5], allow_unused=True)
        actual = [0. if v is None else float(v) for v in reset_tau_gradients]
        assert max(abs(v) for v in actual) < LIMITS["phase_and_reset_independence_gradient"]
        rows.append(dict(test="active_first_event_independent_of_future_reset_and_refractory", phases=phases,
                         reset_derivative=actual[0], tau_derivative=actual[1]))
    return rows


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    directory = Path(__file__).parent
    sources = [Path(__file__), directory.parent / "hcsn_risk_ablation_v1" / "risk_kernel.py",
               directory / "distribution_kernel.py", directory / "kernel_tests.py",
               directory / "stable_probability_tests.py"]
    hashes = {str(path): digest(path) for path in sources}
    registration = dict(schema="hcsn-first-event-independent-registration.v1", cases=CASES,
                        monte_carlo_samples=MC_SAMPLES, monte_carlo_seed=MC_SEED,
                        gradient_parameters=GRADIENT_PARAMETERS, limits=LIMITS, source_sha256=hashes,
                        generator_convention="Q columns; survival transitions rows",
                        identity="risk + surviving_mass = incoming_mass",
                        task_labels_read=False, frozen_sources_changed=False)
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    from experiments.hcsn_risk_ablation_v1 import risk_kernel
    records, failures = {}, []
    for name, function in [("dense_and_monte_carlo", audit_cases), ("gradients", gradients)]:
        try:
            records[name] = function(risk_kernel)
        except Exception:
            failures.append(dict(test=name, traceback=traceback.format_exc()))
    changed = [str(path) for path in sources if digest(path) != hashes[str(path)]]
    result = dict(schema="hcsn-first-event-independent-audit.v1", passed=not failures and not changed,
                  records=records, failures=failures, source_sha256=hashes,
                  source_changed_during_audit=changed, self_cpu_seconds=time.process_time() - start_cpu,
                  wall_seconds=time.perf_counter() - start_wall,
                  peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  gpu_measured=False, energy_measured=False)
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = ["# Independent first-event risk audit", "",
             "The column generator is killed by subtracting the complete marked reset inflow, "
             "including self-reset. Boundary-jump mass is removed before propagation. "
             "Existing refractory phases may release and then fire within the observation window. "
             "The survival operator is never normalized.", "",
             "| Case | Dtype | Risk | Expected event count | Dense survival row L1 error |",
             "|---|---|---:|---:|---:|"]
    for row in records.get("dense_and_monte_carlo", []):
        lines.append(f"| {row['case']} | {row['input_dtype']} | {row['risk']:.9g} | "
                     f"{row['expected_event_count']:.9g} | {row['survival_operator_max_row_l1_error']:.9g} |")
    lines.extend(["", "The risk is an expectation of a first-event indicator. The ordinary regenerative "
                  "event output is an expected repeat-event count and may exceed one. "
                  "For an already active initial state, reset and refractory parameters do not influence "
                  "the first event; their gradients must vanish. For existing refractory mass they may matter.", "",
                  "Poisson truncation bounds exclude floating-point roundoff. Values within a few epsilons "
                  "of zero are retained rather than clipped, and reported explicitly. Risk plus surviving "
                  "mass equals incoming mass; an input's final float32 casting error is not counted as an event.", "",
                  f"Passed: {result['passed']}. Self CPU {result['self_cpu_seconds']:.6f}s; "
                  f"wall {result['wall_seconds']:.6f}s. No GPU/energy measurement.", ""])
    if failures:
        lines.extend(["## Failures", "", *[item["traceback"] for item in failures]])
    (output / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({key: result[key] for key in ("passed", "self_cpu_seconds", "wall_seconds")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    main(args.output)
