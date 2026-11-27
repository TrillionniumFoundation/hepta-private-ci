"""Independent time, renewal, content and unchanged continuation gate controls."""

from fractions import Fraction as F
import math
import unittest

import numpy as np
from scipy.special import ndtr

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from .basis import basis_values
from .model import JointModel
from .reference import renewal_events


def fixture(n=32):
    return JointModel(KilledSpatialGenerator(n, 2.0, -0.12, 0.35), 0.5, 0.2, 0.15)


def initial(model, point=0.5):
    nodes = np.linspace(0, model.spatial.endpoint, model.spatial.intervals + 1)
    p = np.zeros_like(nodes)
    p[int(np.argmin(abs(nodes - point)))] = 1.0
    return p, np.c_[2 * p, -3 * p]


def serial_reference(model, horizon, probability):
    transient, lower, upper, reset = model.ingredients()

    def events(time):
        if time <= 0:
            return {"expected_events": 0.0, "discounted_events": 0.0}
        return renewal_events(
            transient,
            lower,
            upper,
            probability[1:-1],
            reset,
            horizon=time,
            delay=model.delay,
            discount=model.discount,
        )

    end, past = events(horizon), events(horizon - model.delay)
    refractory = end["expected_events"] - past["expected_events"]
    ref_occupation = (
        end["discounted_events"]
        - math.exp(-model.discount * model.delay) * past["discounted_events"]
        - math.exp(-model.discount * horizon) * refractory
    ) / model.discount
    active_occupation = (
        -math.expm1(-model.discount * horizon) / model.discount - ref_occupation
    )
    return np.asarray(
        [
            end["expected_events"],
            end["discounted_events"],
            refractory,
            active_occupation,
        ]
    )


