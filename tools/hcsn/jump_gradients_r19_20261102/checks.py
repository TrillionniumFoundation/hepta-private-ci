"""Predeclared independent checks for analytic actual-solver derivatives."""

import copy
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import scipy
from scipy.integrate import solve_ivp

from ..continuous_task_r18_20261101.task import DEFAULT, payoff
from ..continuous_task_r18_20261101.positive_reference import heat
from . import capture, coordinates as co, directional, global_reference, tangent, training


ROOT = Path(__file__).parent


def error(a, b):
    return float(np.max(abs(a - b) / (1 + abs(b))))


def left_error(a, b):
    return max(error(a[key], b[key]) for key in a)


def heat_ode(solution, mode):
    """Independent scalar Fourier heat/tangent ODE of the linear-hat interpolant."""
    cfg, intervals = solution["config"], len(solution["x"]) - 1
    dt, sigma, width = solution["dt"], cfg["sigma"], cfg["upper"] - cfg["lower"]
    frequencies = (mode + 2 * intervals * np.arange(-3, 4)) * np.pi / width
    initial = np.r_[np.sinc((mode + 2 * intervals * np.arange(-3, 4)) / (2 * intervals)) ** 2, np.zeros(7)]
    decay = .5 * sigma ** 2 * frequencies ** 2
    def rhs(_, y):
        return np.r_[-decay * y[:7], -decay * y[7:] - 2 * decay * y[:7]]
    ode = solve_ivp(rhs, (0., dt), initial, t_eval=[dt], method="DOP853", rtol=2e-12, atol=2e-14)
    if not ode.success:
        raise RuntimeError(ode.message)
    cosine = np.cos(mode * np.pi * (solution["x"] - cfg["lower"]) / width)
    dop = tangent.density_tangent(cfg, intervals, dt, solution["operator"]["quadrature_nodes_per_half_hat"])
    return dict(mode=mode, value_error=error(heat(cosine, solution["operator"]), cosine * ode.y[:7, -1].sum()),
        tangent_error=error(heat(cosine, dop), cosine * ode.y[7:, -1].sum()),
        omitted_alias_log_decay=float(-.5 * sigma ** 2 * (np.pi * (8 * intervals - mode) / width) ** 2 * dt),
        ode_evaluations=ode.nfev)


