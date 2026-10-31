"""Independent numerical evidence for the declared finite propagation model.

Run as a module. Writes raw sampled final states/counts, frozen tolerances, every
gradient comparison and CPU/wall measurements even when an acceptance check fails.
No task-level or continuous-SDE superiority is inferred from these checks.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.special import ndtr

from .propagation import Cell, factorized_rollout, first_passage, flow, generator, remap, rollout


def uniformized(q, rewards, duration):
    """Independent Poisson expansion, including additive event rewards."""
    n, k = rewards.shape
    lam = float(np.max(-np.diag(q)))
    if lam == 0 or duration == 0:
        return np.eye(n), np.zeros((n, k))
    chunks = max(1, math.ceil(lam*duration/12))
    x = lam*duration/chunks
    u = np.eye(n+k)
    u[:n, :n] += q/lam
    u[:n, n:] = rewards/lam
    power, weight = np.eye(n+k), math.exp(-x)
    answer, mass = weight*power, weight
    for order in range(1, 256):
        power = power@u
        weight *= x/order
        answer += weight*power
        mass += weight
        if order > x+12 and weight < 1e-17:
            break
    else:
        raise ArithmeticError("Uniformization expansion budget exhausted")
    if abs(mass-1) > 2e-14:
        raise ArithmeticError("Poisson mass truncation exceeds audit tolerance")
    answer = np.linalg.matrix_power(answer, chunks)
    return answer[:n, :n], answer[:n, n:]


def _sample_reset(c, rng):
    center = c.lower+(c.boundary-c.lower)*(np.arange(c.active)+.5)/c.active
    return _sample_location(c.reset, center, rng)


def _sample_location(x, center, rng):
    if x <= center[0]:
        return 0
    if x >= center[-1]:
        return len(center)-1
    right = int(np.searchsorted(center, x, side="right"))
    probability_right = (x-center[right-1])/(center[right]-center[right-1])
    return right if rng.random() < probability_right else right-1


def sampled_paths(initial, initial_cells, schedule, trajectories, seed):
    """Direct Gillespie path simulator, independent of generator/flow/remap."""
    rng = np.random.default_rng(seed)
    shape = tuple(c.active+c.phases for c in initial_cells)
    final, event_counts = [], []
    for _ in range(trajectories):
        state = list(np.unravel_index(rng.choice(len(initial), p=initial), shape))
        counts = np.zeros(len(shape), dtype=int)
        previous = initial_cells
        for segment in schedule:
            cells, duration = segment["cells"], segment["duration"]
            coupling = segment.get("coupling", 0.)
            for axis, (old, new) in enumerate(zip(previous, cells)):
                i = state[axis]
                if i >= old.active:
                    continue
                x = old.lower+(old.boundary-old.lower)*(i+.5)/old.active
                if x >= new.boundary:
                    state[axis] = new.active+new.phases-1
                    counts[axis] += 1
                else:
                    centers = new.lower+(new.boundary-new.lower)*(
                        np.arange(new.active)+.5)/new.active
                    state[axis] = _sample_location(x, centers, rng)
            elapsed = 0.
            while elapsed < duration:
                actions, rates = [], []
                for axis, c in enumerate(cells):
                    i = state[axis]
                    if i >= c.active:
                        actions.append((axis, "recover" if i == c.active else i-1, False))
                        rates.append(c.phases/c.refractory)
                        continue
                    width = (c.boundary-c.lower)/c.active
                    drift = c.drift
                    for other, oc in enumerate(cells):
                        if other != axis and state[other] < oc.active:
                            ox = oc.lower+(oc.boundary-oc.lower)*(state[other]+.5)/oc.active
                            drift += coupling*(ox-oc.reset)
                    diffusion = .5*(c.sigma/width)**2
                    if i > 0:
                        actions.append((axis, i-1, False))
                        rates.append(diffusion+max(-drift, 0.)/width)
                    firing = i == c.active-1
                    actions.append((axis, c.active+c.phases-1 if firing else i+1, firing))
                    rates.append(diffusion+max(drift, 0.)/width)
                total = sum(rates)
                if total == 0:
                    break
                elapsed += rng.exponential(1/total)
                if elapsed > duration:
                    break
                axis, target, firing = actions[rng.choice(len(actions), p=np.asarray(rates)/total)]
                state[axis] = _sample_reset(cells[axis], rng) if target == "recover" else target
                counts[axis] += int(firing)
            previous = cells
        final.append(int(np.ravel_multi_index(tuple(state), shape)))
        event_counts.append(counts.tolist())
    return np.asarray(final), np.asarray(event_counts)


def protocol():
    cells = (Cell(drift=.43, sigma=.29, reset=-.13, active=4),
             Cell(drift=.27, sigma=.33, reset=-.17, refractory=.31, active=4))
    schedule = []
    for index, (b, dt) in enumerate(((1., .13), (.82, .27), (1.06, .07), (.68, .49), (.9, .31))):
        schedule.append(dict(cells=(replace(cells[0], boundary=b),
                                    replace(cells[1], boundary=b+.11)),
                             duration=dt, coupling=.19))
    initial = np.zeros(36)
    initial[np.ravel_multi_index((2, 3), (6, 6))] = 1.
    return initial, cells, schedule


def _perturbed(cells, schedule, field, epsilon):
    def change(cs):
        if field in ("coupling", "duration"):
            return cs
        return (replace(cs[0], **{field: getattr(cs[0], field)+epsilon}), cs[1])
    out = []
    for s in schedule:
        row = dict(s, cells=change(s["cells"]))
        if field in ("coupling", "duration"):
            row[field] += epsilon
        out.append(row)
    return change(cells), out


def audit(trajectories=4000):
    start, cpu = time.perf_counter(), time.process_time()
    checks, details = [], {}

    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))

    p, cells, schedule = protocol()
    exact = rollout(p, cells, schedule)
    for i, s in enumerate(schedule):
        q, r, dq, dr = generator(s["cells"], s["coupling"], ({"drift": 1.}, {}))
        check(f"generator_{i}", np.max(abs(q.sum(1))) < 2e-14
              and np.max(abs(dq.sum(1))) < 2e-14
              and np.min(q-np.diag(np.diag(q))) >= 0,
              row_defect=float(np.max(abs(q.sum(1)))), derivative_row_defect=float(np.max(abs(dq.sum(1)))))
        t, e, _, _ = flow(s["cells"], s["duration"], s["coupling"])
        ti, ei = uniformized(q, r, s["duration"])
        error = max(float(np.max(abs(t-ti))), float(np.max(abs(e-ei))))
        check(f"independent_poisson_{i}", error < 2e-12, max_absolute_error=error)
    gradient_rows = []
    for field in ("drift", "sigma", "boundary", "reset", "refractory", "coupling", "duration"):
        initial_directions = ({field: 1.}, {}) if field not in ("coupling", "duration") else ({}, {})
        differentiated = []
        for s in schedule:
            differentiated.append(dict(s, directions=initial_directions,
                dcoupling=float(field == "coupling"), dduration=float(field == "duration")))
        analytic = rollout(p, cells, differentiated, initial_directions)
        eps = 2e-6
        plus_cells, plus_schedule = _perturbed(cells, schedule, field, eps)
        minus_cells, minus_schedule = _perturbed(cells, schedule, field, -eps)
        plus, minus = rollout(p, plus_cells, plus_schedule), rollout(p, minus_cells, minus_schedule)
        fd = np.concatenate(((plus["probability"]-minus["probability"])/(2*eps),
                             (plus["counts"]-minus["counts"])/(2*eps)))
        derivative = np.concatenate((analytic["probability_derivative"], analytic["count_derivative"]))
        scaled = float(np.max(abs(fd-derivative)/(1+abs(fd))))
        gradient_rows.append(dict(parameter=field, epsilon=eps,
            frechet=derivative.tolist(), finite_difference=fd.tolist(), scaled_error=scaled))
        check("whole_stream_gradient_"+field, scaled < 3e-7,
              scaled_error=scaled, derivative_mass=float(analytic["probability_derivative"].sum()))
    details["gradient_vectors"] = gradient_rows
    final, count = sampled_paths(p, cells, schedule, trajectories, 118307)
    frequencies = np.bincount(final, minlength=len(p))/trajectories
    se = np.sqrt(exact["probability"]*(1-exact["probability"])/trajectories)
    count_se = count.std(axis=0, ddof=1)/math.sqrt(trajectories)
    check("independent_gillespie_distribution", np.all(abs(frequencies-exact["probability"]) <= 6*se+.003),
          max_absolute_error=float(np.max(abs(frequencies-exact["probability"]))), trajectories=trajectories)
    check("independent_gillespie_repeated_count", np.all(abs(count.mean(0)-exact["counts"]) <= 6*count_se+.01),
          predicted=exact["counts"].tolist(), sampled_mean=count.mean(0).tolist(), standard_error=count_se.tolist())
    details["sampling"] = dict(seed=118307, final_states=final.tolist(), counts=count.tolist(),
                              predicted_probability=exact["probability"].tolist(), observed_probability=frequencies.tolist())
    details["factorized_closure"] = []
    for strength in (0., .19, .65):
        comparison_schedule = [dict(s, coupling=strength) for s in schedule]
        joint = rollout(p, cells, comparison_schedule)
        approximate = factorized_rollout(p, cells, comparison_schedule)
        tv = float(np.sum(abs(joint["probability"]-approximate["probability"]))/2)
        count_error = abs(joint["counts"]-approximate["counts"])
        details["factorized_closure"].append(dict(coupling=strength,
            retained_states=approximate["retained_states"], joint_states=approximate["exact_joint_states"],
            total_variation=tv, count_absolute_error=count_error.tolist(),
            bounded_readout_error_bound_for_norm_le_1=2*tv,
            scope="Measured closure error at this finite protocol; no general error bound"))
        if strength == 0:
            check("uncoupled_factorized_reference", tv < 2e-9 and np.max(count_error) < 2e-9,
                  total_variation=tv, count_absolute_error=count_error.tolist())
    long_cells = (Cell(drift=1.2, sigma=.2, refractory=.11, reset=-.13, active=4),)
    initial = np.zeros(6)
    initial[0] = 1
    probability, total = initial.copy(), np.zeros(1)
    flows = [flow(long_cells, dt) for dt in (.013, .027, .041)]
    mass_error, minimum = 0., 1.
    for i in range(4096):
        transition, event, _, _ = flows[i % 3]
        total += probability@event
        probability = probability@transition
        mass_error = max(mass_error, abs(probability.sum()-1))
        minimum = min(minimum, float(probability.min()))
    check("4096_step_repeated_events", mass_error < 2e-10 and minimum >= -1e-14 and total[0] > 1,
          mass_error=mass_error, minimum=minimum, expected_events=float(total[0]))
    small_cases = [(1e-7, -1., 1e-8, 1e-7), (1e-7, 1., 1e-8, 1e-7),
                   (1e-6, 0., .1, 1e-8), (1., 0., 1., 1.), (.3, -.2, .4, .9)]
    details["fpt_cases"] = []
    for x, mu, sd, horizon in small_cases:
        value = float(first_passage(x, mu, sd, horizon))
        details["fpt_cases"].append(dict(distance=x, drift=mu, sigma=sd, horizon=horizon, probability=value))
        check(f"fpt_finite_{len(details['fpt_cases'])}", 0 <= value <= 1)
    for i, (x, mu, sd, horizon) in enumerate(((.3, -.2, .4, .9), (.7, .3, .5, 1.2), (.4, 0., .3, 2.))):
        def density(t):
            if t == 0:
                return 0.
            return x/(sd*math.sqrt(2*math.pi*t**3))*math.exp(-(x+mu*t)**2/(2*sd*sd*t))
        positive, error = quad(density, 0, horizon, epsabs=1e-12, epsrel=1e-12)
        difference = abs(positive-float(first_passage(x, mu, sd, horizon)))
        check(f"fpt_positive_density_integral_{i}", difference < 2e-10,
              difference=difference, quadrature_error=error)
    check("fpt_zero_drift_identity", abs(float(first_passage(1., 0., 1., 1.))-2*ndtr(-1)) < 2e-15)
    details["protocol"] = dict(initial=p.tolist(), initial_cells=[asdict(c) for c in cells],
        schedule=[dict(cells=[asdict(c) for c in s["cells"]], duration=s["duration"], coupling=s["coupling"]) for s in schedule])
    return dict(schema="hepta.finite-propagation.audit.v1", passed=all(c["passed"] for c in checks),
        checks=checks, details=details, process_cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-start,
        environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                       (Path(__file__), Path(__file__).with_name("propagation.py"))},
        scope="Finite CTMC active-set derivatives and independent sampled CTMC; not a continuum convergence or task superiority claim")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--trajectories", type=int, default=4000)
    args = parser.parse_args()
    if not 1000 <= args.trajectories <= 100000:
        raise ValueError("Audit trajectory budget outside [1000,100000]")
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Audit evidence is immutable; choose a new output path")
    try:
        result = audit(args.trajectories)
    except Exception as exc:
        with path.open("x") as stream:
            stream.write(json.dumps(dict(passed=False, error_type=type(exc).__name__, error=str(exc)), indent=2)+"\n")
        raise
    with path.open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({k: result[k] for k in ("passed", "process_cpu_seconds", "wall_seconds")}))
    print(json.dumps(dict(checks=len(result["checks"]), failed=[c for c in result["checks"] if not c["passed"]])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
