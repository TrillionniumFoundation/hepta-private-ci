"""Behavioral checks for barrier probability and observation contracts."""

import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import erf, ndtr

from experiments.first_passage_cell.filtering import survival_filter
from experiments.first_passage_cell.kernels import (
    first_passage, first_passage_gradients, killed_cdf, killed_density,
    killed_log_density, killed_gradients,
)


class FirstPassageTests(unittest.TestCase):
    def test_reflection_and_rare_survival_logs(self):
        distance = np.array([1e-12, 1e-6, .1, 1., 5., 20., 35.])
        p = first_passage(distance, 0., 1., 1.)
        np.testing.assert_allclose(p["F"], 2*ndtr(-distance), rtol=2e-13)
        np.testing.assert_allclose(p["S"], erf(distance/np.sqrt(2)), rtol=2e-13)
        np.testing.assert_allclose(p["log_S"][:4], np.log(erf(distance[:4]/np.sqrt(2))),
                                   rtol=2e-14, atol=2e-14)
        self.assertAlmostEqual(float(p["log_S"][-1]/(-p["F"][-1])), 1., places=13)

    def test_time_zero_and_absorbing_atom(self):
        p=first_passage([0.,0.,1.], .2, .5, [0.,1.,0.], .1)
        np.testing.assert_array_equal(p["F"], [1.,1.,0.])
        np.testing.assert_array_equal(p["S"], [0.,0.,1.])
        np.testing.assert_array_equal(p["H"], [1.,1.,0.])
        np.testing.assert_array_equal(p["f"], [0.,0.,0.])
        with self.assertRaises(ValueError):
            first_passage_gradients(0.,0.,1.,1.)
        with self.assertRaises(ValueError):
            killed_log_density(1.,1.,0.,1.,0.)

    def test_terminal_and_first_hit_are_different(self):
        terminal=float(ndtr(-1.))
        first=float(first_passage(1.,0.,1.,1.)["F"])
        self.assertAlmostEqual(first,2*terminal,places=14)
        self.assertGreater(first,terminal)

    def test_positive_drift_defective_hitting_law(self):
        p=first_passage(.8,.6,.7,1e4)
        self.assertAlmostEqual(float(p["F"]),np.exp(-2*.6*.8/.7**2),places=13)
        self.assertGreater(float(p["S"]),0.)

    def test_discount_derivative_is_negative_hit_time_moment(self):
        x,mu,sigma,t,q=.4,-.3,.6,1.2,.4
        reference=quad(lambda s: -s*np.exp(-q*s)*x/(sigma*np.sqrt(2*np.pi*s**3))*
                        np.exp(-(x+mu*s)**2/(2*sigma*sigma*s)),0.,t,
                        epsabs=1e-12)[0]
        actual=first_passage_gradients(x,mu,sigma,t,q)["H"]["discount"]
        self.assertAlmostEqual(float(actual),reference,places=11)
        self.assertLess(float(actual),0.)

    def test_zero_discount_value_and_state_gradients(self):
        p=first_passage(.2,-.6,.4,1.,0.)
        g=first_passage_gradients(.2,-.6,.4,1.,0.)
        self.assertEqual(float(p["H"]),float(p["F"]))
        for key in ("x","mu","sigma","horizon"):
            self.assertEqual(float(g["log_H"][key]),float(g["log_F"][key]))

    def test_killed_density_has_lost_mass(self):
        x,mu,sigma,t=.4,-.2,.6,.7
        mass=quad(lambda y: float(killed_density(x,y,mu,sigma,t)),0.,10.,epsabs=1e-12)[0]
        survival=float(first_passage(x,mu,sigma,t)["S"])
        self.assertAlmostEqual(mass,survival,places=11)
        self.assertLess(mass,1.)
        self.assertEqual(float(killed_density(x,0.,mu,sigma,t)),0.)
        self.assertEqual(float(killed_cdf(x,np.inf,mu,sigma,t)),survival)

    def test_killed_tiny_distance_gradient_remains_representable(self):
        x=1e-200
        log_k=killed_log_density(x,x,0.,1.,1.)
        self.assertTrue(np.isfinite(log_k))
        self.assertEqual(float(killed_density(x,x,0.,1.,1.)),0.)
        derivative=float(killed_gradients(x,x,0.,1.,1.)["k"]["x"])
        self.assertGreater(derivative,0.)
        self.assertAlmostEqual(derivative/(np.sqrt(2/np.pi)*x),1.,places=11)
        with self.assertRaises(ValueError):
            killed_gradients(1e-320,1e-320,0.,1.,1.)

    def test_broadcast_and_invalid_inputs(self):
        p=first_passage(np.array([.1,1.])[:,None],np.array([-.3,0.,.4])[None,:],.6,.7)
        self.assertEqual(p["F"].shape,(2,3))
        for args in [(1.,0.,0.,1.),(-1.,0.,1.,1.),(1.,0.,1.,-1.),(1.,np.nan,1.,1.)]:
            with self.assertRaises(ValueError):
                first_passage(*args)
        with self.assertRaises(ValueError):
            first_passage(1.,0.,1e-200,1.)


