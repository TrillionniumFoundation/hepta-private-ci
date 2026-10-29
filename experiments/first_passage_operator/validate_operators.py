"""Run the fixed numerical protocol against independent integration and QVI."""

from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad
from scipy.stats import invgauss, levy, norm

from .free_boundary import NaturalSpikeSpec, optimal_value, solve_boundary, solve_grid_qvi
from .operators import RegenerativeSpec, apply_value, operator_features

HERE = Path(__file__).resolve().parent


def _cdf(distance, mu, sigma, duration):
    if duration <= 0:
        return 0.0
    scale = distance * distance / (sigma * sigma)
    if mu == 0:
        return float(levy.cdf(duration, scale=scale))
    return float(invgauss.cdf(duration, sigma*sigma/(distance*abs(mu)), scale=scale)
                 * (math.exp(-2*mu*distance/sigma**2) if mu > 0 else 1.0))


def _density(distance, mu, sigma, duration):
    if duration <= 0:
        return 0.0
    return math.exp(math.log(distance/sigma) - 0.5*math.log(2*math.pi)
                    - 1.5*math.log(duration)
                    - (distance+mu*duration)**2/(2*sigma*sigma*duration))


def _killed_transform(distance, mu, sigma, duration, decay):
    if duration == 0:
        return math.exp(-decay*distance)
    variance = sigma*sigma*duration
    scale = math.sqrt(variance)
    means = [distance+mu*duration, -distance+mu*duration]
    terms = [math.exp(-decay*m+0.5*decay*decay*variance)
             * norm.cdf((m-decay*variance)/scale) for m in means]
    return terms[0]-math.exp(-2*mu*distance/sigma**2)*terms[1]


def reference_features(spec, distance, horizon, active_decays, refractory_decays):
    """Adaptive time integration, with independent normal and IG expressions."""
    count = int(math.ceil(horizon/spec.refractory))
    active = np.array([_killed_transform(distance, spec.mu, spec.sigma, horizon, z)
                       for z in active_decays])
    refractory = np.zeros(len(refractory_decays))
    events, discounted_events = 0.0, 0.0
    terms = [(distance+n*spec.reset, n*spec.refractory) for n in range(count)]
    for dn, shift in terms:
        hi, lo = horizon-shift, max(0.0, horizon-shift-spec.refractory)
        events += _cdf(dn, spec.mu, spec.sigma, hi)
        discounted_events += quad(lambda v: math.exp(-spec.discount*(shift+v))
                                  * _density(dn, spec.mu, spec.sigma, v),
                                  0, hi, epsabs=2e-12, epsrel=2e-12)[0]
        for j, z in enumerate(active_decays):
            width = horizon-shift-spec.refractory
            if width > 0:
                active[j] += quad(lambda v: _density(dn, spec.mu, spec.sigma, v)
                                  * _killed_transform(spec.reset, spec.mu, spec.sigma, width-v, z),
                                  0, width, epsabs=2e-12, epsrel=2e-12)[0]
        for j, z in enumerate(refractory_decays):
            refractory[j] += quad(lambda v: _density(dn, spec.mu, spec.sigma, v)
                                  * math.exp(-z*(shift+spec.refractory+v-horizon)),
                                  lo, hi, epsabs=2e-12, epsrel=2e-12)[0]
    def active_probability(u):
        ref_mass = sum(_cdf(dn, spec.mu, spec.sigma, u-shift)
                       - _cdf(dn, spec.mu, spec.sigma, u-shift-spec.refractory)
                       for dn, shift in terms)
        return math.exp(-spec.discount*u)*(1-ref_mass)
    active_time = quad(active_probability, 0, horizon, epsabs=2e-11, epsrel=2e-11,
                       points=[shift for _, shift in terms if 0 < shift < horizon], limit=256)[0]
    return {"features": np.r_[active, refractory], "expected_events": events,
            "discounted_events": discounted_events, "discounted_active_time": active_time}


