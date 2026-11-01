"""Reset-aware and free-endpoint forecasts scored on the SAME CTMC outcomes.

The free Gaussian is deliberately a different future law. Its discrepancy on
CTMC paths does not prove Brownian discretization convergence, reset causality,
learned model calibration, task efficacy, or an advantage over a matched CTMC.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import ndtr

from .renewal import expected_events, first_hit, generator, transition
from .renewal_checks import monte_carlo


def run(samples=12000):
    if not isinstance(samples, int) or samples < 10000:
        raise ValueError("at least 10000 independent paths per horizon required")
    wall, cpu = time.perf_counter(), time.process_time()
    physical = dict(boundary=1., diffusion=.575, gain=.45, drift_bias=.04,
                    reset_plus=-.24, reset_minus=.19, recovery_rate=1.125)
    symbol, reliability = 1, .85
    drift = physical["drift_bias"]+physical["gain"]*symbol*(2*reliability-1)
    q, positions = generator(physical, symbol, reliability)
    initial = np.eye(len(q))[len(positions)//2]
    thresholds = np.array([-.5, 0., .5])*physical["boundary"]
    horizons = (.25, .75, 1.5, 3., 6.)
    # Three thresholds partition the active space into four bins. Exact atoms
    # on a threshold belong to its lower bin; refractory modes are separate.
    active_categories = np.searchsorted(thresholds, positions, side="left")
    state_categories = np.r_[active_categories, 4, 5]
    categories = ["active_x<=-0.5B", "active_-0.5B<x<=0", "active_0<x<=0.5B",
                  "active_x>0.5B", "lower_refractory", "upper_refractory"]
    probability_alpha, brier_alpha = .001, .001
    probability_bound = math.sqrt(math.log(2*len(horizons)*6/probability_alpha)/(2*samples))
    rows = []
    for index, horizon in enumerate(horizons):
        seed = 1861100+index
        states, counts, first = monte_carlo(q, horizon, samples, seed)
        outcome = state_categories[states]
        full = initial@transition(q, horizon)
        correct = np.bincount(state_categories, weights=full, minlength=6)
        empirical = np.bincount(outcome, minlength=6)/samples
        cdf = ndtr((thresholds-drift*horizon)/(physical["diffusion"]*math.sqrt(horizon)))
        free = np.r_[np.diff(np.r_[0., cdf, 1.]), 0., 0.]
        for probabilities in (correct, empirical, free):
            if abs(probabilities.sum()-1.) > 3e-12 or np.min(probabilities) < 0:
                raise ArithmeticError("nonexhaustive forecast categories")
        scores_correct = 1.+float(correct@correct)-2*correct[outcome]
        scores_free = 1.+float(free@free)-2*free[outcome]
        paired = scores_free-scores_correct
        delta = float(np.mean(paired))
        delta_se = float(np.std(paired, ddof=1)/math.sqrt(samples))
        exact_delta = float(np.square(free-correct).sum())
        differences_by_category = float(free@free-correct@correct)-2*(free-correct)
        difference_range = float(np.ptp(differences_by_category))
        brier_bound = difference_range*math.sqrt(math.log(2*len(horizons)/brier_alpha)/(2*samples))
        maximum_error = float(np.max(np.abs(correct-empirical)))
        if maximum_error > probability_bound or abs(delta-exact_delta) > brier_bound:
            raise AssertionError("independent CTMC sample disagrees with registered law bound")
        first_prediction = first_hit(q, initial[:len(positions)], horizon)
        event_prediction = expected_events(q, initial, horizon)
        rows.append(dict(
            horizon=horizon, samples=samples, independent_seed=seed,
            category_probabilities=dict(reset_aware_ctmc=correct.tolist(), free_gaussian=free.tolist(), empirical_ctmc=empirical.tolist()),
            empirical_category_standard_error=np.sqrt(empirical*(1-empirical)/samples).tolist(),
            maximum_calibration_discrepancy=dict(reset_aware_ctmc=maximum_error,
                                               free_gaussian=float(np.max(np.abs(free-empirical)))),
            reset_aware_maximum_discrepancy_upper_bound=maximum_error+probability_bound,
            free_gaussian_maximum_discrepancy_lower_bound=max(0., float(np.max(np.abs(free-empirical)))-probability_bound),
            brier=dict(reset_aware_mean=float(scores_correct.mean()), free_gaussian_mean=float(scores_free.mean()),
                       paired_free_minus_reset_mean=delta, paired_standard_error=delta_se,
                       paired_simultaneous_hoeffding_half_width=brier_bound,
                       expected_difference_under_declared_ctmc=exact_delta,
                       expected_reset_aware=1.-float(correct@correct),
                       expected_free_gaussian=1.+float(free@free)-2*float(free@correct)),
            refractory_occupancy=dict(predicted=correct[4:].tolist(), empirical=empirical[4:].tolist(), free_gaussian=[0., 0.]),
            expected_event_counts=event_prediction.tolist(), empirical_event_counts=counts.mean(axis=0).tolist(),
            event_count_descriptive_standard_error=(counts.std(axis=0, ddof=1)/math.sqrt(samples)).tolist(),
            first_event_probability=first_prediction,
            empirical_first_event_probabilities=[float((first == side+1).mean()) for side in (0, 1)]))
    here = Path(__file__).parent
    return dict(
        schema="digital-reset-aware-forecast-comparison-v1", numerical_contract_passed=True,
        source_sha256={name: hashlib.sha256((here/name).read_bytes()).hexdigest()
                       for name in ("renewal.py", "renewal_checks.py", "forecast_comparison.py")},
        physical=physical, input_assumption=dict(symbol=symbol, reliability=reliability,
                                               drift=drift, duration="held constant separately throughout each horizon"),
        initial_state=7, initial_voltage=0., thresholds=thresholds.tolist(), categories=categories,
        independent_paths_per_horizon=samples, total_independent_paths=samples*len(horizons),
        monte_carlo_rng="NumPy default_rng independent vectorized exponential/categorical sampler",
        simultaneous_probability_error_bound=probability_bound, probability_family_alpha=probability_alpha,
        probability_family_size=len(horizons)*6,
        paired_brier_family_alpha=brier_alpha, paired_brier_family_size=len(horizons),
        total_familywise_failure_bound=probability_alpha+brier_alpha,
        brier_definition="sum across all six categories of (forecast probability - outcome indicator)^2",
        free_endpoint_definition="unbounded Gaussian endpoint with mean mu*t and variance sigma^2*t; zero refractory probability",
        rows=rows, scope="diagnostic semantic contrast on declared finite-CTMC paths",
        learned_model_calibration=False, task_efficacy_claim=False, brownian_spatial_convergence=False,
        reset_only_causal_attribution=False, production_activation=False,
        limitations=["CTMC/grid versus continuous Gaussian differs in both propagation and reset/refractory semantics.",
                     "Inclusive thresholds contain CTMC voltage atoms; Gaussian has no threshold atoms.",
                     "A matched generic CTMC/HMM has the same forecast and receives no special-name disadvantage.",
                     "No trained forecast model, real task adoption, complete execution economics, or energy measurement.",
                     "Native event implementation remains a standalone research executable without production ACK-owner integration."],
        timing=dict(wall_seconds=time.perf_counter()-wall, python_cpu_seconds=time.process_time()-cpu))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=12000)
    args = parser.parse_args()
    print(json.dumps(run(args.samples), sort_keys=True, indent=2, allow_nan=False))