class BeliefTests(unittest.TestCase):
    def setUp(self):
        self.grid=np.linspace(.03,4.,32)
        self.prior=np.exp(-.5*((self.grid-.4)/.12)**2)
        self.prior/=self.prior.sum()

    def test_missing_observation_retains_unseen_event_mass(self):
        missing=survival_filter(self.grid,self.prior,-.3,.5,.7,event_observation="missing")
        survived=survival_filter(self.grid,self.prior,-.3,.5,.7,event_observation="observed_survival")
        self.assertGreater(missing["event_mass"],0.)
        self.assertEqual(survived["event_mass"],0.)
        self.assertAlmostEqual(float(missing["alive_mass"].sum())+missing["event_mass"],1.)
        np.testing.assert_allclose(missing["alive_mass"]/missing["alive_mass"].sum(),
                                   survived["alive_mass"],rtol=1e-14)
        self.assertFalse(missing["continuous_semigroup_preserved"])

    def test_sensor_updates_only_declared_live_state(self):
        prior_mean=float(self.prior@self.grid)
        obs=survival_filter(self.grid,self.prior,0.,.3,.2,
                            event_observation="observed_survival",sensor=(1.,.01))
        self.assertGreater(float(obs["alive_mass"]@self.grid),prior_mean)
        with self.assertRaises(ValueError):
            survival_filter(self.grid,self.prior,0.,.3,.2,event_observation="missing",sensor=(1.,.01))

    def test_rare_event_probability_is_not_lost_by_one_minus_survival(self):
        grid=np.array([15.,16.,17.]); prior=np.array([1.,0.,0.])
        event=survival_filter(grid,prior,0.,1.,1.,event_observation="observed_event")
        self.assertGreater(event["observation_probability"],0.)
        self.assertTrue(np.isfinite(event["log_likelihood"]))
        self.assertEqual(event["event_mass"],1.)

    def test_observed_event_is_current_cycle_cumulative_absorption(self):
        cumulative=survival_filter(self.grid,.7*self.prior,0.,.3,0.,
                                   prior_event_mass=.3,event_observation="observed_event")
        self.assertEqual(cumulative["observation_probability"],.3)
        self.assertEqual(cumulative["event_mass"],1.)
        alive=survival_filter(self.grid,.7*self.prior,0.,.3,0.,
                              prior_event_mass=.3,event_observation="observed_survival")
        self.assertAlmostEqual(alive["observation_probability"],.7)
        np.testing.assert_allclose(alive["alive_mass"],self.prior,rtol=1e-14)

    def test_grid_tail_budget_and_impossible_event_reject(self):
        with self.assertRaises(ValueError):
            survival_filter(self.grid,self.prior,8.,.3,1.,event_observation="missing",tail_mass_limit=.01)
        with self.assertRaises(ValueError):
            survival_filter(self.grid,self.prior,0.,.3,0.,event_observation="observed_event")


if __name__=="__main__":
    unittest.main()
