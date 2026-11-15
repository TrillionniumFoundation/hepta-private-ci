"""Physical variational-flow checks; no network or Torch model is imported."""

from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import unittest

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
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


class VariationalFlow(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(
            KilledSpatialGenerator(8, 2.0, -0.12, 0.5), 0.53, 0.2, 0.15
        )
        self.point = np.zeros(9)
        self.point[2] = 1
        self.times = [0.0, 0.1, 0.2, 0.35, 0.6]
        self.options = dict(rtol=2e-11, atol=2e-13, max_step=0.015)

    def test_all_output_partials_against_two_steps_for_three_initial_laws(self):
        sources = [
            Path(__file__),
            Path(__file__).with_name("sensitivities.py"),
            Path(__file__).with_name("model.py"),
            Path(__file__).parents[1] / "hcsn_boundary_audit/spatial_generator.py",
            Path(__file__).parents[1] / "hcsn_boundary_audit/refractory_transport.py",
        ]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        evidence = []
        for name, probability, phase in (
            ("point", self.point, ()),
            (
                "atom",
                self.point * 0,
                (Packet("atom", Fraction(1, 10), Fraction(1, 10), 1, (2, -3)),),
            ),
            (
                "uniform",
                self.point * 0,
                (Packet("uniform", Fraction(1, 20), Fraction(3, 20), 1, (2, -3)),),
            ),
        ):
            content = np.column_stack((2 * probability, -3 * probability))
            values = solve_partials(
                self.model, self.times, probability, content, phase, **self.options
            )
            core = self.model.solve(
                self.times, probability, content, phase, **self.options
            )
            actual = values["rows"][-1]
            np.testing.assert_allclose(
                flatten(actual["primal"]), flatten(core["rows"][-1]), rtol=0, atol=2e-9
            )
            for parameter in PARAMETERS:
                derivative = flatten(actual["partials"][parameter])
                finite_differences = []
                for step in (2e-4, 1e-4):

                    def perturbed(sign):
                        delta = sign * step
                        if parameter == "log_boundary":
                            return replace(self.model, reset=self.model.reset - delta)
                        if parameter == "absolute_reset":
                            return replace(
                                self.model,
                                reset=math.log(math.exp(self.model.reset) + delta),
                            )
                        if parameter == "discount":
                            return replace(
                                self.model, discount=self.model.discount + delta
                            )
                        return replace(
                            self.model,
                            spatial=replace(
                                self.model.spatial,
                                **{
                                    parameter: getattr(self.model.spatial, parameter)
                                    + delta
                                },
                            ),
                        )

                    high = perturbed(1).solve(
                        self.times, probability, content, phase, **self.options
                    )
                    low = perturbed(-1).solve(
                        self.times, probability, content, phase, **self.options
                    )
                    fd = (flatten(high["rows"][-1]) - flatten(low["rows"][-1])) / (
                        2 * step
                    )
                    finite_differences.append(fd)
                    np.testing.assert_allclose(derivative, fd, rtol=3e-4, atol=2e-6)
                np.testing.assert_allclose(
                    finite_differences[0], finite_differences[1], rtol=5e-4, atol=3e-6
                )
                evidence.append(
                    dict(
                        case=name,
                        parameter=parameter,
                        coordinates=len(derivative),
                        maximum_absolute_error=float(np.max(np.abs(derivative - fd))),
                        coarse_fine_maximum=float(
                            np.max(
                                np.abs(finite_differences[0] - finite_differences[1])
                            )
                        ),
                        variational=derivative.tolist(),
                        coarse_fd=finite_differences[0].tolist(),
                        fine_fd=finite_differences[1].tolist(),
                        steps=[2e-4, 1e-4],
                        final_primal=flatten(actual["primal"]).tolist(),
                    )
                )
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        self.assertEqual(before, after)
        print(
            "VARIATIONAL_EVIDENCE",
            json.dumps(
                dict(
                    cases=evidence,
                    source_sha256=before,
                    source_unchanged=True,
                    query_times=self.times,
                    tested_time=self.times[-1],
                    absolute_tolerance=2e-6,
                    relative_tolerance=3e-4,
                ),
                sort_keys=True,
            ),
        )

    def test_boundary_reset_chain_and_marked_mass_derivatives(self):
        result = solve_partials(
            self.model,
            self.times,
            self.point,
            np.column_stack((2 * self.point, -3 * self.point)),
            **self.options,
        )["rows"][-1]
        boundary = flatten(result["partials"]["log_boundary"])
        reset = flatten(result["partials"]["absolute_reset"])
        np.testing.assert_allclose(
            boundary, -math.exp(self.model.reset) * reset, rtol=1e-8, atol=2e-9
        )
        for name, partial in result["partials"].items():
            total = (
                partial["active"].sum(axis=0) + partial["upper"] + partial["refractory"]
            )
            np.testing.assert_allclose(total, 0, rtol=0, atol=2e-9, err_msg=name)
            for key, value in partial.items():
                np.testing.assert_allclose(
                    value[..., 1], 2 * value[..., 0], rtol=1e-8, atol=2e-9
                )
                np.testing.assert_allclose(
                    value[..., 2], -3 * value[..., 0], rtol=1e-8, atol=2e-9
                )

    def test_initial_zero_atom_reset_and_initial_discounted_phase_derivative(self):
        phase = (
            Packet(
                "atom",
                Fraction(0),
                Fraction(0),
                Fraction(2, 5),
                (Fraction(1), Fraction(-7, 10)),
            ),
            Packet(
                "uniform",
                Fraction(1, 20),
                Fraction(3, 20),
                Fraction(3, 5),
                (Fraction(3, 2), Fraction(-21, 20)),
            ),
        )
        result = solve_partials(
            self.model, [0.0], self.point * 0, np.zeros((9, 2)), phase, **self.options
        )["rows"][0]
        self.assertGreater(
            np.max(np.abs(result["partials"]["absolute_reset"]["active"])), 0
        )
        self.assertLess(
            result["partials"]["discount"]["discounted_remaining_phase"][0], 0
        )
        for name in ("mu", "sigma"):
            np.testing.assert_array_equal(flatten(result["partials"][name]), 0)

    def test_zero_rate_reset_knots_and_physical_identity_fail_closed(self):
        zero = np.zeros((9, 1))
        for model in (
            replace(self.model, reset=0.5),
            replace(self.model, spatial=KilledSpatialGenerator(8, 2.0, 1.0, 0.5)),
        ):
            with self.assertRaises(ValueError):
                solve_partials(model, self.times, self.point, zero)
        with self.assertRaises(ValueError):
            solve_partials(self.model, self.times, self.point, zero, absolute_reset=1.0)
        with self.assertRaises(ValueError):
            solve_partials(self.model, self.times, self.point, zero, log_boundary=True)
        with self.assertRaises(ValueError):
            solve_partials(
                self.model,
                [0.0],
                self.point,
                zero,
                log_boundary=math.log(1e-323) - self.model.reset,
                absolute_reset=1e-323,
            )

    def test_new_geometry_cannot_silently_reuse_uniform_jacobian(self):
        class OtherGeometry(KilledSpatialGenerator):
            pass

        changed = replace(self.model, spatial=OtherGeometry(8, 2.0, -0.12, 0.5))
        with self.assertRaises(ValueError):
            solve_partials(changed, self.times, self.point, np.zeros((9, 1)))


if __name__ == "__main__":
    unittest.main()
