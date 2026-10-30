"""Declared numerical acceptance domain for the first-passage clock package.

Run ``python -m experiments.first_passage_clock_v1.validation --output PATH``.
Every failure is recorded; a failed check produces a nonzero exit status. The
domain and tolerances are explicit below and are not fitted to measured errors.
"""

import argparse
from dataclasses import asdict, dataclass
import itertools
import json
import math
from pathlib import Path

import numpy as np

from . import kernels
from .oracle import (
    ReferenceParams, decimal_cdf_derivatives, decimal_discounted_derivatives,
    decimal_log_event, decimal_log_hit, decimal_log_survival, decimal_outcome_law,
    decimal_score_event, quadrature_outcome_law, sample_competing_events,
    shape_clock_negative_control,
)


@dataclass(frozen=True)
class Case:
    name: str
    distance: float
    horizon: float
    mu: float
    sigma: float
    rate: float

    def parameters(self):
        return kernels.Params(self.mu, self.sigma, self.rate)

    def reference_parameters(self):
        return ReferenceParams(self.mu, self.sigma, self.rate)


# This suite includes the actual failures discovered in the old attachment. It
# does not remove sigma=1e-8 from the numerical domain to make the tests pass.
TAIL_CASES = (
    Case("discount_floor_1e-8", .5, 1, 1, 1e-8, 1),
    Case("discount_floor_1e-6", .5, 1, 1, 1e-6, 1),
    Case("arrival_floor_1e-8", 1, 1, 1, 1e-8, 1),
    Case("arrival_floor_1e-6", 1, 1, 1, 1e-6, 0),
    Case("arrival_floor_1e-4", 1, 1, 1, 1e-4, 1e-12),
    Case("survival_2e-20", 1, 1, 10, 1, .3),
    Case("rare_no_hit_rate_score", 1, 1, 10, 1, 0),
    Case("survival_below_float", 1, 1, 100, 1, .3),
    Case("no_hit_below_float_no_cancel", 1, 1, 100, 1, 0),
    Case("hit_below_float", 40, 1, 0, 1, 0),
    Case("negative_drift_tail", 1, 1, -100, 1, .5),
    Case("near_boundary", 1e-12, 1, 2, 1, 0),
    Case("near_boundary_large_drift", 1e-8, 1, 50, 1, .3),
    Case("double_root", 1, 1, 0, 1, 0),
    Case("near_double_root", 1, 1, 1e-12, 1, 1e-24),
    Case("tiny_cancel", 1, 1, .2, .8, 1e-12),
    Case("short_clock", 1e-4, 1e-4, 1, 1e-4, 1),
    Case("long_clock", 1, 1000, -.03, .2, .001),
    Case("fast_cancel", 1, 1, .2, .8, 1000),
)

TOLERANCES = {
    "log_absolute": 5e-10,
    "log_ulp_allowance": 64,
    "probability_absolute": 3e-10,
    "probability_component_relative": 2e-7,
    "derivative_absolute": 3e-9,
    "derivative_relative": 2e-8,
    "positive_quadrature_absolute": 2e-8,
    "physical_sampler_standard_errors": 6.0,
}


