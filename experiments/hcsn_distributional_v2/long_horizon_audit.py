"""Independent renewal identities and long recurrent floating-point audit.

This is a new diagnostic. It does not change a frozen model, select a checkpoint,
read task labels, or treat accurate finite-state propagation as Brownian accuracy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
from scipy.linalg import expm, solve
import torch

from .distribution_kernel import Grid, make_flow, prepare_operator, propagate
from .kernel_tests import independent_generator


CASES = [
    dict(name="central", parameters=[.1, .45, .85, -.1, .75]),
    dict(name="negative_drift", parameters=[-.28, .32, 1.1, -.25, 1.1]),
    dict(name="fast_cycle", parameters=[.48, .6, .55, .05, .3]),
    dict(name="rate_domain_corner", parameters=[.5, .6, .35, -.1, .3]),
]
DURATIONS = [.07, .36, .495755147934, 3.2]
OBSERVATIONS = 4096
SNAPSHOTS = [16, 64, 256, 1024, 4096]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dense_reference(generator, event, initial, duration):
    size = len(initial)
    augmented = np.zeros((size + 1, size + 1))
    augmented[:size, :size] = generator
    augmented[size, :size] = event
    value = expm(augmented * duration) @ np.r_[initial, 0.]
    return value[:-1], float(value[-1])


def renewal_reference(parameters, grid):
    """Two independent cycle/occupation identities for the finite chain."""
    generator, event, centers, reset_weights = independent_generator(*parameters, grid)
    active = generator[:grid.cells, :grid.cells]
    mean_hitting_times = solve(-active.T, np.ones(grid.cells))
    mean_hitting = float(reset_weights @ mean_hitting_times)
    cycle_mean = mean_hitting + parameters[-1]
    renewal_rate = 1 / cycle_mean
    occupation = solve(-active, reset_weights) / cycle_mean
    phase_mass = np.full(grid.refractory_stages,
                         parameters[-1] / grid.refractory_stages / cycle_mean)
    cycle_probability = np.r_[occupation, phase_mass]
    constrained = generator.copy()
    constrained[-1] = 1
    rhs = np.zeros(len(generator)); rhs[-1] = 1
    stationary = solve(constrained, rhs)
    stationary_rate = float(stationary @ event)
    residual = float(np.abs(generator @ stationary).max())
    rate_error = abs(stationary_rate - renewal_rate)
    occupation_error = float(np.abs(stationary - cycle_probability).max())
    return generator, event, stationary, dict(
        mean_active_cycle_time=mean_hitting, mean_cycle_time=cycle_mean,
        renewal_rate=renewal_rate, stationary_rate=stationary_rate,
        rate_absolute_error=rate_error, stationary_residual_max=residual,
        cycle_occupation_max_error=occupation_error,
        stationary_probability=stationary.tolist(),
        cycle_occupation_probability=cycle_probability.tolist(),
        refractory_phase_means=phase_mass.tolist(),
        refractory_law_mean=parameters[-1],
        refractory_law_variance=parameters[-1] ** 2 / grid.refractory_stages,
        algebra_passed=max(rate_error, occupation_error, residual) < 1e-10,
    )


def run_case(case, dtype, output, grid):
    parameters = [torch.tensor(v, dtype=dtype) for v in case["parameters"]]
    represented_parameters = [float(v) for v in parameters]
    generator, event, stationary, renewal = renewal_reference(represented_parameters, grid)
    flow = make_flow(*parameters, grid=grid)
    operators = [prepare_operator(*parameters, torch.tensor(dt, dtype=dtype), grid=grid)
                 for dt in DURATIONS]
    probability = torch.tensor(stationary, dtype=dtype)
    initial = probability.double().numpy().copy()
    count = torch.zeros((), dtype=dtype)
    high_precision_sum = 0.
    elapsed = 0.
    trace = []
    snapshots = []
    first_checked_mass_violation = None
    original_mass_tolerance = max(1e-12, 256 * torch.finfo(dtype).eps)
    with torch.no_grad():
        for step in range(1, OBSERVATIONS + 1):
            index = (step - 1) % len(DURATIONS)
            operator = operators[index]
            duration = float(torch.tensor(DURATIONS[index], dtype=dtype))
            increment = probability @ operator["event_vector"]
            count = count + increment
            high_precision_sum += float(increment)
            probability = probability @ operator["transition"]
            elapsed += duration
            mass = float(probability.sum())
            mass_error = abs(mass - 1)
            if mass_error > original_mass_tolerance and first_checked_mass_violation is None:
                first_checked_mass_violation = step
            trace.append([step, elapsed, mass, float(probability.min()), float(count),
                          high_precision_sum, *probability.double().tolist()])
            if step in SNAPSHOTS:
                ref_probability, ref_count = dense_reference(generator, event, initial, elapsed)
                try:
                    propagate(probability, flow, 0.)
                    checked_accepts, checked_error = True, None
                except ValueError as error:
                    checked_accepts, checked_error = False, str(error)
                snapshots.append(dict(
                    observations=step, physical_time=elapsed, mass=mass,
                    mass_error=mass_error, minimum_probability=float(probability.min()),
                    state_l1_error=float(np.abs(probability.double().numpy() - ref_probability).sum()),
                    events=float(count), dense_reference_events=ref_count,
                    event_error=abs(float(count) - ref_count),
                    event_error_using_double_accumulation=abs(high_precision_sum - ref_count),
                    checked_propagator_accepts_returned_state=checked_accepts,
                    checked_propagator_error=checked_error,
                ))
    filename = f"{case['name']}_{str(dtype).split('.')[-1]}.npz"
    np.savez_compressed(output / filename, trace=np.asarray(trace),
                        initial=initial, generator=generator, event_vector=event,
                        stationary=stationary)
    return dict(case=case["name"], dtype=str(dtype), parameters=represented_parameters,
                renewal=renewal, snapshots=snapshots,
                original_checked_mass_tolerance=original_mass_tolerance,
                first_checked_mass_violation=first_checked_mass_violation,
                trace_path=filename, trace_sha256=digest(output / filename),
                trace_columns=["observation", "physical_time", "mass", "minimum_probability",
                               "events_dtype_sum", "events_double_sum"] +
                              [f"probability_{i}" for i in range(len(generator))])


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    directory = Path(__file__).parent
    files = [Path(__file__), directory / "distribution_kernel.py",
             directory / "kernel_tests.py", directory / "MATH.md"]
    hashes = {str(path): digest(path) for path in files}
    registration = dict(
        schema="hcsn-long-horizon-registration.v1", cases=CASES,
        observations=OBSERVATIONS, snapshots=SNAPSHOTS, durations=DURATIONS,
        dtypes=["float32", "float64"], source_sha256=hashes,
        initialization="Independent finite-chain stationary distribution, cast to tested dtype",
        reference="Dense augmented matrix exponential and independent renewal/occupation linear equations",
        checks="Renewal algebra 1e-10; report original API mass-contract violations without changing its tolerance",
        task_labels_read=False, frozen_protocol_or_source_changed=False,
        limitations=["Finite reflecting-domain CTMC; no unbounded Brownian exactness",
                     "Erlang refractory phases; no deterministic-delay claim",
                     "Roundoff is outside the production analytic Poisson-tail certificate",
                     "Diagnostic horizons do not change the frozen content experiment"],
    )
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    grid = Grid(8, -2., 2, fixed_rate=8.1, fixed_terms=21, max_duration=.36,
                per_token_chunks=True)
    rows = [run_case(case, dtype, output, grid)
            for case in CASES for dtype in [torch.float32, torch.float64]]
    changes = [str(path) for path in files if digest(path) != hashes[str(path)]]
    result = dict(
        schema="hcsn-long-horizon-audit.v1", records=rows,
        algebra_passed=all(row["renewal"]["algebra_passed"] for row in rows),
        all_prepared_rollouts_within_checked_mass_contract=all(
            row["first_checked_mass_violation"] is None for row in rows),
        source_changed_during_audit=changes,
        cpu_seconds=time.process_time() - start_cpu,
        wall_seconds=time.perf_counter() - start_wall,
        peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        python=platform.python_version(), torch=torch.__version__,
        numpy=np.__version__, source_sha256=hashes,
        diagnostic_only=True, gpu_measured=False, energy_measured=False,
    )
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = ["# Independent long-horizon regenerative audit", "",
             "This new diagnostic preserves the frozen kernel and content protocols. "
             "It compares the finite model with independent renewal/occupation equations "
             "and dense matrix exponentials. It does not measure content quality.", "",
             "| Case | Dtype | First original mass-contract violation | Final mass error | Final state L1 error | Final event error |",
             "|---|---|---:|---:|---:|---:|"]
    for row in rows:
        final = row["snapshots"][-1]
        lines.append(f"| {row['case']} | {row['dtype']} | {row['first_checked_mass_violation']} | "
                     f"{final['mass_error']:.9g} | {final['state_l1_error']:.9g} | {final['event_error']:.9g} |")
    lines.extend(["", f"Renewal algebra passed: {result['algebra_passed']}. "
                  "Its comparison separately checks the inverse mean regenerative-cycle time, "
                  "the stationary marked-event rate, and per-phase refractory occupation.", "",
                  "Prepared recurrent updates do not call the checked propagator at each token. "
                  "The reported violation is of the existing checked API's unit-mass tolerance, "
                  "not a newly selected success threshold. Snapshots retain whether that API "
                  "accepts the recurrent state, and every step is saved in the NPZ traces.", "",
                  "The count-error columns include floating-point accumulation. RESULTS.json also "
                  "reports double accumulation of the same per-step increments, separating part "
                  "of that error. Analytic Poisson-tail bounds exclude these roundoff effects.", "",
                  f"Self CPU {result['cpu_seconds']:.6f}s; wall {result['wall_seconds']:.6f}s; "
                  f"peak RSS {result['peak_rss_kib_linux']} KiB. No GPU or energy measurement.", ""])
    (output / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({"algebra_passed": result["algebra_passed"],
                      "all_mass_contracts": result["all_prepared_rollouts_within_checked_mass_contract"],
                      "records": len(rows), "cpu_seconds": result["cpu_seconds"]}))
    if changes or not result["algebra_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    main(args.output)
