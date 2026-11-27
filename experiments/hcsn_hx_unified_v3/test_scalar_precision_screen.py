"""Empirical PyTorch CPU FP32/BF16 threshold and implicit gradient tests."""
from types import SimpleNamespace
import math
import unittest

from .scalar_precision_screen import (reference_threshold,screen_action,
                                       screen_implicit_gradient,UnresolvedPrecision)


class ScalarPrecisionTests(unittest.TestCase):
    examples=(SimpleNamespace(drift=.1,diffusion=.4,discount=.1,cost=1.,reset=0.,refractory=.3),
              SimpleNamespace(drift=-.3,diffusion=1.,discount=.01,cost=.4,reset=-1.,refractory=1.),
              SimpleNamespace(drift=0.,diffusion=.6,discount=.5,cost=1.,reset=0.,refractory=2.))

    def test_boundary_ambiguity_never_silent_accept(self):
        for p in self.examples:
            b=reference_threshold(p)
            for dtype in ('fp32','bf16'):
                with self.subTest(p=p,dtype=dtype):
                    self.assertEqual(screen_action(p,b,dtype).status,'REFUSE')
                    for delta in (-.2,.2):
                        s=screen_action(p,b+delta*max(1,abs(b)),dtype)
                        self.assertEqual(s.status,'ACCEPT_SCREEN')
                        self.assertEqual(s.low_precision_fire,s.reference_fire)
                    for delta in (-1e-9,1e-9):
                        self.assertEqual(screen_action(p,b+delta,dtype).status,'REFUSE')

    def test_fp32_and_bf16_implicit_gradient_reports(self):
        for p in self.examples:
            for dtype in ('fp32','bf16'):
                with self.subTest(p=p,dtype=dtype):
                    g=screen_implicit_gradient(p,dtype)
                    self.assertEqual(len(g.f64_gradients),6)
                    self.assertIn(g.status,('MEASURED_ONLY','REFUSE'))
                    if g.status=='MEASURED_ONLY':
                        self.assertTrue(math.isfinite(g.normalized_max_error))

    def test_invalid_inputs_refused(self):
        p=self.examples[0]
        with self.assertRaises(UnresolvedPrecision):
            screen_action(p,1.,'fp16')
        with self.assertRaises(UnresolvedPrecision):
            screen_action(p,float('nan'),'fp32')
        with self.assertRaises(UnresolvedPrecision):
            reference_threshold(SimpleNamespace(drift=0.,diffusion=0.,discount=.1,
                                                cost=1.,reset=0.,refractory=1.))


if __name__=='__main__':
    unittest.main()
