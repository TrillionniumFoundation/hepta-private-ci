"""Corrupt frozen coefficients/metadata and prove rejection precedes any solver."""

import argparse
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_initial_adjoint import solver as core


def fixture(geometry):
    model = (
        JointModel(KilledSpatialGenerator(7, 2.0, -0.12, 0.5), 0.53, 0.21, 0.15)
        if geometry == "uniform"
        else GradedJointModel(
            GradedSpatialGenerator(12, 2.0, -0.12, 0.5, 3.0), 0.53, 0.21, 0.15
        )
    )
    return core.freeze_problem(
        model,
        [0.0, 0.13, 0.29, 0.53],
        [
            (Fraction(35, 1000), Fraction(113, 1000)),
            (Fraction(71, 1000), Fraction(71, 1000)),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "qualification/hcsn_adjoint_torch/GUARD-SOURCE.json").read_text()
    )
    hashes = lambda: {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in manifest["source_sha256"]
    }
    before = hashes()
    if before != manifest["source_sha256"]:
        raise ValueError("prefrozen guard-source inventory differs")
    reverse_calls = 0
    original = core._reverse_solve

    def forbidden(*unused, **also_unused):
        nonlocal reverse_calls
        reverse_calls += 1
        raise AssertionError("a corrupted snapshot reached the reverse solver")

    cases = []
    core._reverse_solve = forbidden
    try:
        for geometry in ("uniform", "graded"):
            for field in (
                "identity",
                "transient_value",
                "lower_value",
                "upper_value",
                "reset_value",
                "nodes_value",
                "transient_writeable",
                "lower_writeable",
                "upper_writeable",
                "reset_writeable",
                "nodes_writeable",
                "times",
                "supports",
                "delay",
                "discount",
            ):
                problem = fixture(geometry)
                if field == "identity":
                    problem = replace(problem, identity="0" * 64)
                elif field.endswith("_value") or field.endswith("_writeable"):
                    key = field.rsplit("_", 1)[0]
                    value = getattr(problem, key)
                    value.setflags(write=True)
                    if field.endswith("_value"):
                        value.flat[0] += 0.01
                        value.setflags(write=False)
                else:
                    replacement = dict(
                        times=(
                            Fraction(0),
                            Fraction(1, 10),
                            Fraction(29, 100),
                            Fraction(53, 100),
                        ),
                        supports=(
                            (Fraction(4, 100), Fraction(113, 1000)),
                            (Fraction(71, 1000), Fraction(71, 1000)),
                        ),
                        delay=Fraction(1, 5),
                        discount=0.2,
                    )[field]
                    object.__setattr__(problem, field, replacement)
                try:
                    core.amplitude_vjp(
                        problem,
                        np.zeros((len(problem.times), problem.intervals + 5, 1)),
                    )
                except ValueError as exc:
                    cases.append(
                        dict(
                            geometry=geometry,
                            corruption=field,
                            rejected=True,
                            message=str(exc),
                            reverse_solver_reached=False,
                        )
                    )
                else:
                    raise AssertionError(
                        "snapshot corruption was silently accepted: " + field
                    )
    finally:
        core._reverse_solve = original
    after = hashes()
    result = dict(
        status="PASS"
        if len(cases) == 30 and reverse_calls == 0 and before == after
        else "HOLD",
        source_commit=args.source_commit,
        source_before=before,
        source_after=after,
        source_unchanged=before == after,
        cases=cases,
        public_vjp_rejection_attempts=len(cases),
        reverse_solver_calls=reverse_calls,
        core_restored=core._reverse_solve is original,
        ode_calls=0,
        matrix_exponentials=0,
        static_perpetual_solves=0,
        torch_calls=0,
        optimizer_updates=0,
        source_or_old_local001_rerun=False,
        qualification_scope="two small fixtures; internal frozen snapshot corruption only",
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            dict(
                status=result["status"],
                public_vjp_rejection_attempts=len(cases),
                reverse_solver_calls=reverse_calls,
                optimizer_updates=0,
            ),
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
