"""Registered R12 mathematical audits; every attempt is immutable and metered."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback
import warnings

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import mpmath as mp
import numpy as np
import scipy
from scipy.integrate import quad

from experiments.hcsn_validation_r12_20261031.numerics import dynamics as d
from experiments.hcsn_validation_r12_20261031.numerics import pde, safe_hx
from experiments.hcsn_validation_r12_20261031.numerics.upstream import kernel, reference

HERE = Path(__file__).resolve().parent
mp.mp.dps = 70


def literal_cdf(x, mu, sigma, horizon):
    if horizon <= 0:
        return mp.mpf(0)
    scale = sigma * mp.sqrt(2 * horizon)
    return (mp.erfc((x + mu * horizon) / scale)
            + mp.exp(-2 * mu * x / sigma**2) * mp.erfc((x - mu * horizon) / scale)) / 2


def literal_count(*values):
    x, mu, sigma, horizon, reset, refractory = values
    return sum(literal_cdf(x + n * reset, mu, sigma, horizon - n * refractory)
               for n in range(16))


class Recorder:
    def __init__(self, out):
        self.out = out
        self.stream = (out / "cases.jsonl").open("x")
        self.rows = []

    def add(self, group, passed, *, expected_negative=False, **data):
        row = {"group": group, "passed": bool(passed),
               "expected_negative_control": expected_negative, **data}
        if "checks" in row:
            row["checks"] = {key: bool(value) for key, value in row["checks"].items()}
        line = json.dumps(row, allow_nan=False) + "\n"
        self.rows.append(row)
        self.stream.write(line)
        self.stream.flush()

    def raw(self, label, value):
        path = self.out / (label + ".json")
        with path.open("x") as stream:
            json.dump(value, stream, allow_nan=False)
        return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def scalar_checks(rec, protocol):
    gates, edges = protocol["gates"], protocol["bins"]
    for index, values in enumerate(protocol["first_hit_cases"]):
        x, mu, sigma, horizon = values
        actual = float(d.renewal.first_passage_cdf(*values))
        integral, error = quad(lambda t: d.hitting_density(t, x, mu, sigma), 0, horizon,
                               epsabs=2e-12, epsrel=2e-11)
        tol = gates["first_hit_atol"] + gates["first_hit_rtol"] * abs(integral)
        rec.add("first_hit_integral", abs(actual - integral) <= tol, case=values,
                analytic=actual, independent_integral=integral, error=abs(actual - integral),
                quad_error_estimate=error, tolerance=tol)
        expected = d.killed_functionals(x, mu, sigma, horizon, edges)
        moments = [quad(lambda y: y**n * float(d.renewal.killed_density(y, *values)),
                        0, np.inf, epsabs=2e-11, epsrel=2e-10)[0] for n in range(3)]
        rec.add("killed_moments", max(abs(expected[:3] - moments)) <= gates["killed_mass_atol"],
                case=values, analytic_moments=expected[:3].tolist(),
                density_integrals=moments, survival_plus_hit=moments[0] + actual)
        for y in (0.2, 0.8, 1.6):
            first, second = 0.37 * horizon, 0.63 * horizon
            composed, error = quad(lambda z: float(d.renewal.killed_density(z, x, mu, sigma, first))
                * float(d.renewal.killed_density(y, z, mu, sigma, second)),
                0, np.inf, epsabs=2e-12, epsrel=2e-10)
            direct = float(d.renewal.killed_density(y, x, mu, sigma, horizon))
            rec.add("killed_semigroup", abs(composed - direct) <= gates["semigroup_atol"],
                    case=values, y=y, direct=direct, integrated_composition=composed,
                    error=abs(composed - direct), quad_error_estimate=error)
        params = [mp.mpf(str(v)) for v in values]
        ref_jac = np.array([float(mp.diff(lambda q: literal_cdf(*[
            q if j == i else v for j, v in enumerate(params)]), params[i])) for i in range(4)])
        jac = d.first_hit_jacobian(*values)
        tol = gates["gradient_atol"] + gates["gradient_rtol"] * abs(ref_jac)
        rec.add("first_hit_all_parameter_gradient", np.all(abs(jac - ref_jac) <= tol),
                case=values, analytic=jac.tolist(), independent=ref_jac.tolist(),
                error=abs(jac - ref_jac).tolist(), tolerance=tol.tolist())
    for case in protocol["gradient"]["cases"]:
        values = [case[k] for k in protocol["gradient"]["order"]]
        params = [mp.mpf(str(v)) for v in values]
        ref_jac = np.array([float(mp.diff(lambda q: literal_count(*[
            q if j == i else v for j, v in enumerate(params)]), params[i])) for i in range(6)])
        jac = d.count_jacobian(**case)
        tol = gates["gradient_atol"] + gates["gradient_rtol"] * abs(ref_jac)
        rec.add("renewal_all_parameter_gradient", np.all(abs(jac - ref_jac) <= tol),
                case=case, analytic=jac.tolist(), independent=ref_jac.tolist(),
                error=abs(jac - ref_jac).tolist(), tolerance=tol.tolist())


def propagation_checks(rec, protocol):
    gates, edges = protocol["gates"], protocol["bins"]
    for ci, case in enumerate(protocol["successor_cases"]):
        reference_state = d.regenerative_successor(case, edges)
        rec.add("complete_successor_integral", abs(reference_state["mass"] - 1) <= gates["full_successor_mass_atol"],
                case=case, **reference_state)
        previous_error = None
        for gi, h in enumerate(protocol["pde"]["spacings"]):
            result = pde.solve(case, h, edges, regenerate=True)
            target = np.array(reference_state["active"])
            bins_error = float(np.sum(abs(np.array(result["active"])[3:] - target[3:])))
            count_error = abs(result["event_count"] - reference_state["expected_count"])
            recovery_error = abs(result["refractory_mass"] - reference_state["recovery"][0])
            metric = bins_error + count_error + recovery_error
            checks = {"mass": abs(result["accounted_mass"] - 1) <= gates["pde_mass_atol"],
                "positive": result["minimum_probability"] >= gates["pde_min_probability"],
                "upper_loss": result["upper_loss"] <= gates["pde_upper_loss_max"],
                "refinement": previous_error is None or metric <= gates["pde_refinement_factor"] * previous_error}
            if gi == len(protocol["pde"]["spacings"]) - 1:
                checks.update(count=count_error <= gates["pde_final_count_atol"],
                    bins=bins_error <= gates["pde_final_bins_l1"],
                    refractory=recovery_error <= gates["pde_final_refractory_atol"])
            rec.add("complete_successor_pde", all(checks.values()), case=case, spacing=h,
                    checks=checks, bins_l1=bins_error, count_error=count_error,
                    refractory_error=recovery_error, error_metric=metric,
                    previous_error_metric=previous_error,
                    raw=rec.raw(f"successor_{ci}_grid_{gi}", result))
            previous_error = metric
    for ci, spec in enumerate(protocol["moving_cases"]):
        case = {k: spec[k] for k in ("x", "mu", "sigma", "horizon")}
        measured = []
        for gi, h in enumerate(protocol["pde"]["spacings"]):
            result = pde.solve(case, h, edges, regenerate=False,
                               speed=spec["speed"], curvature=spec["curvature"])
            measured.append(result["event_count"])
            checks = {"mass": abs(result["accounted_mass"] - 1) <= gates["pde_mass_atol"],
                "positive": result["minimum_probability"] >= gates["pde_min_probability"],
                "upper_loss": result["upper_loss"] <= gates["pde_upper_loss_max"]}
            if spec["curvature"] == 0:
                exact = float(d.renewal.first_passage_cdf(case["x"], case["mu"] - spec["speed"], case["sigma"], case["horizon"]))
                if gi == 2:
                    checks["exact_linear_error"] = abs(result["event_count"] - exact) <= gates["pde_final_count_atol"]
            else:
                exact = None
            rec.add("moving_boundary_pde", all(checks.values()), case=spec, spacing=h,
                    measured=result["event_count"], exact_linear=exact, checks=checks,
                    raw=rec.raw(f"moving_{ci}_grid_{gi}", result))
        differences = np.abs(np.diff(measured))
        checks = {"successive_difference": differences[-1] <= gates["nonlinear_refinement_atol"],
                  "refinement": differences[-1] <= gates["pde_refinement_factor"] * differences[0]}
        stationary = float(d.renewal.first_passage_cdf(case["x"], case["mu"] - spec["speed"]
            - spec["curvature"] * case["horizon"], case["sigma"], case["horizon"]))
        rec.add("moving_boundary_refinement", all(checks.values()), case=spec,
                values=measured, differences=differences.tolist(), checks=checks,
                average_boundary_velocity_heuristic=stationary,
                heuristic_gap=stationary - measured[-1], rigorous_error_bound=False)


def financial_checks(rec, protocol):
    for state in protocol["hx"]["retain_historical_failure_states"]:
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            values, jac = kernel.evaluate(kernel.BASE, state, coordinate="log_distance")
        finite = bool(np.all(np.isfinite(values)) and np.all(np.isfinite(jac)))
        rec.add("historical_hx_extreme_state", finite, expected_negative=True, state=state,
                outputs=[str(v) for v in values], finite_values=int(np.isfinite(values).sum()),
                finite_jacobian=int(np.isfinite(jac).sum()), warnings=[str(v.message) for v in observed])
    for mode in ("float64", "mixed32", "float32"):
        for x in protocol["hx"]["reference_points"]:
            actual, jac = kernel.evaluate(kernel.BASE, x, coordinate="log_distance", mode=mode)
            params = kernel.BASE if mode == "float64" else kernel.BASE.astype(np.float32).astype(float)
            represented = x if mode == "float64" else float(np.float32(x))
            truth = np.asarray(reference.fields(params, represented, "log_distance"), float)
            derivative = reference.jacobian(params, represented, "log_distance")
            value_error = float(np.max(abs(actual - truth) / np.maximum(1, abs(truth))))
            jac_error = float(np.max(abs(jac - derivative) / np.maximum(1, abs(derivative))))
            value_gate = 2e-8 if mode == "float64" else 8e-7
            passed = value_error <= value_gate and jac_error <= 2e-5
            rec.add("full_hx_reference", passed, expected_negative=mode == "float32", mode=mode,
                    state=x, value_error=value_error, jacobian_error=jac_error,
                    value_gate=value_gate, jacobian_gate=2e-5, admitted_for_training=mode != "float32")
            if mode != "float32":
                new_values, new_jac = safe_hx.evaluate(kernel.BASE, x, mode=mode)
                rec.add("bounded_hx_identity", np.array_equal(actual, new_values) and np.array_equal(jac, new_jac), mode=mode, state=x)
    for mode, state in (("float64", -0.1), ("float64", 2.001), ("float64", 1e308), ("mixed32", 1e308), ("float32", 0.1)):
        try:
            safe_hx.evaluate(kernel.BASE, state, mode=mode)
            refused, message = False, None
        except (ValueError, ArithmeticError, FloatingPointError) as error:
            refused, message = True, str(error)
        rec.add("bounded_hx_refusal", refused, mode=mode, state=state, reason=message)


def gradient_pde_checks(rec, protocol):
    registration = json.loads((HERE / "GRADIENT_PROTOCOL.json").read_text())
    gates, names = registration["gates"], registration["parameter_order"]
    for case in protocol["gradient"]["cases"]:
        exact = d.count_jacobian(**case)
        errors = []
        for spacing in registration["spacings"]:
            estimates = []
            for epsilon in registration["central_steps"]:
                gradient = []
                for name in names:
                    plus = pde.solve(case | {name: case[name] + epsilon}, spacing,
                                     protocol["bins"], regenerate=True)
                    minus = pde.solve(case | {name: case[name] - epsilon}, spacing,
                                      protocol["bins"], regenerate=True)
                    gradient.append((plus["event_count"] - minus["event_count"]) / (2 * epsilon))
                estimates.append(np.asarray(gradient))
            tolerance = gates["gradient_atol"] + gates["gradient_rtol"] * abs(exact)
            stable_tolerance = gates["step_stability_atol"] + gates["step_stability_rtol"] * abs(exact)
            discrepancy = abs(estimates[-1] - exact)
            step_difference = abs(estimates[-1] - estimates[0])
            errors.append(float(np.max(discrepancy)))
            checks = {"independent_pde_gradient": np.all(discrepancy <= tolerance),
                      "step_halving": np.all(step_difference <= stable_tolerance)}
            rec.add("renewal_gradient_pde", all(checks.values()), case=case, spacing=spacing,
                    analytic=exact.tolist(), estimates=[e.tolist() for e in estimates],
                    discrepancy=discrepancy.tolist(), tolerance=tolerance.tolist(),
                    step_difference=step_difference.tolist(), checks=checks)
        rec.add("renewal_gradient_pde_refinement", errors[-1] <= gates["refinement_factor"] * errors[0],
                case=case, maximum_errors=errors, required_factor=gates["refinement_factor"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=("development", "formal"), default="development")
    parser.add_argument("--frozen-commit", default="")
    args = parser.parse_args()
    if args.stage == "formal" and (len(args.frozen_commit) != 40 or any(c not in "0123456789abcdef" for c in args.frozen_commit)):
        parser.error("Formal execution requires the actual 40-character pre-execution source commit")
    args.out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    paths = [HERE / "PROTOCOL.json", HERE / "GRADIENT_PROTOCOL.json", HERE / "UPSTREAM_VERIFIED.json", Path(d.renewal.__file__)]
    paths += sorted(HERE.glob("*.py")) + sorted((HERE / "upstream").glob("*.py"))
    freeze = {"stage": args.stage, "frozen_commit": args.frozen_commit or None,
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "mpmath": mp.__version__},
        "threads": {k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}
    (args.out / "FREEZE.json").write_text(json.dumps(freeze, indent=2) + "\n")
    snapshot = args.out / "sources"
    snapshot.mkdir()
    for path in paths:
        target = snapshot / str(path.relative_to(ROOT)).replace("/", "__")
        shutil.copyfile(path, target)
    recorder = Recorder(args.out)
    cpu, wall = time.process_time(), time.perf_counter()
    for function in (scalar_checks, propagation_checks, financial_checks, gradient_pde_checks):
        started = time.process_time()
        try:
            function(recorder, protocol)
        except Exception as error:
            recorder.add("audit_exception", False, phase=function.__name__, error=repr(error), traceback=traceback.format_exc())
        print(json.dumps({"phase": function.__name__, "cpu_seconds": time.process_time() - started}), flush=True)
    recorder.stream.close()
    unexpected = [r for r in recorder.rows if not r["passed"] and not r["expected_negative_control"]]
    negatives = [r for r in recorder.rows if not r["passed"] and r["expected_negative_control"]]
    summary = {"stage": args.stage, "success": not unexpected, "rows": len(recorder.rows),
        "unexpected_failed_rows": len(unexpected), "retained_negative_control_failures": len(negatives),
        "groups": {g: {"rows": len([r for r in recorder.rows if r["group"] == g]),
                       "passed": len([r for r in recorder.rows if r["group"] == g and r["passed"]])}
                   for g in sorted({r["group"] for r in recorder.rows})},
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
        "full_process_metering": "Use process receipt from parent runner; these counters exclude import time",
        "not_established": protocol["not_established"], "frozen_commit": args.frozen_commit or None}
    (args.out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "FAILURES.json").write_text(json.dumps(unexpected + negatives, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