class TestJointDelayReset(unittest.TestCase):
    def test_active_flow_matches_independent_serial_ctmc_and_signed_marks(self):
        model = fixture()
        p, content = initial(model)
        rows = model.solve(
            [0.0, 0.1, 0.2, 0.3, 0.5, 1.0],
            p,
            content,
            rtol=2e-11,
            atol=2e-13,
            max_step=0.01,
        )["rows"]
        for row in rows[1:]:
            actual = np.asarray(
                [
                    row["events"][0],
                    row["discounted_events"][0],
                    row["refractory"][0],
                    row["discounted_active_time"][0],
                ]
            )
            np.testing.assert_allclose(
                actual, serial_reference(model, row["time"], p), atol=2e-9, rtol=2e-9
            )
            self.assertLess(abs(row["mass_residual"]), 2e-10)
            np.testing.assert_allclose(row["content_residual"], 0, atol=2e-10)
            for name in (
                "active",
                "upper",
                "refractory",
                "events",
                "discounted_events",
            ):
                values = row[name]
                np.testing.assert_allclose(
                    values[..., 1], 2 * values[..., 0], atol=2e-12
                )
                np.testing.assert_allclose(
                    values[..., 2], -3 * values[..., 0], atol=2e-12
                )

    def test_time_tightening_and_irregular_queries_converge_to_serial_reference(self):
        model = fixture()
        p, content = initial(model)
        reference = serial_reference(model, 1.0, p)

        def result(times, **controls):
            row = model.solve(times, p, content, **controls)["rows"][-1]
            return np.asarray(
                [
                    row["events"][0],
                    row["discounted_events"][0],
                    row["refractory"][0],
                    row["discounted_active_time"][0],
                ]
            )

        loose = result(
            [0.0, 0.1, 0.2, 0.3, 0.5, 1.0], rtol=2e-7, atol=2e-9, max_step=0.05
        )
        tight = result(
            [0.0, 0.1, 0.2, 0.3, 0.5, 1.0], rtol=2e-11, atol=2e-13, max_step=0.01
        )
        other = result(
            [0.0, 0.017, 0.137, 0.411, 1.0], rtol=2e-11, atol=2e-13, max_step=0.01
        )
        self.assertLess(max(abs(tight - reference)), max(abs(loose - reference)) / 4)
        np.testing.assert_allclose(tight, other, atol=3e-10, rtol=0)

    def test_exact_phase_atom_releases_at_its_deadline(self):
        model = fixture()
        p = np.zeros(33)
        packet = Packet("atom", F(7, 100), F(7, 100), F(1), (F(2), F(-3)))
        rows = model.solve(
            [0.052, 0.07, 0.1, 1.0],
            p,
            np.zeros((33, 2)),
            (packet,),
            rtol=2e-11,
            atol=2e-13,
            max_step=0.01,
        )["rows"]
        self.assertEqual(rows[0]["active"].sum(), 0)
        self.assertEqual(rows[0]["refractory"][0], 1)
        self.assertAlmostEqual(rows[1]["active"][:, 0].sum(), 1.0, places=12)
        self.assertAlmostEqual(rows[1]["refractory"][0], 0.0, places=12)
        _, _, _, reset = model.ingredients()
        reset_initial = np.r_[0.0, reset, 0.0]
        reference = serial_reference(model, 0.93, reset_initial)
        row = rows[-1]
        self.assertAlmostEqual(row["events"][0], reference[0], delta=2e-9)
        self.assertAlmostEqual(
            row["discounted_events"][0],
            math.exp(-0.15 * 0.07) * reference[1],
            delta=2e-9,
        )

    def test_uniform_phase_release_matches_independent_matrix_quadrature(self):
        model = fixture()
        packet = Packet("uniform", F(3, 50), F(2, 25), F(1), (F(2), F(-3)))
        row = model.solve(
            [0.052, 0.1],
            np.zeros(33),
            np.zeros((33, 2)),
            (packet,),
            rtol=2e-11,
            atol=2e-13,
            max_step=0.005,
        )["rows"][-1]
        _, _, _, reset = model.ingredients()
        law = np.r_[0.0, reset, 0.0]
        references = []
        for count in (16, 32):
            nodes, weights = np.polynomial.legendre.leggauss(count)
            releases = 0.07 + 0.01 * nodes
            references.append(
                sum(
                    weight * (law @ model.spatial.transition(0.1 - release))
                    for weight, release in zip(weights, releases)
                )
                / 2
            )
        np.testing.assert_allclose(references[0], references[1], atol=3e-14, rtol=0)
        np.testing.assert_allclose(
            row["active"][:, 0], references[1][1:-1], atol=3e-10, rtol=0
        )
        self.assertAlmostEqual(row["refractory"][0], references[1][0], delta=3e-10)

    def test_backward_continuation_is_consistent_with_actual_delayed_flow(self):
        model = fixture()
        p, content = initial(model)
        row = model.solve(
            [0.0, 0.173, 0.417, 1.0], p, content, rtol=2e-11, atol=2e-13, max_step=0.01
        )["rows"][-1]
        values, reset_value = model.perpetual()
        terminal = (
            row["active"][:, 0] @ values[1:-1]
            + row["upper"][0] * model.active_reward / model.discount
        )
        terminal += row["discounted_remaining_phase"][0] * reset_value
        actual = (
            model.active_reward * row["discounted_active_time"][0]
            + model.hit_reward * row["discounted_events"][0]
            + math.exp(-model.discount) * terminal
        )
        self.assertAlmostEqual(actual, float(p @ values), delta=5e-9)

    def test_upper_escape_is_retained_active_and_exposes_returning_tail_difference(
        self,
    ):
        model = fixture()
        p, content = initial(model, point=1.75)
        row = model.solve([0.0, 1.0], p, content, rtol=2e-10, atol=2e-12)["rows"][-1]
        self.assertGreater(row["upper"][0], 0.1)
        self.assertLess(abs(row["mass_residual"]), 2e-9)
        values = basis_values(
            JointModel(KilledSpatialGenerator(128, 8.0, -0.12, 0.35), 0.32, 0.2, 0.15)
        )
        self.assertGreater(max(abs(values["upper_truncation_error"])), 1e-8)
        self.assertLess(
            max(
                abs(values["candidate"] - values["halfline_continuum"])
                / np.maximum(1, abs(values["halfline_continuum"]))
            ),
            0.01,
        )

    def test_same_law_uniform_basis_integrals_refine_without_relaxing_one_percent(self):
        errors = []
        for n in (128, 256, 512):
            values = basis_values(
                JointModel(KilledSpatialGenerator(n, 8.0, -0.12, 0.35), 0.32, 0.2, 0.15)
            )
            error = max(
                (
                    abs(values["spatial_reset_basis_error"])
                    + abs(values["upper_truncation_error"])
                )
                / np.maximum(1, abs(values["halfline_continuum"]))
            )
            self.assertLess(error, 0.01)
            errors.append(error)
        self.assertTrue(all(right < left for left, right in zip(errors, errors[1:])))

    def test_invalid_phase_budget_reset_and_initial_boundary_atom_fail_closed(self):
        model = fixture()
        p, content = initial(model)
        with self.assertRaises(ValueError):
            model.solve([0.0, 1.0], p, content, (object(),))
        with self.assertRaises(ValueError):
            JointModel(model.spatial, 0.001, 0.2, 0.15)
        with self.assertRaises(ValueError):
            JointModel(model.spatial, 0.5, 1e-100, 0.15).solve([0.0, 1.0], p, content)
        p[0] = 0.1
        with self.assertRaises(ValueError):
            model.solve([0.0, 0.1], p, content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
