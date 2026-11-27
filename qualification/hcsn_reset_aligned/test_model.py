"""Independent generator/DDE differences for the exact-reset moving mesh."""

from fractions import Fraction
import json
import math
import unittest

import numpy as np

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator, continuum_lower_hit
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_reset_aligned.mesh import aligned_model
from qualification.hcsn_reset_aligned.sensitivities import PARAMETERS, solve_aligned_partials


OPTIONS = dict(rtol=2e-11, atol=2e-13, max_step=.02)
GEOMETRY = dict(left_intervals=4, right_intervals=4, endpoint=2., grading=1., delay=.2)


def flatten(row):
    return np.concatenate([np.asarray(row[k]).ravel() for k in
        ("active", "upper", "refractory", "events", "discounted_events",
         "discounted_active_time", "discounted_remaining_phase")])


class AlignedReset(unittest.TestCase):
    records = []

    @classmethod
    def tearDownClass(cls):
        print("ALIGNED_RESET_EVIDENCE", json.dumps(dict(records=cls.records,
            initial_law="fixed moving-nodal weights", point_reset_smoothed=False,
            physical_prior_migration_gradients=False, rare_tail_relative_qualified=False), sort_keys=True))

    def setUp(self):
        self.theta = np.array([.01, -.12, .5, math.exp(.51), .15])
        self.active = np.r_[0., np.arange(1., 9.)/45]
        self.content = np.column_stack((2*self.active, -3*self.active))
        self.phase = (Packet("atom", Fraction(0), Fraction(0), Fraction(1, 10), (Fraction(1,5), Fraction(-3,10))),
                      Packet("uniform", Fraction(1,20), Fraction(3,20), Fraction(1,10), (Fraction(1,5), Fraction(-3,10))))
        self.times = [0., .1, .2, .6]

    def test_generator_jacobian_crosses_old_reset_nodes(self):
        evidence = []
        for reset in (.4999, .5, .5001):
            theta = self.theta.copy()
            theta[3] = math.exp(reset+theta[0])
            model, jacobian = aligned_model(theta, **GEOMETRY)
            self.assertEqual(np.count_nonzero(model.ingredients()[3]), 1)
            np.testing.assert_allclose(model.ingredients()[3].sum(), 1, rtol=0, atol=0)
            for j, name in enumerate(PARAMETERS):
                errors = []
                for step in (2e-5, 1e-5):
                    delta = np.zeros(5)
                    delta[j] = step
                    high = aligned_model(theta+delta, **GEOMETRY)[0].spatial.matrix()
                    low = aligned_model(theta-delta, **GEOMETRY)[0].spatial.matrix()
                    fd = (high-low)/(2*step)
                    np.testing.assert_allclose(jacobian[j], fd, rtol=2e-7, atol=2e-6)
                    errors.append(float(np.max(abs(jacobian[j]-fd))))
                evidence.append(dict(reset=reset, parameter=name, errors=errors))
        self.records.append(dict(case="generator_derivatives", evidence=evidence))

    def test_full_history_physical_partials_match_independent_forward(self):
        evidence = []
        for label, mu, sigma, horizon in (("old_knot", -.12, .5, .6),
                                         ("low_noise", 0., .08, .25),
                                         ("short_time", -.12, .5, .001)):
            theta = self.theta.copy()
            theta[1:3] = mu, sigma
            times = [0., horizon]
            model, jacobian = aligned_model(theta, **GEOMETRY)
            actual = solve_aligned_partials(model, jacobian, times, self.active, self.content,
                                           self.phase, **OPTIONS)["rows"][-1]
            reference = model.solve(times, self.active, self.content, self.phase, **OPTIONS)["rows"][-1]
            np.testing.assert_allclose(flatten(actual["primal"]), flatten(reference), rtol=0, atol=5e-9)
            for j, name in enumerate(PARAMETERS):
                derivative = flatten(actual["partials"][name])
                errors, finite_differences = [], []
                for step in (2e-4, 1e-4):
                    delta = np.zeros(5)
                    delta[j] = step
                    high = aligned_model(theta+delta, **GEOMETRY)[0].solve(times,
                        self.active, self.content, self.phase, **OPTIONS)["rows"][-1]
                    low = aligned_model(theta-delta, **GEOMETRY)[0].solve(times,
                        self.active, self.content, self.phase, **OPTIONS)["rows"][-1]
                    fd = (flatten(high)-flatten(low))/(2*step)
                    np.testing.assert_allclose(derivative, fd, rtol=5e-4, atol=4e-6)
                    errors.append(float(np.max(abs(derivative-fd))))
                    finite_differences.append(fd.tolist())
                evidence.append(dict(case=label, parameter=name, horizon=horizon,
                    maximum_absolute_errors=errors, variational=derivative.tolist(),
                    finite_differences=finite_differences))
                partial = actual["partials"][name]
                np.testing.assert_allclose(partial["active"].sum(0)+partial["upper"]+
                                           partial["refractory"], 0, rtol=0, atol=5e-9)
        self.records.append(dict(case="dde_physical_jacobian", evidence=evidence))

    def test_old_node_left_right_slopes_have_vanishing_gap(self):
        def value(delta):
            theta = self.theta.copy()
            theta[3] = math.exp(.5+theta[0]+delta)
            model = aligned_model(theta, **GEOMETRY)[0]
            return model.solve([0., .6], self.active, self.content, self.phase,
                               **OPTIONS)["rows"][-1]["events"][0]
        center, attempts = value(0), []
        for step in (2e-4, 1e-4):
            left, right = (center-value(-step))/step, (value(step)-center)/step
            attempts.append(dict(step=step, left=left, right=right, gap=abs(left-right)))
        self.assertLess(attempts[1]["gap"], .6*attempts[0]["gap"])
        self.assertLess(attempts[1]["gap"], .002)
        self.records.append(dict(case="old_knot_crossing", attempts=attempts))

    def test_original_uniform_reset_kink_is_retained(self):
        point = np.zeros(9)
        point[1] = 1.
        def value(reset):
            model = JointModel(KilledSpatialGenerator(8, 2., -.12, .5), reset, .2, .15)
            return model.solve([0., .6], point, point[:, None], **OPTIONS)["rows"][-1]["events"][0]
        center, attempts = value(.5), []
        for step in (2e-4, 1e-4):
            left, right = (center-value(.5-step))/step, (value(.5+step)-center)/step
            attempts.append(dict(step=step, left=left, right=right, gap=abs(left-right)))
        self.assertGreater(attempts[-1]["gap"], .01)
        self.records.append(dict(case="original_uniform_reset_kink", attempts=attempts,
                                 original_model_changed=False))

    def test_same_point_reset_continuation_refines_to_finite_continuum(self):
        errors = []
        for half in (8, 16, 32, 64):
            model = aligned_model(self.theta, **dict(GEOMETRY,
                left_intervals=half, right_intervals=half))[0]
            phi = continuum_lower_hit(model.spatial.nodes, model.spatial.endpoint,
                model.spatial.mu, model.spatial.sigma, model.discount)
            reset_phi = float(continuum_lower_hit([model.reset], model.spatial.endpoint,
                model.spatial.mu, model.spatial.sigma, model.discount)[0])
            base, eta = model.active_reward/model.discount, math.exp(-model.discount*model.delay)
            vr = (base*(1-reset_phi)+model.hit_reward*reset_phi)/(1-eta*reset_phi)
            exact = base+phi*(model.hit_reward+eta*vr-base)
            candidate, candidate_reset = model.perpetual()
            errors.append(dict(intervals=2*half, max_absolute_error=float(max(abs(candidate-exact))),
                               reset_absolute_error=abs(candidate_reset-vr)))
        self.assertTrue(all(b["max_absolute_error"] < .4*a["max_absolute_error"]
                            for a, b in zip(errors, errors[1:])))
        self.records.append(dict(case="continuation_refinement", errors=errors,
                                 original_14336_gate=False))


if __name__ == "__main__":
    unittest.main()
