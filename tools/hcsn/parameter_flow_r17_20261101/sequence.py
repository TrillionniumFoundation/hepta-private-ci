"""Actual multi-prefix forward differentiation over shared generator/observation law."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .flow import BASE, P, NAMES, GradientLaw


HISTORIES = [
    [(0.17, "read", 0), (0.03, None, None), (0.83, "refresh", 2)],
    [(0.17, "reset", None), (0.03, "read", 4), (0.83, "refresh", 2)],
]


def evaluate(model, history, gradients):
    state, ds = model.prior.copy(), model.dprior.copy()
    loglik, dll = 0., np.zeros(P)
    for duration, quality, token in history:
        if gradients:
            transition, derivative = model.operator(duration)
            ds = ds @ transition + np.einsum("i,kij->kj", state, derivative)
        else:
            transition = model.operator(duration, gradients=False)
        state = state @ transition
        if quality is None:
            continue
        if quality == "reset":
            state, ds = state @ model.R, ds @ model.R
            continue
        emission = model.E[quality][:, token]
        if gradients:
            weighted = ds * emission + state * model.dE[quality][:, :, token]
            devidence = weighted.sum(1)
        state *= emission
        evidence = float(state.sum())
        if not np.isfinite(evidence) or evidence <= 0:
            raise ValueError("Observed prefix has no positive likelihood")
        state /= evidence
        loglik += np.log(evidence)
        if gradients:
            ds = (weighted - devidence[:, None] * state) / evidence
            dll += devidence / evidence
    value = np.r_[state, loglik]
    return (value, np.c_[ds, dll]) if gradients else value


def run(output):
    root = Path(__file__).parent
    freeze = dict(source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  flow_sha256=hashlib.sha256((root / "flow.py").read_bytes()).hexdigest(),
                  histories=HISTORIES, configurations=[[.30,.018],[.22,.008],[.38,.032]],
                  epsilon=5e-6, max_scaled_error=2e-6,
                  scope="Deterministic forward-chain derivative check, not training or scientific confirmation")
    with output.with_suffix(".freeze.json").open("x") as stream:
        json.dump(freeze, stream, indent=2)
    started = time.process_time()
    rows = []
    for sigma, liquidity in freeze["configurations"]:
        coordinates = BASE.copy()
        coordinates[2], coordinates[5] = sigma, liquidity
        for index, history in enumerate(HISTORIES):
            value, gradient = evaluate(GradientLaw(coordinates), history, True)
            errors = []
            for parameter, name in enumerate(NAMES):
                step = freeze["epsilon"] * max(1., abs(coordinates[parameter]))
                offset = np.eye(P)[parameter] * step
                fd = (evaluate(GradientLaw(coordinates + offset), history, False)
                      - evaluate(GradientLaw(coordinates - offset), history, False)) / (2 * step)
                errors.append(dict(name=name, scaled_error=float(np.max(abs(gradient[parameter] - fd) / (1 + abs(fd))))))
            rows.append(dict(sigma=sigma, liquidity=liquidity, history=index,
                             log_likelihood=float(value[-1]), probability_mass=float(value[:-1].sum()),
                             max_tangent_mass=float(abs(gradient[:, :-1].sum(1)).max()), errors=errors))
    maximum = max(e["scaled_error"] for row in rows for e in row["errors"])
    result = dict(schema="hcsn-r17-multi-prefix-gradient-v1", source_freeze=freeze,
                  rows=rows, parameter_case_count=len(rows) * P, maximum_scaled_error=maximum,
                  gate=maximum < freeze["max_scaled_error"], cpu_seconds=time.process_time() - started)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("parameter_case_count", "maximum_scaled_error", "gate", "cpu_seconds")},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
