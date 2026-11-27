"""Regression checks for fp32 rounding cells; no native/GPU assertion."""
import math
import random
import unittest

import numpy as np

from .quantized_barrier import (classify_fp32_barrier, fp32_cell,
                                guarded_fp32_passage)
from .bond_fpt_independent import reflected_passage


class QuantizedBarrierTests(unittest.TestCase):
    def test_literal_float32_alias_is_ambiguous(self):
        b=64.6251766753
        a=b*(1+1e-9)
        self.assertGreater(a,b)
        self.assertEqual(np.float32(a), np.float32(b))
        order,bracket=guarded_fp32_passage(
            a,b,drift=-.02,sigma=.25,discount=.08,horizon=2.)
        self.assertEqual(order.status,'AMBIGUOUS')
        self.assertIsNone(bracket)

    def test_one_ulp_not_silently_classified(self):
        b=np.float32(64.)
        plus_one=np.nextafter(b,np.float32(math.inf))
        plus_two=np.nextafter(plus_one,np.float32(math.inf))
        self.assertEqual(classify_fp32_barrier(float(plus_one),float(b)).status,
                         'AMBIGUOUS')
        self.assertEqual(classify_fp32_barrier(float(plus_two),float(b)).status,
                         'ABOVE')

    def test_negative_side_default_is_immediate(self):
        order,bracket=guarded_fp32_passage(
            63.,64.,drift=.2,sigma=.3,discount=.05,horizon=10.)
        self.assertEqual(order.status,'BELOW')
        self.assertEqual((bracket.lower_f,bracket.upper_f,
                          bracket.lower_g,bracket.upper_g),(1.,1.,1.,1.))

    def test_cells_conservatively_include_preimages(self):
        rng=random.Random(20261030)
        for _ in range(200):
            x=10**rng.uniform(-25,30)
            cell=fp32_cell(x)
            self.assertLessEqual(cell.lower,x)
            self.assertGreaterEqual(cell.upper,x)
            self.assertEqual(float(np.float32(x)),cell.encoded)

    def test_numeric_brackets_cover_double_precision_reference(self):
        rng=random.Random(10230)
        count=0
        for _ in range(80):
            b=10**rng.uniform(-4,4)
            a=b*rng.uniform(1.0001,8.)
            drift=rng.uniform(-.5,.5)
            sigma=rng.uniform(.1,.8)
            q=10**rng.uniform(-4,.7)
            horizon=10**rng.uniform(-2,1)
            order,bracket=guarded_fp32_passage(
                a,b,drift=drift,sigma=sigma,discount=q,horizon=horizon)
            self.assertEqual(order.status,'ABOVE')
            exact=reflected_passage(math.log(a/b),drift=drift,
                                    sigma=sigma,discount=q,horizon=horizon)
            self.assertLessEqual(bracket.lower_f-3e-11,exact.probability)
            self.assertGreaterEqual(bracket.upper_f+3e-11,exact.probability)
            self.assertLessEqual(bracket.lower_g-3e-11,exact.discounted)
            self.assertGreaterEqual(bracket.upper_g+3e-11,exact.discounted)
            count+=1
        self.assertEqual(count,80)

    def test_near_barrier_fp32_cells_cover_high_precision_endpoint_fixtures(self):
        # Frozen 120-dps mpmath references from the *exact binary64*
        # fp32 rounding-cell endpoints, with log(asset/boundary) evaluated
        # before converting to f64. The old log(asset)-log(boundary) lost
        # 1e-15 in x and put a true endpoint outside the estimated bracket.
        # Numerical agreement is evidence only, NOT a certified interval.
        cases=(
            # asset, boundary, drift, sigma, q, T,
            # far F, near F, far G, near G
            (2461.6043065865556,2461.601799999847,
             .878797831826607,.01636151046030649,.0015892965090648003,
             .6015898216497764,
             .9928627249211992,.9941566116312371,
             .9928627229622654,.9941566100263843),
            (.00020627679851852393,.00020627619697328605,
             .6659121606708411,.018016058057038903,.00015264391301638805,
             7.486235697243127,
             .9876300990973714,.9882020356281458,
             .9876300984106261,.9882020349729629),
        )
        for asset,boundary,drift,sigma,q,horizon,far_f,near_f,far_g,near_g in cases:
            with self.subTest(asset=asset,boundary=boundary):
                order,bracket=guarded_fp32_passage(
                    asset,boundary,drift=drift,sigma=sigma,
                    discount=q,horizon=horizon)
                self.assertEqual(order.status,'ABOVE')
                self.assertIsNotNone(bracket)
                self.assertLessEqual(bracket.lower_f,far_f)
                self.assertGreaterEqual(bracket.upper_f,near_f)
                self.assertLessEqual(bracket.lower_g,far_g)
                self.assertGreaterEqual(bracket.upper_g,near_g)

    def test_seeded_1500_guard_decisions(self):
        # Bounded adversarial probe across fp32 exponent ranges. This does
        # not make the numerical brackets formally interval-certified.
        rng=random.Random(98720261030)
        checked=ambiguous=0
        for _ in range(1500):
            b=10**rng.uniform(-20,20)
            a=b*(1+10**rng.uniform(-8,1.2))
            drift=rng.uniform(-.8,.8)
            sigma=10**rng.uniform(-1.8,.1)
            q=10**rng.uniform(-7,.4)
            horizon=10**rng.uniform(-3,1.4)
            order,bracket=guarded_fp32_passage(
                a,b,drift=drift,sigma=sigma,discount=q,horizon=horizon)
            if order.status=='AMBIGUOUS':
                self.assertIsNone(bracket)
                ambiguous+=1
                continue
            self.assertEqual(order.status,'ABOVE')
            exact=reflected_passage(math.log(a/b),drift=drift,
                                    sigma=sigma,discount=q,horizon=horizon)
            self.assertLessEqual(bracket.lower_f-exact.probability,3e-11)
            self.assertLessEqual(exact.probability-bracket.upper_f,3e-11)
            self.assertLessEqual(bracket.lower_g-exact.discounted,3e-11)
            self.assertLessEqual(exact.discounted-bracket.upper_g,3e-11)
            checked+=1
        self.assertGreater(checked,1000)
        self.assertGreater(ambiguous,100)

    def test_invalid_encodings_refused(self):
        for val in (0.,-1.,float('nan'),float('inf'),1e-80,1e100):
            with self.subTest(value=val),self.assertRaises(ValueError):
                fp32_cell(val)
        with self.assertRaises(ValueError):
            guarded_fp32_passage(65.,64.,drift=0.,sigma=0.,discount=.1,horizon=1.)


if __name__=='__main__':
    unittest.main()
