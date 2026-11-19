"""Compare the actual first-segment RHS with the sparse Jacobian callback.

This performs no ODE solve and no optimizer update. Every augmented state
coordinate is perturbed at two steps, including all signed-content channels.
"""

import argparse
from fractions import Fraction
import hashlib
import inspect
import json
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde import sensitivities
from qualification.hcsn_joint_dde.graded_sensitivities import solve_graded_partials


class CapturedSegment(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    sources = [
        Path(__file__),
        Path(inspect.getfile(sensitivities)),
        Path(inspect.getfile(solve_graded_partials)),
        Path(inspect.getfile(GradedJointModel)),
        Path(inspect.getfile(GradedSpatialGenerator)),
        Path(inspect.getfile(GradedJointModel.solve)),
        Path(inspect.getfile(Packet)),
    ]

    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}

    before = hashes()
    model = GradedJointModel(
        GradedSpatialGenerator(16, 2.0, -0.12, 0.5, 4.0), 0.53, 0.2, 0.15
    )
    active = np.zeros(17)
    active[8] = 0.6
    content = np.column_stack([2 * active, -3 * active, 0.7 * active, -0.2 * active])
    phase = (
        Packet("atom0", Fraction(0), Fraction(0), Fraction(1, 10), (1, -2, 3, -4)),
        Packet("source", Fraction(0), Fraction(1, 20), Fraction(3, 10), (-2, 3, -4, 5)),
    )
    arrays, cases = {}, []

    def capture(rhs, span, initial, **options):
        if span != (0.0, 0.02) or "jac" not in options:
            raise AssertionError("expected exact-Jacobian first segment")
        state = initial + 0.01 * np.sin(np.arange(len(initial)))
        arrays["state"] = state
        for index, time in enumerate((0.0, 0.007, 0.019)):
            exact = options["jac"](time, state).toarray()
            arrays[f"time{index}_jacobian"] = exact
            for label, step in (("coarse", 2e-6), ("fine", 1e-6)):
                differences = np.empty_like(exact)
                for column in range(len(state)):
                    high, low = state.copy(), state.copy()
                    high[column] += step
                    low[column] -= step
                    differences[:, column] = (rhs(time, high) - rhs(time, low)) / (
                        2 * step
                    )
                arrays[f"time{index}_{label}_fd"] = differences
                ratio = abs(exact - differences) / (1e-7 + 1e-8 * abs(differences))
                cases.append(
                    dict(
                        time=time,
                        step=step,
                        shape=list(exact.shape),
                        coordinates=exact.size,
                        nonzeros=int(np.count_nonzero(exact)),
                        maximum_absolute_error=float(np.max(abs(exact - differences))),
                        maximum_gate_ratio=float(np.max(ratio)),
                        gate_failures=int(np.count_nonzero(ratio > 1)),
                    )
                )
        raise CapturedSegment

    with patch.object(sensitivities, "solve_ivp", capture):
        try:
            solve_graded_partials(model, [0.0, 0.02], active, content, phase)
        except CapturedSegment:
            pass
        else:
            raise AssertionError("RHS capture did not run")
    np.savez_compressed(args.output / "ARRAYS.npz", **arrays)
    passed = (
        before == hashes()
        and len(cases) == 6
        and not any(c["gate_failures"] for c in cases)
    )
    report = dict(
        status="PASS" if passed else "HOLD",
        cases=cases,
        source_sha256=before,
        source_unchanged=before == hashes(),
        arrays_sha256=hashlib.sha256(
            (args.output / "ARRAYS.npz").read_bytes()
        ).hexdigest(),
        wall_seconds=time.perf_counter() - start,
        ode_solves=0,
        optimizer_updates=0,
        scope="Actual first-segment augmented RHS at one n16 marked fixture, not flow or continuum qualification",
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
