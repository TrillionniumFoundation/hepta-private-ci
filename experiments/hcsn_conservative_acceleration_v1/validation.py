"""Independent finite-generator, value and gradient audit of the accelerated kernel.

The reference assembles physical jumps with scalar NumPy loops and evaluates a
SciPy augmented matrix exponential.  It never imports the optimized matrix
construction.  This audit concerns the declared finite chain, not convergence
of that chain to a Brownian free-boundary problem or a network quality claim.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import traceback

import numpy as np
from scipy.linalg import expm, solve
import torch

from experiments.hcsn_distributional_v2 import distribution_kernel as original
from experiments.hcsn_distributional_v2.stable_probability import (
    REGENERATIVE_PROBABILITY, advance_probability,
)
from . import kernel


GRID = original.Grid(8, -2.0, 2, fixed_rate=8.1, fixed_terms=21,
                     max_duration=0.36, per_token_chunks=True)
NAMES = ("mu", "sigma", "boundary", "reset", "tau", "duration",
         "old_boundary", "rho", "cost")
PARAMETERS = (0.237, 0.513, 0.8431, -0.173, 0.417, 0.495755147934,
              1.217, 0.437, 0.413)
LIMITS = dict(float32_transition_l1=2e-5, float32_functional_scaled=3e-5,
              float64_transition_l1=8e-10, float64_functional_scaled=2e-10,
              original_float64_scaled=8e-10, original_float32_scaled=2e-5,
              gradient_original_scaled=2e-9, gradient_dense_scaled=2e-5,
              gradient_absolute_floor=1e-5, finite_difference_step=1e-5,
              long_float32_state_l1=2e-5, long_event_scaled=5e-5,
              batch_float64_absolute=3e-12)


def independent_generator(parameters, grid):
    """Column generator from directed physical jumps, independently assembled."""
    mu, sigma, boundary, reset, tau = map(float, parameters[:5])
    n, m = grid.cells, grid.refractory_stages
    h = (boundary - grid.lower) / n
    centers = grid.lower + (np.arange(n) + 0.5) * h
    diffusion = sigma * sigma / (2 * h * h)
    upward = diffusion + max(mu, 0.0) / h
    downward = diffusion + max(-mu, 0.0) / h
    outward = 2 * diffusion + max(mu, 0.0) / h
    left = min(n - 2, max(0, int(math.floor((reset - centers[0]) / h))))
    weights = np.zeros(n)
    weights[left + 1] = (reset - centers[left]) / h
    weights[left] = 1 - weights[left + 1]
    matrix, event = np.zeros((n + m, n + m)), np.zeros(n + m)

    def jump(source, destination, rate):
        matrix[destination, source] += rate
        matrix[source, source] -= rate

    for i in range(n):
        if i:
            jump(i, i - 1, downward)
        if i < n - 1:
            jump(i, i + 1, upward)
        else:
            event[i] = outward
            if m:
                jump(i, n, outward)
            else:
                for j, weight in enumerate(weights):
                    jump(i, j, outward * weight)
    for j in range(m):
        if j < m - 1:
            jump(n + j, n + j + 1, m / tau)
        else:
            for i, weight in enumerate(weights):
                jump(n + j, i, (m / tau) * weight)
    return matrix, event, centers, weights


def independent_remap(old, boundary, grid, reset_weights, cost):
    n, m = grid.cells, grid.refractory_stages
    before = np.linspace(grid.lower, old, n + 1)
    after = np.linspace(grid.lower, boundary, n + 1)
    spacing = (old - grid.lower) / n
    matrix = np.zeros((n + m, n + m))
    event, reward = np.zeros(n + m), np.zeros(n + m)
    for i in range(n):
        for j in range(n):
            matrix[i, j] = max(0.0, min(before[i + 1], after[j + 1]) -
                               max(before[i], after[j])) / spacing
        left, right = max(before[i], boundary), before[i + 1]
        if right > left:
            event[i] = (right - left) / spacing
            reward[i] = event[i] * ((left + right) / 2 - cost)
            if m:
                matrix[i, n] += event[i]
            else:
                matrix[i, :n] += event[i] * reset_weights
    for j in range(m):
        matrix[n + j, n + j] = 1
    return matrix, event, reward


def dense_reference(parameters=PARAMETERS, grid=GRID):
    mu, sigma, b, reset, tau, dt, old, rho, cost = map(float, parameters)
    generator, event, centers, weights = independent_generator(parameters, grid)
    size = len(generator)
    augmented = np.zeros((size + 1, size + 1))
    augmented[:size, :size] = generator.T
    augmented[:size, size] = event
    exponential = expm(dt * augmented)
    remap, immediate, jump_reward = independent_remap(old, b, grid, weights, cost)
    transition = remap @ exponential[:size, :size]
    count = immediate + remap @ exponential[:size, size]
    reward = jump_reward + (b - cost) * (remap @ exponential[:size, size])
    J = solve(rho * np.eye(size) - generator.T, (b - cost) * event)
    delay = ((grid.refractory_stages / tau) /
             (grid.refractory_stages / tau + rho)) ** grid.refractory_stages \
        if grid.refractory_stages else 1.0
    G = J.copy()
    G[:grid.cells] = centers - cost + delay * (weights @ J[:grid.cells])
    return dict(transition=transition, event_vector=count, reward_vector=reward,
                J=J, G=G)


def prepare(implementation, arguments, grid=GRID):
    mu, sigma, b, reset, tau, dt, old, rho, cost = arguments
    return implementation.prepare_operator(mu, sigma, b, reset, tau, dt, grid,
        old_boundary=old, rho=rho, K=cost, reward_intercept=-cost)


def arrays(operator):
    return {**{name: operator[name] for name in
               ("transition", "event_vector", "reward_vector")},
            "J": operator["values"]["J"], "G": operator["values"]["G"]}


def _scaled_error(a, b, floor=1.0):
    return float(np.max(np.abs(a - b) / np.maximum(floor, np.abs(b))))


def forward_audit():
    rows = []
    cases = [list(PARAMETERS) for _ in range(8)]
    for params, duration in zip(cases, (0.0, 0.12, 0.36, 0.360001,
                                      0.495755147934, 0.72, 3.2, 7.31), strict=True):
        params[5] = duration
    # 4096 full chunks: an explicit long-segment check in float64, in addition
    # to the separate float32 many-observation recurrence below.
    long_case = list(PARAMETERS); long_case[5] = 0.36 * 4096
    for dtype in (torch.float32, torch.float64):
        dtype_name = str(dtype).split(".")[-1]
        for case in cases + ([long_case] if dtype == torch.float64 else []):
            arguments = [torch.tensor(v, dtype=dtype) for v in case]
            represented = [float(v) for v in arguments]
            reference = dense_reference(represented)
            candidate = prepare(kernel, arguments)
            baseline = arrays(prepare(original, arguments))
            actual = arrays(candidate)
            errors, comparisons = {}, {}
            for name, tensor in actual.items():
                value = tensor.detach().double().numpy()
                errors[name] = _scaled_error(value, reference[name])
                comparisons[name] = _scaled_error(value, baseline[name].detach().double().numpy())
                assert np.isfinite(value).all(), (dtype_name, name, "nonfinite")
                if name in ("transition", "event_vector"):
                    assert value.min() >= 0, (dtype_name, name, "negative")
            row_l1 = float(np.max(np.abs(actual["transition"].double().numpy() -
                                         reference["transition"]).sum(-1)))
            assert row_l1 <= LIMITS[dtype_name + "_transition_l1"], (dtype_name, represented, row_l1)
            assert max(errors.values()) <= LIMITS[dtype_name + "_functional_scaled"], errors
            assert max(comparisons.values()) <= LIMITS["original_" + dtype_name + "_scaled"], comparisons
            rows.append(dict(dtype=dtype_name, parameters=dict(zip(NAMES, represented, strict=True)),
                dense_transition_max_row_l1=row_l1, dense_scaled_errors=errors,
                original_scaled_errors=comparisons,
                transition_mass_defect=float((actual["transition"].sum(-1) - 1).abs().max())))
    return rows


def objective_from_arrays(values):
    size = len(values["J"])
    probability = np.random.default_rng(103001).dirichlet(np.ones(size))
    state = probability @ values["transition"]
    state /= state.sum()
    return float(state @ np.linspace(-0.7, 0.8, size) +
        0.2 * probability @ values["event_vector"] +
        0.07 * probability @ values["reward_vector"] +
        0.1 * state @ values["J"] + 0.03 * state @ values["G"])


def torch_objective(implementation, parameters=PARAMETERS, gradient=True):
    arguments = [torch.tensor(v, dtype=torch.float64, requires_grad=gradient) for v in parameters]
    operator = prepare(implementation, arguments)
    size = operator["transition"].shape[-1]
    probability = torch.tensor(np.random.default_rng(103001).dirichlet(np.ones(size)),
                               dtype=torch.float64)
    result = advance_probability(probability, operator["transition"],
        operator_kind=REGENERATIVE_PROBABILITY,
        event_vector=operator["event_vector"], reward_vector=operator["reward_vector"])
    p = result["probability"]
    objective = (p @ torch.linspace(-0.7, 0.8, size, dtype=p.dtype) +
                 0.2 * result["events"] + 0.07 * result["reward"] +
                 0.1 * (p * operator["values"]["J"]).sum() +
                 0.03 * (p * operator["values"]["G"]).sum())
    derivatives = torch.autograd.grad(objective, arguments) if gradient else None
    return float(objective.detach()), None if derivatives is None else [float(v) for v in derivatives]


def gradient_audit():
    value, derivatives = torch_objective(kernel)
    original_value, original_derivatives = torch_objective(original)
    rows = []
    for index, name in enumerate(NAMES):
        plus, minus = list(PARAMETERS), list(PARAMETERS)
        step = LIMITS["finite_difference_step"]
        plus[index] += step; minus[index] -= step
        difference = (objective_from_arrays(dense_reference(plus)) -
                      objective_from_arrays(dense_reference(minus))) / (2 * step)
        scaled = abs(derivatives[index] - difference) / max(
            LIMITS["gradient_absolute_floor"], abs(difference))
        original_error = abs(derivatives[index] - original_derivatives[index]) / max(
            LIMITS["gradient_absolute_floor"], abs(original_derivatives[index]))
        assert scaled <= LIMITS["gradient_dense_scaled"], (name, scaled)
        assert original_error <= LIMITS["gradient_original_scaled"], (name, original_error)
        assert math.isfinite(derivatives[index]) and abs(derivatives[index]) > 1e-8, name
        rows.append(dict(parameter=name, autograd=derivatives[index],
            original_autograd=original_derivatives[index], dense_central_difference=difference,
            dense_scaled_error=scaled, original_scaled_error=original_error))
    return dict(objective=value, original_objective=original_value, parameters=rows,
        scope="First derivatives away from interpolation/drift/chunk switching surfaces; no global gradient certificate")


def batch_and_knots_audit():
    rows = []
    cases = [list(PARAMETERS) for _ in range(3)]
    cases[1][0] = -0.19; cases[1][5] = 7.31
    cases[2][2] = 0.731; cases[2][5] = 0.0
    arguments = [torch.tensor(column, dtype=torch.float64, requires_grad=True)
                 for column in zip(*cases)]
    batched = arrays(prepare(kernel, arguments))
    for i, case in enumerate(cases):
        scalar = arrays(prepare(kernel, [torch.tensor(v, dtype=torch.float64) for v in case]))
        error = max(float((batched[k][i] - scalar[k]).detach().abs().max()) for k in batched)
        assert error <= LIMITS["batch_float64_absolute"], (i, error)
        rows.append(dict(case=i, scalar_batch_max_absolute_error=error))
    selected = sum(value[0].sum() for value in batched.values())
    gradients = torch.autograd.grad(selected, arguments)
    neighbor_gradient = max(float(g[1:].abs().max()) for g in gradients)
    assert neighbor_gradient == 0, neighbor_gradient
    knot = list(PARAMETERS)
    knot[3] = GRID.lower + (5 + 0.5) * (knot[2] - GRID.lower) / GRID.cells
    knot_records = []
    for displacement in (-1e-8, 0.0, 1e-8):
        case = knot.copy(); case[3] += displacement
        candidate_value, derivative = torch_objective(kernel, case)
        original_value, original_derivative = torch_objective(original, case)
        assert abs(candidate_value - original_value) < 3e-12
        assert np.isfinite(derivative).all()
        assert _scaled_error(np.array(derivative), np.array(original_derivative), 1e-5) < 2e-9
        knot_records.append(dict(displacement=displacement, value=candidate_value,
                                 reset_autograd=derivative[3]))
    return dict(rows=rows, unrelated_batch_future_gradient=neighbor_gradient,
        reset_knot=knot_records,
        knot_scope="Forward continuity and original autodiff convention only; the knot has no unique ordinary derivative")


def refractory_semantics_audit():
    """Include instantaneous reset self-events and a nondefault Erlang chain."""
    rows = []
    for stages, tau in ((0, 0.0), (3, 0.6)):
        grid = original.Grid(8, -2.0, stages, fixed_rate=8.1, fixed_terms=21,
                             max_duration=0.36, per_token_chunks=True)
        case = list(PARAMETERS); case[4] = tau
        reference = dense_reference(case, grid)
        actual = arrays(prepare(kernel, [torch.tensor(v, dtype=torch.float64) for v in case], grid))
        errors = {name: _scaled_error(value.detach().numpy(), reference[name])
                  for name, value in actual.items()}
        assert max(errors.values()) < 5e-12, (stages, errors)
        rows.append(dict(refractory_stages=stages, tau=tau, dense_scaled_errors=errors))
    return rows


def guard_audit():
    cases = []
    for name, index, value in (("negative_duration", 5, -0.1),
                               ("negative_sigma", 1, -0.1),
                               ("nonfinite_mu", 0, float("nan")),
                               ("invalid_reset", 3, 9.0),
                               ("zero_refractory", 4, 0.0),
                               ("duration_resource_cap", 5,
                                GRID.max_duration * (GRID.max_independent_chunks + 2))):
        case = list(PARAMETERS); case[index] = value
        cases.append((name, case, GRID))
    cases.extend((name, PARAMETERS, grid) for name, grid in (
        ("insufficient_uniformization_rate", original.Grid(8, -2, 2, fixed_rate=1.0,
            fixed_terms=21, max_duration=0.36, per_token_chunks=True)),
        ("uncertified_truncation", original.Grid(8, -2, 2, fixed_rate=8.1,
            fixed_terms=20, max_duration=0.36, per_token_chunks=True))))
    records = []
    for name, case, grid in cases:
        try:
            prepare(kernel, [torch.tensor(v, dtype=torch.float64) for v in case], grid)
        except (ValueError, RuntimeError, TypeError) as error:
            records.append(dict(case=name, rejected=True, error=str(error)))
        else:
            raise AssertionError("Invalid contract accepted: " + name)
    return records


def long_float32_audit(observations=4096):
    parameters = list(PARAMETERS); parameters[6] = parameters[2]
    represented = [float(torch.tensor(v, dtype=torch.float32)) for v in parameters]
    durations = (0.0, 0.17, 0.36, 0.495755147934)
    operators = []
    for dt in durations:
        case = parameters.copy(); case[5] = dt
        operators.append(prepare(kernel, [torch.tensor(v, dtype=torch.float32) for v in case]))
    p0 = np.random.default_rng(103003).dirichlet(np.ones(10))
    p = torch.tensor(p0, dtype=torch.float32)
    initial = p.double().numpy(); initial /= initial.sum()
    count, reward, elapsed, correction, maximum_defect = 0.0, 0.0, 0.0, 0.0, 0.0
    with torch.no_grad():
        for step in range(observations):
            i = step % len(durations)
            operator = operators[i]
            result = advance_probability(p, operator["transition"],
                operator_kind=REGENERATIVE_PROBABILITY,
                event_vector=operator["event_vector"], reward_vector=operator["reward_vector"])
            p = result["probability"]
            count += float(result["events"]); reward += float(result["reward"])
            elapsed += float(torch.tensor(durations[i], dtype=torch.float32))
            correction += float(result["diagnostics"]["actual_l1_correction"])
            maximum_defect = max(maximum_defect,
                                abs(float(result["diagnostics"]["post_projection_mass"]) - 1))
    represented[5] = elapsed
    reference = dense_reference(represented)
    target = initial @ reference["transition"]
    target_count = float(initial @ reference["event_vector"])
    target_reward = float(initial @ reference["reward_vector"])
    error = float(np.abs(p.double().numpy() - target).sum())
    count_error = abs(count - target_count) / max(1, abs(target_count))
    assert error < LIMITS["long_float32_state_l1"], error
    assert count_error < LIMITS["long_event_scaled"], count_error
    return dict(observations=observations, physical_time=elapsed, final_state_l1_error=error,
        event_count=count, reference_event_count=target_count, event_scaled_error=count_error,
        reward=reward, reference_reward=target_reward, reward_absolute_error=abs(reward - target_reward),
        maximum_post_projection_mass_defect=maximum_defect,
        cumulative_actual_l1_roundoff_correction=correction,
        count_accumulation="Python binary64 over float32 per-step expected counts",
        profile="tagged regenerative bounded unit-mass correction")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    files = [Path(__file__), source / "kernel.py", source / "kernel_tests.py",
             Path(original.__file__), source.parent / "hcsn_distributional_v2/stable_probability.py"]
    hashes = {str(p): _sha(p) for p in files}
    registration = dict(schema="hcsn-conservative-acceleration-validation.v1",
        grid=asdict(GRID), parameter_names=NAMES, gradient_parameters=PARAMETERS,
        limits=LIMITS, source_sha256=hashes,
        independent_reference="scalar physical jump assembly, SciPy augmented expm and dense value solve",
        long_float32_observations=4096, no_task_labels=True,
        excludes=["Brownian spatial exactness", "global gradient error proof", "GPU/energy performance"])
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    records, failures = {}, []
    for name, function in (("forward", forward_audit), ("gradients", gradient_audit),
                           ("batch_knots", batch_and_knots_audit),
                           ("refractory_semantics", refractory_semantics_audit),
                           ("guards", guard_audit),
                           ("long_float32", long_float32_audit)):
        try:
            records[name] = function()
        except Exception:
            failures.append(dict(section=name, traceback=traceback.format_exc()))
    changed = [str(p) for p in files if _sha(p) != hashes[str(p)]]
    result = dict(schema="hcsn-conservative-acceleration-validation-result.v1",
        passed=not failures and not changed, records=records, failures=failures,
        source_changed_during_run=changed, source_sha256=hashes,
        cpu_seconds=time.process_time() - start_cpu, wall_seconds=time.perf_counter() - start_wall,
        python=platform.python_version(), torch=torch.__version__, gpu_measured=False)
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "cpu_seconds", "wall_seconds")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    main(options.output)
