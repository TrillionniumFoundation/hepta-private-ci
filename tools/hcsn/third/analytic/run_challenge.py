"""Replay combined-parameter admission and independent analytic checks.

Historical evidence is read-only. New evidence is written beside this script.
The corner grid is an adversarial test, not a uniform-domain proof.
"""

from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
import hashlib
import io
import itertools
import json
import platform
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from analytic import HXModel, Parameters
from analytic.admissibility import boundary_cashflow, InadmissibleBoundaryError
from analytic.hx_model import HXBoundaryCandidate
from analytic.hx_precision import precision_boundary_equity
from analytic.hx_reference import boundary_from_quadrature, green_equity
from analytic import run_validation as original


NAMES = tuple(asdict(Parameters()))
LOWER = np.array([.04, .01, .08, 0., 0., 1e-4, .01, .5, 20.])
UPPER = np.array([.15, .2, .8, 1., .6, .1, 20., 10., 100.])
SEED = 301026


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def combinations():
    corners = [np.where(bits, UPPER, LOWER)
               for bits in itertools.product([False, True], repeat=len(NAMES))]
    random = np.random.default_rng(SEED).uniform(LOWER, UPPER, (200, len(NAMES)))
    for index, values in enumerate(np.vstack((corners, random))):
        yield index, Parameters(**dict(zip(NAMES, map(float, values))))


def challenge_candidates():
    points = np.r_[0., np.geomspace(1e-8, .01, 12), np.linspace(.02, 8., 50)]
    rows, rejected = [], []
    for index, params in combinations():
        row = dict(index=index, source="corner" if index < 512 else "random",
                   parameters=asdict(params))
        try:
            candidate = HXBoundaryCandidate(params)
        except ValueError as error:
            row.update(candidate_status="no_positive_boundary", candidate_error=str(error))
            try:
                HXModel(params)
            except ValueError:
                row.update(admitted=False, passed=True)
            else:
                row.update(admitted=True, passed=False)
            rows.append(row)
            continue
        equity = candidate.equity(points)
        negative = bool(np.min(equity) < -1e-7)
        monotone = bool(np.min(np.diff(equity)) >= -1e-7)
        row.update(boundary=candidate.boundary,
                   boundary_cashflow=boundary_cashflow(params, candidate.boundary),
                   boundary_second_derivative=candidate.boundary_taylor()[0],
                   equity_min=float(np.min(equity)),
                   equity_min_increment=float(np.min(np.diff(equity))),
                   candidate_status="negative_equity" if negative else "nonnegative_sample")
        try:
            checked = HXModel(params)
        except InadmissibleBoundaryError as error:
            row.update(admitted=False, rejection_reason=str(error))
            row["passed"] = bool(negative and row["boundary_cashflow"] > 0)
            rejected.append((index, params))
        else:
            f, g = checked.first_hit(points, params.maturity)
            row.update(admitted=True)
            row["passed"] = bool(not negative and monotone and np.all(np.isfinite(equity))
                                 and np.min(f) >= -2e-12 and np.max(f) <= 1+2e-12
                                 and np.min(g) >= -2e-12 and np.max(g-f) <= 2e-12)
        rows.append(row)
    return dict(seed=SEED, corner_count=512, random_count=200,
                parameters=list(NAMES), lower=LOWER.tolist(), upper=UPPER.tolist(),
                log_distances=points.tolist(), rows=rows,
                admitted=sum(row["admitted"] for row in rows),
                rejected_nonpositive=sum(row["candidate_status"] == "no_positive_boundary" for row in rows),
                rejected_negative_equity=len(rejected),
                passed=all(row["passed"] for row in rows)), rejected


