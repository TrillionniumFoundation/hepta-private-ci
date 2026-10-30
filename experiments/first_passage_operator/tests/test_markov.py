"""Independent bin integration and augmented-state boundary contracts."""

import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import log_ndtr
from scipy.stats import norm

from experiments.first_passage_operator.markov import state_bin, transition_bins
from experiments.first_passage_operator.operators import RegenerativeSpec
from experiments.first_passage_operator.validate_operators import _cdf, _density


def _normal_log_interval(lo, hi):
    if hi <= 0:
        upper, lower = log_ndtr(hi), log_ndtr(lo)
    elif lo >= 0:
        upper, lower = log_ndtr(-lo), log_ndtr(-hi)
    else:
        return np.log(norm.cdf(hi)-norm.cdf(lo))
    with np.errstate(divide="ignore"):
        return upper+np.log(-np.expm1(min(0.0, lower-upper)))


def _killed_cdf_reference(x, y, mu, sigma, t):
    if t == 0:
        return float(x <= y)
    scale = sigma*np.sqrt(t)
    first = _normal_log_interval(-(x+mu*t)/scale, (y-x-mu*t)/scale)
    second = _normal_log_interval(-(-x+mu*t)/scale, (y+x-mu*t)/scale)-2*mu*x/sigma**2
    return float(np.exp(first)-np.exp(second))


def independent_bins(spec, x, t, ae, re):
    """Integrate event time directly instead of using the Markov difference."""
    count = int(np.ceil(t/spec.refractory))
    cumulative = np.array([_killed_cdf_reference(x, y, spec.mu, spec.sigma, t) for y in ae[1:-1]])
    cumulative_ref = np.zeros(len(re))
    omitted_bound = 0.0
    for n in range(count):
        d = x+n*spec.reset
        width = t-(n+1)*spec.refractory
        cumulative_ref += [_cdf(d, spec.mu, spec.sigma, width+fraction*spec.refractory) for fraction in re]
        if width <= 0:
            continue
        mass = _cdf(d, spec.mu, spec.sigma, width)
        if mass < 1e-14:
            omitted_bound += mass
            continue
        mode = 2*d*d/(3*spec.sigma**2+np.sqrt(9*spec.sigma**4+4*spec.mu**2*d*d))
        points = [mode*factor for factor in (0.1, 1, 10) if 0 < mode*factor < width]
        for j, y in enumerate(ae[1:-1]):
            cumulative[j] += quad(lambda v: _density(d, spec.mu, spec.sigma, v)
                                   * _killed_cdf_reference(spec.reset, y, spec.mu, spec.sigma, width-v),
                                   0, width, points=points, epsabs=2e-11, epsrel=2e-11, limit=200)[0]
    ref = np.diff(cumulative_ref)
    return np.r_[np.diff(np.r_[0, cumulative, 1-np.sum(ref)]), ref], omitted_bound


class MarkovTests(unittest.TestCase):
    def test_natural_boundary_atom_precedes_zero_horizon(self):
        spec = RegenerativeSpec(-0.55, 0.32, 0.9, 0.06)
        actual = transition_bins(spec, 0.0, 0.0)
        expected = transition_bins(spec, spec.reset, 0.0, spec.refractory)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(actual[-1], 1.0)

    def test_hold_release_and_remaining_duration(self):
        spec = RegenerativeSpec(-0.55, 0.32, 0.9, 0.12)
        held = transition_bins(spec, 0.9, 0.02, 0.1)
        self.assertEqual(held[state_bin(0.9, 0.08, 0.12)], 1.0)
        released = transition_bins(spec, 0.9, 0.1, 0.1)
        self.assertEqual(released[state_bin(0.9, 0, 0.12)], 1.0)
        after = transition_bins(spec, 0.9, 0.4, 0.1)
        direct = transition_bins(spec, 0.9, 0.3)
        np.testing.assert_allclose(after, direct, rtol=1e-11, atol=1e-12)

    def test_bins_against_independent_hit_time_integrals(self):
        ae, re = np.array([0, .2, .5, 1, 2, np.inf]), np.array([0, .25, .5, 1])
        cases = [(-.55, .32, .9, .06, .015, .63), (-.85, .48, .55, .04, .015, .75),
                 (.15, .48, .55, .04, .015, .75), (-.4, .4, .6, .12, .7, .32)]
        for mu, sigma, reset, refractory, x, t in cases:
            spec = RegenerativeSpec(mu, sigma, reset, refractory)
            actual = transition_bins(spec, x, t, active_edges=ae, refractory_edges=re)
            expected, bound = independent_bins(spec, x, t, ae, re)
            self.assertLess(bound, 1e-12)
            np.testing.assert_allclose(actual, expected, rtol=2e-8, atol=2e-10)
            self.assertGreaterEqual(float(actual.min()), 0)
            self.assertAlmostEqual(float(actual.sum()), 1, places=11)

    def test_invalid_partitions_and_clocks_are_rejected(self):
        spec = RegenerativeSpec(-0.5, 0.4, 0.8, 0.1)
        for edges in ([], [0], [0, 1], [0, np.nan, np.inf], [[0, np.inf]]):
            with self.assertRaises(ValueError):
                transition_bins(spec, 0.8, 0.2, active_edges=edges)
        with self.assertRaises(ValueError):
            state_bin(-0.1, 0, 0.1)
        with self.assertRaises(ValueError):
            state_bin(0.8, 0.2, 0.1)

    def test_infinite_tail_and_partition_additivity(self):
        spec = RegenerativeSpec(0.15, 0.48, 0.55, 0.04)
        fine = transition_bins(spec, 4.0, 0.75, active_edges=np.array([0, 2, 4, 6, np.inf]),
                               refractory_edges=np.array([0, .5, 1]))
        coarse = transition_bins(spec, 4.0, 0.75, active_edges=np.array([0, 4, np.inf]),
                                 refractory_edges=np.array([0, 1]))
        np.testing.assert_allclose(coarse, [fine[0]+fine[1], fine[2]+fine[3], fine[4]+fine[5]], atol=1e-12)
        self.assertGreater(coarse[1], 0.5)


if __name__ == "__main__":
    unittest.main()