def run_validation():
    checks = []

    def check(label, actual, reference, absolute, relative=0.0, case=None):
        got, ref = np.asarray(actual, dtype=float), np.asarray(reference, dtype=float)
        matching_infinity = np.isinf(got) & (got == ref)
        finite = np.isfinite(got) & np.isfinite(ref)
        error = np.where(finite, np.abs(np.where(finite, got, 0) - np.where(finite, ref, 0)), 0)
        allowance = absolute + relative * np.abs(np.where(finite, ref, 0))
        good = matching_infinity | (finite & (error <= allowance))
        checks.append({
            "name": label, "case": case, "passed": bool(np.all(good)),
            "actual": got.tolist(), "reference": ref.tolist(),
            "max_absolute_error": float(np.max(error)),
            "absolute_tolerance": absolute, "relative_tolerance": relative,
        })

    moderate = [
        Case(f"moderate_{i}", d, t, m, s, q)
        for i, (d, t, m, s, q) in enumerate(itertools.product(
            (.25, 1.0), (.2, 1.3), (-.7, 0.0, 1.0), (.5, 1.5), (0.0, .4)
        ))
    ]
    cases = moderate + list(TAIL_CASES)
    for case in cases:
        d, t, p = case.distance, case.horizon, case.parameters()
        reference_params = case.reference_parameters()
        source = asdict(case)
        try:
            log_values = (
                ("log_cdf", kernels.log_fpt_cdf(d, t, p.mu, p.sigma),
                 decimal_log_hit(d, t, p.mu, p.sigma)),
                ("log_survival", kernels.log_survival(d, t, p.mu, p.sigma),
                 decimal_log_survival(d, t, p.mu, p.sigma)),
                ("log_discounted_hit", kernels.log_discounted_hit(d, t, p.mu, p.sigma, p.cancel_rate),
                 decimal_log_hit(d, t, p.mu, p.sigma, p.cancel_rate)),
            )
            for label, got, ref in log_values:
                check(label, got, ref, TOLERANCES["log_absolute"],
                      TOLERANCES["log_ulp_allowance"] * np.finfo(float).eps, source)
            got_law = kernels.outcome_law(d, t, p)
            ref_law = decimal_outcome_law(d, t, reference_params)
            check("outcome_law", got_law, ref_law, TOLERANCES["probability_absolute"], case=source)
            for event, got, ref in zip(("hit", "survive", "cancel"), got_law, ref_law):
                if 1e-250 < ref < 1e-4:
                    check("rare_mass_" + event, got, ref, 0,
                          TOLERANCES["probability_component_relative"], source)
            check("cdf_derivatives", kernels.cdf_derivatives(d, t, p.mu, p.sigma),
                  decimal_cdf_derivatives(d, t, p.mu, p.sigma),
                  TOLERANCES["derivative_absolute"], TOLERANCES["derivative_relative"], source)
            if hasattr(kernels, "discounted_hit_derivatives"):
                check("discounted_derivatives", kernels.discounted_hit_derivatives(d, t, p),
                      decimal_discounted_derivatives(d, t, reference_params),
                      TOLERANCES["derivative_absolute"], TOLERANCES["derivative_relative"], source)
            for event in ("hit", "survive", "cancel", "no_hit"):
                ref_log = decimal_log_event(event, t, d, reference_params)
                got_log = kernels.log_event_likelihood(event, t, d, p)
                check("likelihood_" + event, got_log, ref_log, TOLERANCES["log_absolute"],
                      TOLERANCES["log_ulp_allowance"] * np.finfo(float).eps, source)
                # A no-hit score at a vanishing censoring probability can exceed
                # floating-point range; that is outside this score contract.
                if math.isfinite(ref_log) and not (event == "no_hit" and ref_log < -650):
                    check("score_" + event, kernels.score_event(event, t, d, p),
                          decimal_score_event(event, t, d, reference_params),
                          TOLERANCES["derivative_absolute"], TOLERANCES["derivative_relative"], source)
        except Exception as exc:
            checks.append({"name": "case_exception", "case": source, "passed": False,
                           "error": f"{type(exc).__name__}: {exc}"})

    # Original positive densities give an independent route to all three masses.
    quadrature_cases = moderate[::4]
    for case in quadrature_cases:
        check("positive_density_quadrature",
              kernels.outcome_law(case.distance, case.horizon, case.parameters()),
              quadrature_outcome_law(case.distance, case.horizon, case.reference_parameters()),
              TOLERANCES["positive_quadrature_absolute"], case=asdict(case))

    # Exact-law physical draws independently test the distribution, including
    # defective hits at negative drift. This is a fixed-seed statistical test.
    physical_cases = (
        Case("physical_positive", 1, 1.5, .8, 1.2, .4),
        Case("physical_zero", .7, 1.0, 0, 1.0, .3),
        Case("physical_negative", .5, 1.3, -.7, .8, .2),
    )
    count = 120_000
    for i, case in enumerate(physical_cases):
        expected = kernels.outcome_law(case.distance, case.horizon, case.parameters())
        observed = sample_competing_events(case.distance, case.horizon,
                                           case.reference_parameters(), count, 71800 + i)
        standard_error = np.sqrt(expected * (1 - expected) / count)
        check("exact_physical_sampler_zscore", (observed - expected) / (standard_error + 1 / count),
              np.zeros(3), TOLERANCES["physical_sampler_standard_errors"], case=asdict(case))

    speed = 4.0
    base = kernels.Params(.8, 1.2, .4)
    fast = kernels.Params(speed * base.mu, math.sqrt(speed) * base.sigma, speed * base.cancel_rate)
    before, after, null_residual = shape_clock_negative_control(base.mu, base.sigma, base.cancel_rate, speed)
    check("shape_clock_invariance", before, after, 2e-14)
    check("shape_clock_null_direction", null_residual, np.zeros(2), 2e-14)
    check("physical_clock_rescaling", kernels.outcome_law(1, 1.3 / speed, fast),
          kernels.outcome_law(1, 1.3, base), 2e-12)
    for event in ("hit", "cancel", "survive"):
        jacobian = math.log(speed) if event != "survive" else 0.0
        check("event_clock_jacobian_" + event,
              kernels.log_event_likelihood(event, .7 / speed, 1, fast),
              kernels.log_event_likelihood(event, .7, 1, base) + jacobian, 2e-12)
    separation = float(np.linalg.norm(kernels.outcome_law(1, 1.3, fast) - kernels.outcome_law(1, 1.3, base)))
    checks.append({"name": "fixed_clock_distinguishes_shape_twins", "passed": separation > .05,
                   "l2_probability_separation": separation, "minimum_separation": .05})

    for d, t, expected in ((0, 0, [1, 0, 0]), (0, 1, [1, 0, 0]), (1, 0, [0, 1, 0])):
        check("boundary_law", kernels.outcome_law(d, t, base), expected, 0,
              case={"distance": d, "horizon": t})
    failures = [record for record in checks if not record["passed"]]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checked_cases": len(cases), "checks": len(checks), "failures": failures,
        "tolerances": TOLERANCES,
        "scope": {
            "moderate_cases": len(moderate), "tail_cases": [asdict(c) for c in TAIL_CASES],
            "positive_quadrature_cases": len(quadrature_cases),
            "physical_sampler_cases": len(physical_cases), "draws_per_physical_case": count,
            "arithmetic_reference": "100-digit Decimal plus 40 guard digits; independent Gaussian series/continued fraction",
            "distribution_reference": "positive FPT/absorbed-density integrals and exact-law inverse-Gaussian/Levy draws",
            "not_claimed": [
                "All floating-point inputs, arbitrary moving barriers, or state-dependent coefficients",
                "Relative probability accuracy for probabilities below the float range",
                "Finite no-hit scores when their magnitude exceeds the float range",
                "Global learning convergence, energy superiority, or production readiness",
            ],
        },
        "records": checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = run_validation()
    def json_safe(value):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        if isinstance(value, dict):
            return {key: json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [json_safe(item) for item in value]
        return value
    report = json_safe(report)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "checked_cases", "checks", "failures")}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
