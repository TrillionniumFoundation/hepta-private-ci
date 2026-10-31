"""Run deterministic finite-oracle verification and retain all numerical rows."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.linalg import expm
from scipy.optimize import brentq, linprog
from scipy.special import log_ndtr, ndtr

from .finite_qvi import (action_values, build_affine, evaluate_policy,
                         implicit_gradient, residual_certificate, solve_policy)
from .reference_solvers import linear_program, value_iteration
from .task_model import (build_posterior_task, conditional_generators,
                         labeled_policy_value)


def serial(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def single_stop_policy(problem):
    n = len(problem.grid)
    rewards = problem.rewards.max(0)
    result = linprog(np.ones(n)/n,
                     A_ub=np.vstack([problem.generator-problem.rho*np.eye(n), -np.eye(n)]),
                     b_ub=np.r_[-problem.running, -rewards], bounds=[(None, None)]*n,
                     method="highs")
    if not result.success:
        raise RuntimeError(result.message)
    keep = (problem.running+problem.rate*result.x+problem.generator@result.x)/(problem.rho+problem.rate)
    return np.where(rewards > keep+1e-11, problem.rewards.argmax(0)+1, 0)


def first_passage_records():
    records = []
    for mu, sigma, distance, duration in [(.1, .45, .3, .6), (-.28, .58, .8, 2.),
                                         (.48, .32, .6, .7), (-.4, .3, 1.2, 4.)]:
        rho = .3
        def cdf(t, drift=mu):
            z1, z2 = (drift*t-distance)/(sigma*np.sqrt(t)), (-drift*t-distance)/(sigma*np.sqrt(t))
            return ndtr(z1)+np.exp(2*drift*distance/sigma**2+log_ndtr(z2))
        def density(t):
            return distance*np.exp(-(distance-mu*t)**2/(2*sigma*sigma*t))/(sigma*np.sqrt(2*np.pi*t**3))
        omega = np.sqrt(mu*mu+2*rho*sigma*sigma)
        kappa = (omega-mu)/(sigma*sigma)
        probability, quadrature_error = quad(density, 0, duration, epsabs=1e-12, epsrel=1e-12)
        discounted, discount_error = quad(lambda t: np.exp(-rho*t)*density(t), 0, duration,
                                         epsabs=1e-12, epsrel=1e-12)
        step = 1e-6
        fd = (cdf(duration+step)-cdf(duration-step))/(2*step)
        closed_h = np.exp(-kappa*distance)*cdf(duration, omega)
        records.append(dict(mu=mu, sigma=sigma, distance=distance, duration=duration,
                            F=float(cdf(duration)), f=float(density(duration)), H=float(closed_h),
                            endpoint=float(ndtr((mu*duration-distance)/(sigma*np.sqrt(duration)))),
                            F_integral_error=abs(cdf(duration)-probability),
                            H_integral_error=abs(closed_h-discounted),
                            density_fd_error=abs(fd-density(duration)),
                            quadrature_reported_errors=[quadrature_error, discount_error]))
    return records


def event_records(problem, solution):
    expanded = labeled_policy_value(problem, solution["action"])
    q, event = expanded["generator"], expanded["event_rate"]
    size = len(event)
    initial = np.zeros(size)
    for k, (label, i) in enumerate(expanded["states"]):
        initial[k] = problem.reset[i]*(problem.grid[i] if label else 1-problem.grid[i])
    killed = q.copy()
    killed[:, expanded["phase0"]] -= event
    augmented = np.zeros((size+1, size+1))
    augmented[:size, :size], augmented[:size, size] = q, event
    discounted = augmented.copy()
    discounted[:size, :size] = killed-problem.rho*np.eye(size)
    records = []
    for duration in (.1, .5, 2., 8.):
        transition = expm(killed*duration)
        count = float(initial@expm(augmented*duration)[:size, size])
        first = float(1-initial@transition@np.ones(size))
        density = float(initial@transition@event)
        h = float(initial@expm(discounted*duration)[:size, size])
        step = 1e-6
        fd = float(initial@(expm(killed*(duration-step))-expm(killed*(duration+step)))@np.ones(size)/(2*step))
        records.append(dict(duration=duration, C=count, P=first, F=first, f=density,
                            H=h, initial_atom=0., density_fd_error=abs(density-fd),
                            valid_order=bool(count+1e-10 >= first >= h-1e-10 >= -1e-10 and first <= 1+1e-10)))
    return records


def switching_record():
    index = 12
    def margin(tau):
        problem, _ = build_posterior_task(tau=tau)
        solution = solve_policy(problem)
        values = solution["values"]
        return values[0, index]-values[1:, index].max()
    tau = brentq(margin, .5, 1.5, xtol=1e-12)
    sides = []
    for offset in (-1e-6, 1e-6):
        problem, derivative = build_posterior_task(tau=tau+offset)
        solution = solve_policy(problem)
        gradient = implicit_gradient(problem, solution, derivative["tau"])
        sides.append(dict(tau=tau+offset, action_at_probe=int(solution["action"][index]),
                          reset_value=float(problem.reset@solution["value"]),
                          reset_derivative=float(problem.reset@gradient)))
    return dict(probe_posterior=index/32, switching_tau=tau, sides=sides,
                derivative_jump=sides[1]["reset_derivative"]-sides[0]["reset_derivative"],
                implication="Policy changes; no unique global smooth-boundary gradient is claimed")


def audit(output):
    output.mkdir(parents=True, exist_ok=False)
    started, wall = time.process_time(), time.perf_counter()
    root = Path(__file__).parent
    protocol = json.loads((root/"ORACLE_PROTOCOL.json").read_text())
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(root.iterdir()) if p.suffix in (".py", ".json")}
    registration = dict(protocol=protocol, source_hashes=hashes, execution="deterministic validation; not a content heldout study")
    (output/"REGISTRATION.json").write_text(json.dumps(registration, indent=2)+"\n")
    checks, rows = [], []
    def check(name, passed, **detail):
        checks.append(dict(name=name, passed=bool(passed), **detail))
    tol = protocol["tolerances"]
    for family in ("affine", "task"):
        for case in protocol[family+"_cases"]:
            params = {key: val for key, val in case.items() if key != "name"}
            for nodes in protocol[family+"_nodes"]:
                if family == "affine":
                    kappa = (np.sqrt(params["mu"]**2+2*params["rho"]*params["sigma"]**2)-params["mu"])/params["sigma"]**2
                    grid = np.linspace(-2, params["K"]+2/kappa, nodes)
                    problem, _ = build_affine(grid, **params)
                else:
                    problem, _ = build_posterior_task(nodes=nodes, **params)
                solution, lp = solve_policy(problem), linear_program(problem)
                cert = residual_certificate(problem, solution["value"])
                scale = max(1., float(np.max(np.abs(solution["value"]))))
                error = float(np.max(np.abs(solution["value"]-lp["value"])))
                identity = family+"/"+case["name"]+"/"+str(nodes)
                check(identity+"/LP", error/scale <= tol["lp_value_scaled"], value_error=error)
                check(identity+"/QVI", cert["residual"] <= tol["bellman_residual"] and
                      cert["value_error_bound"] <= tol["contraction_value_bound"], **cert)
                row = dict(family=family, case=case["name"], nodes=nodes, parameters=params,
                           grid=problem.grid, value=solution["value"], policy=solution["action"],
                           reset_value=float(problem.reset@solution["value"]), iterations=solution["iterations"],
                           lp_error=error, certificate=cert)
                if nodes == 17:
                    vi = value_iteration(problem)
                    vi_error = float(np.max(np.abs(solution["value"]-vi["value"])))
                    check(identity+"/VI", vi_error <= 3e-9, error=vi_error, iterations=vi["iterations"])
                    row["value_iteration"] = {k: v for k, v in vi.items() if k != "value"}
                if family == "affine":
                    D = problem.delay_discount
                    boundary = brentq(lambda b: kappa*(b-params["K"])-1+D*np.exp(-kappa*(b-params["reset"])),
                                      params["K"], params["K"]+1/kappa)
                    policy = (grid >= boundary).astype(np.int64)
                    fixed_value = evaluate_policy(problem, policy)
                    row.update(analytic_boundary=boundary, analytic_threshold_grid_value=float(problem.reset@fixed_value),
                               improvement_over_analytic_threshold=float(problem.reset@(solution["value"]-fixed_value)))
                    check(identity+"/dominates_mapped_analytic", np.min(solution["value"]-fixed_value) >= -1e-8)
                else:
                    conditional = conditional_generators(problem)
                    mixed = (1-problem.grid[:, None])*conditional[0]+problem.grid[:, None]*conditional[1]
                    martingale = float(np.max(np.abs(problem.generator@problem.grid)))
                    mixture = float(np.max(np.abs(mixed-problem.generator)))
                    check(identity+"/posterior_law", max(martingale, mixture) <= tol["martingale_absolute"],
                          martingale_error=martingale, conditional_mixture_error=mixture)
                    if np.all(solution["action"][problem.reset > 0] == 0):
                        labeled = labeled_policy_value(problem, solution["action"])
                        label_error = float(np.max(np.abs(labeled["value"]-solution["value"])))
                        check(identity+"/labeled_generator", label_error/scale <= tol["labeled_value_scaled"], error=label_error)
                        row["labeled_generator_error"] = label_error
                    else:
                        row["labeled_generator_status"] = "reset is in firing set; immediate-cycle policy uses Bellman/LP only"
                    one_shot = single_stop_policy(problem)
                    one_shot_value = evaluate_policy(problem, one_shot)
                    always_fire = problem.rewards.argmax(0)+1
                    always_value = evaluate_policy(problem, always_fire)
                    row.update(single_stop_policy=one_shot, single_stop_in_true_task=float(problem.reset@one_shot_value),
                               always_fire_value=float(problem.reset@always_value),
                               continuation_gain=float(problem.reset@(solution["value"]-one_shot_value)))
                    active = np.flatnonzero(solution["action"] == 0)
                    if len(active):
                        threshold_policy = np.where(problem.grid < problem.grid[active[0]], 1,
                                                    np.where(problem.grid > problem.grid[active[-1]], 2, 0))
                        threshold_error = float(np.max(np.abs(evaluate_policy(problem, threshold_policy)-solution["value"])))
                        row["ordinary_two_threshold_error"] = threshold_error
                        check(identity+"/ordinary_threshold_equivalence", threshold_error <= 1e-8,
                              lower_continue=float(problem.grid[active[0]]), upper_continue=float(problem.grid[active[-1]]))
                rows.append(row)
    gradients = []
    for family in ("affine", "task"):
        case = protocol[family+"_cases"][0 if family == "affine" else -1]
        params = {k: v for k, v in case.items() if k != "name"}
        if family == "affine":
            grid = np.linspace(-2., 4., 33)
            build = lambda p: build_affine(grid, **p)
        else:
            build = lambda p: build_posterior_task(nodes=33, **p)
        problem, derivatives = build(params)
        solution = solve_policy(problem)
        for key, derivative in derivatives.items():
            step = protocol["gradient_cases"]["step"]
            plus, minus = dict(params), dict(params)
            plus[key], minus[key] = plus[key]+step, minus[key]-step
            positive, negative = solve_policy(build(plus)[0]), solve_policy(build(minus)[0])
            stable = np.array_equal(positive["action"], solution["action"]) and np.array_equal(negative["action"], solution["action"])
            gradient = implicit_gradient(problem, solution, derivative)
            fd = (positive["value"]-negative["value"])/(2*step)
            scaled_error = float(np.max(np.abs(gradient-fd)/(1+np.abs(fd))))
            record = dict(family=family, parameter=key, policy_stable=stable,
                          derivative=gradient, finite_difference=fd, scaled_error=scaled_error)
            gradients.append(record)
            check(family+"/gradient/"+key, stable and scaled_error <= tol["implicit_gradient_scaled"],
                  scaled_error=scaled_error, policy_stable=stable)
    first = first_passage_records()
    for i, row in enumerate(first):
        check("first_passage/"+str(i), max(row["F_integral_error"], row["H_integral_error"], row["density_fd_error"]) <= 1e-8
              and row["F"] >= row["endpoint"], **row)
    task, _ = build_posterior_task()
    events = event_records(task, solve_policy(task))
    for i, row in enumerate(events):
        check("regenerative_event/"+str(i), row["valid_order"] and row["density_fd_error"] < 1e-7, **row)
    check("regenerative_count_exceeds_one", max(r["C"] for r in events) > 1)
    switch = switching_record()
    check("active_set_switch_is_not_hidden", switch["sides"][0]["action_at_probe"] != switch["sides"][1]["action_at_probe"])
    unchanged = all(hashlib.sha256((root/name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
    check("source_unchanged", unchanged)
    result = dict(schema="hcsn-blocker-oracle-audit.v1", complete=True,
                  passed=all(x["passed"] for x in checks), checks=checks,
                  cases=rows, gradients=gradients, first_passage=first, events=events, active_set_switch=switch,
                  source_hashes=hashes, protocol_sha256=hashes["ORACLE_PROTOCOL.json"],
                  versions=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                  cpu_seconds=time.process_time()-started, wall_seconds=time.perf_counter()-wall,
                  scope=protocol["limitations"])
    (output/"RESULTS.json").write_text(json.dumps(result, indent=2, default=serial, allow_nan=False)+"\n")
    print(json.dumps(dict(passed=result["passed"], checks=len(checks), failures=[x for x in checks if not x["passed"]],
                          cases=len(rows), cpu_seconds=result["cpu_seconds"]), default=serial))
    if not result["passed"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.output)


if __name__ == "__main__":
    main()
