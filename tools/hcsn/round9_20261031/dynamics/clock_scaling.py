"""Physical clock covariance and finite-phase recovery semigroup checks."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from tools.hcsn.round8_20261031.event_dynamics.event_kernel import discounted_hit, first_hit
from tools.hcsn.round8_20261031.event_dynamics.generator import erlang_recovery
from tools.hcsn.round8_20261031.event_dynamics.renewal import expected_count


def audit():
    base = [.8, .7, 1., .001, 3., .5]
    reference = expected_count(*base)
    f_reference = first_hit(.8, 1., .001, 3.)["probability"]
    g_reference = discounted_hit(.8, 1., .001, 3., .7)["value"]
    rows = []
    for scale in (.01, .1, 1., 10., 100.):
        # The same law written with a physical clock stretched by scale.
        parameters = [.8, .7, 1. / scale, .001 / math.sqrt(scale), 3. * scale, .5 * scale]
        actual = expected_count(*parameters)
        f = first_hit(.8, parameters[2], parameters[3], parameters[4])["probability"]
        g = discounted_hit(.8, parameters[2], parameters[3], parameters[4], .7 / scale)["value"]
        gradient = actual["gradient"].copy()
        gradient["drift"] /= scale
        gradient["sigma"] /= math.sqrt(scale)
        gradient["recovery_mean"] *= scale
        rows.append(dict(clock_scale=scale, parameters=parameters, count=actual["expected_count"],
                         count_error=abs(actual["expected_count"] - reference["expected_count"]),
                         first_hit_error=abs(f - f_reference), discounted_value_error=abs(g - g_reference),
                         gradient_in_original_units=gradient,
                         gradient_error={name: abs(value - reference["gradient"][name]) for name, value in gradient.items()}))
    exact = erlang_recovery(.5, 2, 3.)
    recovery = []
    for substeps in (1, 2, 4, 8, 16, 32, 64):
        composed = np.linalg.matrix_power(erlang_recovery(.5, 2, 3. / substeps), substeps)
        recovery.append(dict(substeps=substeps, interval=3. / substeps,
                             maximum_probability_error=float(np.max(np.abs(composed - exact)))))
    gates = [dict(name="clock_value_covariance", passed=max(max(row[k] for k in
             ("count_error", "first_hit_error", "discounted_value_error")) for row in rows) < 3e-11),
             dict(name="clock_gradient_covariance", passed=max(max(row["gradient_error"].values()) for row in rows) < 3e-9),
             dict(name="recovery_semigroup_refinement", passed=max(row["maximum_probability_error"] for row in recovery) < 2e-14)]
    source = Path(__file__).resolve().parents[2] / "round8_20261031/event_dynamics"
    return dict(schema="hcsn_round9_physical_clock_v1", reference=reference, rows=rows, recovery=recovery,
                gates=gates, passed=all(g["passed"] for g in gates),
                source_sha256={name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                               for name in ("event_kernel.py", "renewal.py", "generator.py")},
                limitation="Clock covariance and finite-phase semigroup identities do not establish voltage-grid convergence.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result["gates"], indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
