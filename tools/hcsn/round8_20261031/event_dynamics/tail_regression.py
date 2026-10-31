"""Independent near-boundary regression: Decimal CDFs and time-density tails.

The Decimal reference evaluates the reflection formula at 90 digits. It does
not use scipy.special or the tested positive-integral survival evaluation.
"""

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.special import erfcx, log_ndtr

from .event_kernel import first_hit
from .renewal import sample_counts


def decimal_survival(distance, drift):
    """Unit noise/time reflection formula, |drift|<=5 and distance>=1e-30."""
    with localcontext() as ctx:
        ctx.prec = 90
        pi = Decimal("3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342")
        root_two = Decimal(2).sqrt()
        def cdf(z):
            x = z/root_two
            term, total, n = x, x, 0
            while True:
                n += 1
                term *= -x*x/Decimal(n)
                add = term/Decimal(2*n+1)
                total += add
                if abs(add) < Decimal("1e-85"):
                    return (1+2*total/pi.sqrt())/2
                if n > 1000:
                    raise ArithmeticError("Decimal normal series did not converge")
        a, v = Decimal.from_float(distance), Decimal.from_float(drift)
        value = cdf(a-v)-(2*a*v).exp()*cdf(-a-v)
        return float(value), float(value.ln())


def time_density_log_survival(distance, drift):
    """Positive-drift first-hit density integrated from unit time to infinity.

    The substitution t=1+u/max(1,drift^2) resolves the short tail scale. This
    integral has neither a spatial killed density nor a reflected CDF term.
    """
    rate = max(1., drift*drift)
    def integrand(u):
        delta = u/rate
        exponent = (-1.5*math.log1p(delta)-.5*(drift*drift/rate)*u
                    +.5*distance*distance*delta/(1+delta))
        return math.exp(exponent)
    value, error = quad(integrand, 0., math.inf, epsabs=1e-13, epsrel=2e-13)
    return (math.log(distance)-.5*math.log(2*math.pi)-.5*(distance-drift)**2
            -math.log(rate)+math.log(value)), error/value


def legacy_survival(distance, drift):
    """Reproduce the frozen 3a0e62c direct log subtraction for this audit."""
    z, w = drift-distance, -drift-distance
    reflected = (-.5*z*z+math.log(.5*float(erfcx(-w/math.sqrt(2))))
                 if w <= 0 else 2*drift*distance+float(log_ndtr(w)))
    free = float(log_ndtr(-z))
    difference = reflected-free
    return None if difference >= 0 else math.exp(free+math.log(-math.expm1(difference)))


def audit():
    rows, tails = [], []
    for distance in (1e-8, 1e-15, 1e-30):
        for drift in (-5., -1., 0., 1., 5.):
            reference, log_reference = decimal_survival(distance, drift)
            actual = first_hit(distance, drift, 1., 1.)
            old = legacy_survival(distance, drift)
            rows.append(dict(distance=distance, drift=drift, reference=reference,
                actual=actual["survival"], log_reference=log_reference,
                log_actual=actual["log_survival"],
                relative_error=abs(actual["survival"]-reference)/reference,
                legacy=old, legacy_relative_error=None if old is None else abs(old-reference)/reference))
    for drift in (1., 10., 40., 1000.):
        reference, error = time_density_log_survival(1e-15, drift)
        actual = first_hit(1e-15, drift, 1., 1.)
        tails.append(dict(drift=drift, log_reference=reference,
            log_actual=actual["log_survival"], absolute_log_error=abs(reference-actual["log_survival"]),
            reference_relative_quadrature_estimate=error))
    tiny = first_hit(1e-300, 0., 1., 1.)
    tiny_ref = math.log(1e-300)+.5*math.log(2/math.pi)
    scaled_tiny = first_hit(1e-200, 0., 1e100, 1.)
    scaled_tiny_ref = math.log(1e-200)-math.log(1e100)+.5*math.log(2/math.pi)
    underflow = first_hit(1e-300, 0., 1e100, 1.)
    underflow_ref = math.log(1e-300)-math.log(1e100)+.5*math.log(2/math.pi)
    samples = [sample_counts(.001, 10., 1., .1, .1, .2,
                paths=1, seed=seed, max_events=1).tolist() for seed in range(5)]
    gates = [
        dict(name="small_gap_positive_and_negative_drift", passed=max(r["relative_error"] for r in rows) < 3e-12,
             criterion="15 near-boundary cases agree with 90-digit Decimal survival within 3e-12 relative"),
        dict(name="positive_drift_time_density_tail", passed=max(r["absolute_log_error"] for r in tails) < 2e-10,
             criterion="4 independent time-density tails agree within 2e-10 absolute log error"),
        dict(name="very_small_survival_log", passed=max(abs(tiny["log_survival"]-tiny_ref),
             abs(scaled_tiny["log_survival"]-scaled_tiny_ref),
             abs(underflow["log_survival"]-underflow_ref)) < 3e-13,
             criterion="dimensionless gaps through 1e-400 retain survival logs, including ratio underflow"),
        dict(name="event_budget_is_inclusive", passed=samples == [[1]]*5,
             criterion="five exact paths ending after one event accept max_events=1"),
    ]
    return dict(schema="hcsn_round8_tail_regression_v1", passed=all(g["passed"] for g in gates),
        frozen_source_commit="3a0e62c61b595576f16313c9b6016ec62cf8088b",
        environment=dict(numpy=np.__version__, scipy=scipy.__version__),
        decimal_reference_precision=90, small_gap_cases=rows, density_tail_cases=tails,
        tiny_gap=dict(actual_log=tiny["log_survival"], reference_log=tiny_ref,
            scaled_actual_log=scaled_tiny["log_survival"], scaled_reference_log=scaled_tiny_ref,
            underflow_actual_log=underflow["log_survival"], underflow_reference_log=underflow_ref),
        inclusive_budget_samples=samples, gates=gates,
        limitations=["This diagnostic is not a uniform float64 or interval-arithmetic proof.",
                     "Quadrature error estimates do not bound floating-point roundoff."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    source = Path(__file__).parent
    result["source_sha256"] = {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
        for name in ("event_kernel.py", "renewal.py", "tail_regression.py")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "gates": result["gates"]}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
