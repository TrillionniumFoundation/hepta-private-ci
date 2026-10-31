"""Independent reset/Erlang grid refinement against the renewal-time oracle.

The physical recovery law and initial/reset gap are identical at every grid.
Thresholds below are fixed before the first run; failures remain failures.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import scipy
from scipy.sparse import bmat, coo_matrix, csr_matrix
from scipy.sparse.linalg import expm_multiply

from .event_kernel import first_hit
from .generator import rates
from .renewal import expected_count
from .resolution_audit import bernoulli_prime


PROTOCOL = dict(parameters=dict(boundary=1., drift=.4, sigma=.6, duration=3.,
    recovery_mean=.5, phases=2), lower_boundary_ratio=8,
    intervals=[72, 144, 288, 576], schemes=["upwind", "fitted"],
    minimum_last_order=dict(upwind=.85, fitted=1.8),
    maximum_final_error=dict(upwind=.005, fitted=.0002),
    finite_difference_intervals=144, finite_difference_step=.00002,
    maximum_finite_difference_error=.000002, count_tail_tolerance=1e-12,
    maximum_count_domain_bound=1e-8, maximum_oracle_gradient_term_change=1e-9)
METRICS = ("count", "drift", "sigma", "boundary", "recovery_mean")


def finite_count(parameters, intervals, scheme, sensitivities=True):
    b, mu, sigma, recovery_mean = (parameters[k] for k in
        ("boundary", "drift", "sigma", "recovery_mean"))
    phases, duration = parameters["phases"], parameters["duration"]
    ratio = PROTOCOL["lower_boundary_ratio"]
    if intervals % (ratio+1) or min(b, mu, sigma, recovery_mean) <= 0:
        raise ValueError("Positive fixed parameters and an exactly aligned zero/reset node required")
    h, n = (ratio+1)*b/intervals, intervals-1
    initial_index = ratio*intervals//(ratio+1)-1
    rate = phases/recovery_mean
    diagnostic = rates(mu, sigma, h, scheme)
    up, down = float(diagnostic["up"]), float(diagnostic["down"])
    diffusion = sigma*sigma/(2*h*h)
    if scheme == "fitted":
        peclet = 2*mu*h/(sigma*sigma)
        bp, bm = bernoulli_prime(peclet), bernoulli_prime(-peclet)
        derivatives = dict(drift=(-bm/h, bp/h, 0.),
            sigma=(2*(up+diffusion*peclet*bm)/sigma,
                   2*(down-diffusion*peclet*bp)/sigma, 0.),
            boundary=((-2*up-mu*bm/h)/b, (-2*down+mu*bp/h)/b, 0.))
    else:
        derivatives = dict(drift=(1/h, 0., 0.),
            sigma=(2*diffusion/sigma, 2*diffusion/sigma, 0.),
            boundary=((-2*diffusion-mu/h)/b, -2*diffusion/b, 0.))
    derivatives["recovery_mean"] = (0., 0., -rate/recovery_mean)

    def augmented(u, d, recovery_rate):
        source = np.arange(n)
        plus = np.where(source+1 < n, source+1, n)
        minus = np.where(source > 0, source-1, n+phases)
        recovery = np.arange(n, n+phases)
        next_phase = np.r_[np.arange(n+1, n+phases), initial_index]
        row = np.r_[source, source, source, recovery, recovery]
        col = np.r_[plus, minus, source, next_phase, recovery]
        data = np.r_[np.full(n, u), np.full(n, d), np.full(n, -u-d),
                     np.full(phases, recovery_rate), np.full(phases, -recovery_rate)]
        q = coo_matrix((data, (row, col)), shape=(n+phases+1, n+phases+1)).tocsr()
        event_flux = coo_matrix(([u], ([n-1], [0])), shape=(n+phases+1, 1)).tocsr()
        return bmat([[q, event_flux], [None, csr_matrix((1, 1))]], format="csr").T

    base = augmented(up, down, rate)
    size = base.shape[0]
    start = np.zeros(size)
    start[initial_index] = 1.
    if not sensitivities:
        result = expm_multiply(duration*base, start,
            traceA=duration*base.diagonal().sum())
        return float(result[-1])
    blocks = [[base]+[None]*4]
    for i, metric in enumerate(METRICS[1:]):
        row = [augmented(*derivatives[metric])]+[None]*4
        row[i+1] = base
        blocks.append(row)
    system = bmat(blocks, format="csr")
    result = expm_multiply(duration*system, np.r_[start, np.zeros(4*size)],
        traceA=5*duration*base.diagonal().sum())
    return {metric: float(result[(i+1)*size-1]) for i, metric in enumerate(METRICS)}


def audit():
    cpu = time.process_time()
    p = PROTOCOL["parameters"]
    args = (p["boundary"], p["boundary"], p["drift"], p["sigma"],
            p["duration"], p["recovery_mean"], p["phases"])
    oracle = expected_count(*args, tail_tolerance=PROTOCOL["count_tail_tolerance"])
    more = expected_count(*args, tail_tolerance=PROTOCOL["count_tail_tolerance"],
        included_events=oracle["included_events"]+4)
    reference = dict(count=oracle["expected_count"], drift=oracle["gradient"]["drift"],
        sigma=oracle["gradient"]["sigma"], recovery_mean=oracle["gradient"]["recovery_mean"],
        boundary=oracle["gradient"]["initial_gap"]+oracle["gradient"]["reset_gap"])
    m = oracle["included_events"]
    lower_probability = first_hit(PROTOCOL["lower_boundary_ratio"]*p["boundary"],
        -p["drift"], p["sigma"], p["duration"])["probability"]
    count_domain_bound = m*(m+1)*lower_probability+(m+1)*oracle["count_tail_bound"]
    gradient_change = max(abs(more["gradient"][k]-oracle["gradient"][k]) for k in oracle["gradient"])
    rows, checks, gates = [], [], []
    for scheme in PROTOCOL["schemes"]:
        previous = None
        for intervals in PROTOCOL["intervals"]:
            values = finite_count(p, intervals, scheme)
            errors = {k: abs(values[k]-reference[k]) for k in METRICS}
            order = None if previous is None else {k: float(np.log2(previous[k]/errors[k])) for k in METRICS}
            rows.append(dict(scheme=scheme, intervals=intervals, values=values,
                absolute_error=errors, observed_order=order))
            previous = errors
        selected = [r for r in rows if r["scheme"] == scheme]
        gates.extend([
            dict(name=scheme+"_all_errors_decrease", passed=all(a["absolute_error"][k] > b["absolute_error"][k]
                for a,b in zip(selected, selected[1:]) for k in METRICS)),
            dict(name=scheme+"_last_order", passed=min(selected[-1]["observed_order"].values()) >= PROTOCOL["minimum_last_order"][scheme]),
            dict(name=scheme+"_final_accuracy", passed=max(selected[-1]["absolute_error"].values()) < PROTOCOL["maximum_final_error"][scheme])])
        for name in METRICS[1:]:
            step = PROTOCOL["finite_difference_step"]
            plus, minus = p.copy(), p.copy()
            plus[name] += step
            minus[name] -= step
            n = PROTOCOL["finite_difference_intervals"]
            finite_difference = (finite_count(plus, n, scheme, False)-finite_count(minus, n, scheme, False))/(2*step)
            exact = next(r for r in selected if r["intervals"] == n)["values"][name]
            checks.append(dict(scheme=scheme, parameter=name, derivative=exact,
                finite_difference=finite_difference, absolute_error=abs(exact-finite_difference)))
    gates.extend([
        dict(name="matrix_derivatives_against_finite_differences", passed=max(r["absolute_error"] for r in checks) < PROTOCOL["maximum_finite_difference_error"]),
        dict(name="continuous_lower_domain_count_bound", passed=count_domain_bound < PROTOCOL["maximum_count_domain_bound"]),
        dict(name="oracle_gradient_term_stability", passed=gradient_change < PROTOCOL["maximum_oracle_gradient_term_change"])])
    return dict(schema="hcsn_round8_renewal_resolution_v1", protocol=PROTOCOL,
        passed=all(g["passed"] for g in gates), gates=gates, reference=reference,
        oracle=oracle, rows=rows, finite_difference_checks=checks,
        lower_domain=dict(single_excursion_probability_bound=lower_probability,
            finite_count_bound=count_domain_bound, included_events=m,
            gradient_error_certified=False), oracle_extra_terms_gradient_change=gradient_change,
        process_cpu_seconds=time.process_time()-cpu,
        environment=dict(numpy=np.__version__, scipy=scipy.__version__),
        limitations=["One fixed regular scalar Brownian/reset/Erlang contract; not a uniform continuum theorem.",
            "The lower-domain count bound does not certify lower-domain gradient error; total gradient convergence is measured against the unbounded-domain oracle.",
            "The renewal count-tail bound does not certify derivative-tail error; extra-term stability is diagnostic.",
            "No observed refinement order implies low-noise coarse-grid admissibility."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    protocol_file = args.output.with_name(args.output.stem+"_protocol.json")
    with protocol_file.open("x") as stream:
        json.dump(PROTOCOL, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    result = audit()
    source = Path(__file__).parent
    result["source_sha256"] = {name:hashlib.sha256((source/name).read_bytes()).hexdigest()
        for name in ("event_kernel.py", "generator.py", "renewal.py", "resolution_audit.py", "renewal_resolution.py")}
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result["passed"], "gates": result["gates"],
        "process_cpu_seconds": result["process_cpu_seconds"]}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
