"""P0: reject nonfinite QVI values and expose consistent obstacle."""
import unittest
from .stopping import Stop,regenerative_value,regenerative_obstacle,qvi

class QviSiblingFiniteTests(unittest.TestCase):
    def test_nonfinite_renewal_refuses(self):
        p=Stop(1e308,1e308,.1,0.,-1.,0.)
        with self.assertRaises(ArithmeticError):
            regenerative_value(p,0.)

    def test_signed_obstacle_agrees_with_qvi(self):
        p=Stop(-1.,1e200,.1,0.,-1.,0.)
        o=regenerative_obstacle(p,-1e200)
        self.assertLess(o,-1e198)
        self.assertEqual(o,qvi(p,-1e200)['obstacle'])
