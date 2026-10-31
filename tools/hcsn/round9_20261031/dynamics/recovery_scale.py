"""Resolve a fast Erlang recovery law independently of the hit-time integral."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.integrate import quad_vec
from scipy.special import gammaincc, gammaln, ndtr

from .audit import load_source


PROTOCOL = dict(initial_gap=.8, reset_gap=.7, drift=1., sigma=.4, time=2.2, phases=2,
                recovery_means=[.5, .05, .005, .0005, .00005, .000005, .0000005],
                reference_terms=48, maximum_count_error=3e-10, maximum_recovery_gradient_error=3e-8)


def gamma_reference(mean):
    """Convolve closed IG CDF with Gamma density in x=rate*recovery.

    Recovery-mean derivative integrates -(x/phases)*first_hit_density. This
    uses neither the tested kernel nor its first-passage coordinate/gradient.
    """
    p = PROTOCOL
    rate = p["phases"] / mean
    total, limit = np.zeros(2), np.zeros(2)
    estimate, cutoff = 0., 0.
    for event in range(1, p["reference_terms"] + 1):
        gap = p["initial_gap"] + (event - 1) * p["reset_gap"]

        def passage(t):
            if t <= 0:
                return 0., 0.
            scale = p["sigma"] * math.sqrt(t)
            z = (p["drift"] * t - gap) / scale
            probability = float(ndtr(z) + math.exp(2 * p["drift"] * gap / p["sigma"]**2)
                                * ndtr(-(p["drift"] * t + gap) / scale))
            density = gap * math.exp(-.5 * z * z) / (scale * t * math.sqrt(2 * math.pi))
            return probability, density

        probability, density = passage(p["time"])
        limit += [probability, -(event - 1) * density]
        if event == 1:
            total[0] += probability
            continue
        shape = p["phases"] * (event - 1)
        log_gamma = float(gammaln(shape))
        maximum = shape + 16 * math.sqrt(shape) + 64
        upper = min(rate * p["time"], maximum)
        cutoff += float(gammaincc(shape, maximum))

        def integrand(x):
            if x <= 0:
                return np.zeros(2)
            probability, density = passage(p["time"] - x / rate)
            gamma_density = math.exp((shape - 1) * math.log(x) - x - log_gamma)
            return gamma_density * np.array([probability, -x * density / p["phases"]])

        points = sorted(set(x for x in [shape - 1] + [shape + k * math.sqrt(shape)
            for k in (-8, -4, -1, 0, 1, 4, 8, 16)] if 0 < x < upper))
        value, error = quad_vec(integrand, 0., upper, points=points,
                                epsabs=2e-13, epsrel=2e-12, limit=300)
        total += value
        estimate += error
    # A common tilt=1 Chernoff/geometric bound, conservatively dropping the
    # Erlang factors, bounds omitted count terms for every registered mean.
    kappa = 2 / (p["drift"] + math.hypot(p["drift"], math.sqrt(2) * p["sigma"]))
    ratio = math.exp(-kappa * p["reset_gap"])
    count_tail = math.exp(p["time"] - kappa * p["initial_gap"]) * ratio**p["reference_terms"] / (1 - ratio)
    return dict(expected_count=float(total[0]), recovery_mean_gradient=float(total[1]),
                zero_recovery_limit=dict(expected_count=float(limit[0]), recovery_mean_gradient=float(limit[1])),
                quadrature_error_estimate=float(estimate), integration_cutoff_bound=cutoff,
                count_tail_bound=count_tail, gradient_tail_certified=False)


def audit(source_root):
    _, renewal, source = load_source(source_root)
    rows = []
    p = PROTOCOL
    for mean in p["recovery_means"]:
        reference = gamma_reference(mean)
        actual = renewal.expected_count(p["initial_gap"], p["reset_gap"], p["drift"],
                                        p["sigma"], p["time"], mean, p["phases"])
        rows.append(dict(recovery_mean=mean, reference=reference, actual=actual,
                         count_error=abs(reference["expected_count"] - actual["expected_count"]),
                         gradient_error=abs(reference["recovery_mean_gradient"] - actual["gradient"]["recovery_mean"])))
    gates = [dict(name="recovery_scale_counts", passed=max(r["count_error"] for r in rows) < p["maximum_count_error"]),
             dict(name="recovery_scale_gradients", passed=max(r["gradient_error"] for r in rows) < p["maximum_recovery_gradient_error"])]
    return dict(schema="hcsn_round9_recovery_scale_v1", protocol=p, rows=rows, gates=gates,
                passed=all(g["passed"] for g in gates),
                source_sha256={name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                               for name in ("event_kernel.py", "renewal.py")},
                reference_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                limitation="Registered physical recovery scales; numerical estimates exclude roundoff and do not certify derivative tails.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record-baseline", action="store_true")
    args = parser.parse_args()
    result = audit(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(dict(gates=result["gates"], maximum_count_error=max(r["count_error"] for r in result["rows"]),
                         maximum_gradient_error=max(r["gradient_error"] for r in result["rows"])), indent=2))
    if not result["passed"] and not args.record_baseline:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
