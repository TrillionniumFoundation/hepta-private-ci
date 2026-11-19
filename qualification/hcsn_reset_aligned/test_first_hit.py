"""Discrete F-gradient checks and retained continuum/low-noise limitations."""

import json
import math
import unittest

import numpy as np
from scipy.special import log_ndtr

from qualification.hcsn_joint_dde.graded import ShortGapKernel
from qualification.hcsn_reset_aligned.first_hit import first_hit_partials
from qualification.hcsn_reset_aligned.mesh import aligned_model


GEOMETRY = dict(left_intervals=4, right_intervals=4, endpoint=2., grading=1., delay=.2)


def halfline_hit(distance, mu, sigma, time):
    scale = sigma*math.sqrt(time)
    return float(np.exp(np.logaddexp(log_ndtr((-distance-mu*time)/scale),
        -2*mu*distance/sigma**2+log_ndtr((-distance+mu*time)/scale))))


class KilledFirstHit(unittest.TestCase):
    records = []

    @classmethod
    def tearDownClass(cls):
        print("FIRST_HIT_EVIDENCE", json.dumps(cls.records, sort_keys=True))

    def test_frechet_partials_against_generator_forward_and_spectral(self):
        theta = np.array([.01, -.12, .5, math.exp(.51), .15])
        times = [.01, .1, .6]
        values, jacobian = first_hit_partials(theta, times, GEOMETRY)
        model = aligned_model(theta, **GEOMETRY)[0]
        kernel = ShortGapKernel(model.spatial, model.discount)
        spectral = np.stack([kernel.at(t)[0][1:] for t in times])
        np.testing.assert_allclose(values, spectral, rtol=0, atol=3e-13)
        np.testing.assert_array_equal(jacobian[:, :, 4], 0.)
        errors = []
        for j in range(5):
            delta = np.zeros(5)
            delta[j] = 1e-5
            high = first_hit_partials(theta+delta, times, GEOMETRY)[0]
            low = first_hit_partials(theta-delta, times, GEOMETRY)[0]
            fd = (high-low)/(2e-5)
            np.testing.assert_allclose(jacobian[:, :, j], fd, rtol=2e-5, atol=2e-7)
            errors.append(float(np.max(abs(fd-jacobian[:, :, j]))))
        self.records.append(dict(case="frechet_fd", query_times=times, absolute_errors=errors,
                                 discount_derivative_exactly_zero=True))

    def test_same_discrete_training_does_not_establish_continuum_or_domain(self):
        theta = np.array([.01, -.12, .5, math.exp(.51), .15])
        records = []
        for total in (8, 64):
            geometry = dict(GEOMETRY, left_intervals=total//2, right_intervals=total//2)
            model = aligned_model(theta, **geometry)[0]
            values = first_hit_partials(theta, [.01, .1], geometry)[0][:, total//2-1]
            for t, discrete in zip((.01, .1), values):
                halfline = halfline_hit(model.reset, -.12, .5, t)
                upper_bound = halfline_hit(2.-model.reset, .12, .5, t)
                records.append(dict(intervals=total, time=t, discrete=float(discrete),
                    halfline=halfline, upper_exit_probability_bound=upper_bound,
                    relative_difference=float(discrete/halfline-1)))
        self.assertGreater(records[1]["relative_difference"], 1.)
        self.assertGreater(records[-1]["relative_difference"], .01)
        low_noise = theta.copy()
        low_noise[2] = .08
        for total in (8, 16, 32, 64):
            with self.assertRaisesRegex(ValueError, "positive rates"):
                aligned_model(low_noise, **dict(GEOMETRY, left_intervals=total//2, right_intervals=total//2))
        self.records.append(dict(case="retained_negative_qualification", cases=records,
            negative_drift_low_noise_rejected_through_64=True, continuum_qualified=False))


if __name__ == "__main__":
    unittest.main()
