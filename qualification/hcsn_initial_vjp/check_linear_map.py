"""Independent directional finite differences of actual initial amplitudes."""

import argparse
from fractions import Fraction
import hashlib
import inspect
import json
from pathlib import Path
import resource
import time

import numpy as np

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
from .linear_map import direct_flow, initial_map


def fixture(geometry):
    if geometry == "uniform":
        count = 7
        model = JointModel(
            KilledSpatialGenerator(count, 2.0, -0.12, 0.5), 0.53, 0.21, 0.15
        )
    elif geometry == "graded":
        count = 12
        model = GradedJointModel(
            GradedSpatialGenerator(count, 2.0, -0.12, 0.5, 3.0), 0.53, 0.21, 0.15
        )
    else:
        raise ValueError("explicit uniform or graded fixture required")
    active = np.linspace(0.04, 0.09, count)
    active *= 0.55 / active.sum()
    content = np.column_stack(
        [0.17 * np.cos(np.arange(count)), 0.23 * np.sin(np.arange(count) + 0.3)]
    )
    mass = np.array([0.2, 0.15])
    phase_content = np.array([[-0.31, 0.27], [0.23, -0.13]])
    supports = (
        (Fraction(35, 1000), Fraction(113, 1000)),
        (Fraction(71, 1000), Fraction(71, 1000)),
    )
    return (
        model,
        [0.0, 0.13, 0.29, 0.53],
        supports,
        (active, content, mass, phase_content),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    sources = [
        Path(__file__),
        Path(inspect.getfile(initial_map)),
        Path(inspect.getfile(JointModel)),
        Path(inspect.getfile(GradedJointModel)),
        Path(inspect.getfile(KilledSpatialGenerator)),
        Path(inspect.getfile(GradedSpatialGenerator)),
    ]

    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}

    before = hashes()
    arrays, reports = {}, []
    options = dict(rtol=2e-11, atol=2e-13, max_step=0.01)
    for geometry in ("uniform", "graded"):
        model, times, supports, inputs = fixture(geometry)
        count = model.spatial.intervals
        mapped = initial_map(model, times, supports, **options)
        operator = mapped["operator"]
        amplitudes = np.vstack(
            [np.c_[inputs[0], inputs[1]], np.c_[inputs[2], inputs[3]]]
        )
        predicted = np.einsum("tsd,dc->tsc", operator, amplitudes)
        actual = direct_flow(model, times, *inputs, supports, **options)
        maximum_primal = float(np.max(abs(predicted - actual)))
        if maximum_primal > 3e-9:
            raise ArithmeticError(
                "shared signed-direction map disagrees with actual initial forward"
            )
        cotangent = np.sin(np.arange(actual.size) + 0.2).reshape(actual.shape)
        vjp = np.einsum("tsd,tsc->dc", operator, cotangent)
        arrays[f"{geometry}_operator"] = operator
        arrays[f"{geometry}_primal_direct"] = actual
        arrays[f"{geometry}_primal_map"] = predicted
        arrays[f"{geometry}_cotangent"] = cotangent
        arrays[f"{geometry}_vjp"] = vjp
        for index, value in enumerate(inputs):
            arrays[f"{geometry}_input{index}"] = value
        cases = []
        for selected in range(5):
            directions = [
                np.sin(np.arange(v.size) + 0.4 + index).reshape(v.shape)
                / max(1, v.size)
                if selected in (index, 4)
                else np.zeros_like(v)
                for index, v in enumerate(inputs)
            ]
            direction = np.vstack(
                [
                    np.c_[directions[0], directions[1]],
                    np.c_[directions[2], directions[3]],
                ]
            )
            jvp = np.einsum("tsd,dc->tsc", operator, direction)
            projection = float(np.sum(vjp * direction))
            differences = []
            for label, step in (("coarse", 2e-4), ("fine", 1e-4)):
                high = direct_flow(
                    model,
                    times,
                    *(v + step * d for v, d in zip(inputs, directions)),
                    supports,
                    **options,
                )
                low = direct_flow(
                    model,
                    times,
                    *(v - step * d for v, d in zip(inputs, directions)),
                    supports,
                    **options,
                )
                fd = (high - low) / (2 * step)
                differences.append(fd)
                ratio = abs(jvp - fd) / (2e-7 + 2e-5 * abs(fd))
                prefix = f"{geometry}_direction{selected}_{label}"
                arrays[prefix + "_high"], arrays[prefix + "_low"] = high, low
                arrays[prefix + "_fd"] = fd
                cases.append(
                    dict(
                        direction=selected,
                        step=step,
                        coordinates=fd.size,
                        maximum_absolute_error=float(np.max(abs(jvp - fd))),
                        maximum_gate_ratio=float(np.max(ratio)),
                        gate_failures=int(np.count_nonzero(ratio > 1)),
                        projected_vjp=projection,
                        projected_fd=float(np.sum(fd * cotangent)),
                    )
                )
            arrays[f"{geometry}_direction{selected}"] = direction
            arrays[f"{geometry}_direction{selected}_jvp"] = jvp
            stable = abs(differences[0] - differences[1]) / (
                3e-7 + 3e-5 * abs(differences[1])
            )
            if np.any(stable > 1):
                raise ArithmeticError("initial-amplitude directional FD is unstable")
        reports.append(
            dict(
                geometry=geometry,
                intervals=count,
                maximum_primal_error=maximum_primal,
                map_scalars=mapped["map_scalars"],
                basis_forward_calls=mapped["basis_forward_calls"],
                basis_costs=mapped["basis_costs"],
                direct_forward_calls=21,
                cases=cases,
            )
        )
    np.savez_compressed(args.output / "ARRAYS.npz", **arrays)
    passed = before == hashes() and not any(
        c["gate_failures"] for r in reports for c in r["cases"]
    )
    result = dict(
        status="PASS" if passed else "HOLD",
        reports=reports,
        source_sha256=before,
        source_unchanged=before == hashes(),
        arrays_sha256=hashlib.sha256(
            (args.output / "ARRAYS.npz").read_bytes()
        ).hexdigest(),
        steps=[2e-4, 1e-4],
        absolute_gate=2e-7,
        relative_gate=2e-5,
        wall_seconds=time.perf_counter() - started,
        cpu_seconds=time.process_time() - cpu,
        maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        optimizer_updates=0,
        native_torch_qualified=False,
        projection_not_exhaustive_initial_jacobian=True,
        independent_future_task=False,
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
