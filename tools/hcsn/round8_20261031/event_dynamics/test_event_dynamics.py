"""Behavioral regression tests for the new event-law contracts."""

import math
import unittest

import numpy as np

from .event_kernel import (DomainError, discounted_hit, first_hit, first_hit_gradient,
                           two_segment_first_hit)
from .generator import (ResolutionError, absorbing_generator, erlang_recovery,
                        hazard_from_reference_release, rates, require_local_resolution)
from .renewal import expected_count, sample_counts
from .validation import audit


class EventLawTests(unittest.TestCase):
    def test_independent_numerical_qualification(self):
        result = audit()
        self.assertEqual([g["name"] for g in result["gates"] if not g["passed"]], [])

    def test_affine_boundary_and_parameter_gradient(self):
        actual = first_hit(.8,.6,.4,1.3,boundary_slope=.2)
        reference = first_hit(.8,.4,.4,1.3)
        for key in actual:
            self.assertAlmostEqual(actual[key],reference[key],places=13)
        gradient = first_hit_gradient(.8,.6,.4,1.3,boundary_slope=.2)
        self.assertEqual(gradient["boundary_slope"],-gradient["drift"])

    def test_probability_and_value_remain_distinct(self):
        actual = first_hit(1.,.4,.6,1.2)["probability"]
        self.assertEqual(discounted_hit(1.,.4,.6,1.2,0.)["value"],actual)
        self.assertLess(discounted_hit(1.,.4,.6,1.2,.7)["value"],actual)

    def test_tail_underflow_is_retained_in_logs(self):
        row=first_hit(40.,0.,1.,1.)
        self.assertEqual(row["probability"],0.)
        self.assertTrue(math.isfinite(row["log_probability"]))
        tail=first_hit(1.,1.,.1,10.)
        self.assertEqual(tail["probability"],1.)
        self.assertGreater(tail["survival"],0.)

    def test_boundary_jump_accounts_for_all_surviving_mass(self):
        result=two_segment_first_hit(1.,(.001,.2,.05),(.1,.4,.2),boundary_jump=-1000.)
        self.assertAlmostEqual(result["probability"],1.,places=11)
        self.assertGreater(result["jump_hit"],.99)

    def test_out_of_domain_fails_explicitly(self):
        for args in ((0.,1.,.1,1.),(1.,1.,0.,1.),(1.,1.,.1,-1.),
                     (1.,1.,1e-300,1.),(1e7,0.,1.,1.),(1.,math.nan,.1,1.)):
            with self.assertRaises(DomainError):
                first_hit(*args)
        with self.assertRaises(DomainError):
            expected_count(.8,.7,1.,.4,3.,.5,included_events=1)
        with self.assertRaises(DomainError):
            sample_counts(.8,math.nan,1.,.4,3.,.5,paths=10)

    def test_generator_drift_and_necessary_resolution_gate(self):
        for scheme in ("upwind","fitted"):
            result=rates(np.array([-1.,0.,1.]),.45,.02,scheme)
            np.testing.assert_allclose(result["represented_drift"],[-1.,0.,1.],atol=2e-14,rtol=0.)
        good=absorbing_generator(.4,.6,n_grid=63,scheme="fitted")
        self.assertTrue(require_local_resolution(good["diagnostics"])["passed"])
        bad=absorbing_generator(1.,.05,n_grid=63,scheme="fitted")
        with self.assertRaises(ResolutionError):
            require_local_resolution(bad["diagnostics"])

    def test_recovery_is_a_physical_clock(self):
        hazard=hazard_from_reference_release(.65,1.)
        release=erlang_recovery(1/hazard,1,1.)[0,-1]
        self.assertAlmostEqual(release,.65,places=14)
        tenth=erlang_recovery(1/hazard,1,.1)
        np.testing.assert_allclose(np.linalg.matrix_power(tenth,10),erlang_recovery(1/hazard,1,1.),atol=2e-14,rtol=0.)
        self.assertLess(tenth[0,-1],.65)


if __name__=="__main__":
    unittest.main()
