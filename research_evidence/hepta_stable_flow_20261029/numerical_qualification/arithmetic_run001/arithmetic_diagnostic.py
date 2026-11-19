"""New scalar arithmetic diagnosis; NOT a reconstruction of lost Hepta runs.

Uses Decimal as an independent high-precision oracle and NumPy for explicitly
typed float32/float64 arithmetic. No trained weights or task data are used.
"""

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np


ROOT = Path(__file__).resolve().parent
METHODS = ("direct", "expm1", "series")
CONTRACT = {
    "scope": "new arithmetic diagnosis only; no recovered checkpoint or old-run claim",
    "phi": "phi_k(z)=sum_{j>=0} z**j/(j+k)!; k=1,2",
    "series_degree": 18,
    "series_switch_abs_z": 0.25,
    "z_grid": [-10.0, -1.0, -0.25, -0.1, -0.01, -0.001, -0.0001, -0.00001, -0.000001, -0.0000001, -0.00000001, 0.0],
    "call_kappa": [0.25, 1.0, 4.0],
    "call_x": [0.1, 0.01, 0.001, 0.0001, 0.00001, 0.000001, 0.0000001, 0.00000001],
    "etd2_affine_ode": "dy/dt=-lambda*y+(alpha*y+c), y(0)=y0, T=1",
    "affine_parameters_from_float32": {"lambda": 0.001, "alpha": 0.4, "c": 0.1, "y0": 0.2},
    "affine_steps": [4, 8, 16, 32, 64, 128, 256, 512, 1024],
    "reference_decimal_precision": 80,
    "reference_semantics": "Exact real function of the same represented float32 inputs; finite-polynomial series is only the candidate, not the oracle",
    "precision_comparison": "Both float64 and float32 use exactly upcast original float32 scalar inputs",
    "acceptance_scope": "Arithmetic errors reported; not a trained-cell convergence acceptance",
}


def d(value):
    return Decimal.from_float(float(value))


def oracle_phi(z, k):
    with localcontext() as ctx:
        ctx.prec = 80
        z = d(z)
        if z == 0:
            return float(Decimal(1) / math.factorial(k)), float(Decimal(1) / math.factorial(k + 1))
        exponential = z.exp()
        if k == 1:
            value = (exponential - 1) / z
            derivative = (z * exponential - exponential + 1) / z**2
        else:
            value = (exponential - 1 - z) / z**2
            derivative = ((z - 2) * exponential + z + 2) / z**3
        return float(value), float(derivative)


def typed_phi(z, k, method, dtype):
    z = dtype(z)
    if z == 0:
        return dtype(1 / math.factorial(k)), dtype(1 / math.factorial(k + 1))
    if method == "series" and abs(z) <= 0.25:
        # Horner derivatives are derivatives of this polynomial, not a separate
        # unstable quotient. A tensor implementation can differentiate Horner.
        value = dtype(1 / math.factorial(18 + k))
        derivative = dtype(18 / math.factorial(18 + k))
        for j in range(17, -1, -1):
            value = dtype(value * z + dtype(1 / math.factorial(j + k)))
        for j in range(17, 0, -1):
            derivative = dtype(derivative * z + dtype(j / math.factorial(j + k)))
        return value, derivative
    exponential = dtype(np.exp(z))
    numerator1 = dtype(exponential - dtype(1)) if method == "direct" else dtype(np.expm1(z))
    if k == 1:
        value = dtype(numerator1 / z)
        derivative = dtype((exponential * z - numerator1) / dtype(z * z))
    else:
        numerator2 = dtype(numerator1 - z)
        value = dtype(numerator2 / dtype(z * z))
        # The derivative expm1'=exp still requires cancellation of exp(z)-1.
        derivative = dtype((dtype(exponential - dtype(1)) * z - dtype(2) * numerator2) / dtype(z * z * z))
    return value, derivative


def error(value, reference):
    absolute = abs(float(value) - reference)
    return {"value": float(value), "absolute_error": absolute, "relative_error": absolute / abs(reference) if reference else None}


def oracle_call(x, kappa):
    with localcontext() as ctx:
        ctx.prec = 80
        x, kappa = d(x), d(kappa)
        ep, en = x.exp(), (-kappa * x).exp()
        denominator = kappa * ep + en
        numerator = denominator - (kappa + 1)
        dx_den = kappa * (ep - en)
        dk_den = ep - x * en
        value = numerator / denominator
        dx = (kappa + 1) * dx_den / denominator**2
        dk = ((dk_den - 1) * denominator - numerator * dk_den) / denominator**2
        return tuple(float(v) for v in (value, dx, dk))


def typed_call(x, kappa, stable, dtype):
    x, kappa = dtype(x), dtype(kappa)
    ep, en = dtype(np.exp(x)), dtype(np.exp(-kappa * x))
    denominator = dtype(kappa * ep + en)
    dk_den = dtype(ep - x * en)
    if stable:
        phi_pos, dphi_pos = typed_phi(x, 2, "series", dtype)
        phi_neg, dphi_neg = typed_phi(-kappa * x, 2, "series", dtype)
        coefficient = dtype(kappa * phi_pos + kappa * kappa * phi_neg)
        numerator = dtype(x * x * coefficient)
        dx_num = dtype(dtype(2) * x * coefficient + x * x * (kappa * dphi_pos - kappa * kappa * kappa * dphi_neg))
        dk_num = dtype(x * x * (phi_pos + dtype(2) * kappa * phi_neg - kappa * kappa * x * dphi_neg))
        dx_den = dtype(kappa * (dtype(np.expm1(x)) - dtype(np.expm1(-kappa * x))))
    else:
        numerator = dtype(denominator - dtype(kappa + dtype(1)))
        dx_num = dtype(kappa * ep - kappa * en)
        dx_den = dx_num
        dk_num = dtype(dk_den - dtype(1))
    value = dtype(numerator / denominator)
    dx = dtype((dx_num * denominator - numerator * dx_den) / dtype(denominator * denominator))
    dk = dtype((dk_num * denominator - numerator * dk_den) / dtype(denominator * denominator))
    return value, dx, dk