def special_cases():
    raw = co.encode(DEFAULT); cfg = co.decode(raw)
    dx, dt = .125, .02
    cases = []
    # Construct an exact first-admission STOP/RESET tie, not an outcome search.
    grid = np.linspace(cfg["lower"], cfg["upper"], 65)
    reward = payoff(cfg, grid)
    cell = int(np.argmin(abs(grid - .25)))
    at_reset = np.array([np.interp(cfg["reset_x"], grid, row) for row in reward])
    tie_cfg = copy.deepcopy(cfg)
    no_reset_left = capture.solve(cfg, dx, dt)["first_left_limit"]
    tie_cfg["reset_fee"][0] = np.asarray(cfg["content_transition"])[0] @ at_reset - cfg["recovery_cost"] * cfg["recovery"] - no_reset_left[0, cell]
    cases.append(("right_jump_stop_reset_tie", co.encode(tie_cfg), 3))
    # If c=max Lg, g is an obstacle solution and a maximizer is biactive.
    curvature = np.c_[2 * (reward[:, 1] - reward[:, 0]), np.diff(reward, 2, axis=1), 2 * (reward[:, -2] - reward[:, -1])]
    tie_cfg = copy.deepcopy(cfg)
    tie_cfg["wait_cost"] = float(np.max(.5 * cfg["sigma"] ** 2 / dx ** 2 * curvature))
    cases.append(("left_lcp_biactive_wait_stop", co.encode(tie_cfg), 1))
    knot = raw.copy(); knot[5] = .5
    cases.append(("reset_interpolation_knot", knot, 5))
    output = []
    for name, base, coordinate in cases:
        s = capture.solve(co.decode(base), dx, dt)
        rejected = False
        try:
            tangent.jump(s, base)
        except co.Nondifferentiable:
            rejected = True
        directions = []
        for sign in (1., -1.):
            vector = np.eye(co.P)[coordinate] * sign
            analytic = directional.solve(s, base, vector)
            perturbed = capture.solve(co.decode(base + 1e-6 * vector), dx, dt)
            fd = (perturbed["values"] - s["values"]) / 1e-6
            left_fd = {key: (perturbed["left_limits"][key] - s["left_limits"][key]) / 1e-6 for key in s["left_limits"]}
            directions.append(dict(sign=sign, right_error=error(analytic["derivative"], fd),
                left_error=left_error(analytic["left_derivatives"], left_fd),
                maximum_directional_derivative=float(np.max(abs(analytic["derivative"])))))
        plus = directional.solve(s, base, np.eye(co.P)[coordinate])["derivative"]
        minus = directional.solve(s, base, -np.eye(co.P)[coordinate])["derivative"]
        output.append(dict(name=name, ordinary_rejected=rejected, coordinate=co.NAMES[coordinate], directions=directions,
                           nonodd_directionality=float(np.max(abs(plus + minus)))))
    s = capture.solve(cfg, dx, dt); g = tangent.jump(s, raw)["jacobian"]
    knot_rejected = False
    try:
        co.query(s, g, 15, 0, .25)
    except co.Nondifferentiable:
        knot_rejected = True
    i = int(np.argmin(abs(s["x"] - .25))); values = s["values"][15, 0]
    slopes = [(values[i] - values[i - 1]) / dx, (values[i + 1] - values[i]) / dx]
    state = dict(ordinary_knot_rejected=knot_rejected, state=.25, left_slope=float(slopes[0]), right_slope=float(slopes[1]),
                 clarke_interval=[float(min(slopes)), float(max(slopes))], reason="Finite linear interpolant; no fabricated unique state derivative at knot")
    time = co.time_contract(s, .2, -1.5, 1)
    off_lattice = []
    prior = sys.getprofile()
    for key in ("recovery", "horizon"):
        config = copy.deepcopy(cfg); config[key] += 1e-6
        try:
            capture.solve(config, dx, dt)
        except ValueError as exception:
            off_lattice.append(dict(coordinate=key, rejected=True, reason=str(exception)))
        else:
            raise RuntimeError("Off-lattice timing change was silently differentiated")
    if sys.getprofile() is not prior:
        raise RuntimeError("Canonical capture failed to restore prior profiler on error")
    binding = []
    mismatch = raw.copy(); mismatch[0] += .01
    positive = capture.reference(cfg, dx, dt)
    for name, action in (("jump_raw_mismatch", lambda: tangent.jump(s, mismatch)),
                         ("positive_raw_mismatch", lambda: tangent.positive(positive, mismatch)),
                         ("directional_raw_mismatch", lambda: directional.solve(s, mismatch, np.eye(co.P)[0])),
                         ("negative_query_index", lambda: co.query(s, g, -1, 0, .17))):
        try:
            action()
        except ValueError as exception:
            binding.append(dict(name=name, rejected=True, reason=str(exception)))
        else:
            raise RuntimeError(f"Unbound derivative request accepted: {name}")
    positive16 = capture.positive_reference.solve(cfg, dx, dt, nodes=16)
    jac16 = tangent.positive(positive16, raw)["jacobian"][..., 0]
    offset = np.eye(co.P)[0] * 5e-6
    plus16, minus16 = (capture.positive_reference.solve(co.decode(raw + sign * offset), dx, dt, nodes=16) for sign in (1, -1))
    fd16 = (plus16["values"] - minus16["values"]) / 1e-5
    return dict(corners=output, query_state=state, time_contract=time, off_lattice=off_lattice, profiler_restored=True,
                binding_rejections=binding, quadrature16_sigma_error=error(jac16, fd16))


