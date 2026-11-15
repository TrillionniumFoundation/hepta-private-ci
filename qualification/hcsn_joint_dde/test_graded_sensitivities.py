"""New-geometry physical partial qualification, independent of uniform receipts."""

from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import unittest

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.graded_sensitivities import solve_graded_partials
from qualification.hcsn_joint_dde.sensitivities import PARAMETERS, solve_partials


def flatten(row):
    return np.concatenate(
        [
            np.asarray(row[name]).ravel()
            for name in (
                "active",
                "upper",
                "refractory",
                "events",
                "discounted_events",
                "discounted_active_time",
                "discounted_remaining_phase",
            )
        ]
    )


class GradedVariations(unittest.TestCase):
    def test_actual_node_partials_with_two_fd_steps_and_raw_arrays(self):
        source_root = Path(__file__).parents[1]
        names = [
            "hcsn_joint_dde/model.py",
            "hcsn_joint_dde/sensitivities.py",
            "hcsn_joint_dde/graded_sensitivities.py",
            "hcsn_joint_dde/test_graded_sensitivities.py",
            "hcsn_graded/model.py",
            "hcsn_graded/spatial.py",
            "hcsn_boundary_audit/refractory_transport.py",
        ]
        before = {
            name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
            for name in names
        }
        cases = []
        developmental = GradedJointModel(
            GradedSpatialGenerator(16, 2.0, -0.12, 0.5, 4), 0.53, 0.2, 0.15
        )
        point = np.zeros(17)
        point[np.argmin(abs(developmental.spatial.nodes - 0.5))] = 1
        actual = GradedJointModel(
            GradedSpatialGenerator(64, 8.0, -0.12, 0.35, 6), 0.319, 0.2, 0.15
        )
        actual_point = np.zeros(65)
        actual_point[np.argmin(abs(actual.spatial.nodes - 0.15))] = 1
        fixtures = [
            ("graded_point", developmental, point, (), [0.0, 0.1, 0.2, 0.35, 0.6], 3),
            (
                "graded_atom",
                developmental,
                point * 0,
                (Packet("atom", Fraction(1, 10), Fraction(1, 10), 1, (2, -3)),),
                [0.0, 0.1, 0.2, 0.35, 0.6],
                3,
            ),
            (
                "graded_uniform",
                developmental,
                point * 0,
                (Packet("uniform", Fraction(1, 20), Fraction(3, 20), 1, (2, -3)),),
                [0.0, 0.1, 0.2, 0.35, 0.6],
                3,
            ),
            (
                "training_range_profile",
                actual,
                actual_point * 0.6,
                (
                    Packet(
                        "uniform",
                        Fraction(0),
                        Fraction(1, 20),
                        Fraction(2, 5),
                        (Fraction(4, 5),),
                    ),
                ),
                [0.0, 0.001, 0.02, 0.08],
                2,
            ),
        ]
        options = dict(rtol=2e-11, atol=2e-13, max_step=0.015)
        for label, model, probability, phase, times, channels in fixtures:
            content = np.column_stack((2 * probability, -3 * probability))[
                :, : channels - 1
            ]
            result = solve_graded_partials(
                model, times, probability, content, phase, **options
            )
            core = model.solve(times, probability, content, phase, **options)
            row = result["rows"][-1]
            np.testing.assert_allclose(
                flatten(row["primal"]), flatten(core["rows"][-1]), rtol=0, atol=3e-9
            )
            for parameter in PARAMETERS:
                derivative = flatten(row["partials"][parameter])
                differences = []
                for step in (2e-4, 1e-4):

                    def change(direction):
                        delta = direction * step
                        if parameter == "log_boundary":
                            return replace(model, reset=model.reset - delta)
                        if parameter == "absolute_reset":
                            return replace(
                                model, reset=math.log(math.exp(model.reset) + delta)
                            )
                        if parameter == "discount":
                            return replace(model, discount=model.discount + delta)
                        return replace(
                            model,
                            spatial=replace(
                                model.spatial,
                                **{
                                    parameter: getattr(model.spatial, parameter) + delta
                                },
                            ),
                        )

                    high, low = (
                        change(sign).solve(
                            times, probability, content, phase, **options
                        )
                        for sign in (1, -1)
                    )
                    difference = (
                        flatten(high["rows"][-1]) - flatten(low["rows"][-1])
                    ) / (2 * step)
                    differences.append(difference)
                    np.testing.assert_allclose(
                        derivative, difference, rtol=4e-4, atol=3e-6
                    )
                np.testing.assert_allclose(
                    differences[0], differences[1], rtol=6e-4, atol=5e-6
                )
                cases.append(
                    dict(
                        case=label,
                        parameter=parameter,
                        coordinates=len(derivative),
                        variational=derivative.tolist(),
                        coarse_fd=differences[0].tolist(),
                        fine_fd=differences[1].tolist(),
                        steps=[2e-4, 1e-4],
                        primal=flatten(row["primal"]).tolist(),
                        nodes=model.spatial.nodes.tolist(),
                        maximum_absolute_error=float(
                            np.max(abs(derivative - differences[1]))
                        ),
                    )
                )
        self.assertEqual(
            before,
            {
                name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                for name in names
            },
        )
        print(
            "GRADED_VARIATIONAL_EVIDENCE",
            json.dumps(
                dict(
                    cases=cases,
                    sources=before,
                    source_unchanged=True,
                    absolute_tolerance=3e-6,
                    relative_tolerance=4e-4,
                ),
                sort_keys=True,
            ),
        )

    def test_uniform_entry_refuses_graded_and_actual_knots_are_rejected(self):
        model = GradedJointModel(
            GradedSpatialGenerator(16, 2.0, -0.12, 0.5, 4), 0.53, 0.2, 0.15
        )
        probability = np.zeros(17)
        probability[8] = 1
        marked = probability[:, None]
        with self.assertRaises(ValueError):
            solve_partials(model, [0.1], probability, marked)
        at_knot = replace(model, reset=float(model.spatial.nodes[10]))
        with self.assertRaises(ValueError):
            solve_graded_partials(at_knot, [0.1], probability, marked)
        oversized = GradedJointModel(
            GradedSpatialGenerator(1024, 2.0, -0.12, 0.5, 4), 0.53, 0.2, 0.15
        )
        with self.assertRaises(ValueError):
            solve_graded_partials(
                oversized, [0.1], np.zeros(1025), np.zeros((1025, 16))
            )

    def test_graded_mark_conservation_boundary_chain_and_stability(self):
        model = GradedJointModel(
            GradedSpatialGenerator(16, 2.0, -0.12, 0.5, 4), 0.53, 0.2, 0.15
        )
        probability = np.zeros(17)
        probability[8] = 1
        content = np.column_stack((2 * probability, -3 * probability))
        loose = solve_graded_partials(
            model, [0.1, 0.4], probability, content, rtol=2e-9, atol=2e-11
        )
        tight = solve_graded_partials(
            model, [0.1, 0.4], probability, content, rtol=2e-11, atol=2e-13
        )
        for j, name in enumerate(PARAMETERS):
            partial = tight["rows"][-1]["partials"][name]
            np.testing.assert_allclose(
                flatten(partial),
                flatten(loose["rows"][-1]["partials"][name]),
                rtol=2e-4,
                atol=2e-6,
            )
            np.testing.assert_allclose(
                partial["active"].sum(0) + partial["upper"] + partial["refractory"],
                0,
                atol=2e-9,
            )
        boundary = flatten(tight["rows"][-1]["partials"]["log_boundary"])
        reset = flatten(tight["rows"][-1]["partials"]["absolute_reset"])
        np.testing.assert_allclose(
            boundary, -math.exp(model.reset) * reset, atol=2e-9, rtol=1e-8
        )


if __name__ == "__main__":
    unittest.main()
