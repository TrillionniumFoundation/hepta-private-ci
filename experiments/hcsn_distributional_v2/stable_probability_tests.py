"""Independent tests of the new bounded unit-mass numerical profile.

The failed uncorrected audit is kept in its original result directory. This
script registers all tolerances before computing any diagnostic and compares
against dense finite-state references, not against a repeated copy of itself.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import numpy as np
from scipy.linalg import expm, solve
import torch

from .distribution_kernel import Grid, make_flow, prepare_operator, propagate
from .kernel_tests import independent_generator
from .long_horizon_audit import CASES, DURATIONS, OBSERVATIONS, SNAPSHOTS, dense_reference, renewal_reference
from .stable_probability import PROFILE, advance_probability, probability_tolerances


TAG = "regenerative_probability"
GRID = Grid(8, -2., 2, fixed_rate=8.1, fixed_terms=21, max_duration=.36,
            per_token_chunks=True)
LIMITS = dict(float32_state_l1=2e-5, float64_state_l1=5e-10,
              float32_event_scaled=5e-5, float64_event_scaled=1e-9,
              float32_moving_state_l1=2e-5, float64_moving_state_l1=5e-10,
              gradient_scaled=2e-5, gradient_absolute_floor=1e-5,
              finite_difference_step=1e-5)
GRADIENT_PARAMETERS = [.237, .513, .8431, -.173, .417, .437, .413, 1.]
GRADIENT_NAMES = ["mu", "sigma", "boundary", "reset", "tau", "rho", "K", "duration_scale"]
MOVING_STEPS = 128
BOUNDARY_OFFSETS = [-.117, .223, .054]
MOVING_DURATIONS = [0., .19, .271, .495755147934]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_remap(old_boundary, parameters, grid, K):
    """Physical overlap assembled by scalar loops, including immediate events."""
    n, m = grid.cells, grid.refractory_stages
    boundary = parameters[2]
    old_edges = np.linspace(grid.lower, old_boundary, n + 1)
    new_edges = np.linspace(grid.lower, boundary, n + 1)
    h = (old_boundary - grid.lower) / n
    matrix = np.zeros((n + m, n + m))
    event, reward = np.zeros(n + m), np.zeros(n + m)
    _, _, _, reset_weights = independent_generator(*parameters, grid)
    for i in range(n):
        for j in range(n):
            overlap = max(0., min(old_edges[i + 1], new_edges[j + 1]) -
                          max(old_edges[i], new_edges[j]))
            matrix[i, j] = overlap / h
        left, right = max(old_edges[i], boundary), old_edges[i + 1]
        if right > left:
            event[i] = (right - left) / h
            reward[i] = event[i] * ((left + right) / 2 - K)
            if m:
                matrix[i, n] += event[i]
            else:
                matrix[i, :n] += event[i] * reset_weights
    for i in range(m):
        matrix[n + i, n + i] = 1
    return matrix, event, reward


def independent_policy(parameters, grid, rho, K):
    generator, event, centers, reset = independent_generator(*parameters, grid)
    J = solve(rho * np.eye(len(generator)) - generator.T, (parameters[2] - K) * event)
    delay = (grid.refractory_stages / parameters[4] /
             (grid.refractory_stages / parameters[4] + rho)) ** grid.refractory_stages
    G = J.copy()
    G[:grid.cells] = centers - K + delay * (reset @ J[:grid.cells])
    return J, G


def long_case(case, dtype, output):
    parameters = [torch.tensor(v, dtype=dtype) for v in case["parameters"]]
    generator, event, stationary, _ = renewal_reference([float(v) for v in parameters], GRID)
    flow = make_flow(*parameters, grid=GRID)
    operators = [prepare_operator(*parameters, torch.tensor(dt, dtype=dtype), grid=GRID)
                 for dt in DURATIONS]
    p = torch.tensor(stationary, dtype=dtype)
    initial = p.double().numpy().copy()
    initial /= initial.sum()
    count = torch.zeros((), dtype=dtype)
    double_count, elapsed, cumulative_correction = 0., 0., 0.
    snapshots, trace = [], []
    maximum_raw_defect, maximum_post_defect = 0., 0.
    with torch.no_grad():
        for step in range(1, OBSERVATIONS + 1):
            index = (step - 1) % len(DURATIONS)
            operator = operators[index]
            result = advance_probability(p, operator["transition"], operator_kind=TAG,
                                         event_vector=operator["event_vector"])
            p = result["probability"]
            count = count + result["events"]
            double_count += float(result["events"])
            elapsed += float(torch.tensor(DURATIONS[index], dtype=dtype))
            diag = result["diagnostics"]
            correction = float(diag["actual_l1_correction"])
            cumulative_correction += correction
            raw_mass, post_mass = float(diag["pre_projection_mass"]), float(diag["post_projection_mass"])
            maximum_raw_defect = max(maximum_raw_defect, abs(raw_mass - 1))
            maximum_post_defect = max(maximum_post_defect, abs(post_mass - 1))
            trace.append([step, elapsed, raw_mass, post_mass, correction, cumulative_correction,
                          float(count), double_count, *p.double().tolist()])
            if step in SNAPSHOTS:
                ref, ref_count = dense_reference(generator, event, initial, elapsed)
                propagate(p, flow, 0.)  # The original checked API must now accept it.
                snapshots.append(dict(observations=step, mass=post_mass,
                    maximum_pre_projection_mass_defect=maximum_raw_defect,
                    maximum_post_projection_mass_defect=maximum_post_defect,
                    cumulative_actual_l1_correction=cumulative_correction,
                    state_l1_error=float(np.abs(p.double().numpy() - ref).sum()),
                    phase_mass_l1_error=float(np.abs(p.double().numpy()[GRID.cells:] - ref[GRID.cells:]).sum()),
                    events_dtype_sum=float(count), events_double_sum=double_count,
                    reference_events=ref_count, events_dtype_sum_error=abs(float(count) - ref_count),
                    events_double_sum_error=abs(double_count - ref_count),
                    original_checked_propagator_accepts=True,
                    minimum_probability=float(p.min())))
    name = str(dtype).split(".")[-1]
    final = snapshots[-1]
    assert final["state_l1_error"] < LIMITS[name + "_state_l1"]
    assert final["events_double_sum_error"] < LIMITS[name + "_event_scaled"] * max(1., abs(final["reference_events"]))
    assert maximum_post_defect <= probability_tolerances(dtype)["input_mass"]
    filename = f"long_{case['name']}_{name}.npz"
    np.savez_compressed(output / filename, trace=np.asarray(trace))
    return dict(case=case["name"], dtype=name, snapshots=snapshots,
                trace_path=filename, trace_sha256=digest(output / filename),
                trace_columns=["observation", "physical_time", "pre_projection_mass", "post_projection_mass",
                               "actual_l1_correction", "cumulative_actual_l1_correction",
                               "events_dtype_sum", "events_double_sum"] +
                              [f"probability_{i}" for i in range(len(generator))])


def moving_torch(parameters, dtype, return_gradient=False):
    args = [torch.tensor(v, dtype=dtype, requires_grad=return_gradient) for v in parameters]
    mu, sigma, b, reset, tau, rho, K, scale = args
    offsets = torch.tensor([BOUNDARY_OFFSETS[i % len(BOUNDARY_OFFSETS)] for i in range(MOVING_STEPS)], dtype=dtype)
    durations = torch.tensor([MOVING_DURATIONS[i % len(MOVING_DURATIONS)] for i in range(MOVING_STEPS)], dtype=dtype)
    boundaries = b + offsets
    old = torch.cat(((b + .377).reshape(1), boundaries[:-1]))
    operators = prepare_operator(mu, sigma, boundaries, reset, tau, durations * scale, GRID,
                                 old_boundary=old, rho=rho, K=K, reward_intercept=-K)
    p = torch.tensor(np.random.default_rng(103001).dirichlet(np.ones(10)), dtype=dtype)
    events, rewards = torch.zeros((), dtype=dtype), torch.zeros((), dtype=dtype)
    maximum_correction, maximum_mass_defect = 0., 0.
    for i in range(MOVING_STEPS):
        out = advance_probability(p, operators["transition"][i], operator_kind=TAG,
                                  event_vector=operators["event_vector"][i],
                                  reward_vector=operators["reward_vector"][i])
        p = out["probability"]
        events, rewards = events + out["events"], rewards + out["reward"]
        maximum_correction = max(maximum_correction, float(out["diagnostics"]["actual_l1_correction"]))
        maximum_mass_defect = max(maximum_mass_defect, abs(float(out["diagnostics"]["post_projection_mass"]) - 1))
    weights = torch.linspace(-.7, .8, 10, dtype=dtype)
    objective = p @ weights + .2 * events + .07 * rewards + .1 * (p * operators["values"]["J"][-1]).sum() + \
                .03 * (p * operators["values"]["G"][-1]).sum()
    gradients = torch.autograd.grad(objective, args) if return_gradient else None
    return dict(objective=float(objective.detach()), probability=p.detach().double().numpy(),
                events=float(events.detach()), reward=float(rewards.detach()),
                maximum_l1_correction=maximum_correction, maximum_mass_defect=maximum_mass_defect,
                gradients=None if gradients is None else [float(v) for v in gradients])


def moving_reference(parameters):
    mu, sigma, b, reset, tau, rho, K, scale = parameters
    p = np.random.default_rng(103001).dirichlet(np.ones(10))
    old, events, reward = b + .377, 0., 0.
    cache = {}
    for i in range(MOVING_STEPS):
        boundary = b + BOUNDARY_OFFSETS[i % len(BOUNDARY_OFFSETS)]
        duration = MOVING_DURATIONS[i % len(MOVING_DURATIONS)] * scale
        current = [mu, sigma, boundary, reset, tau]
        key = (old, boundary, duration)
        if key not in cache:
            remap, immediate, jump_reward = independent_remap(old, current, GRID, K)
            generator, event, _, _ = independent_generator(*current, GRID)
            aug = np.zeros((12, 12)); aug[:10, :10] = generator
            aug[10, :10] = event; aug[11, :10] = (boundary - K) * event
            cache[key] = remap, immediate, jump_reward, expm(aug * duration)
        remap, immediate, jump_reward, propagation = cache[key]
        events += float(p @ immediate); reward += float(p @ jump_reward)
        output = propagation @ np.r_[p @ remap, 0., 0.]
        p = output[:10]; events += float(output[10]); reward += float(output[11])
        old = boundary
    J, G = independent_policy(current, GRID, rho, K)
    objective = p @ np.linspace(-.7, .8, 10) + .2 * events + .07 * reward + .1 * (p @ J) + .03 * (p @ G)
    return dict(objective=float(objective), probability=p, events=events, reward=reward)


def moving_and_gradients():
    reference = moving_reference(GRADIENT_PARAMETERS)
    rows = []
    for dtype in (torch.float32, torch.float64):
        out = moving_torch(GRADIENT_PARAMETERS, dtype, return_gradient=dtype == torch.float64)
        name = str(dtype).split(".")[-1]
        state_error = float(np.abs(out["probability"] - reference["probability"]).sum())
        assert state_error < LIMITS[name + "_moving_state_l1"]
        rows.append(dict(dtype=name, state_l1_error=state_error,
                         refractory_phase_l1_error=float(np.abs(out["probability"][8:] - reference["probability"][8:]).sum()),
                         event_error=abs(out["events"] - reference["events"]),
                         reward_error=abs(out["reward"] - reference["reward"]),
                         maximum_actual_l1_correction=out["maximum_l1_correction"],
                         maximum_post_projection_mass_defect=out["maximum_mass_defect"],
                         objective=out["objective"], reference_objective=reference["objective"]))
        if dtype == torch.float64:
            gradients = out["gradients"]
    gradient_rows = []
    for i, name in enumerate(GRADIENT_NAMES):
        plus, minus = list(GRADIENT_PARAMETERS), list(GRADIENT_PARAMETERS)
        h = LIMITS["finite_difference_step"]
        plus[i] += h; minus[i] -= h
        fd = (moving_reference(plus)["objective"] - moving_reference(minus)["objective"]) / (2 * h)
        scaled = abs(gradients[i] - fd) / max(LIMITS["gradient_absolute_floor"], abs(fd))
        assert scaled < LIMITS["gradient_scaled"], (name, gradients[i], fd, scaled)
        assert abs(gradients[i]) > 1e-8, (name, "inactive parameter")
        gradient_rows.append(dict(parameter=name, autograd=gradients[i], independent_dense_finite_difference=fd,
                                  scaled_error=scaled))
    return dict(steps=MOVING_STEPS, moving_boundary_and_zero_duration=True,
                records=rows, gradients=gradient_rows)


def guards_and_denominator_gradient():
    p = torch.tensor([.2, .3, .5], dtype=torch.float64)
    identity = torch.eye(3, dtype=p.dtype)
    cases = [dict(name="killed_tag", p=p, T=identity, tag="killed_no_event"),
             dict(name="large_substochastic_deficit", p=p, T=.9 * identity, tag=TAG),
             dict(name="large_superstochastic_excess", p=p, T=1.1 * identity, tag=TAG),
             dict(name="negative_input", p=torch.tensor([-.1, .3, .8], dtype=p.dtype), T=identity, tag=TAG),
             dict(name="nonunit_input", p=.9 * p, T=identity, tag=TAG),
             dict(name="nonfinite_input", p=torch.tensor([float("nan"), .3, .7], dtype=p.dtype), T=identity, tag=TAG)]
    bad = identity.clone(); bad[0, 1] = -1e-15; bad[0, 0] += 1e-15
    cases.append(dict(name="negative_roundoff_is_not_clipped", p=p, T=bad, tag=TAG))
    records = []
    for case in cases:
        try:
            advance_probability(case["p"], case["T"], operator_kind=case["tag"])
        except (TypeError, ValueError) as error:
            records.append(dict(name=case["name"], rejected=True, error=str(error)))
        else:
            raise AssertionError("Did not reject " + case["name"])
    scalar = torch.tensor(1 + 4e-13, dtype=p.dtype, requires_grad=True)
    out = advance_probability(p, scalar * identity, operator_kind=TAG,
                              event_vector=torch.tensor([.1, 1., 3.], dtype=p.dtype))
    derivative = torch.autograd.grad(out["probability"] @ torch.tensor([1., 2., 4.], dtype=p.dtype), scalar)[0]
    assert abs(float(derivative)) < 1e-12
    assert float(out["events"]) == float(p @ torch.tensor([.1, 1., 3.], dtype=p.dtype))
    return dict(rejections=records, normalization_denominator_gradient_preserved=True,
                uniform_scale_derivative=float(derivative), events_computed_from_pre_state=True,
                unavoidable_semantic_contract="A caller must label kernel semantics truthfully; tiny killing cannot be inferred from row sums alone")


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    directory = Path(__file__).parent
    sources = [Path(__file__), directory / "stable_probability.py", directory / "distribution_kernel.py",
               directory / "kernel_tests.py", directory / "long_horizon_audit.py"]
    hashes = {str(path): digest(path) for path in sources}
    registration = dict(schema="hcsn-stable-probability-registration.v1", profile=PROFILE,
        source_sha256=hashes, limits=LIMITS, cases=CASES, durations=DURATIONS,
        observations=OBSERVATIONS, snapshots=SNAPSHOTS,
        guard_float32=probability_tolerances(torch.float32), guard_float64=probability_tolerances(torch.float64),
        moving_steps=MOVING_STEPS, boundary_offsets=BOUNDARY_OFFSETS, moving_durations=MOVING_DURATIONS,
        gradient_parameters=dict(zip(GRADIENT_NAMES, GRADIENT_PARAMETERS)),
        prior_failure_preserved="../sixstage_20261030_math/RESULTS.json",
        frozen_sources_changed=False, task_labels_read=False,
        limitations=["Only ordinary regenerative state is normalized; killed survival is excluded",
                     "Roundoff guard is not an IEEE forward-error proof",
                     "Finite-grid reference, not Brownian spatial exactness",
                     "Float32 cumulative count summation is a separate source of drift"])
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    records, failures = {}, []
    for case in CASES:
        for dtype in (torch.float32, torch.float64):
            name = case["name"] + "_" + str(dtype).split(".")[-1]
            try:
                records[name] = long_case(case, dtype, output)
            except Exception:
                failures.append(dict(test=name, traceback=traceback.format_exc()))
    for name, function in [("moving_and_gradients", moving_and_gradients),
                           ("guards_and_denominator_gradient", guards_and_denominator_gradient)]:
        try:
            records[name] = function()
        except Exception:
            failures.append(dict(test=name, traceback=traceback.format_exc()))
    changed = [str(path) for path in sources if digest(path) != hashes[str(path)]]
    result = dict(schema="hcsn-stable-probability-audit.v1", profile=PROFILE,
        passed=not failures and not changed, records=records, failures=failures,
        source_changed_during_audit=changed, source_sha256=hashes,
        self_cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall,
        peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        gpu_measured=False, energy_measured=False)
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = ["# Bounded regenerative probability correction", "",
             "This new profile retains the failed uncorrected diagnostic and frozen sources. "
             "It validates inputs and operator semantics, rejects excessive defects and any negatives, "
             "then divides by the observed mass in float64 with a differentiable denominator. "
             "It never applies to killed/no-event transitions.", "",
             "| Case | Dtype | Maximum mass error after correction | Final state L1 error | Event error (double sum) | Event error (dtype sum) |",
             "|---|---|---:|---:|---:|---:|"]
    for row in records.values():
        if "snapshots" not in row:
            continue
        final = row["snapshots"][-1]
        lines.append(f"| {row['case']} | {row['dtype']} | {final['maximum_post_projection_mass_defect']:.9g} | "
                     f"{final['state_l1_error']:.9g} | {final['events_double_sum_error']:.9g} | {final['events_dtype_sum_error']:.9g} |")
    lines.extend(["", "The actual per-step and cumulative corrections are saved, as are raw mass defects. "
                  "The helper restores the unit-mass contract, but does not prove exact finite-grid dynamics "
                  "or prevent separate error in float32 accumulation of thousands of expected event counts. "
                  "Double accumulation is tested explicitly; per-step event vectors retain their original semantics.", "",
                  "The moving-boundary test includes zero-duration observation jumps and 128 regenerative steps. "
                  "Eight parameters are differentiated through the full recurrence and compared with central "
                  "finite differences of independently assembled dense generators, physical-overlap maps and value solves.", "",
                  f"Passed: {result['passed']}. Self CPU: {result['self_cpu_seconds']:.6f}s; "
                  f"wall: {result['wall_seconds']:.6f}s. No GPU/energy measurement.", ""])
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
