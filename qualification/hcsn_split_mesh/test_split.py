"""Two declared split meshes: discrete gradients and retained rare failures."""

import json
import math
import unittest

import numpy as np
from scipy.linalg import expm
from scipy.special import log_ndtr

from qualification.hcsn_reset_aligned.mesh import aligned_model
from qualification.hcsn_reset_aligned.sensitivities import PARAMETERS, solve_aligned_partials
from qualification.hcsn_reset_aligned.test_model import flatten
from .mesh import split_model


GEOMETRIES = [dict(left_intervals=32, right_intervals=32, endpoint=2.,
                  grading=left, right_grading=0., delay=.2) for left in (1., 0.)]
OPTIONS = dict(rtol=2e-11, atol=2e-13, max_step=.02)


def halfline_hit(distance, drift, sigma, time):
    scale = sigma*math.sqrt(time)
    return float(np.exp(np.logaddexp(log_ndtr((-distance-drift*time)/scale),
        -2*drift*distance/sigma**2+log_ndtr((-distance+drift*time)/scale))))


class SplitMesh(unittest.TestCase):
    records = []

    @classmethod
    def tearDownClass(cls):
        print("SPLIT_EVIDENCE", json.dumps(dict(records=cls.records, exploratory_only=True,
            continuum_rare_gate_closed=False, common_source_changed=False,
            torch_adapter_supplied=False, fixed_physical_prior_jacobian=False), sort_keys=True))

    def setUp(self):
        self.theta = np.array([.01, -.12, .08, math.exp(.51), .15])

    def test_inherited_grading_preserves_common_operator(self):
        theta = self.theta.copy()
        theta[2] = .5
        geometry = dict(left_intervals=4, right_intervals=4, endpoint=2.)
        old, old_jacobian = aligned_model(theta, **geometry)
        new, new_jacobian = split_model(theta, **geometry)
        np.testing.assert_array_equal(old.spatial.nodes, new.spatial.nodes)
        np.testing.assert_array_equal(old.spatial.matrix(), new.spatial.matrix())
        np.testing.assert_array_equal(old_jacobian, new_jacobian)

    def test_negative_drift_low_noise_rates_and_generator_fd(self):
        for geometry in GEOMETRIES:
            errors = []
            for reset in (.4999, .5, .5001):
                theta = self.theta.copy()
                theta[3] = math.exp(reset+theta[0])
                model, jacobian = split_model(theta, **geometry)
                nodes, matrix = model.spatial.nodes, model.spatial.matrix()
                self.assertGreater(min(map(np.min, model.spatial.rates)), 0)
                np.testing.assert_allclose((matrix @ nodes)[1:-1], theta[1], atol=2e-13, rtol=0)
                np.testing.assert_allclose((matrix @ nodes**2)[1:-1],
                    2*theta[1]*nodes[1:-1]+theta[2]**2, atol=5e-13, rtol=0)
                self.assertEqual(np.count_nonzero(model.ingredients()[3]), 1)
                for j, name in enumerate(PARAMETERS):
                    for step in (2e-5, 1e-5):
                        delta = np.zeros(5)
                        delta[j] = step
                        high = split_model(theta+delta, **geometry)[0].spatial.matrix()
                        low = split_model(theta-delta, **geometry)[0].spatial.matrix()
                        fd = (high-low)/(2*step)
                        np.testing.assert_allclose(jacobian[j], fd, rtol=2e-7, atol=2e-6)
                        errors.append(dict(reset=reset, parameter=name, step=step,
                            maximum_absolute_error=float(np.max(abs(jacobian[j]-fd)))))
            model, _ = split_model(self.theta, **geometry)
            self.records.append(dict(case="low_noise_positive_generator", geometry=geometry,
                minimum_down=float(min(model.spatial.rates[0])),
                minimum_up=float(min(model.spatial.rates[1])), differences=errors))

    def test_full_delayed_physical_partials_at_two_fixed_geometries(self):
        active = np.zeros(65)
        active[[1, 12]] = .5
        content = -.4*active[:, None]
        for geometry in GEOMETRIES:
            model, jacobian = split_model(self.theta, **geometry)
            candidate = solve_aligned_partials(model, jacobian, [0., .1, .4],
                active, content, **OPTIONS)["rows"][-1]
            reference = model.solve([0., .1, .4], active, content, **OPTIONS)["rows"][-1]
            forward_error = float(max(abs(flatten(candidate["primal"])-flatten(reference))))
            self.assertLess(forward_error, 5e-9)
            errors = []
            for j, name in enumerate(PARAMETERS):
                derivative = flatten(candidate["partials"][name])
                for step in (2e-4, 1e-4):
                    delta = np.zeros(5)
                    delta[j] = step
                    high = split_model(self.theta+delta, **geometry)[0].solve(
                        [0., .1, .4], active, content, **OPTIONS)["rows"][-1]
                    low = split_model(self.theta-delta, **geometry)[0].solve(
                        [0., .1, .4], active, content, **OPTIONS)["rows"][-1]
                    fd = (flatten(high)-flatten(low))/(2*step)
                    np.testing.assert_allclose(derivative, fd, rtol=5e-4, atol=4e-6)
                    errors.append(dict(parameter=name, step=step,
                        maximum_absolute_error=float(max(abs(derivative-fd))),
                        tolerance_scaled_error=float(max(abs(derivative-fd)/(4e-6+5e-4*abs(fd)))),
                        variational=derivative.tolist(), finite_difference=fd.tolist()))
            self.records.append(dict(case="low_noise_delayed_derivatives", geometry=geometry,
                forward_max_absolute_error=forward_error, differences=errors,
                nodal_rows=64, phase_rows_remaining_under_current_torch_cap=0))

    def test_short_rare_continuum_failure_is_retained(self):
        theta = self.theta.copy()
        theta[2] = .5
        for geometry in GEOMETRIES:
            model, _ = split_model(theta, **geometry)
            records = []
            for time in (.01, .1):
                actual = float(expm(time*model.spatial.matrix())[32, 0])
                exact = halfline_hit(.5, -.12, .5, time)
                relative = actual/exact-1
                if time == .01:
                    self.assertGreater(relative, 1e5)
                records.append(dict(time=time, ctmc=actual, continuum_halfline=exact,
                    relative_error=relative, upper_reach_probability_bound=halfline_hit(1.5, .12, .5, time)))
            self.records.append(dict(case="retained_continuum_failures", geometry=geometry, records=records))


if __name__ == "__main__":
    unittest.main()