def affine_reference(parameters):
    with localcontext() as ctx:
        ctx.prec = 80
        lam, alpha, c, y0 = (d(parameters[k]) for k in ("lambda", "alpha", "c", "y0"))
        gamma = alpha - lam
        exponential = gamma.exp()
        phi = (exponential - 1) / gamma
        dphi = (gamma * exponential - exponential + 1) / gamma**2
        return float(exponential * y0 + c * phi), float(-exponential * y0 - c * dphi)


def affine_etd2(parameters, steps, method, dtype):
    lam, alpha, c, y = (dtype(parameters[k]) for k in ("lambda", "alpha", "c", "y0"))
    gradient = dtype(0)
    h = dtype(1 / steps)
    z = dtype(-lam * h)
    e = dtype(np.exp(z))
    phi1, dphi1 = typed_phi(z, 1, method, dtype)
    phi2, dphi2 = typed_phi(z, 2, method, dtype)
    for _ in range(steps):
        force = dtype(alpha * y + c)
        dforce = dtype(alpha * gradient)
        predictor = dtype(e * y + h * phi1 * force)
        dpredictor = dtype(-h * e * y + e * gradient - h * h * dphi1 * force + h * phi1 * dforce)
        correction = dtype(alpha * (predictor - y))
        dcorrection = dtype(alpha * (dpredictor - gradient))
        y = dtype(predictor + h * phi2 * correction)
        gradient = dtype(dpredictor - h * h * dphi2 * correction + h * phi2 * dcorrection)
    return y, gradient


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    protocol = {**CONTRACT, "source_sha256": source_sha, "numpy_version": np.__version__}
    protocol_bytes = (json.dumps(protocol, indent=2, sort_keys=True) + "\n").encode()
    (output / "PROTOCOL.json").write_bytes(protocol_bytes)
    start = time.process_time()
    phi_rows, call_rows, flow_rows = [], [], []
    for precision, dtype in (("float32", np.float32), ("float64", np.float64)):
        for raw_z in CONTRACT["z_grid"]:
            z = float(np.float32(raw_z))
            for k in (1, 2):
                reference = oracle_phi(z, k)
                for method in METHODS:
                    values = typed_phi(z, k, method, dtype)
                    phi_rows.append({"precision": precision, "z": z, "k": k, "method": method, "function": error(values[0], reference[0]), "derivative": error(values[1], reference[1])})
        for raw_kappa in CONTRACT["call_kappa"]:
            for raw_x in CONTRACT["call_x"]:
                x, kappa = float(np.float32(raw_x)), float(np.float32(raw_kappa))
                reference = oracle_call(x, kappa)
                for stable in (False, True):
                    values = typed_call(x, kappa, stable, dtype)
                    call_rows.append({"precision": precision, "x": x, "kappa": kappa, "method": "stable_series" if stable else "direct", **{name: error(value, ref) for name, value, ref in zip(("function", "dx", "dkappa"), values, reference, strict=True)}})
        parameters = {k: float(np.float32(v)) for k, v in CONTRACT["affine_parameters_from_float32"].items()}
        reference = affine_reference(parameters)
        for steps in CONTRACT["affine_steps"]:
            for method in METHODS:
                values = affine_etd2(parameters, steps, method, dtype)
                flow_rows.append({"precision": precision, "steps": steps, "h": 1 / steps, "method": method, "function": error(values[0], reference[0]), "lambda_gradient": error(values[1], reference[1])})
    checks = []
    _, derivative = affine_etd2(parameters, 64, "series", np.float64)
    for epsilon in (1e-5, 1e-6, 1e-7):
        plus, minus = dict(parameters), dict(parameters)
        plus["lambda"] += epsilon
        minus["lambda"] -= epsilon
        numerical = (affine_etd2(plus, 64, "series", np.float64)[0] - affine_etd2(minus, 64, "series", np.float64)[0]) / (2 * epsilon)
        checks.append({"epsilon": epsilon, "finite_difference": float(numerical), "forward_sensitivity": float(derivative), "absolute_error": float(abs(numerical - derivative))})
    result = {"status": "complete_new_arithmetic_diagnosis", "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(), "source_sha256": source_sha, "cpu_seconds": time.process_time() - start, "phi_records": phi_rows, "call_records": call_rows, "affine_records": flow_rows, "discrete_gradient_fd_checks": checks, "old_model_claim": "None: original source, checkpoints and task trajectories were unavailable to this diagnosis"}
    path = output / "RESULTS.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "phi_records": len(phi_rows), "call_records": len(call_rows), "affine_records": len(flow_rows), "cpu_seconds": result["cpu_seconds"], "results_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
