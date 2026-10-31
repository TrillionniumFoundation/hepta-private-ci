"""Separate spatial-refinement audit for explicitly hashed event kernels.

The grid represents Brownian motion on (-4*b,b), starting at its exact zero
node. Moving b in a derivative moves both endpoints at fixed ratio. Explicit
image-series bounds control the resulting lower-truncation errors in values
and derivatives against the one-upper-boundary closed form. The fitted and
upwind chains remain finite models at each resolution.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import scipy
from scipy.sparse import bmat, csr_matrix, diags
from scipy.sparse.linalg import expm_multiply

from .event_kernel import discounted_hit, first_hit, first_hit_gradient
from .generator import (ResolutionError, absorbing_generator, first_exit,
                        rates, require_local_resolution)


PROTOCOL = dict(
    parameters=dict(boundary=1.0, drift=0.4, sigma=0.6, duration=1.2, discount=0.7),
    lower_boundary_ratio=4, intervals=[40, 80, 160, 320, 640],
    schemes=["upwind", "fitted"],
    minimum_last_refinement_order=dict(upwind=0.85, fitted=1.8),
    maximum_final_absolute_error=dict(upwind=0.005, fitted=0.00005),
    sensitivity_check_intervals=80, sensitivity_fd_step=0.00002,
    maximum_sensitivity_fd_error=0.000002,
    lower_truncation_budget=1e-30,
    low_noise_grids=[15, 31, 63, 127, 255],
    maximum_extra_variance_ratio=0.05,
)
METRICS = ("F", "G", "F_drift", "F_boundary", "G_drift", "G_boundary")


def bernoulli_prime(z):
    """Derivative of z/expm1(z), with its removable singularity resolved."""
    if abs(z) < 0.01:
        return -0.5 + z/6 - z**3/180 + z**5/5040 - z**7/151200
    denominator = math.expm1(z)
    return (denominator - z*math.exp(z)) / denominator**2


def finite_law(boundary, drift, sigma, intervals, scheme):
    if intervals % 5 or intervals < 10 or min(boundary, sigma, drift) <= 0:
        raise ValueError("This audit requires positive parameters and a grid divisible by five")
    spacing = 5*boundary/intervals
    diagnostic = rates(drift, sigma, spacing, scheme)
    up, down = float(diagnostic["up"]), float(diagnostic["down"])
    diffusion = sigma*sigma/(2*spacing*spacing)
    if scheme == "upwind":
        up_mu, down_mu = 1/spacing, 0.0
        up_b, down_b = (-2*diffusion-drift/spacing)/boundary, -2*diffusion/boundary
    else:
        peclet = 2*drift*spacing/(sigma*sigma)
        bp, bm = bernoulli_prime(peclet), bernoulli_prime(-peclet)
        up_mu, down_mu = -bm/spacing, bp/spacing
        up_b = (-2*up-drift*bm/spacing)/boundary
        down_b = (-2*down+drift*bp/spacing)/boundary
    size = intervals-1

    def blocks(u, d):
        killed = diags([np.full(size-1, d), np.full(size, -u-d),
                        np.full(size-1, u)], [-1, 0, 1], format="csr")
        flux = csr_matrix(([u], ([size-1], [0])), shape=(size, 1))
        return killed, flux

    return dict(blocks=blocks(up, down), drift_blocks=blocks(up_mu, down_mu),
                boundary_blocks=blocks(up_b, down_b), initial_index=4*intervals//5-1,
                spacing=spacing, diagnostic=diagnostic)


def propagate(law, duration, discount, sensitivities=True):
    """Sparse exponential plus its exact finite-matrix parameter sensitivity.

    The last coordinate integrates upper absorption flux, discounted before
    absorption. It is never computed by subtracting survival from one.
    """
    killed, flux = law["blocks"]
    size = killed.shape[0]
    end = csr_matrix((1, 1))
    base = bmat([[killed-discount*diags(np.ones(size)), flux], [None, end]], format="csr").T
    initial = np.zeros(size+1)
    initial[law["initial_index"]] = 1
    if not sensitivities:
        out = expm_multiply(duration*base, initial, traceA=duration*base.diagonal().sum())
        return float(out[-1])
    derivatives = []
    for key in ("drift_blocks", "boundary_blocks"):
        q, r = law[key]
        derivatives.append(bmat([[q, r], [None, end]], format="csr").T)
    system = bmat([[base, None, None], [derivatives[0], base, None],
                   [derivatives[1], None, base]], format="csr")
    start = np.r_[initial, np.zeros(2*(size+1))]
    out = expm_multiply(duration*system, start, traceA=3*duration*base.diagonal().sum())
    return dict(value=float(out[size]), drift=float(out[2*size+1]),
                boundary=float(out[3*size+2]))


def closed_reference(parameters):
    b, mu, sigma, duration, discount = (parameters[k] for k in
        ("boundary", "drift", "sigma", "duration", "discount"))
    f = first_hit(b, mu, sigma, duration)["probability"]
    grad = first_hit_gradient(b, mu, sigma, duration)
    kappa = math.sqrt(mu*mu + 2*discount*sigma*sigma)
    coefficient = math.exp((mu-kappa)*b/(sigma*sigma))
    transformed = first_hit(b, kappa, sigma, duration)["probability"]
    transformed_grad = first_hit_gradient(b, kappa, sigma, duration)
    g_mu = coefficient*((b/(sigma*sigma))*(1-mu/kappa)*transformed
                        + (mu/kappa)*transformed_grad["drift"])
    g_b = coefficient*((mu-kappa)/(sigma*sigma)*transformed
                       + transformed_grad["distance"])
    return dict(F=f, G=discounted_hit(b, mu, sigma, duration, discount)["value"],
                F_drift=grad["drift"], F_boundary=grad["distance"],
                G_drift=g_mu, G_boundary=g_b)


def lower_truncation_bounds(parameters):
    """Absolute image-tail bounds, including endpoint-scaled derivatives.

    The nonzero images have distances (10*j-1)*b and (10*j+1)*b, j>=1.
    With a=d/(sigma*sqrt(T)), their integrated magnitudes are bounded by
    exp(mu*b/sigma^2)*2*phi(a)/a. Adjacent image ratios give geometric sums.
    Differentiating density w.r.t. b adds an integral bounded by 2*a*phi(a).
    Discount >= 0 only reduces these upper bounds. See RESOLUTION.md.
    """
    b, mu, sigma, duration = (parameters[k] for k in ("boundary", "drift", "sigma", "duration"))
    scale = sigma*math.sqrt(duration)
    step = 10*b/scale
    sum_zero = sum_second = 0.0
    for distance in (9*b, 11*b):
        a = distance/scale
        if a < 1:
            raise ValueError("The registered Gaussian-tail bound requires a>=1")
        phi = math.exp(-a*a/2)/math.sqrt(2*math.pi)
        ratio_zero = math.exp(-a*step-step*step/2)
        ratio_second = (1+step/a)*ratio_zero
        if ratio_second >= 1:
            raise ArithmeticError("Image geometric envelope did not contract")
        sum_zero += 2*phi/a/(1-ratio_zero)
        sum_second += 2*a*phi/(1-ratio_second)
    factor = math.exp(mu*b/(sigma*sigma))
    value = factor*sum_zero
    drift = (b+abs(mu)*duration)/(sigma*sigma)*value
    boundary = factor*((2/b+abs(mu)/(sigma*sigma))*sum_zero + sum_second/b)
    return dict(F=value, G=value, F_drift=drift, G_drift=drift,
                F_boundary=boundary, G_boundary=boundary,
                interpretation="analytic absolute bounds evaluated in binary64; no interval-arithmetic roundoff certificate")


def audit():
    start = time.process_time()
    parameters = PROTOCOL["parameters"]
    reference = closed_reference(parameters)
    truncation = lower_truncation_bounds(parameters)
    rows, gates, checks = [], [], []

    def gate(name, passed, criterion):
        gates.append(dict(name=name, passed=bool(passed), criterion=criterion))

    gate("lower_truncation_values_and_derivatives",
         max(truncation[k] for k in METRICS) < PROTOCOL["lower_truncation_budget"],
         "all six analytic image bounds below the preregistered 1e-30 budget")
    for scheme in PROTOCOL["schemes"]:
        previous = None
        for intervals in PROTOCOL["intervals"]:
            law = finite_law(parameters["boundary"], parameters["drift"], parameters["sigma"], intervals, scheme)
            f = propagate(law, parameters["duration"], 0)
            g = propagate(law, parameters["duration"], parameters["discount"])
            values = dict(F=f["value"], G=g["value"], F_drift=f["drift"], F_boundary=f["boundary"],
                          G_drift=g["drift"], G_boundary=g["boundary"])
            errors = {k:abs(values[k]-reference[k]) for k in METRICS}
            order = None if previous is None else {k:math.log2(previous[k]/errors[k]) for k in METRICS}
            rows.append(dict(scheme=scheme, intervals=intervals, interior_states=intervals-1,
                             spacing=law["spacing"], values=values, absolute_error=errors,
                             observed_order=order,
                             extra_variance_ratio=float(law["diagnostic"]["extra_variance_ratio"])))
            previous = errors
        selected = [r for r in rows if r["scheme"] == scheme]
        decreasing = all(a["absolute_error"][k] > b["absolute_error"][k]
                         for a,b in zip(selected, selected[1:]) for k in METRICS)
        gate(scheme+"_all_errors_decrease", decreasing,
             "every successive refinement decreases all six absolute errors")
        gate(scheme+"_last_order", min(selected[-1]["observed_order"].values()) >= PROTOCOL["minimum_last_refinement_order"][scheme],
             "last-pair observed order >= "+str(PROTOCOL["minimum_last_refinement_order"][scheme])+" for all six quantities")
        gate(scheme+"_final_accuracy", max(selected[-1]["absolute_error"].values()) < PROTOCOL["maximum_final_absolute_error"][scheme],
             "all finest-grid absolute errors < "+str(PROTOCOL["maximum_final_absolute_error"][scheme]))
        law = finite_law(parameters["boundary"], parameters["drift"], parameters["sigma"], PROTOCOL["sensitivity_check_intervals"], scheme)
        for discount in (0, parameters["discount"]):
            result = propagate(law, parameters["duration"], discount)
            for name in ("boundary", "drift"):
                delta = PROTOCOL["sensitivity_fd_step"]
                plus, minus = parameters.copy(), parameters.copy()
                plus[name] += delta
                minus[name] -= delta
                laws = [finite_law(p["boundary"], p["drift"], p["sigma"], PROTOCOL["sensitivity_check_intervals"], scheme) for p in (plus, minus)]
                fd = (propagate(laws[0], parameters["duration"], discount, False)
                      - propagate(laws[1], parameters["duration"], discount, False))/(2*delta)
                checks.append(dict(scheme=scheme, discount=discount, parameter=name,
                                   sensitivity=result[name], central_difference=fd,
                                   absolute_error=abs(result[name]-fd)))
    gate("finite_matrix_sensitivities", max(c["absolute_error"] for c in checks) < PROTOCOL["maximum_sensitivity_fd_error"],
         "sparse block-exponential sensitivities agree with fixed-grid central differences within 2e-6")
    low_noise = []
    exact = first_hit(1, 1, 0.05, 0.8)["probability"]
    for grid in PROTOCOL["low_noise_grids"]:
        for scheme in PROTOCOL["schemes"]:
            flow = absorbing_generator(1, 0.05, n_grid=grid, scheme=scheme)
            finite = first_exit(flow, 0.8)
            try:
                require_local_resolution(flow["diagnostics"], PROTOCOL["maximum_extra_variance_ratio"])
                admitted = True
            except ResolutionError:
                admitted = False
            low_noise.append(dict(grid=grid, scheme=scheme, upper_probability=finite["plus"],
                reference_upper_probability=exact, local_resolution_admitted=admitted,
                extra_variance_ratio=float(np.max(flow["diagnostics"]["extra_variance_ratio"]))))
    gate("low_noise_coarse_grids_still_rejected", not any(r["local_resolution_admitted"] for r in low_noise),
         "no registered low-noise grid bypasses the unchanged 5% local-variance gate")
    return dict(schema="hcsn_round8_spatial_resolution_audit_v1", protocol=PROTOCOL,
                reference=reference, lower_truncation_bounds=truncation, rows=rows,
                finite_matrix_gradient_checks=checks, low_noise=low_noise,
                gates=gates, passed=all(g["passed"] for g in gates), process_cpu_seconds=time.process_time()-start,
                environment=dict(numpy=np.__version__, scipy=scipy.__version__),
                limitations=["Empirical refinement at one fixed regular parameter group is not a uniform convergence theorem.",
                    "Boundary derivatives rescale both endpoints; the separate image bound controls the lower-boundary effect.",
                    "The sparse matrix exponential has numerical, not interval-certified, error.",
                    "This audit does not change prior evidence, learned checkpoints, or its fixed resolution protocol."])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    source = Path(__file__).parent
    result["source_sha256"] = {name:hashlib.sha256((source/name).read_bytes()).hexdigest()
        for name in ("resolution_audit.py", "event_kernel.py", "generator.py")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=result["passed"], gates=result["gates"], process_cpu_seconds=result["process_cpu_seconds"]), indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