def semigroup_check(spec, distance, first_time, second_time, active_decays, refractory_decays):
    """Integrate P_t(P_s g) over active AND unreleased refractory states.

    The first interval is shorter than refractory duration, so its exact
    transition consists only of a killed density and a first-hit clock measure.
    The second interval permits repeated emissions and releases.
    """
    if not 0 < first_time < spec.refractory:
        raise ValueError("first interval must be inside one refractory period")
    y_max = max(distance, spec.reset)+max(spec.mu, 0)*first_time+12*spec.sigma*math.sqrt(first_time)
    nodes, weights = np.polynomial.legendre.leggauss(160)
    y = y_max*(nodes+1)/2
    scale = spec.sigma*math.sqrt(first_time)
    density = (norm.pdf(y, distance+spec.mu*first_time, scale)
               - math.exp(-2*spec.mu*distance/spec.sigma**2)
               * norm.pdf(y, -distance+spec.mu*first_time, scale))
    active_weight = y_max*weights*density/2
    etas = spec.refractory-first_time/2+first_time*nodes/2
    ref_weight = first_time*weights/2*np.array([
        _density(distance, spec.mu, spec.sigma, first_time-spec.refractory+eta) for eta in etas])
    basis_weights = np.linspace(-0.4, 0.7, len(active_decays)+len(refractory_decays))
    active_values = [apply_value(operator_features(
        spec, state, second_time, active_decays=active_decays, refractory_decays=refractory_decays,
        quadrature_order=192), basis_weights, running_reward=0.6, event_reward=-0.5) for state in y]
    ref_values = [apply_value(operator_features(
        spec, spec.reset, second_time, pending_refractory=eta,
        active_decays=active_decays, refractory_decays=refractory_decays,
        quadrature_order=192), basis_weights, running_reward=0.6, event_reward=-0.5) for eta in etas]
    prefix = operator_features(spec, distance, first_time, active_decays=active_decays,
                               refractory_decays=refractory_decays, quadrature_order=192)
    composition = (0.6*prefix["discounted_active_time"]-0.5*prefix["discounted_events"]
                   + math.exp(-spec.discount*first_time)*(active_weight@active_values+ref_weight@ref_values))
    direct = apply_value(operator_features(
        spec, distance, first_time+second_time, active_decays=active_decays,
        refractory_decays=refractory_decays, quadrature_order=192), basis_weights,
        running_reward=0.6, event_reward=-0.5)
    return {"direct": direct, "composition": float(composition),
            "absolute_error": float(abs(composition-direct)),
            "outer_mass_defect": float(np.sum(active_weight)+np.sum(ref_weight)-1)}


