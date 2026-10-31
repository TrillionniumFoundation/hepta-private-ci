"""Quantify numerical-promotion blockers without changing the registered cell.

These are diagnostic accuracy gates, not implementation unit-test verdicts.
Thresholds were set after exploratory discovery of the corner failures; they
must not be represented as preregistered statistical hypotheses.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform

import numpy as np
import scipy
from scipy.special import log_ndtr, ndtr
from scipy.stats import t as student_t
import torch

try:
    from .dynamics import EventDynamics
except ImportError:
    from dynamics import EventDynamics


GRIDS = (9, 15, 31, 63)
MAIN_GRID = 15


def brownian_exit_reference(drift: float, sigma: float, boundary: float, dt: float) -> np.ndarray:
    """Both first-exit probabilities from x=0 in (-b,b).

    Integrate the killed Brownian transition density's boundary flux from dt
    to infinity, then subtract from the eventual splitting probabilities.  Its
    exponentially decaying series is independent of the upwind CTMC.  This
    implementation is used in a moderate-drift regime to avoid cancellation.
    """
    n = np.arange(1, 400, dtype=np.float64)
    wave = n * np.pi / (2.0 * boundary)
    decay = 0.5 * sigma**2 * wave**2 + drift**2 / (2.0 * sigma**2)
    sine = np.sin(n * np.pi / 2.0)
    if abs(drift) < 1e-12:
        eventually_plus = 0.5
    else:
        eventually_plus = float(-np.expm1(-2.0 * drift * boundary / sigma**2) / -np.expm1(-4.0 * drift * boundary / sigma**2))
    common = sigma**2 / (2.0 * boundary)
    tail = sine * wave / decay * np.exp(-decay * dt)
    plus = eventually_plus - common * math.exp(drift * boundary / sigma**2) * np.sum((-1.0) ** (n + 1.0) * tail)
    minus = 1.0 - eventually_plus - common * math.exp(-drift * boundary / sigma**2) * np.sum(tail)
    return np.array([plus, minus], dtype=np.float64)


def brownian_cell(mode: str, grid: int, low_noise: bool = False) -> EventDynamics:
    cell = EventDynamics(mode, grid)
    with torch.no_grad():
        # Kappa < 1.3e-15; this is a Brownian validation subcase, not a claim
        # that the default learned OU process has zero leak.
        cell.raw_leak.fill_(-35.0)
        if low_noise:
            cell.raw_diffusion.fill_(-35.0)
    return cell


def audit() -> dict:
    torch.set_num_threads(1)
    gates = []

    def gate(name: str, passed: bool, criterion: str, scope: str) -> None:
        gates.append({"name": name, "status": "PASS" if passed else "FAIL", "criterion": criterion, "scope": scope})

    reference = brownian_exit_reference(1.0, 0.45, 1.0, 1.0)
    drifted = []
    max_mass_error = 0.0
    minimum_probability = 1.0
    for n in GRIDS:
        cell = brownian_cell("first_passage", n)
        transition, _ = cell.transition_matrix(torch.tensor([1.0], dtype=torch.float64))
        max_mass_error = max(max_mass_error, float((transition.sum(-1) - 1.0).abs().max().detach()))
        minimum_probability = min(minimum_probability, float(transition.min().detach()))
        _, events = cell(cell.initial(1), torch.tensor([1.0], dtype=torch.float64))
        values = events[0].detach().numpy()
        error = float(np.max(np.abs(values - reference)))
        drifted.append({"grid": n, "probabilities_plus_minus": values.tolist(), "max_absolute_error": error, "accuracy_status": "PASS" if error <= 1e-3 else "FAIL"})
    main_drift = next(row for row in drifted if row["grid"] == MAIN_GRID)
    gate("default_noise_fpt_main_grid", main_drift["max_absolute_error"] <= 1e-3, "max channel probability error <= 0.001", "Brownian validation subcase, drift=1, sigma=.45, b=1, dt=1")
    errors = [row["max_absolute_error"] for row in drifted]
    gate("drifted_fpt_mesh_refinement_progress", all(a > b for a, b in zip(errors, errors[1:])), "error strictly decreases on grids 9,15,31,63", "Refinement progress is not an accuracy acceptance or continuous-model proof")
    gate("ctmc_probability_law", max_mass_error <= 2e-10 and minimum_probability >= -2e-13, "row mass error <= 2e-10 and entries >= -2e-13", "Implementation probability law only")

    sigma, drift, b, dt = 0.05, 1.0, 1.0, 0.8
    first_argument = (drift * dt - b) / (sigma * math.sqrt(dt))
    second_argument = (-drift * dt - b) / (sigma * math.sqrt(dt))
    single_barrier = float(ndtr(first_argument) + math.exp(2.0 * drift * b / sigma**2 + log_ndtr(second_argument)))
    low_noise = []
    for n in GRIDS:
        cell = brownian_cell("first_passage", n, low_noise=True)
        _, events = cell(cell.initial(1), torch.tensor([drift], dtype=torch.float64), dt)
        actual = float(events[0, 0].detach())
        error = abs(actual - single_barrier)
        low_noise.append({"grid": n, "plus_probability": actual, "absolute_error": error, "effective_variance_rate_at_zero": sigma**2 + abs(drift) * 2.0 * b / (n + 1), "accuracy_status": "PASS" if error <= 1e-4 else "FAIL"})
    main_low = next(row for row in low_noise if row["grid"] == MAIN_GRID)
    gate("low_noise_fpt_main_grid", main_low["absolute_error"] <= 1e-4, "absolute upper-hit probability error <= 0.0001", "sigma=.05, drift=1, b=1, dt=.8; lower-first-exit correction is bounded by exp(-800)")

    small_dt = []
    for n in GRIDS:
        for tick in (0.1, 0.01, 0.001, 0.0001):
            row = {"grid": n, "dt": tick, "reference_variance": 0.45**2 * tick}
            for mode in EventDynamics.MODES:
                cell = brownian_cell(mode, n)
                mass, _ = cell(cell.initial(1), torch.zeros(1, dtype=torch.float64), tick)
                ratio = float(cell.state_features(mass)[0, 1].detach()) / row["reference_variance"]
                row[mode] = {"variance_ratio": ratio, "accuracy_status": "PASS" if abs(ratio - 1.0) <= 0.05 else "FAIL"}
            small_dt.append(row)
    for mode in EventDynamics.MODES:
        main_rows = [row for row in small_dt if row["grid"] == MAIN_GRID]
        gate(f"small_dt_fixed_grid_{mode}", all(row[mode]["accuracy_status"] == "PASS" for row in main_rows), "variance ratio within 5% of sigma^2*dt at every tested dt", "Zero drift, sigma=.45, fixed grid15; tiny actual Brownian boundary-hit probability is negligible here")

    recovery = []
    q = 0.65
    cohort_error = 0.0
    for tick in (1.0, 0.1, 0.01):
        cell = EventDynamics("clocked", MAIN_GRID)
        transition, _ = cell.transition_matrix(torch.zeros(1, dtype=torch.float64), tick)
        refractory = transition[0, -2:, -2:].detach().numpy()
        windows = []
        for steps in (1, 3, 8):
            observed = float(np.linalg.matrix_power(refractory, steps)[0, 0])
            expected = (1.0 - q) ** steps
            cohort_error = max(cohort_error, abs(observed - expected))
            windows.append({"ticks": steps, "unreleased_original_cohort": observed, "geometric_reference": expected})
        recovery.append({"dt": tick, "q": q, "expected_whole_refractory_ticks": 1.0 / q, "expected_whole_refractory_duration": tick / q, "unreleased_fraction_after_physical_time_1": (1.0 - q) ** round(1.0 / tick), "cohort_checks": windows})
    gate("refractory_discrete_window_contract", cohort_error <= 1e-13, "original refractory cohort survival agrees with (1-q)^k within 1e-13", "A check of the declared discrete recovery law")
    durations = [row["expected_whole_refractory_duration"] for row in recovery]
    gate("fixed_q_preserves_physical_recovery_when_dt_changes", max(durations) / min(durations) <= 1.05, "mean physical refractory duration changes by at most 5%", "A prerequisite for claiming a same-process dt convergence study; the current tick-relative model does not promise this")

    heavy_tail = []
    for threshold in (1.0, 2.0, 3.0):
        predicted = float(ndtr(-threshold))
        references = {"laplace_unit_variance": 0.5 * math.exp(-math.sqrt(2.0) * threshold), "student_t3_unit_variance": float(student_t.sf(threshold * math.sqrt(3.0), df=3))}
        for distribution, reference_tail in references.items():
            error = abs(predicted - reference_tail)
            relative = error / reference_tail
            heavy_tail.append({"distribution": distribution, "threshold_standard_deviations": threshold, "gaussian_prediction": predicted, "actual_terminal_tail": reference_tail, "absolute_error": error, "relative_error": relative, "accuracy_status": "PASS" if error <= 1e-3 and relative <= 0.10 else "FAIL"})
    gate("gaussian_kernel_calibration_after_noise_law_swap", all(row["accuracy_status"] == "PASS" for row in heavy_tail), "all terminal tails have absolute error <=.001 and relative error <=10%", "Hypothetical non-Gaussian internal-noise substitution with equal mean/variance; non-Gaussian external content alone does not invalidate a conditional Gaussian kernel")

    extreme_tails = []
    for argument in (-8.0, -9.0, -10.0):
        tensor = torch.tensor(argument, dtype=torch.float64)
        implemented = float(torch.special.ndtr(tensor))
        erfc_reference = float(0.5 * torch.erfc(-tensor / math.sqrt(2.0)))
        scipy_reference = float(ndtr(argument))
        relative_error = abs(implemented - scipy_reference) / scipy_reference
        extreme_tails.append({"standardized_argument": argument,
                              "registered_torch_ndtr": implemented,
                              "torch_erfc_reference": erfc_reference,
                              "scipy_ndtr_reference": scipy_reference,
                              "relative_error": relative_error,
                              "accuracy_status": "PASS" if relative_error <= 1e-3 else "FAIL"})
    gate("registered_gaussian_extreme_tail_accuracy",
         all(row["accuracy_status"] == "PASS" for row in extreme_tails),
         "relative lower-tail error <= 0.1% at z=-8,-9,-10",
         "Known cancellation in this runtime's torch.special.ndtr; the already running primary model was deliberately not changed")

    path = Path(__file__).with_name("dynamics.py")
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dynamics_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "runtime": {"python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__, "scipy": scipy.__version__, "dtype": "float64", "torch_threads": torch.get_num_threads()},
        "main_grid": MAIN_GRID,
        "grids": list(GRIDS),
        "status": "NUMERICAL_PROMOTION_BLOCKED" if any(g["status"] == "FAIL" for g in gates) else "ACCURACY_GATES_PASSED",
        "scope": "Diagnostics of the registered fixed-grid models; failures are not proof of code bugs and no generator was retuned to hide them.",
        "threshold_registration": "Diagnostic tolerances were declared after exploratory corner discovery, not before data collection; no confirmatory statistical claim.",
        "accuracy_gates": gates,
        "drifted_brownian_first_exit": {"configuration": {"drift": 1.0, "sigma": .45, "boundary": 1.0, "dt": 1.0, "leak_bound": 1.3e-15}, "reference_plus_minus": reference.tolist(), "reference_method": "Independently integrated killed-Brownian boundary flux, 399 exponentially decaying terms", "measurements": drifted},
        "low_noise_first_exit": {"configuration": {"drift": 1.0, "sigma": .05, "boundary": 1.0, "dt": .8, "leak_bound": 1.3e-15}, "single_upper_barrier_reference": single_barrier, "log_upper_bound_on_lower_first_exit_correction": -800.0, "measurements": low_noise},
        "fixed_mesh_small_dt": small_dt,
        "recovery_windows": {"measurements": recovery, "max_discrete_cohort_error": cohort_error, "physical_time_note": "A continuous recovery hazard lambda would require q(dt)=1-exp(-lambda*dt), plus an explicit convention for the event tick remainder. That alternative is not implemented here."},
        "non_gaussian_terminal_tails": heavy_tail,
        "registered_normal_cdf_extreme_tails": extreme_tails,
        "probability_law_check": {"maximum_row_mass_error": max_mass_error, "minimum_transition_entry": minimum_probability},
        "promotion_limitations": [
            "Fixed-grid first-passage performance is performance of the specified CTMC, not verified continuous-OU first-passage evidence.",
            "At drift mu and mesh h, upwind local variance rate is sigma^2+abs(mu)*h; low-noise learned parameters can be dominated by numerical diffusion.",
            "Endpoint Gaussian binning can freeze at fixed mesh as dt decreases; voltage and time must be refined jointly.",
            "The continuous comparison is also a projected finite-grid distribution model with boundary-tail bias.",
            "Current q is relative to the tick; fixed-q dt sweeps change the physical refractory process.",
            "A Gaussian conditional transition is not calibrated for arbitrary non-Gaussian internal increments merely because mean and variance match.",
            "The frozen torch.special.ndtr implementation returns zero at standardized arguments -9 and -10 in this runtime; extreme-tail likelihood accuracy is not established. An erfc/log-CDF correction belongs to a separately versioned rerun.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("evidence") / "numerical_audit.json")
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["status"], "accuracy_gates": report["accuracy_gates"]}, indent=2))


if __name__ == "__main__":
    main()

