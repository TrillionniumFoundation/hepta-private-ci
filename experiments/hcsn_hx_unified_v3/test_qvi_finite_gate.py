"""P0 fail-closed finite-QVI and renewal obstacle research regressions."""
import math
import unittest

from .stopping import (Stop, qvi, regenerative_boundary,
                       regenerative_obstacle, regenerative_value)


class QviFiniteGateTests(unittest.TestCase):
    def test_lost_unit_obstacle_is_recovered_without_value_subtraction(self):
        # Direct D*V(reset)-V(x) rounds to zero for sigma=1e17, x=0.
        p=Stop(0.,1e17,.1,0.,-1.,0.)
        b=regenerative_boundary(p)
        a=regenerative_obstacle(p,0.,boundary=b)
        self.assertAlmostEqual(a,-1.,delta=5e-8)
        self.assertEqual(regenerative_obstacle(p,b,boundary=b),0.)

    def test_normal_qvi_and_both_obstacle_branches(self):
        p=Stop(.1,.4,.1,1.,0.,.3)
        b=regenerative_boundary(p)
        for x in (p.reset,b-.1,b,b+.1):
            with self.subTest(x=x):
                data=qvi(p,x,boundary=b)
                self.assertTrue(all(math.isfinite(data[k]) for k in
                                    ('value','obstacle','generator','complementarity')))
                self.assertLessEqual(data['obstacle'],1e-9)
                self.assertLessEqual(data['generator'],1e-9)
                self.assertLessEqual(abs(data['complementarity']),1e-9)
        self.assertEqual(qvi(p,b,boundary=b)['obstacle'],0.)

    def test_f64_unresolved_high_diffusion_generator_refuses_not_overflows(self):
        p=Stop(-1.,1e200,.1,0.,-1.,0.)
        b=regenerative_boundary(p)
        self.assertTrue(math.isfinite(regenerative_value(p,0.,boundary=b)))
        self.assertAlmostEqual(regenerative_obstacle(p,0.,boundary=b),-1.,delta=1e-9)
        with self.assertRaisesRegex(ArithmeticError,'generator'):
            qvi(p,0.,boundary=b)

    def test_f64_unresolved_large_discount_generator_refuses(self):
        p=Stop(0.,1.,1e308,0.,-1.,0.)
        self.assertTrue(math.isfinite(regenerative_obstacle(p,0.)))
        with self.assertRaisesRegex(ArithmeticError,'generator'):
            qvi(p,0.)

    def test_nonfinite_renewal_amplitude_refuses_not_returns_infinity(self):
        p=Stop(1e308,1e308,.1,0.,-1.,0.)
        with self.assertRaisesRegex(ArithmeticError,'amplitude|value'):
            regenerative_value(p,0.)
        with self.assertRaisesRegex(ArithmeticError,'amplitude|value'):
            qvi(p,0.)


if __name__=='__main__':
    unittest.main()
