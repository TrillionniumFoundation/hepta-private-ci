"""Independent convolution and conservative PDE checks of fixed reset kernels."""

import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import expm_multiply
from scipy.special import ndtr

from qualification.hcsn_regenerative.fixed_renewal import (
    FixedDiffusion, instant_reset_transition, instant_reset_value, released_interval,
)


def reference_density(x, time, mu, sigma):
    return x/(sigma*math.sqrt(2*math.pi*time**3))*math.exp(-(x+mu*time)**2/(2*sigma*sigma*time))


def reference_killed_interval(x, time, lo, hi, mu, sigma):
    scale = sigma*math.sqrt(time)
    return (ndtr((hi-x-mu*time)/scale)-ndtr((lo-x-mu*time)/scale)
            - math.exp(-2*mu*x/sigma**2)*(ndtr((hi+x-mu*time)/scale)-ndtr((lo+x-mu*time)/scale)))


def conservative_reset_pde(spacing):
    """Independent upwind finite-volume generator; no use of renewal formulas."""
    maximum, time, mu, sigma, reset, start = 4., 1.4, -.1, .3, .25, .35
    n = int(round(maximum/spacing))
    centers = (np.arange(n)+.5)*spacing
    q = lil_matrix((n+1, n+1), dtype=np.float64)
    initial = np.zeros(n+1)

    def deposit(array, point, weight):
        position = point/spacing-.5
        left = int(math.floor(position))
        fraction = position-left
        array[left] += weight*(1-fraction)
        array[left+1] += weight*fraction

    reset_weights = np.zeros(n)
    deposit(reset_weights, reset, 1.)
    deposit(initial, start, 1.)
    diffusion = .5*sigma*sigma/spacing**2
    for j in range(n):
        if j > 0:
            rate = diffusion+max(-mu, 0)/spacing
            q[j-1,j] += rate
            q[j,j] -= rate
        else:
            rate = 2*diffusion+max(-mu, 0)/spacing
            for i in np.flatnonzero(reset_weights):
                q[i,j] += rate*reset_weights[i]
            q[j,j] -= rate
            q[n,j] += rate
        if j+1 < n:
            rate = diffusion+max(mu, 0)/spacing
            q[j+1,j] += rate
            q[j,j] -= rate
    state = expm_multiply(time*q.tocsr(), initial)
    return centers, state[:n], float(state[-1])


class FixedRenewalTests(unittest.TestCase):
    def test_release_against_independent_positive_time_convolution(self):
        for mu in (-.2, 0., .2):
            process = FixedDiffusion(mu, .3)
            for distance, time in ((.35,1.4),(.04,.1),(.9,2.)):
                for low, high in ((0.,.1),(.1,.4),(.4,1.2),(0.,math.inf)):
                    with self.subTest(mu=mu, distance=distance, time=time, interval=(low,high)):
                        actual = released_interval(process, distance, .25, time, low, high)
                        expected, error = quad(
                            lambda u: reference_density(distance,time*u*u,mu,.3)
                            * reference_killed_interval(.25,time*(1-u*u),low,high,mu,.3)*2*time*u,
                            0,1,epsabs=1e-11,epsrel=1e-10,limit=150)
                        self.assertLess(error, 2e-10)
                        self.assertAlmostEqual(actual, expected, delta=2e-10)

    def test_zero_delay_atoms_and_same_generator_values(self):
        p = FixedDiffusion(-.1,.3)
        at_zero = instant_reset_transition(p,.25,0.,0.,[0.,.2,.3,1.])
        np.testing.assert_array_equal(at_zero.active_bins,[0.,1.,0.])
        self.assertEqual(at_zero.expected_hits_partial,1.)
        self.assertEqual(at_zero.omitted_active_mass,0.)
        value = instant_reset_value(p,at_zero,0.,active_reward=.4,terminal_reward=.2)
        self.assertEqual(value['value'],1.2)
        with self.assertRaises(ValueError):
            instant_reset_value(FixedDiffusion(.1,.3),at_zero,0.)
        with self.assertRaises(ValueError):
            instant_reset_value(p,at_zero,.1)

    def test_renewal_tail_and_spatial_aggregation_without_normalization(self):
        for mu,sigma,x,time in ((-.1,.3,.35,1.4),(.2,.3,.4,2.),(-2.,.05,.35,.8)):
            p=FixedDiffusion(mu,sigma)
            fine=instant_reset_transition(p,.25,x,time,[0.,.1,.25,.5,1.,2.],tolerance=1e-10)
            coarse=instant_reset_transition(p,.25,x,time,[0.,.25,1.,2.],tolerance=1e-10)
            np.testing.assert_allclose(coarse.active_bins,
                                       [fine.active_bins[:2].sum(),fine.active_bins[2:4].sum(),fine.active_bins[4]],
                                       rtol=1e-9,atol=5e-11)
            self.assertAlmostEqual(coarse.upper_tail,fine.upper_tail,delta=5e-11)
            self.assertLess(abs(fine.mass_residual_against_truncated_law),5e-10)
            self.assertLessEqual(fine.omitted_hit_count_bound,1e-10)
            observed_tail=sum(p.first_hit(x+n*.25,time) for n in range(fine.terms,fine.terms+20))
            self.assertLessEqual(observed_tail,fine.omitted_hit_count_bound*(1+1e-9)+1e-300)
            self.assertLessEqual(fine.expected_discounted_hits_partial,fine.expected_hits_partial+1e-11)
        with self.assertRaises(FloatingPointError):
            instant_reset_transition(FixedDiffusion(-2.,.05),.01,.1,8.,[0.,.1,1.],max_terms=4)

    def test_strong_drift_release_uses_log_weight_without_overflow(self):
        p=FixedDiffusion(-2.,.05)
        result=released_interval(p,8.,.25,4.,0.,math.inf)
        expected=p.first_hit(8.,4.)-p.first_hit(8.25,4.)
        self.assertAlmostEqual(result,expected,delta=5e-10)
        self.assertTrue(math.isfinite(result))

    def test_underflow_does_not_claim_an_exact_zero_renewal_tail(self):
        p=FixedDiffusion(-.1,.3)
        state=instant_reset_transition(p,.25,1e-5,1e-6,[0.,.1,.25,.5,1.])
        self.assertEqual(state.omitted_active_mass,0.)
        self.assertTrue(math.isfinite(state.log_omitted_active_mass))
        self.assertLess(state.log_omitted_active_mass,-10000)
        self.assertGreater(state.omitted_hit_count_bound,0.)

    def test_independent_zero_delay_pde_refinement(self):
        p=FixedDiffusion(-.1,.3)
        errors=[]
        count_errors=[]
        for spacing in (.1,.05,.025):
            centers,masses,count=conservative_reset_pde(spacing)
            edges=np.arange(len(centers)+1,dtype=float)*spacing
            exact=instant_reset_transition(p,.25,.35,1.4,edges)
            errors.append(float(np.abs(np.cumsum(masses)-np.cumsum(exact.active_bins)).max()))
            count_errors.append(abs(count-exact.expected_hits_partial))
            self.assertAlmostEqual(float(masses.sum()),1.,delta=2e-11)
        self.assertLess(errors[-1],errors[0]*.6)
        self.assertLess(count_errors[-1],count_errors[0]*.6)
        self.assertLess(errors[-1],.01)
        self.assertLess(count_errors[-1],.02)


if __name__ == '__main__':
    unittest.main()
