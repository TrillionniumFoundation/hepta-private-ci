"""Deterministic derivative verification, not held-out scientific confirmation.

FD checks parameter-to-generator/values. The ODE checks exponential and Frechet
transport independently given those generator tangents; it does not independently
rederive the inherited FullHX formula. Every advertised coordinate is retained.
"""

import argparse
import hashlib
import json
import platform
import resource
import time
from pathlib import Path

import numpy as np
import scipy
from scipy.integrate import solve_ivp

from ..addressed_decision_r15_20261101.law import Law
from .flow import BASE, NAMES, P, GradientLaw


ROOT = Path(__file__).parent
TIMES = (0., .00001, .17, 2.7, 8.)
CONFIGS = ((.30, .018), (.22, .008), (.38, .032))
OBSERVATIONS = (("read", 0), ("read", 4), ("refresh", 2))


def scaled_error(a, b):
    return float(np.max(abs(a - b) / (1 + abs(b))))


def reference(model):
    """Row-state sensitivity ODE including event flux and reset successors."""
    count, size = P + 1, 40
    rows = np.r_[model.prior[None], model.dprior]
    initial = np.r_[rows.ravel(), rows.ravel(), (rows @ model.R).ravel(), np.zeros(2 * count)]

    def rhs(_, flat):
        full = flat[:count * size].reshape(count, size)
        alive = flat[count * size:2 * count * size].reshape(count, size)
        reset = flat[2 * count * size:3 * count * size].reshape(count, size)
        derivatives = []
        for state, q, dq in ((full, model.Q, model.dQ), (alive, model.K, model.dK),
                             (reset, model.Q, model.dQ)):
            derivative = state @ q
            derivative[1:] += np.einsum("i,kij->kj", state[0], dq)
            derivatives.append(derivative.ravel())
        first = alive @ model.rates
        first[1:] += model.drates @ alive[0]
        count_derivative = full @ model.rates
        count_derivative[1:] += model.drates @ full[0]
        return np.r_[*derivatives, first, count_derivative]

    result = solve_ivp(rhs, (0., TIMES[-1]), initial, t_eval=TIMES,
                       method="DOP853", rtol=3e-12, atol=3e-14)
    if not result.success:
        raise RuntimeError(result.message)
    return result


def from_reference(model, flat, quality, token):
    count, block = P + 1, (P + 1) * 40
    full, alive, reset = (flat[j * block:(j + 1) * block].reshape(count, 40) for j in range(3))
    survival = alive.sum(1)
    conditional = alive[0] / survival[0]
    dconditional = (alive[1:] - survival[1:, None] * conditional) / survival[0]
    e, de = model.E[quality][:, token], model.dE[quality][:, :, token]
    weighted = full[0] * e
    dweighted = full[1:] * e + full[0] * de
    evidence, devidence = weighted.sum(), dweighted.sum(1)
    posterior = weighted / evidence
    dposterior = (dweighted - devidence[:, None] * posterior) / evidence
    first, events = flat[3 * block:3 * block + count], flat[3 * block + count:]
    value = np.r_[full[0], alive[0], conditional, first[0], events[0], evidence,
                  posterior, reset[0], model.boundary, model.reset]
    derivative = np.c_[full[1:], alive[1:], dconditional, first[1:], events[1:], devidence,
                       dposterior, reset[1:], model.dboundary, model.dreset]
    return value, derivative


def time_derivative(model, value, quality, token):
    full, alive = value[:40], value[40:80]
    dfull, dalive = full @ model.Q, alive @ model.K
    conditional, posterior = value[80:120], value[123:163]
    dconditional = (dalive - dalive.sum() * conditional) / alive.sum()
    e = model.E[quality][:, token]
    dweighted, evidence = dfull * e, value[122]
    devidence = dweighted.sum()
    dposterior = (dweighted - devidence * posterior) / evidence
    return np.r_[dfull, dalive, dconditional, alive @ model.rates,
                 full @ model.rates, devidence, dposterior, value[163:203] @ model.Q, 0., 0.]