def independent_rejections(rejected):
    points = np.array([0., 1e-8, 1e-5, .001, .01, .1, .5, 1.])
    rows = []
    for index, params in rejected:
        candidate = HXBoundaryCandidate(params)
        b_numeric = boundary_from_quadrature(candidate)
        b_precise, e_precise = precision_boundary_equity(params, points, digits=60)
        e_green = np.array([green_equity(candidate, x, b_numeric) for x in points])
        e_candidate = candidate.equity(points)
        errors = dict(boundary_vs_green=abs(candidate.boundary-b_numeric),
                      boundary_vs_mpmath60=abs(candidate.boundary-b_precise),
                      equity_vs_green=float(np.max(abs(e_candidate-e_green))),
                      equity_vs_mpmath60=float(np.max(abs(e_candidate-np.array(e_precise)))))
        rows.append(dict(index=index, log_distances=points.tolist(),
                         equity_candidate=e_candidate.tolist(), equity_green=e_green.tolist(),
                         equity_mpmath60=e_precise, errors=errors,
                         passed=bool(max(errors.values()) < 2e-7
                                     and np.min(e_precise) < -1e-7
                                     and np.min(e_green) < -1e-7)))
    return dict(methods=["literal A5/A7 mpmath 60 digits", "independent Green quadrature and free-boundary root"],
                tolerance=2e-7, rows=rows, passed=all(row["passed"] for row in rows))


def replay_original_checks():
    with redirect_stdout(io.StringIO()):
        record = dict(parameter_checks=original.validate_values(),
                      bvp_checks=original.validate_bvp(),
                      debt_pde_checks=original.validate_debt_pde(),
                      limit_checks=original.validate_limits(),
                      calibration_checks=original.validate_calibration(),
                      parameter_derivative_checks=original.validate_parameter_derivatives(),
                      taylor_overlap_checks=original.validate_taylor_overlap())
    record["passed"] = all(all(row["passed"] for row in value) if isinstance(value, list)
                           else value["passed"] for value in record.values())
    return record


def jax_admission_checks():
    """Small scalar-map JIT; no model training, data loading or accelerator use."""
    import jax
    jax.config.update("jax_enable_x64", True)
    import jax.numpy as jnp
    from analytic import jax_hx

    domain_matches = (np.array_equal(LOWER, jax_hx.LOWER)
                      and np.array_equal(UPPER, jax_hx.UPPER)
                      and NAMES == jax_hx.NAMES)
    values = np.array([list(asdict(params).values()) for _, params in combinations()])
    theta = jnp.asarray(values, jnp.float64)
    observed = np.asarray(jax.jit(jax.vmap(jax_hx.boundary))(theta))
    expected = []
    host_rejection_count = 0
    for _, params in combinations():
        try:
            jax_hx.validate_parameters(params)
            expected.append(HXModel(params).boundary)
        except ValueError:
            expected.append(np.nan)
            host_rejection_count += 1
    expected = np.asarray(expected)
    mask = np.isfinite(expected)
    mask_equal = bool(np.array_equal(np.isfinite(observed), mask))
    error = float(np.max(abs(observed[mask]-expected[mask])))
    base = jnp.asarray(list(asdict(Parameters()).values()), jnp.float64)
    derivative = np.asarray(jax.jit(jax.jacfwd(jax_hx.boundary))(base))
    fd = []
    for i in range(len(base)):
        h = max(abs(float(base[i])), .01)*1e-5
        direction = np.eye(len(base))[i]*h
        plus = Parameters(**dict(zip(NAMES, map(float, np.asarray(base)+direction))))
        minus = Parameters(**dict(zip(NAMES, map(float, np.asarray(base)-direction))))
        fd.append((HXModel(plus).boundary-HXModel(minus).boundary)/(2*h))
    fd = np.asarray(fd)
    grad_error = float(np.max(abs(derivative-fd)/np.maximum(1., abs(fd))))
    selected = [(i, p) for i, p in combinations() if i in [128, 130, 131, 146, 147]]
    points = np.array([0., 1e-8, 1e-5, .001, .01, .1, 1.])
    evaluate = jax.jit(jax.vmap(lambda t: jax.vmap(lambda x: jax_hx.equity_x(x, t))(jnp.asarray(points))))
    observed_equity = np.asarray(evaluate(jnp.asarray([list(asdict(p).values()) for _, p in selected])))
    regression = []
    for (index, params), e_jax in zip(selected, observed_equity):
        model = HXModel(params)
        b90, e90 = precision_boundary_equity(params, points, digits=90)
        b_jax = observed[index]
        errors = dict(numpy_boundary=abs(model.boundary-b90), jax_boundary=abs(b_jax-b90),
                      numpy_equity=float(np.max(abs(model.equity(points)-e90))),
                      jax_equity=float(np.max(abs(e_jax-e90))))
        regression.append(dict(index=index, log_distances=points.tolist(), errors_vs_mpmath90=errors,
                               passed=bool(max(errors.values()) < 2e-7)))
    return dict(jax_version=jax.__version__, precision="float64", case_count=len(values),
                execution_backend=jax.default_backend(), devices=[str(device) for device in jax.devices()],
                declared_numeric_domain_matches=bool(domain_matches),
                host_rejection_count=host_rejection_count, admission_mask_matches=mask_equal,
                accepted_max_boundary_abs_error=error, parameter_gradient=derivative.tolist(),
                finite_difference=fd.tolist(), gradient_scaled_error=grad_error,
                near_singular_regression=regression,
                passed=bool(domain_matches and mask_equal and error < 2e-7 and grad_error < 2e-6
                            and all(row["passed"] for row in regression)))


