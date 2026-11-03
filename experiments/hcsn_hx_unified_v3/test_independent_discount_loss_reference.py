"""Focused numerical research tests, not a global HX proof."""
import random
import unittest
import mpmath as mp
from .independent_discount_loss_reference import first_hit_loss, review_float32


class DirectLossTests(unittest.TestCase):
    def test_exact_zero_discount(self):
        v = first_hit_loss('.7','.12','.42','1.3',0)
        self.assertEqual(v.first_probability, v.discounted_probability)
        self.assertEqual(v.discount_loss,0)
        self.assertTrue(review_float32(v).allowed)

    def test_absorbed_initial_condition(self):
        v = first_hit_loss(0,'.12','.42','1.3','.2')
        self.assertEqual(tuple((v.first_probability,v.discounted_probability,v.discount_loss)),(1,1,0))

    def test_zero_horizon(self):
        v = first_hit_loss('.3','.12','.42',0,'.2')
        self.assertEqual(tuple((v.first_probability,v.discounted_probability,v.discount_loss)),(0,0,0))

    def test_direct_loss_survives_tiny_discount_in_high_precision(self):
        tiny=first_hit_loss('.4','-.05','.8','2','1e-23',dps=100)
        self.assertGreater(tiny.discount_loss, mp.mpf(0))
        self.assertLess(tiny.discount_loss, mp.mpf('1e-22'))
        with mp.workdps(100):
            self.assertLess(abs((tiny.first_probability - tiny.discounted_probability)-tiny.discount_loss),mp.mpf("1e-90"))
        v=review_float32(tiny)
        self.assertFalse(v.allowed)
        self.assertEqual(v.reason,'POSITIVE_LOSS_ERASED_BY_FLOAT32')

    def test_regular_float32_keeps_order(self):
        normal=first_hit_loss('.3','0','.8','2','1',dps=80)
        r=review_float32(normal)
        self.assertGreater(normal.discount_loss,0)
        with mp.workdps(90):
            self.assertLess(abs(normal.first_probability-normal.discounted_probability-normal.discount_loss),mp.mpf("1e-70"))
        self.assertTrue(r.allowed,r.reason)

    def test_twenty_moderate_random_independent_quadratures(self):
        rng=random.Random(202610304)
        for _ in range(20):
            x=f'{rng.uniform(.15,1):.15g}'
            drift=f'{rng.uniform(-.25,.25):.15g}'
            sigma=f'{rng.uniform(.25,.9):.15g}'
            horizon=f'{rng.uniform(.5,3):.15g}'
            q=f'{rng.uniform(.01,.6):.15g}'
            with self.subTest(x=x,drift=drift,sigma=sigma,q=q):
                t=first_hit_loss(x,drift,sigma,horizon,q,dps=66)
                self.assertTrue(0 < t.discounted_probability < t.first_probability < 1)
                self.assertGreater(t.discount_loss,0)

    def test_parameter_rejections(self):
        bad=[(1,0,0,1,1),(-1,0,1,1,1),(1,0,1,-1,1),(1,0,1,1,-1),
             (1,0,1,float('inf'),1),(1,0,1,1,float('nan')),(True,0,1,1,1)]
        for args in bad:
            with self.subTest(args=args),self.assertRaises(ValueError):
                first_hit_loss(*args)
        with self.assertRaises(ValueError):
            first_hit_loss(1,0,1,1,1,dps=40)

    def test_refuse_precision_budget_exhaustion(self):
        with self.assertRaisesRegex(ArithmeticError,'precision budget'):
            first_hit_loss('.4','-.05','.8','2','1e-80',dps=80)


if __name__=='__main__':
    unittest.main()
