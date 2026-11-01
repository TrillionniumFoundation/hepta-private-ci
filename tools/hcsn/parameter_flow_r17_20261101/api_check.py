"""Boundary/error contracts for the finite derivative API; no zero-likelihood repair."""

import json
from pathlib import Path

import numpy as np

from .flow import BASE, GradientLaw


def run(output):
    model = GradientLaw()
    rows = []
    checks = [
        ("impossible_erasure_with_gradient", lambda: model.evaluate(0., 4, "read")),
        ("impossible_erasure_without_gradient", lambda: model.evaluate(0., 4, "read", False)),
        ("underflow_survival_with_gradient", lambda: model.evaluate(1e6)),
        ("underflow_survival_without_gradient", lambda: model.evaluate(1e6, gradients=False)),
        ("negative_event_time", lambda: model.events(-1.)),
        ("nan_event_time", lambda: model.events(float("nan"))),
        ("infinite_event_time", lambda: model.events(float("inf"))),
        ("negative_operator_time", lambda: model.operator(-1.)),
        ("infinite_operator_time", lambda: model.operator(float("inf"))),
    ]
    knot = BASE.copy()
    knot[9] = np.log(model.boundary) + .25
    checks.append(("reset_interpolation_knot", lambda: GradientLaw(knot)))
    for name, call in checks:
        try:
            with np.errstate(divide="raise", invalid="raise", over="raise", under="ignore"):
                call()
        except ValueError as error:
            rows.append(dict(name=name, rejected=True, exception=str(error)))
        else:
            raise RuntimeError(f"Invalid input accepted: {name}")
    result = dict(schema="hcsn-r17-gradient-boundary-contracts-v1", checks=rows, passed=len(rows))
    with Path(output).open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