def run():
    start = time.perf_counter()
    protocol_bytes = (HERE/"NUMERICAL_PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    rng = np.random.default_rng(protocol["seed"])
    az, rz = protocol["active_decays"], protocol["refractory_decays"]
    domain = protocol["operator_domain"]
    operator_rows = []
    for index in range(protocol["operator_cases"]):
        values = {k: float(rng.uniform(*v)) for k, v in domain.items() if k != "discount"}
        q = domain["discount"][index % len(domain["discount"])]
        spec = RegenerativeSpec(values["mu"], values["sigma"], values["reset"], values["refractory"], q)
        arguments = (spec, values["distance"], values["horizon"])
        base = operator_features(*arguments, active_decays=az, refractory_decays=rz, quadrature_order=96)
        fine = operator_features(*arguments, active_decays=az, refractory_decays=rz, quadrature_order=192)
        reference = reference_features(*arguments, az, rz)
        operator_rows.append({"index": index, "spec": asdict(spec), "distance": values["distance"],
                              "horizon": values["horizon"],
                              "feature_reference_error": float(np.max(np.abs(fine["features"]-reference["features"]))),
                              "feature_refinement_error": float(np.max(np.abs(fine["features"]-base["features"]))),
                              "default_feature_reference_error": float(np.max(np.abs(base["features"]-reference["features"]))),
                              "event_reference_error": max(abs(fine[k]-reference[k]) for k in
                                                           ["expected_events", "discounted_events"]),
                              "occupation_reference_error": abs(fine["discounted_active_time"]-reference["discounted_active_time"]),
                              "mass_quad_error": abs(fine["mass_quadrature_defect"]),
                              "features": fine["features"].tolist(),
                              "expected_events": fine["expected_events"]})
    semigroup_rows = []
    for index in range(protocol["semigroup_cases"]):
        spec = RegenerativeSpec(-0.4-0.1*index, 0.35+0.05*index, 0.4+0.1*index, 0.15, 0.2+0.1*index)
        semigroup_rows.append(semigroup_check(spec, 0.12+0.04*index, 0.06, 0.37, az, rz))
    bd = protocol["boundary_domain"]
    boundary_rows = []
    for index in range(protocol["boundary_cases"]):
        values = {k: float(rng.uniform(*v)) for k, v in bd.items()}
        spec = NaturalSpikeSpec(values["mu"], values["sigma"], values["reset"], values["refractory"],
                                values["discount"], values["reset"]+values["cost_minus_reset"])
        result = solve_boundary(spec)
        b, lam = result["boundary"], result["lambda"]
        state = np.linspace(spec.reset-8/lam, b, 512)
        gap = optimal_value(spec, state)-(state-spec.spike_cost+result["beta"]*result["reset_value"])
        gradient_errors = {}
        for name, exact in result["boundary_gradients"].items():
            step = 1e-5*max(1, abs(getattr(spec, name)))
            high = solve_boundary(replace(spec, **{name: getattr(spec, name)+step}))["boundary"]
            low = solve_boundary(replace(spec, **{name: getattr(spec, name)-step}))["boundary"]
            gradient_errors[name] = abs((high-low)/(2*step)-exact)/max(1, abs(exact))
        row = {"index": index, "spec": asdict(spec), **result,
               "minimum_obstacle_gap": float(np.min(gap)), "gradient_relative_errors": gradient_errors}
        if index < protocol["boundary_gates"]["grid_cases"]:
            grids = []
            for spacing in protocol["boundary_gates"]["grid_spacings"]:
                grid = solve_grid_qvi(spec, spacing=spacing, lower=spec.reset-14/lam,
                                      upper=spec.spike_cost+4/lam)
                grids.append({k: v for k, v in grid.items() if k not in {"state", "value", "stop"}})
            row["grid_refinements"] = grids
            row["fine_boundary_spacing_error"] = abs(grids[-1]["boundary"]-b)/grids[-1]["spacing"]
            row["fine_value_relative_error"] = abs(grids[-1]["reset_value"]-result["reset_value"])/result["reset_value"]
        boundary_rows.append(row)
    summary = {
        "maximum_feature_reference_error": max(r["feature_reference_error"] for r in operator_rows),
        "maximum_default_feature_reference_error": max(r["default_feature_reference_error"] for r in operator_rows),
        "maximum_event_reference_error": max(r["event_reference_error"] for r in operator_rows),
        "maximum_occupation_reference_error": max(r["occupation_reference_error"] for r in operator_rows),
        "maximum_mass_quad_error": max(r["mass_quad_error"] for r in operator_rows),
        "maximum_semigroup_error": max(r["absolute_error"] for r in semigroup_rows),
        "maximum_matching_error": max(max(abs(r["smooth_fit_residual"]), abs(r["value_matching_residual"])) for r in boundary_rows),
        "minimum_obstacle_gap": min(r["minimum_obstacle_gap"] for r in boundary_rows),
        "maximum_gradient_relative_error": max(max(r["gradient_relative_errors"].values()) for r in boundary_rows),
        "maximum_grid_value_relative_error": max(r.get("fine_value_relative_error", 0) for r in boundary_rows),
        "maximum_grid_boundary_spacing_error": max(r.get("fine_boundary_spacing_error", 0) for r in boundary_rows),
        "maximum_grid_bellman_residual": max(g["bellman_residual"] for r in boundary_rows for g in r.get("grid_refinements", [])),
    }
    og, bg = protocol["operator_gates"], protocol["boundary_gates"]
    gates = {
        "operator_features": summary["maximum_feature_reference_error"] < og["independent_feature_max_abs_error"],
        "default_operator_features": summary["maximum_default_feature_reference_error"] < og["independent_feature_max_abs_error"],
        "events": summary["maximum_event_reference_error"] < og["event_max_abs_error"],
        "occupation": summary["maximum_occupation_reference_error"] < og["occupation_max_abs_error"],
        "mass": summary["maximum_mass_quad_error"] < og["mass_quad_max_abs_error"],
        "semigroup": summary["maximum_semigroup_error"] < og["semigroup_max_abs_error"],
        "matching": summary["maximum_matching_error"] < bg["matching_max_abs_error"],
        "obstacle": summary["minimum_obstacle_gap"] >= bg["qvi_gap_minimum"],
        "implicit_gradients": summary["maximum_gradient_relative_error"] < bg["implicit_gradient_relative_error"],
        "grid_value": summary["maximum_grid_value_relative_error"] < bg["grid_value_max_relative_error"],
        "grid_boundary": summary["maximum_grid_boundary_spacing_error"] < bg["grid_boundary_spacing_units"],
        "grid_residual": summary["maximum_grid_bellman_residual"] < bg["bellman_max_abs_residual"],
    }
    gates = {key: bool(value) for key, value in gates.items()}
    result = {"schema": "hepta.regenerative-operator.numerical-validation.v1",
              "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
              "source_sha256": {p: hashlib.sha256((HERE/p).read_bytes()).hexdigest() for p in
                                ["operators.py", "free_boundary.py", "validate_operators.py"]},
              "summary": summary, "gates": gates, "passed": all(gates.values()),
              "operator_cases": operator_rows, "semigroup_cases": semigroup_rows,
              "boundary_cases": boundary_rows, "wall_seconds": time.perf_counter()-start}
    output = HERE/"NUMERICAL_VALIDATION.json"
    if output.exists():
        raise FileExistsError("retain the first fixed-grid result; choose an explicitly versioned subsequent run")
    output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+'\n')
    print(json.dumps({"summary": summary, "gates": gates, "passed": result["passed"],
                      "wall_seconds": result["wall_seconds"]}, sort_keys=True))
    return result


if __name__ == "__main__":
    if not run()["passed"]:
        raise SystemExit(1)
