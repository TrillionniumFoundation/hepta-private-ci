import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr

from experiments.first_passage_adaptive.gradients import expected_task_loss, outcome_law


class CompetingGradientTests(unittest.TestCase):
    def test_three_outcomes_against_independent_time_integrals(self):
        for a,mu,sigma,rate,T in [(1.,0.,1.,0.,1.),(.7,-.3,.6,.8,1.3),(1.2,1.1,.8,.1,.7)]:
            def f(t):
                return a/(sigma*math.sqrt(2*math.pi*t**3))*math.exp(-(a-mu*t)**2/(2*sigma*sigma*t))
            def survival(t):
                if t == 0:
                    return 1.0
                root = sigma*math.sqrt(t)
                return ndtr((a-mu*t)/root)-math.exp(2*mu*a/sigma**2)*ndtr((-a-mu*t)/root)
            reference = np.array([
                quad(lambda t:math.exp(-rate*t)*f(t),0,T,epsabs=1e-12)[0],
                math.exp(-rate*T)*survival(T),
                quad(lambda t:rate*math.exp(-rate*t)*survival(t),0,T,epsabs=1e-12)[0],
            ])
            law = outcome_law(a,mu,sigma,rate,T)
            np.testing.assert_allclose(law.probability,reference,atol=1e-10,rtol=1e-9)
            np.testing.assert_allclose(law.jacobian.sum(0),np.zeros(4),atol=2e-15)
            np.testing.assert_allclose(law.hessian.sum(0),np.zeros((4,4)),atol=2e-15)

    def test_jacobian_and_hessian_against_perturbed_operator(self):
        for parameters in [np.array([.8,.4,.7,.3]),np.array([1.2,-.5,1.1,.8])]:
            law = outcome_law(*parameters,.9)
            for index in range(4):
                delta = np.zeros(4)
                delta[index] = 2e-5
                plus = outcome_law(*(parameters+delta),.9,derivatives=1)
                minus = outcome_law(*(parameters-delta),.9,derivatives=1)
                np.testing.assert_allclose((plus.probability-minus.probability)/4e-5,
                                           law.jacobian[:,index],atol=2e-8,rtol=2e-7)
                np.testing.assert_allclose((plus.jacobian-minus.jacobian)/4e-5,
                                           law.hessian[:,:,index],atol=2e-8,rtol=2e-7)

    def test_expected_hard_loss_is_not_loss_of_expected_output(self):
        law = outcome_law(.9,.2,.8,.3,1.)
        target = np.array([1.,0.,0.])
        costs = np.sum((np.eye(3)-target)**2,axis=1)/2
        expected,gradient,_ = expected_task_loss(law,costs)
        self.assertAlmostEqual(expected,1-law.probability[0])
        self.assertGreater(expected,float(np.sum((law.probability-target)**2)/2))
        self.assertGreater(gradient[3],0)

    def test_zero_drift_zero_cancel_has_finite_root_free_derivatives(self):
        law = outcome_law(1.,0.,1.,0.,1.)
        self.assertTrue(np.isfinite(law.jacobian).all())
        self.assertTrue(np.isfinite(law.hessian).all())
        self.assertEqual(law.probability[2],0.)
        self.assertGreater(law.jacobian[2,3],0.)
        with self.assertRaises(ValueError):
            outcome_law(1.,0.,0.,.2,1.)


if __name__ == "__main__":
    unittest.main()
