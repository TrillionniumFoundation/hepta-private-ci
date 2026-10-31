"""Independent equations, native execution, semigroup and derivative validation.

This verifies an explicitly finite model, not the continuum or task utility.
Every declared case is retained, including failure, and outputs are exclusive.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.integrate import solve_ivp

from ...task_value_factorial_20261030.cells import physical
from ...task_value_factorial_20261030.propagation import generator as independent_generator
from .finite import augmented_features, generator, physical_state, transition

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def invoke(binary, theta, family, events, driver=.2, horizon=1.3, restore_after=None):
    request = dict(parameters=list(theta), family=family, seed=710731,
        events=[dict(driver=e["driver"], micros=round(e["duration"]*1e6), reset=e["reset"]) for e in events],
        driver=driver, horizon_micros=round(horizon*1e6), restore_after=restore_after)
    run = subprocess.run([str(binary)], input=json.dumps(request), capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(dict(request=request, stdout=run.stdout, stderr=run.stderr))
    return json.loads(run.stdout)


def main(args):
    wall, cpu = time.perf_counter(), time.process_time()
    rng = np.random.default_rng(713971)
    rows, failures = [], []
    histories = [[], [dict(driver=.3, duration=.000001, reset=False)],
        [dict(driver=.7, duration=128., reset=False)],
        [dict(driver=.8, duration=.31, reset=False), dict(driver=-.7, duration=1.2, reset=True),
         dict(driver=-.4, duration=3.4, reset=False), dict(driver=.1, duration=0., reset=False)]]
    parameters = [np.zeros(11), np.linspace(-2.7, 2.7, 11)] + [rng.uniform(-1.8, 1.8, 11) for _ in range(4)]
    max_errors = dict(generator=0., probability=0., features=0., event_count=0., ode=0.,
                      frechet=0., split=0., native_split=0.)
    for pi, theta in enumerate(parameters):
        for hi, history in enumerate(histories):
            q, _, _, _ = generator(theta[:6], .2)
            iq, ir, _, _ = independent_generator((physical(theta, .2),))
            independent = np.zeros_like(q)
            independent[:5, :5], independent[:5, 5] = iq, ir[:, 0]
            for family in ("ordinary", "distribution"):
                native = invoke(args.binary, theta, family, history)
                record = dict(history=history, driver=.2, horizon=1.3)
                feature = augmented_features(family, theta, [record])[0]
                state = physical_state(theta, history)
                errors = dict(generator=float(np.max(np.abs(q-np.asarray(native["generator"])))),
                              independent_generator=float(np.max(np.abs(q-independent))),
                              features=float(np.max(np.abs(feature-native["features"]))))
                if family == "distribution":
                    errors.update(probability=float(np.max(np.abs(state[:-1]-native["probability"]))),
                                  event_count=abs(float(state[-1])-native["events"]))
                restored = invoke(args.binary, theta, family, history,
                                  restore_after=max(1, len(history)//2))
                recovery = native == restored
                row = dict(parameters=pi, history=hi, family=family, errors=errors,
                           recovery_exact=recovery, passed=max(errors.values()) < 2e-10 and recovery)
                rows.append(row)
                for key, value in errors.items():
                    if key in max_errors:
                        max_errors[key] = max(max_errors[key], value)
                if not row["passed"]:
                    failures.append(row)
    theta = parameters[2]
    q, origin, _, _ = generator(theta[:6], .3)
    p0 = np.r_[origin, 0.]
    ode = solve_ivp(lambda t, p: p@q, (0., 3.1), p0, method="DOP853", rtol=1e-11, atol=1e-13)
    max_errors["ode"] = float(np.max(np.abs(ode.y[:, -1]-p0@transition(theta, .3, 3.1))))
    derivatives = []
    history = histories[-1]
    for i in range(6):
        direction = np.eye(6)[i]
        _, derivative = physical_state(theta, history, direction=direction)
        errors = []
        for epsilon in (2e-5, 1e-5):
            step = np.r_[direction, np.zeros(5)]*epsilon
            numeric = (physical_state(theta+step, history)-physical_state(theta-step, history))/(2*epsilon)
            errors.append(float(np.max(np.abs(numeric-derivative))))
        derivatives.append(dict(parameter=i, errors=errors, maximum=float(np.max(np.abs(derivative)))))
    max_errors["frechet"] = max(x["errors"][-1] for x in derivatives)
    split_rows = []
    for duration in (1e-6, .001, .47, 7., 128.):
        first = duration*.4
        second = duration-first
        direct = transition(theta, .3, duration)
        composed = transition(theta, .3, first)@transition(theta, .3, second)
        error = float(np.max(np.abs(direct-composed)))
        native_one = invoke(args.binary, theta, "distribution", [dict(driver=.3, duration=duration, reset=False)])
        native_two = invoke(args.binary, theta, "distribution", [dict(driver=.3, duration=round(first, 6), reset=False),
            dict(driver=.3, duration=round(duration-round(first, 6), 6), reset=False)])
        native_error = max(np.max(np.abs(np.asarray(native_one["probability"])-native_two["probability"])),
                           abs(native_one["events"]-native_two["events"]))
        max_errors["split"] = max(max_errors["split"], error)
        max_errors["native_split"] = max(max_errors["native_split"], float(native_error))
        split_rows.append(dict(duration=duration, exponential_error=error, native_error=float(native_error)))
    tiny = invoke(args.binary, theta, "distribution", [], driver=.2, horizon=.000001)
    tiny_python = float(augmented_features("analytic", theta,
        [dict(history=[], driver=.2, horizon=.000001)])[0, 3])
    negative_requests = []
    for event in (dict(driver=1.1, micros=1, reset=False), dict(driver=0., micros=128000001, reset=False)):
        request = dict(parameters=theta.tolist(), family="distribution", seed=1, events=[event],
                       driver=.2, horizon_micros=1000, restore_after=None)
        process = subprocess.run([str(args.binary)], input=json.dumps(request), capture_output=True, text=True)
        negative_requests.append(dict(request=request, returncode=process.returncode, stdout=process.stdout,
                                      rejected=process.returncode != 0))
    success = (not failures and max_errors["ode"] < 1e-9 and max_errors["frechet"] < 1e-7
               and max_errors["split"] < 1e-9 and max_errors["native_split"] < 1e-9
               and tiny_python > 0 and tiny["features"][3] > 0
               and all(x["rejected"] for x in negative_requests))
    sources = [HERE/"finite.py", HERE/"probe.rs", HERE/"probe_tests.rs", Path(__file__).resolve(),
               REPO/"tools/hcsn/round9_20261031/native/src/cell.rs"]
    result = dict(schema="hcsn.finite-shared-kernel.audit.r11.v1", success=success, failures=failures,
        native_cases=rows, maximum_errors=max_errors, derivatives=derivatives, splits=split_rows,
        tiny_first_hit=dict(python=tiny_python, native=tiny["features"][3]), negative_requests=negative_requests,
        binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        source_sha256={str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        continuum_equivalence=False, scientific_efficacy_claim=False,
        limits=["Floating-point comparisons on declared cases, not a formal global error bound",
                "Same finite dynamics do not prove that task observations follow a Brownian law",
                "Recovery check restores the actual native Cell; task owner persistence is tested separately"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(dict(success=success, maximum_errors=max_errors, cases=len(rows), output=str(args.output))))
    return 0 if success else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