def verify(output):
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for name, digest in freeze["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed frozen source: {name}")
    started, wall = time.process_time(), time.perf_counter()
    records, rows, identities = [], [], []
    for sigma, liquidity in CONFIGS:
        x = BASE.copy()
        x[2], x[5] = sigma, liquidity
        model = GradientLaw(x)
        inherited = Law((sigma, liquidity))
        parity = dict(generator=float(np.max(abs(model.Q - inherited.Q))),
                      prior=float(np.max(abs(model.prior - inherited.prior))),
                      read=float(np.max(abs(model.E["read"] - inherited.E_read))),
                      refresh=float(np.max(abs(model.E["refresh"] - inherited.E_refresh))))
        identities.append(dict(sigma=sigma, liquidity=liquidity, reset_segment=model.segment,
                               coordinate_sha256=hashlib.sha256(x.tobytes()).hexdigest(), parity=parity))
        ode = reference(model)
        for time_index, duration in enumerate(TIMES):
            for quality, token in OBSERVATIONS:
                value, gradient = model.evaluate(duration, token, quality)
                ov, og = from_reference(model, ode.y[:, time_index], quality, token)
                row = dict(sigma=sigma, liquidity=liquidity, duration=duration, quality=quality,
                           token=token, ode_value_error=scaled_error(value, ov),
                           ode_gradient_error=scaled_error(gradient, og),
                           ode_function_evaluations=ode.nfev, parameter_rows=[])
                for index, name in enumerate(NAMES):
                    errors, estimates = [], []
                    for epsilon in (1e-5, 5e-6):
                        step = epsilon * max(1., abs(x[index]))
                        offset = np.eye(P)[index] * step
                        plus, minus = GradientLaw(x + offset), GradientLaw(x - offset)
                        if plus.segment != model.segment or minus.segment != model.segment:
                            raise RuntimeError("Registered finite difference crosses a reset knot")
                        fd = (plus.evaluate(duration, token, quality, False)
                              - minus.evaluate(duration, token, quality, False)) / (2 * step)
                        errors.append(scaled_error(gradient[index], fd))
                        estimates.append(fd)
                    parameter = dict(name=name, fd_scaled_error=errors,
                                     fd_step_change=scaled_error(estimates[0], estimates[1]),
                                     gradient_max_abs=float(abs(gradient[index]).max()))
                    row["parameter_rows"].append(parameter)
                    rows.append(parameter)
                step = 1e-6
                if duration:
                    fdtime = (model.evaluate(duration + step, token, quality, False)
                              - model.evaluate(duration - step, token, quality, False)) / (2 * step)
                else:
                    fdtime = (-3 * value + 4 * model.evaluate(step, token, quality, False)
                              - model.evaluate(2 * step, token, quality, False)) / (2 * step)
                row["time_derivative_error"] = scaled_error(time_derivative(model, value, quality, token), fdtime)
                row["mass_error"] = float(abs(value[:40].sum() - 1))
                row["mass_tangent_error"] = float(abs(gradient[:, :40].sum(1)).max())
                row["hit_survival_error"] = float(abs(value[120] + value[40:80].sum() - 1))
                row["hit_survival_tangent_error"] = float(abs(gradient[:, 120] + gradient[:, 40:80].sum(1)).max())
                records.append(row)
    maximum = dict(parameter_fd=max(row["fd_scaled_error"][1] for row in rows),
                   parameter_fd_step_change=max(row["fd_step_change"] for row in rows),
                   ode_value=max(row["ode_value_error"] for row in records),
                   ode_gradient=max(row["ode_gradient_error"] for row in records),
                   time_gradient=max(row["time_derivative_error"] for row in records),
                   mass=max(row["mass_error"] for row in records),
                   mass_tangent=max(row["mass_tangent_error"] for row in records),
                   hit_survival=max(row["hit_survival_error"] for row in records),
                   hit_survival_tangent=max(row["hit_survival_tangent_error"] for row in records),
                   inherited_parity=max(v for item in identities for v in item["parity"].values()))
    tolerances = json.loads((ROOT / "PROTOCOL.json").read_text())["tolerances"]
    gates = {key: maximum[key] < threshold for key, threshold in tolerances.items()}
    result = dict(schema="hcsn-r17-finite-all-coordinate-derivative-v1", independent_units="None: deterministic numerical verification",
                  parameter_names=NAMES, parameter_count=P, observation_time_cases=len(records),
                  parameter_case_count=len(rows), maximum_scaled_errors=maximum, gates=gates,
                  identities=identities, records=records, source_freeze=freeze,
                  scope="Analytic derivative API for R15-compatible finite law extension; not all-domain proof, continuous-free-boundary solution, task gain or production admission.",
                  runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
                  cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
                  max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("parameter_count", "observation_time_cases", "parameter_case_count", "maximum_scaled_errors", "gates", "cpu_seconds")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    verify(parser.parse_args().output)