def run(output):
    output.mkdir(exist_ok=False)
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for name, digest in freeze["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed frozen source: {name}")
    for entry in json.loads((ROOT / "DEPENDENCIES.json").read_text())["files"]:
        path = ROOT.parents[2] / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Changed canonical dependency: {entry['path']}")
    started, wall = time.process_time(), time.perf_counter()
    records, ode_records, global_records, query_records, snapshots = [], [], [], [], []
    coverage = {engine: {name: 0 for name in co.NAMES} for engine in ("jump", "positive")}
    for sigma in protocol["sigma_profiles"]:
        raw = co.encode(DEFAULT); raw[0] = np.log(sigma)
        for dx, dt in protocol["meshes"]:
            config = co.decode(raw)
            s, p = capture.solve(config, dx, dt), capture.reference(config, dx, dt)
            j, r = tangent.jump(s, raw), tangent.positive(p, raw)
            if dx == protocol["meshes"][0][0]:
                independent = global_reference.solve(s)
                global_records.append(dict(sigma=sigma, dx=dx, dt=dt,
                    right_errors=[error(j["jacobian"][..., k], independent["jacobian"][..., k]) for k in range(co.P)],
                    left_errors=[left_error({t: a[..., k] for t, a in j["left_jacobians"].items()}, {t: a[..., k] for t, a in independent["left_jacobians"].items()}) for k in range(co.P)],
                    residual=independent["maximum_equation_residual"], equations=independent["equations"], nonzeros=independent["nonzeros"]))
            for mode in (1, 3, 11):
                ode_records.append(dict(sigma=sigma, dx=dx, dt=dt, **heat_ode(p, mode)))
            for coordinate, name in enumerate(co.NAMES):
                row = dict(sigma=sigma, dx=dx, dt=dt, coordinate=name, finite_difference=[])
                admitted = {"jump": True, "positive": True}
                for step in protocol["fd_steps"]:
                    offset = np.eye(co.P)[coordinate] * step
                    plus, minus = capture.solve(co.decode(raw + offset), dx, dt), capture.solve(co.decode(raw - offset), dx, dt)
                    pp, pm = capture.reference(co.decode(raw + offset), dx, dt), capture.reference(co.decode(raw - offset), dx, dt)
                    fd = (plus["values"] - minus["values"]) / (2 * step)
                    fl = {t: (plus["left_limits"][t] - minus["left_limits"][t]) / (2 * step) for t in plus["left_limits"]}
                    fpr = (pp["values"] - pm["values"]) / (2 * step)
                    js, jm = tangent.signature(plus), tangent.signature(minus)
                    ps, pmask = tangent.signature(pp, True), tangent.signature(pm, True)
                    smooth_jump = js["branch_sha256"] == jm["branch_sha256"] == j["branch_sha256"] and not(js["critical_count"] or jm["critical_count"])
                    smooth_positive = ps["branch_sha256"] == pmask["branch_sha256"] == r["branch_sha256"] and not(ps["critical_count"] or pmask["critical_count"])
                    admitted["jump"] &= smooth_jump; admitted["positive"] &= smooth_positive
                    row["finite_difference"].append(dict(step=step, jump_right_error=error(j["jacobian"][..., coordinate], fd),
                        jump_left_error=left_error({t: a[..., coordinate] for t, a in j["left_jacobians"].items()}, fl),
                        positive_error=error(r["jacobian"][..., coordinate], fpr), smooth_jump=smooth_jump, smooth_positive=smooth_positive))
                row["admitted"] = admitted
                for engine in coverage:
                    coverage[engine][name] += int(admitted[engine])
                records.append(row)
            qrows = []
            for remaining, mode, state in training.DATA:
                index = int(round(remaining / dt))
                value, derivative, state_derivative = co.query(s, j["jacobian"], index, mode, state)
                h = 1e-6
                fd_state = (np.interp(state + h, s["x"], s["values"][index, mode]) - np.interp(state - h, s["x"], s["values"][index, mode])) / (2 * h)
                query_records.append(dict(sigma=sigma, dx=dx, dt=dt, remaining=remaining, mode=mode, state=state,
                                          state_gradient_error=error(np.array(state_derivative), np.array(fd_state))))
                qrows.append(dict(remaining=remaining, mode=mode, state=state, value=value, gradient=derivative.tolist(), state_gradient=state_derivative))
            snapshots.append(dict(sigma=sigma, dx=dx, dt=dt, queries=qrows,
                jump_source_sha256=s["canonical_source_sha256"], jump_branch_sha256=j["branch_sha256"], positive_branch_sha256=r["branch_sha256"],
                gauge_error=float(max(abs(j["jacobian"][..., 6] + j["jacobian"][..., 7]).max(), abs(j["jacobian"][..., 8] + j["jacobian"][..., 9]).max()))))
    special = special_cases()
    fit = training.run()
    gates = dict(nonvacuous_all_coordinate_coverage=all(count > 0 for engine in coverage.values() for count in engine.values()),
        regular_finite_difference=all(max(item["jump_right_error"], item["jump_left_error"], item["positive_error"]) < protocol["tolerances"]["fd"] for row in records for item in row["finite_difference"]),
        independent_global=all(max(*r["right_errors"], *r["left_errors"], r["residual"]) < protocol["tolerances"]["global"] for r in global_records),
        independent_heat_tangent_ode=max(max(r["value_error"], r["tangent_error"]) for r in ode_records) < protocol["tolerances"]["heat_ode"],
        continuous_input_inside_cell=max(r["state_gradient_error"] for r in query_records) < protocol["tolerances"]["state"],
        critical_directional=all(r["ordinary_rejected"] and all(max(d["right_error"], d["left_error"]) < protocol["tolerances"]["directional"] for d in r["directions"]) for r in special["corners"]),
        explicit_time_knot_contract=special["query_state"]["ordinary_knot_rejected"] and len(special["off_lattice"]) == 2 and special["time_contract"]["ordinary_time_gradient"] is None,
        actual_primal_binding=len(special["binding_rejections"]) == 4 and special["quadrature16_sigma_error"] < protocol["tolerances"]["fd"],
        training_gradient_update=all(fit["gates"].values()), gauge=max(r["gauge_error"] for r in snapshots) < protocol["tolerances"]["global"])
    result = dict(schema="hcsn-r19-actual-jump-full-coordinate-gradients-v1", source_freeze=freeze, parameter_names=co.NAMES,
        parameter_count=co.P, registered_parameter_cases=len(records), coverage=coverage, gates=gates,
        finite_difference=records, independent_global=global_records, independent_heat_ode=ode_records,
        state_input_checks=query_records, query_jacobians=snapshots, nonsmooth_contracts=special, fixed_input_training=fit,
        scope=protocol["scope"], cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
        runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__), production_activation=False)
    with (output / "RESULTS.json").open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps(dict(gates=gates, coverage=coverage, training=fit["gates"], cpu_seconds=result["cpu_seconds"]), indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