def main():
    started = time.perf_counter()
    history_paths = [ROOT/"analytic/validation_results.json", ROOT/"analytic/jax_validation_results.json",
                     ROOT/"next/full_kernel/validation_results.json", ROOT/"next/full_kernel/join_results.json"]
    old_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in history_paths}
    challenge, rejected = challenge_candidates()
    result = dict(schema="hepta.hcsn.combined_parameter_admission.v1",
                  interpretation="Necessary local admission test plus finite adversarial samples; not a global stopping proof",
                  python=platform.python_version(), numpy=np.__version__,
                  environment=dict(platform=platform.platform(), machine=platform.machine(),
                                   execution_location="Current task CPU runtime; not a verified dot-host run"),
                  counterexample_mechanism="Eq12 gives E=E_x=0 but positive boundary cashflow implies E_xx<0",
                  combined_parameters=challenge,
                  independent_rejections=independent_rejections(rejected),
                  original_checks=replay_original_checks(),
                  historical_evidence_sha256=old_hashes)
    if "--with-jax" in sys.argv:
        result["jax_admission"] = jax_admission_checks()
    else:
        result["jax_admission"] = dict(status="not_run", passed=None)
    result["historical_evidence_unchanged"] = all(sha256(ROOT/name) == digest for name, digest in old_hashes.items())
    sources = [ROOT/"analytic/admissibility.py", ROOT/"analytic/hx_model.py", ROOT/"analytic/jax_hx.py",
               ROOT/"analytic/hx_precision.py", ROOT/"analytic/hx_reference.py", Path(__file__)]
    result["source_sha256"] = {str(path.relative_to(ROOT)): sha256(path) for path in sources}
    result["elapsed_seconds"] = time.perf_counter()-started
    result["all_executed_checks_passed"] = bool(challenge["passed"]
        and result["independent_rejections"]["passed"] and result["original_checks"]["passed"]
        and result["historical_evidence_unchanged"] and result["jax_admission"]["passed"] is not False)
    result["complete_with_jax"] = bool(result["all_executed_checks_passed"] and result["jax_admission"]["passed"])
    destination = HERE/("results.json" if "--with-jax" in sys.argv else "scipy_results.json")
    destination.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"file": destination.name, "admitted": challenge["admitted"],
                      "rejected_nonpositive": challenge["rejected_nonpositive"],
                      "rejected_negative_equity": challenge["rejected_negative_equity"],
                      "passed": result["all_executed_checks_passed"],
                      "jax": result["jax_admission"], "elapsed_seconds": result["elapsed_seconds"]}, indent=2))
    if not result["all_executed_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
