"""Independent scalar integral and event-time reset regression controls."""

import copy
import json
import math
from fractions import Fraction as F
from unittest.mock import patch

import numpy as np
from scipy.integrate import quad

from qualification.hcsn_currentstate_n256_engineering import candidate as primitive
from qualification.hcsn_currentstate_n256_sparse_dynamic_v2_intent import sparse_dynamic as old
from qualification.hcsn_n256_multistep import flow


def empty(module, n):
    return module.DynamicState(np.zeros((5, 2, n)), np.zeros((5, 3)),
        np.zeros((5, 2)), np.zeros((5, 2)), np.zeros((5, 3)))


def repaired_constructor(operator, upper_flow, sparse):
    core = old._csr(operator, sparse)
    prefix = (0.,) * (operator.dimension - len(upper_flow))
    sink = sparse.csr_matrix([prefix + tuple(upper_flow)], dtype="float64").T
    return sparse.bmat(((core, sink), (None, sparse.csr_matrix((1, 1)))), format="csr")


def constructor_case():
    operator = primitive.CSR.from_rows(({0: -1.}, {1: -2.}, {2: -3.}))
    from scipy import sparse
    try:
        with patch.object(old, "INTERIOR", 3):
            old._extended(operator, (0., 0., .2), sparse)
    except (ValueError, TypeError) as error:
        return {"legacy_exception": str(error), "dynamic_actions": 0}
    raise ValueError("legacy tuple-constructor defect unexpectedly absent")


def occupation_case(parent):
    start, end = F(1, 5), F(21, 100)
    duration = float(end - start)
    spatial = primitive.CSR.from_rows(({0: -1.7},))
    source = primitive.CSR.from_rows(({0: -.4}, {1: -.9}))
    marks = np.array([1., -.3, .8, -.5, .07])
    seed = np.array([.4, .2, -.3, .6, -.1])
    amplitude = np.column_stack((2 * marks, .7 * marks))
    output = (1.2, .3)
    values = {}
    for name, module in (("legacy", old), ("repaired", flow)):
        with patch.object(module, "INTERIOR", 1), patch.object(primitive, "INTERIOR", 1), \
                patch.object(old, "_extended", repaired_constructor):
            state = empty(module, 1)
            state.active[:, 1 if parent else 0, 0] = seed
            args = ("scalar-source", 2, 2, 1, start, end, source,
                    tuple(amplitude.ravel()), output)
            packets = (module.Packet(*args, (1.,)),) if name == "repaired" and parent else ()
            if name == "legacy" and parent:
                packets = (module.Packet(*args),)
            state, _, _ = module._advance(state, packets, start, end, primitive,
                spatial, (1.5,), (.2,), [1.], "synthetic-control",
                module._numeric_modules(), module.Counts())
            values[name] = state.occupation[:, 2 if parent else 1].tolist()

    def probability(channel, time):
        result = seed[channel] * math.exp(-1.7 * time)
        if parent:
            for rate, alpha, coefficient in zip((.4, .9), amplitude[channel], output):
                result += alpha * coefficient * (math.exp(-rate * time) - math.exp(-1.7 * time)) / (1.7 - rate)
        return result

    reference = []
    for channel in range(5):
        def integrand(time):
            escaped = .2 * quad(lambda v: probability(channel, v), 0, time, epsabs=1e-13)[0]
            return math.exp(-flow.DISCOUNT * (float(start) + time)) * (probability(channel, time) + escaped)
        reference.append(quad(integrand, 0, duration, epsabs=1e-13)[0])
    values["independent_quadrature"] = reference
    values["legacy_max_abs_error"] = float(np.max(np.abs(np.array(values["legacy"]) - reference)))
    values["repaired_max_abs_error"] = float(np.max(np.abs(np.array(values["repaired"]) - reference)))
    if values["legacy_max_abs_error"] < 1e-5 or values["repaired_max_abs_error"] > 1e-12:
        raise ValueError("occupation regression or reference disagreement")
    return values


def reset_case():
    spatial = primitive.CSR.from_rows(({0: -1.5, 1: .4}, {0: .6, 1: -1.8}))
    results = {}
    for name, module in (("legacy", old), ("repaired", flow)):
        with patch.object(module, "INTERIOR", 2), patch.object(primitive, "INTERIOR", 2), \
                patch.object(old, "_extended", repaired_constructor):
            state = empty(module, 2)
            state.active[:, 0] = np.array([1., -.3, .8, -.5, .07])[:, None] * np.array([.6, .4])
            reset = [.25, .75]
            _, packets, _ = module._advance(state, (), F(0), F(1, 100), primitive,
                spatial, (1.1, 0.), (0., 1.2), reset, "synthetic-control",
                module._numeric_modules(), module.Counts())
            branch = []
            for future_reset in ([.25, .75], [.8, .2]):
                actual, _, _ = module._advance(empty(module, 2), copy.deepcopy(packets),
                    F(1, 5), F(21, 100), primitive, spatial, (1.1, 0.), (0., 1.2),
                    future_reset, "synthetic-control", module._numeric_modules(), module.Counts())
                branch.append(actual.active[:, 1].copy())
            reset[:] = [.9, .1]
            if name == "repaired" and packets[0].reset != (.25, .75):
                raise ValueError("event snapshot aliases caller reset")
            results[name] = {"first": branch[0].tolist(), "changed_future": branch[1].tolist(),
                            "max_abs_difference": float(np.max(np.abs(branch[0] - branch[1])))}
    if results["legacy"]["max_abs_difference"] < 1e-4 or results["repaired"]["max_abs_difference"] != 0:
        raise ValueError("event-time reset regression")
    return results


def run():
    return {"constructor": constructor_case(), "no_parent_occupation": occupation_case(False),
            "latent_parent_occupation": occupation_case(True),
            "event_reset": reset_case(), "authentic_n256_inputs": 0,
            "optimizer_steps": 0, "old_source_unchanged": True,
            "legacy_later_controls": "constructor-only in-memory repair to expose independent occupation/reset defects"}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, indent=2, allow_nan=False))
