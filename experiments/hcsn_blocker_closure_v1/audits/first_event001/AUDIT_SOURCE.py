"""Independent dense next-event reference: no accelerated generator import."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad_vec
from scipy.linalg import expm
import torch

from experiments.hcsn_blocker_closure_v1.content.models import first_event_vectors
from experiments.hcsn_distributional_v2.distribution_kernel import Grid, make_flow


def dense(parameters):
    mu, sigma, boundary, reset, tau, rho, duration = parameters
    n, m, lower = 8, 2, -2.
    h = (boundary-lower)/n
    centers = lower+h*(np.arange(n)+.5)
    diffusion = sigma*sigma/(2*h*h)
    up, down = diffusion+max(mu, 0)/h, diffusion+max(-mu, 0)/h
    event_rate = 2*diffusion+max(mu, 0)/h
    q = np.zeros((n+m, n+m))
    for i in range(n):
        if i:
            q[i, i-1] = down
        if i+1 < n:
            q[i, i+1] = up
        else:
            q[i, n] = event_rate
    q[n, n+1] = m/tau
    reset_weights = np.maximum(1-np.abs(centers-reset)/h, 0)
    reset_weights /= reset_weights.sum()
    q[n+1, :n] = (m/tau)*reset_weights
    np.fill_diagonal(q, -q.sum(1))
    killed = q.copy()
    killed[n-1, n] = 0
    event = np.zeros(n+m)
    event[n-1] = event_rate
    f = 1-expm(killed*duration)@np.ones(n+m)
    augmented = np.zeros((n+m+1, n+m+1))
    augmented[:-1, :-1], augmented[:-1, -1] = killed-rho*np.eye(n+m), event
    hvalue = expm(augmented*duration)[:-1, -1]
    return dict(F=f, H=hvalue, killed=killed, full=q, event=event)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time()
    model_source = Path("experiments/hcsn_blocker_closure_v1/content/models.py")
    source_sha = hashlib.sha256(model_source.read_bytes()).hexdigest()
    cases = [[.1, .45, 1.3, -.13, .75, .45, .12],
             [-.25, .55, .9, -.25, 1.05, .7, .4]]
    names = ("mu", "sigma", "boundary", "reset", "tau", "rho", "horizon")
    checks, records = [], []
    torch.set_num_threads(1)
    for index, parameters in enumerate(cases):
        values = [torch.tensor(x, dtype=torch.float64, requires_grad=True) for x in parameters]
        flow = make_flow(*values[:5], grid=Grid(cells=8, lower=-2., refractory_stages=2,
            fixed_rate=8.1, fixed_terms=21, max_duration=.36, per_token_chunks=True))
        actual = first_event_vectors(flow, values[5], values[6])
        reference = dense(parameters)
        weights = np.arange(1, 11, dtype=np.float64)/55
        record = dict(parameters=dict(zip(names, parameters)), forward={}, gradients=[])
        for name in ("F", "H"):
            vector = actual[name].detach().numpy()
            error = float(np.max(np.abs(vector-reference[name])))
            checks.append(dict(name=f"case{index}/{name}/dense", passed=error <= 1e-11, max_error=error))
            integral, quadrature_error = quad_vec(lambda t: np.exp(-parameters[5]*t if name == "H" else 0)
                *(expm(reference["killed"]*t)@reference["event"]), 0, parameters[-1], epsabs=1e-12, epsrel=1e-12)
            integral_error = float(np.max(np.abs(vector-integral)))
            checks.append(dict(name=f"case{index}/{name}/independent_flux_quadrature", passed=integral_error <= 1e-11,
                               max_error=integral_error, quadrature_reported_error=quadrature_error))
            record["forward"][name] = dict(value=vector.tolist(), reference=reference[name].tolist(), error=error)
            objective = (actual[name]*torch.from_numpy(weights)).sum()
            derivatives = torch.autograd.grad(objective, values, retain_graph=True)
            for j, parameter in enumerate(names):
                plus, minus = parameters.copy(), parameters.copy()
                plus[j] += 1e-6
                minus[j] -= 1e-6
                fd = float(weights@(dense(plus)[name]-dense(minus)[name])/(2e-6))
                derivative = float(derivatives[j])
                scaled_error = abs(derivative-fd)/(1+abs(fd))
                checks.append(dict(name=f"case{index}/{name}/gradient/{parameter}", passed=scaled_error <= 1e-8,
                                   scaled_error=scaled_error))
                record["gradients"].append(dict(channel=name, parameter=parameter, autodiff=derivative,
                                                dense_finite_difference=fd, scaled_error=scaled_error))
        f, h = actual["F"].detach().numpy(), actual["H"].detach().numpy()
        checks.append(dict(name=f"case{index}/probability_order", passed=bool(
            np.all(h >= -1e-12) and np.all(f <= 1+1e-12) and np.all(h <= f+1e-12))))
        checks.append(dict(name=f"case{index}/existing_refractory_completes", passed=bool(np.all(f[-2:] > 0))))
        full = np.zeros((11, 11))
        full[:10, :10], full[:10, 10] = reference["full"], reference["event"]
        long_count = expm(full*4)[:10, 10]
        long_first = 1-expm(reference["killed"]*4)@np.ones(10)
        record["long_horizon"] = dict(horizon=4., expected_repeat_count=long_count.tolist(),
                                     next_first_event_probability=long_first.tolist())
        checks.append(dict(name=f"case{index}/repeat_count_not_first_probability", passed=bool(
            np.all(long_count >= long_first-1e-10) and long_count.max() > 1)))
        records.append(record)
    unchanged = hashlib.sha256(model_source.read_bytes()).hexdigest() == source_sha
    checks.append(dict(name="tested_source_unchanged", passed=unchanged))
    result = dict(schema="hcsn-first-event-independent-audit.v1", passed=all(x["passed"] for x in checks),
                  checks=checks, records=records, tested_source=str(model_source), tested_source_sha256=source_sha,
                  audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  torch_version=torch.__version__, cpu_seconds=time.process_time()-start,
                  scope="Two float64 flow cases, 28 physical/channel derivatives; finite-model numerical evidence, not a global derivative certificate")
    (output/"RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(passed=result["passed"], checks=len(checks), failures=[x for x in checks if not x["passed"]],
                          cpu_seconds=result["cpu_seconds"])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
